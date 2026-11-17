"""Change detection service for Onshape document versions and microversions.

Implements polling-based version comparison to prevent redundant syncs,
and provides webhook signature validation and event handling structures.
References:
- https://onshape-public.github.io/docs/app-dev/webhooks/
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from app.connectors.onshape.adapter import OnshapeConnector
from app.models.document import LinkedDocument

logger = logging.getLogger(__name__)


class ChangeDetectionService:
    """Detects CAD design updates via version/microversion polling and webhook notifications."""

    def __init__(self, connector: OnshapeConnector):
        self.connector = connector

    def check_for_changes(self, doc: LinkedDocument) -> dict[str, Any]:
        """Poll Onshape document versions to determine if a newer version or microversion exists.

        Returns:
            Dictionary with has_changes (bool), current_version, latest_version,
            and explanation.
        """
        versions = self.connector.get_versions(doc.document_id)
        if not versions:
            return {
                "has_changes": False,
                "reason": "No versions found for document",
                "last_synced_version": doc.last_synced_version_id,
            }

        # Most recent version is typically the first or highest version in the list
        latest_version = versions[0]
        latest_version_id = latest_version.get("id")
        latest_microversion = latest_version.get("microversion")

        has_version_change = (
            doc.last_synced_version_id is None
            or doc.last_synced_version_id != latest_version_id
        )
        has_microversion_change = (
            latest_microversion is not None
            and doc.last_synced_microversion_id != latest_microversion
        )

        has_changes = has_version_change or has_microversion_change

        return {
            "has_changes": has_changes,
            "document_id": doc.document_id,
            "element_id": doc.element_id,
            "last_synced_version_id": doc.last_synced_version_id,
            "last_synced_microversion_id": doc.last_synced_microversion_id,
            "latest_version_id": latest_version_id,
            "latest_version_name": latest_version.get("name"),
            "latest_microversion_id": latest_microversion,
            "reason": (
                "Newer version detected"
                if has_changes
                else "Document is up to date with last synced version"
            ),
        }

    @staticmethod
    def verify_webhook_signature(
        payload_bytes: bytes,
        signature_header: str,
        webhook_secret: str,
    ) -> bool:
        """Validate Onshape webhook HMAC-SHA256 signature.

        Onshape webhooks include an HMAC signature header to verify authenticity.
        """
        if not signature_header or not webhook_secret:
            return False

        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            payload_bytes,
            "sha256",
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature_header)
