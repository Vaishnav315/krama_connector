"""Unit tests for change detection and Onshape webhook signature verification."""

import hmac
import uuid

from app.connectors.onshape.adapter import OnshapeConnector
from app.models.document import LinkedDocument
from app.services.change_detection import ChangeDetectionService


def test_webhook_signature_verification_valid():
    """Verify that a valid HMAC-SHA256 signature for an Onshape webhook payload passes."""
    webhook_secret = "whsec_test_secret_key_12345"
    payload = b'{"event":"onshape.model.lifecycle.changed","documentId":"65a1f2b3c4d5e6f7a8b9c0d1","versionId":"9c4d6e8a23f5b7a9c1d3f5b7"}'

    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        payload,
        "sha256",
    ).hexdigest()

    is_valid = ChangeDetectionService.verify_webhook_signature(
        payload_bytes=payload,
        signature_header=signature,
        webhook_secret=webhook_secret,
    )
    assert is_valid is True


def test_webhook_signature_verification_tampered_payload():
    """Verify that payload tampering causes webhook signature verification to fail."""
    webhook_secret = "whsec_test_secret_key_12345"
    original_payload = b'{"event":"onshape.model.lifecycle.changed","documentId":"65a1f2b3c4d5e6f7a8b9c0d1"}'
    tampered_payload = b'{"event":"onshape.model.lifecycle.changed","documentId":"attacker_modified_id"}'

    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        original_payload,
        "sha256",
    ).hexdigest()

    is_valid = ChangeDetectionService.verify_webhook_signature(
        payload_bytes=tampered_payload,
        signature_header=signature,
        webhook_secret=webhook_secret,
    )
    assert is_valid is False


def test_webhook_signature_verification_invalid_secret_or_empty():
    """Verify that an incorrect secret or empty headers fail securely."""
    payload = b'{"event":"ping"}'
    assert ChangeDetectionService.verify_webhook_signature(payload, "", "secret") is False
    assert ChangeDetectionService.verify_webhook_signature(payload, "sig", "") is False
    assert ChangeDetectionService.verify_webhook_signature(payload, "invalid_sig", "secret") is False


def test_check_for_changes_new_version():
    """Verify change detection identifies when a new document version is released."""
    connector = OnshapeConnector(use_fixtures=True)
    detector = ChangeDetectionService(connector)

    # Document last synced with v1, but latest version in fixtures is v3
    doc = LinkedDocument(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        document_id="65a1f2b3c4d5e6f7a8b9c0d1",
        element_id="43210fedcba9876543210fed",
        last_synced_version_id="7a2e4b8f01c3d5e7a9b0c1d2",
        last_synced_microversion_id="8b3f5c9e12d4a6f8b0c2e4a6",
    )

    change_info = detector.check_for_changes(doc)
    assert change_info["has_changes"] is True
    assert "Newer version detected" in change_info["reason"]


def test_check_for_changes_already_up_to_date():
    """Verify change detection returns false when document matches the latest committed version."""
    connector = OnshapeConnector(use_fixtures=True)
    detector = ChangeDetectionService(connector)

    # Find latest version by createdAt
    versions = connector.get_versions("65a1f2b3c4d5e6f7a8b9c0d1")
    latest = max(versions, key=lambda v: v.get("createdAt", ""))

    doc = LinkedDocument(
        id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        document_id="65a1f2b3c4d5e6f7a8b9c0d1",
        element_id="43210fedcba9876543210fed",
        last_synced_version_id=latest["id"],
        last_synced_microversion_id=latest.get("microversion"),
    )

    change_info = detector.check_for_changes(doc)
    assert change_info["has_changes"] is False
    assert "up to date" in change_info["reason"]
