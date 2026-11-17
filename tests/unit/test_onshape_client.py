"""Unit tests for Onshape authentication, client retry, and error handling."""

import httpx
import pytest

from app.connectors.onshape.auth import (
    format_rfc1123_date,
    generate_nonce,
    generate_onshape_hmac_headers,
    generate_onshape_oauth_headers,
)
from app.connectors.onshape.client import (
    OnshapeAuthenticationError,
    OnshapeClient,
    OnshapeNotFoundError,
    OnshapeRateLimitError,
)


def test_hmac_header_generation():
    """Verify HMAC headers include Date, On-Nonce, and proper Authorization format."""
    headers = generate_onshape_hmac_headers(
        method="GET",
        path="/api/documents/123",
        query_params={"includeWorkspaces": "true"},
        access_key="test_access_key",
        secret_key="test_secret_key",
        date_str="Tue, 17 Nov 2026 12:00:00 GMT",
        nonce="1234567890123456789012345",
    )
    assert headers["Date"] == "Tue, 17 Nov 2026 12:00:00 GMT"
    assert headers["On-Nonce"] == "1234567890123456789012345"
    assert headers["Authorization"].startswith("On test_access_key:HmacSHA256:")
    assert headers["Accept"] == "application/vnd.onshape.v1+json; charset=UTF-8;qs=0.1"


def test_oauth_header_generation():
    """Verify OAuth Bearer header generation."""
    headers = generate_onshape_oauth_headers("mock_oauth_bearer_token")
    assert headers["Authorization"] == "Bearer mock_oauth_bearer_token"


def test_nonce_and_date_helpers():
    """Verify nonce length and RFC 1123 date format."""
    nonce = generate_nonce(25)
    assert len(nonce) == 25
    date_str = format_rfc1123_date()
    assert "GMT" in date_str


def test_client_authentication_error():
    """Verify OnshapeAuthenticationError is raised on 401."""
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"message": "Invalid API key"}, request=request)
    )
    client = OnshapeClient(
        base_url="https://cad.onshape.com",
        access_key="bad_key",
        secret_key="bad_secret",
        transport=mock_transport,
    )
    with pytest.raises(OnshapeAuthenticationError, match="Onshape authentication failed"):
        client.get_document("doc-123")


def test_client_not_found_error():
    """Verify OnshapeNotFoundError is raised on 404."""
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"message": "Document not found"}, request=request)
    )
    client = OnshapeClient(
        base_url="https://cad.onshape.com",
        access_key="key",
        secret_key="secret",
        transport=mock_transport,
    )
    with pytest.raises(OnshapeNotFoundError, match="Onshape resource not found"):
        client.get_document("nonexistent_doc")


def test_client_rate_limit_retry_exhausted():
    """Verify OnshapeRateLimitError is raised when 429 retries are exhausted."""
    call_count = 0

    def rate_limit_handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "0.01"},
            json={"message": "Too Many Requests"},
            request=request,
        )

    mock_transport = httpx.MockTransport(rate_limit_handler)
    client = OnshapeClient(
        base_url="https://cad.onshape.com",
        access_key="key",
        secret_key="secret",
        max_retries=1,
        transport=mock_transport,
    )
    with pytest.raises(OnshapeRateLimitError, match="Rate limit exceeded"):
        client.get_document("doc-123")
    assert call_count == 2  # initial + 1 retry
