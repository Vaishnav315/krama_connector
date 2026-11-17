"""Integration tests for FastAPI connector endpoints and database persistence."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.ingestion.intake import reset_ingestion_cache
from app.main import app

# In-memory test SQLite engine
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("USE_MOCK_ONSHAPE", "true")
    # Clear settings cache so ENVIRONMENT='test' takes effect
    from app.config import get_settings
    get_settings.cache_clear()
    Base.metadata.create_all(bind=test_engine)
    reset_ingestion_cache()
    yield
    Base.metadata.drop_all(bind=test_engine)
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient):
    """Verify GET /health returns service health status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_connect_onshape_account(client: TestClient):
    """Verify POST /connections/onshape registers connection and masks secrets."""
    payload = {
        "name": "Production Onshape",
        "base_url": "https://cad.onshape.com",
        "access_key": "ABCDEFGHIJKL12345678",
        "secret_key": "SUPER_SECRET_KEY_NOT_LOGGED",
    }
    response = client.post("/connections/onshape", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Production Onshape"
    assert data["provider"] == "onshape"
    assert data["access_key_masked"] == "ABCD...5678"
    assert "SUPER_SECRET" not in str(data)  # Secret must not be in response


def test_full_project_sync_lifecycle(client: TestClient):
    """Verify full end-to-end flow: connect -> link document -> sync v1 -> sync v2 -> list -> get -> diff -> changes."""
    project_id = str(uuid.uuid4())

    # 1. Connect account
    conn_res = client.post(
        "/connections/onshape",
        json={"name": "KRAMA Test Onshape", "access_key": "KEY1234567890"},
    )
    assert conn_res.status_code == 201
    conn_id = conn_res.json()["id"]

    # 2. Link document
    link_res = client.post(
        f"/projects/{project_id}/documents",
        json={
            "connection_id": conn_id,
            "document_id": "doc-robot-arm-001",
            "element_id": "elem-asm-top-001",
        },
    )
    assert link_res.status_code == 201
    doc_id = link_res.json()["id"]

    # 3. Trigger sync for Version 1
    sync1_res = client.post(
        f"/projects/{project_id}/sync",
        json={
            "document_id": doc_id,
            "version_id": "ver-release-1.0",
        },
    )
    assert sync1_res.status_code == 200
    sync1_data = sync1_res.json()
    assert sync1_data["status"] == "completed"
    assert sync1_data["version_id"] == "ver-release-1.0"
    snap1_id = sync1_data["snapshot_id"]
    assert snap1_id is not None

    # 4. Trigger deduplicated sync (identical version without force)
    sync_dedup_res = client.post(
        f"/projects/{project_id}/sync",
        json={
            "document_id": doc_id,
            "version_id": "ver-release-1.0",
            "force": False,
        },
    )
    assert sync_dedup_res.status_code == 200
    assert sync_dedup_res.json()["status"] == "deduplicated"

    # 5. Trigger sync for Version 2 (with real design changes)
    sync2_res = client.post(
        f"/projects/{project_id}/sync",
        json={
            "document_id": doc_id,
            "version_id": "ver-release-2.0",
        },
    )
    assert sync2_res.status_code == 200
    sync2_data = sync2_res.json()
    assert sync2_data["status"] == "completed"
    assert sync2_data["version_id"] == "ver-release-2.0"
    snap2_id = sync2_data["snapshot_id"]
    assert snap2_id is not None
    assert snap2_id != snap1_id

    # 6. List snapshots for project
    list_res = client.get(f"/projects/{project_id}/snapshots")
    assert list_res.status_code == 200
    snaps_list = list_res.json()
    assert len(snaps_list) == 2

    # 7. Retrieve single snapshot
    get_res = client.get(f"/snapshots/{snap1_id}")
    assert get_res.status_code == 200
    snapshot_doc = get_res.json()
    assert snapshot_doc["snapshot_id"] == snap1_id
    assert snapshot_doc["document"]["version_id"] == "ver-release-1.0"
    assert len(snapshot_doc["assembly"]["instances"]) == 22

    # 8. Compare snapshots via GET /snapshots/{id}/diff/{other_id}
    diff_res = client.get(f"/snapshots/{snap1_id}/diff/{snap2_id}")
    assert diff_res.status_code == 200
    diff_data = diff_res.json()
    assert diff_data["base_snapshot_id"] == snap1_id
    assert diff_data["target_snapshot_id"] == snap2_id
    assert len(diff_data["added_instances"]) >= 1
    assert len(diff_data["removed_instances"]) >= 1
    assert diff_data["assembly_delta"]["mass_delta"] is not None

    # 9. Check for source changes via GET /projects/{id}/changes
    changes_res = client.get(f"/projects/{project_id}/changes")
    assert changes_res.status_code == 200
    changes_data = changes_res.json()
    assert changes_data["documents_checked"] == 1
    assert len(changes_data["changes"]) == 1
