"""Authentication handlers for Onshape API.

Implements official Onshape API Key HMAC-SHA256 signing and OAuth2 Bearer token authentication.
References:
- https://onshape-public.github.io/docs/auth/apikeys/
- https://onshape-public.github.io/docs/auth/oauth/
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import string
import urllib.parse
from datetime import UTC, datetime


def generate_nonce(length: int = 25) -> str:
    """Generate a cryptographically secure random alphanumeric nonce string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def format_rfc1123_date(dt: datetime | None = None) -> str:
    """Format UTC datetime into RFC 1123/2822 compliant string (e.g. 'Tue, 17 Nov 2026 12:00:00 GMT')."""
    target = dt or datetime.now(UTC)
    return target.strftime("%a, %d %b %Y %H:%M:%S GMT")


def generate_onshape_hmac_headers(
    method: str,
    path: str,
    query_params: dict[str, str] | str = "",
    access_key: str | None = None,
    secret_key: str | None = None,
    content_type: str = "application/json",
    date_str: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Generate official Onshape HMAC-SHA256 authorization headers.

    The string-to-sign in Onshape API Key authentication follows the specification:
    method (lowercase) + '\n' +
    nonce + '\n' +
    date + '\n' +
    content_type (lowercase) + '\n' +
    path (lowercase) + '\n' +
    query_string (canonical URL-encoded) + '\n'
    """
    if not access_key or not secret_key:
        raise ValueError("Both access_key and secret_key are required for HMAC authentication")

    # Canonicalize path (must begin with / and be lowercase)
    if not path.startswith("/"):
        path = "/" + path
    normalized_path = path.lower()

    # Canonicalize query string
    if isinstance(query_params, dict):
        # Sort query params for deterministic signature
        sorted_params = sorted(query_params.items())
        query_string = urllib.parse.urlencode(sorted_params)
    else:
        query_string = query_params

    # Header parameters
    date_header = date_str or format_rfc1123_date()
    nonce_header = nonce or generate_nonce(25)

    # Construct string to sign
    to_sign = (
        f"{method.lower()}\n"
        f"{nonce_header}\n"
        f"{date_header}\n"
        f"{content_type.lower()}\n"
        f"{normalized_path}\n"
        f"{query_string}\n"
    )

    # Compute HMAC-SHA256 signature
    signature = base64.b64encode(
        hmac.new(
            secret_key.encode("utf-8"),
            to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    auth_header = f"On {access_key}:HmacSHA256:{signature}"

    return {
        "Date": date_header,
        "On-Nonce": nonce_header,
        "Authorization": auth_header,
        "Content-Type": content_type,
        "Accept": "application/vnd.onshape.v1+json; charset=UTF-8;qs=0.1",
    }


def generate_onshape_oauth_headers(token: str) -> dict[str, str]:
    """Generate OAuth2 Bearer authorization headers."""
    if not token:
        raise ValueError("OAuth access token cannot be empty")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.onshape.v1+json; charset=UTF-8;qs=0.1",
    }


def get_auth_headers_for_request(
    method: str,
    path: str,
    query_params: dict[str, str] | str = "",
    access_key: str | None = None,
    secret_key: str | None = None,
    oauth_token: str | None = None,
) -> dict[str, str]:
    """Determine available authentication method and return appropriate headers.

    Priority:
    1. OAuth2 Bearer token (if provided)
    2. API Key HMAC-SHA256 (if access & secret keys provided)
    3. Fallback: unauthenticated headers (will fail on protected endpoints, used for mocks/diagnostics)
    """
    if oauth_token:
        return generate_onshape_oauth_headers(oauth_token)

    acc_key = access_key or os.getenv("ONSHAPE_ACCESS_KEY")
    sec_key = secret_key or os.getenv("ONSHAPE_SECRET_KEY")
    if acc_key and sec_key:
        return generate_onshape_hmac_headers(
            method=method,
            path=path,
            query_params=query_params,
            access_key=acc_key,
            secret_key=sec_key,
        )

    # Unauthenticated / diagnostic headers
    return {
        "Content-Type": "application/json",
        "Accept": "application/vnd.onshape.v1+json; charset=UTF-8;qs=0.1",
    }
