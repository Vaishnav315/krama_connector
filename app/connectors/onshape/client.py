"""Onshape REST API Client.

Provides synchronous HTTP client methods with automatic HMAC signing,
rate limit backoff (HTTP 429), and explicit error handling.
References:
- https://onshape-public.github.io/docs/api-intro/
- https://onshape-public.github.io/docs/auth/limits/
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings
from app.connectors.onshape.auth import get_auth_headers_for_request

logger = logging.getLogger(__name__)


class OnshapeAPIError(Exception):
    """Base exception for Onshape API communications."""

    def __init__(self, message: str, status_code: int | None = None, response_text: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class OnshapeAuthenticationError(OnshapeAPIError):
    """Raised when authentication fails (HTTP 401 or 403)."""


class OnshapeNotFoundError(OnshapeAPIError):
    """Raised when the requested document, version, or element is not found (HTTP 404)."""


class OnshapeRateLimitError(OnshapeAPIError):
    """Raised when API rate limits are exceeded (HTTP 429)."""

    def __init__(self, message: str, retry_after: float | None = None, response_text: str | None = None):
        super().__init__(message, status_code=429, response_text=response_text)
        self.retry_after = retry_after


class OnshapeClient:
    """Production HTTP client for the Onshape REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        oauth_token: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.ONSHAPE_BASE_URL).rstrip("/")
        self.access_key = access_key or settings.ONSHAPE_ACCESS_KEY
        self.secret_key = secret_key or settings.ONSHAPE_SECRET_KEY
        self.oauth_token = oauth_token or settings.ONSHAPE_OAUTH_TOKEN
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=transport,
        )

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._client.close()

    def __enter__(self) -> OnshapeClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute signed HTTP request with retry logic for transient errors and rate limits."""
        if not path.startswith("/"):
            path = "/" + path

        # Filter None params
        query_params = {k: str(v) for k, v in (params or {}).items() if v is not None}
        retries_remaining = self.max_retries
        backoff_delay = 1.0

        while True:
            headers = get_auth_headers_for_request(
                method=method,
                path=path,
                query_params=query_params,
                access_key=self.access_key,
                secret_key=self.secret_key,
                oauth_token=self.oauth_token,
            )

            try:
                response = self._client.request(
                    method=method,
                    url=path,
                    params=query_params,
                    json=json_data,
                    headers=headers,
                )

                if response.status_code == 200:
                    return response.json() if response.content else {}

                if response.status_code in (401, 403):
                    raise OnshapeAuthenticationError(
                        f"Onshape authentication failed ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                        response_text=response.text,
                    )

                if response.status_code == 404:
                    raise OnshapeNotFoundError(
                        f"Onshape resource not found at {path} ({response.status_code}): {response.text}",
                        status_code=404,
                        response_text=response.text,
                    )

                if response.status_code == 429:
                    retry_after_header = response.headers.get("Retry-After")
                    retry_after = float(retry_after_header) if retry_after_header else backoff_delay
                    logger.warning("Onshape rate limit (429) encountered. Retries left: %d. Waiting: %.2fs", retries_remaining, retry_after)
                    if retries_remaining > 0:
                        retries_remaining -= 1
                        time.sleep(retry_after)
                        backoff_delay *= 2.0
                        continue
                    raise OnshapeRateLimitError(
                        f"Rate limit exceeded on {path}",
                        retry_after=retry_after,
                        response_text=response.text,
                    )

                if response.status_code >= 500:
                    if retries_remaining > 0:
                        retries_remaining -= 1
                        time.sleep(backoff_delay)
                        backoff_delay *= 2.0
                        continue
                    raise OnshapeAPIError(
                        f"Onshape server error ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                        response_text=response.text,
                    )

                raise OnshapeAPIError(
                    f"Unexpected Onshape API response ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response_text=response.text,
                )

            except httpx.RequestError as exc:
                if retries_remaining > 0:
                    retries_remaining -= 1
                    time.sleep(backoff_delay)
                    backoff_delay *= 2.0
                    continue
                raise OnshapeAPIError(f"Network transport error calling {path}: {exc}") from exc

    def check_connection(self) -> bool:
        """Verify API connectivity and authentication against Onshape session or user endpoint."""
        try:
            # Use /api/users/sessioninfo or /api/documents as connectivity check
            resp = self._request("GET", "/api/users/sessioninfo")
            return "id" in resp or "name" in resp
        except OnshapeAuthenticationError:
            return False
        except Exception as exc:
            logger.info("Connection check failed: %s", exc)
            return False

    def get_document(self, document_id: str) -> dict[str, Any]:
        """Fetch metadata for a document."""
        return self._request("GET", f"/api/documents/{document_id}")

    def get_document_versions(self, document_id: str) -> list[dict[str, Any]]:
        """List all immutable committed versions for a document."""
        res = self._request("GET", f"/api/documents/d/{document_id}/versions")
        return res if isinstance(res, list) else res.get("items", [])

    def get_document_workspaces(self, document_id: str) -> list[dict[str, Any]]:
        """List all workspaces/branches for a document."""
        res = self._request("GET", f"/api/documents/d/{document_id}/workspaces")
        return res if isinstance(res, list) else res.get("items", [])

    def get_assembly_definition(
        self,
        document_id: str,
        wvm_type: str,
        wvm_id: str,
        element_id: str,
        include_instances: bool = True,
    ) -> dict[str, Any]:
        """Retrieve complete assembly structure, subassemblies, parts, and occurrences."""
        path = f"/api/assemblies/d/{document_id}/{wvm_type}/{wvm_id}/e/{element_id}"
        params = {
            "includeInstances": str(include_instances).lower(),
            "includeParts": "true",
            "includeSubassemblies": "true",
        }
        return self._request("GET", path, params=params)

    def get_assembly_mass_properties(
        self,
        document_id: str,
        wvm_type: str,
        wvm_id: str,
        element_id: str,
    ) -> dict[str, Any]:
        """Retrieve physical mass properties (mass, centroid, inertia tensor) for the assembly."""
        path = f"/api/assemblies/d/{document_id}/{wvm_type}/{wvm_id}/e/{element_id}/massproperties"
        return self._request("GET", path)

    def get_assembly_bounding_boxes(
        self,
        document_id: str,
        wvm_type: str,
        wvm_id: str,
        element_id: str,
    ) -> dict[str, Any]:
        """Retrieve overall 3D bounding extents for the assembly."""
        path = f"/api/assemblies/d/{document_id}/{wvm_type}/{wvm_id}/e/{element_id}/boundingboxes"
        return self._request("GET", path)

    def get_element_metadata(
        self,
        document_id: str,
        wvm_type: str,
        wvm_id: str,
        element_id: str,
    ) -> dict[str, Any]:
        """Retrieve custom metadata properties for the element."""
        path = f"/api/metadata/d/{document_id}/{wvm_type}/{wvm_id}/e/{element_id}"
        return self._request("GET", path)

    def get_parts_metadata(
        self,
        document_id: str,
        wvm_type: str,
        wvm_id: str,
        element_id: str,
    ) -> list[dict[str, Any]]:
        """Retrieve metadata (material, part number, revision) for parts within the element."""
        path = f"/api/metadata/d/{document_id}/{wvm_type}/{wvm_id}/e/{element_id}/p"
        res = self._request("GET", path)
        return res if isinstance(res, list) else res.get("items", [])
