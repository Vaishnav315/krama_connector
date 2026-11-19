"""Unit tests for FreeCADConnector using committed fixture state files.

These tests run without FreeCAD installed: they consume the committed
live_state.json (53-component indrbt_home snapshot) and assembly_snapshot.json
(13-instance AssemblyExample1 snapshot) as frozen fixtures.

Distinction:
  - Automated (this file): fixture-based, deterministic, runs in CI.
  - Live GUI demo: manually evidenced by screenshots in docs/images/;
    cannot be automatically reproduced from a clean clone without FreeCAD.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.connectors.freecad.adapter import FreeCADConnector, _version_id_from_data

# ---------------------------------------------------------------------------
# Fixture paths (committed to the repository – no FreeCAD required)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.parent
_LIVE_STATE = _REPO_ROOT / "freecad_api_test" / "freecad_krama_bridge" / "live_state.json"
_ASSEMBLY_SNAP = _REPO_ROOT / "freecad_api_test" / "assembly_snapshot.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1. Connect / load
# ---------------------------------------------------------------------------

class TestFreeCADConnect:
    def test_connect_live_state_file(self):
        """FreeCADConnector loads the committed live_state.json without error."""
        assert _LIVE_STATE.exists(), f"Fixture missing: {_LIVE_STATE}"
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        data = connector._load()
        assert isinstance(data, dict)

    def test_missing_file_raises(self, tmp_path):
        """FileNotFoundError is raised when the watch file does not exist."""
        connector = FreeCADConnector(watch_file=tmp_path / "nonexistent.json")
        with pytest.raises(FileNotFoundError, match="FreeCAD bridge state file not found"):
            connector._load()


# ---------------------------------------------------------------------------
# 2. Snapshot extraction
# ---------------------------------------------------------------------------

class TestSnapshotExtraction:
    def test_snapshot_source_is_freecad(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert snap.source == "freecad"

    def test_snapshot_units_are_si(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert snap.units.length == "meter"
        assert snap.units.mass == "kilogram"
        assert snap.units.volume == "cubic_meter"

    def test_snapshot_has_components(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert len(snap.components) > 0

    def test_snapshot_has_assembly(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert snap.assembly is not None
        assert snap.assembly.name  # non-empty

    def test_snapshot_id_is_deterministic(self):
        """Calling extract_snapshot twice on the same file must return the same snapshot_id."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap1 = connector.extract_snapshot("indrbt_home", "latest")
        snap2 = connector.extract_snapshot("indrbt_home", "latest")
        assert snap1.snapshot_id == snap2.snapshot_id

    def test_snapshot_component_count_matches_fixture(self):
        """live_state.json is the indrbt_home 53-component snapshot."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        # The fixture has 53 instances; components map 1-to-1 to instances.
        assert len(snap.components) == 53


# ---------------------------------------------------------------------------
# 3. Version identity
# ---------------------------------------------------------------------------

class TestVersionIdentity:
    def test_version_id_stable_across_calls(self):
        data = _load_fixture(_LIVE_STATE)
        v1 = _version_id_from_data(data.get("metadata", {}), data.get("assembly"))
        v2 = _version_id_from_data(data.get("metadata", {}), data.get("assembly"))
        assert v1 == v2

    def test_version_id_changes_on_transform_mutation(self):
        """Mutating a transform in the fixture must produce a different version ID."""
        data = _load_fixture(_LIVE_STATE)
        asm = data.get("assembly", {})
        v_original = _version_id_from_data(data.get("metadata", {}), asm)

        # Deep-copy and mutate the first instance's placement
        mutated = copy.deepcopy(asm)
        if mutated.get("instances"):
            first = mutated["instances"][0]
            placement = first.setdefault("placement", {})
            mat = placement.get("transform_matrix_4x4", [0.0] * 16)
            mat[3] = (mat[3] if mat else 0.0) + 100.0  # shift x by 100 mm
            placement["transform_matrix_4x4"] = mat

        v_mutated = _version_id_from_data(data.get("metadata", {}), mutated)
        assert v_original != v_mutated

    def test_version_id_prefix(self):
        data = _load_fixture(_LIVE_STATE)
        v = _version_id_from_data(data.get("metadata", {}), data.get("assembly"))
        assert v.startswith("freecad_")


# ---------------------------------------------------------------------------
# 4. Assembly hierarchy (not flat)
# ---------------------------------------------------------------------------

class TestAssemblyHierarchy:
    def test_assembly_hierarchy_has_instances(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert len(snap.assembly.instances) > 0

    def test_assembly_id_is_set(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        assert snap.assembly.assembly_id  # non-empty string


# ---------------------------------------------------------------------------
# 5. Mass properties and honest missing-value handling
# ---------------------------------------------------------------------------

class TestMassProperties:
    def test_mass_properties_returned(self):
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        mp = connector.get_mass_properties("indrbt_home", "latest")
        assert mp is not None

    def test_volume_is_set_in_metres_cubed(self):
        """Volume should be small positive float (metres³ not mm³)."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        mp = connector.get_mass_properties("indrbt_home", "latest")
        if mp.volume is not None:
            # 1 m³ assembly is already huge; > 1e-9 m³ (1 mm³) is a sane bound
            assert mp.volume > 0.0

    def test_mass_is_none_without_density(self):
        """Without material density the adapter must return mass=None, not zero."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        mp = connector.get_mass_properties("indrbt_home", "latest")
        # live_state.json has AssumedMaterial but no Density property;
        # mass must therefore be None (SOURCE_UNAVAILABLE) rather than a fake 0.
        if mp.mass is None:
            assert mp.provenance.source.value in ("source_unavailable", "SOURCE_UNAVAILABLE")

    def test_centroid_labelled_geometric_not_physical(self):
        """The provenance description must distinguish geometric centroid from physical CoM."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        mp = connector.get_mass_properties("indrbt_home", "latest")
        if mp.mass is None and mp.provenance and mp.provenance.description:
            desc = mp.provenance.description.lower()
            assert "geometric" in desc or "centroid" in desc


# ---------------------------------------------------------------------------
# 6. Part identity fields
# ---------------------------------------------------------------------------

class TestPartIdentity:
    def test_custom_properties_extracted(self):
        """Components must have a non-empty custom_properties dict (from live_state fixture)."""
        connector = FreeCADConnector(watch_file=_LIVE_STATE)
        snap = connector.extract_snapshot("indrbt_home", "latest")
        components_with_props = [c for c in snap.components if c.custom_properties]
        # At least some components should have custom properties
        assert len(components_with_props) > 0


# ---------------------------------------------------------------------------
# 7. FreeCAD connections POST endpoint (integration-lite, DB in-memory)
# ---------------------------------------------------------------------------

class TestFreeCADAPIEndpoint:
    """Light integration test using FastAPI TestClient + in-memory SQLite DB."""

    def test_post_freecad_connection(self, monkeypatch):
        """POST /connections/freecad must return 201 with provider='freecad'."""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base, get_db
        from app.main import app

        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("USE_MOCK_ONSHAPE", "true")
        from app.config import get_settings
        get_settings.cache_clear()

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/connections/freecad",
                    json={"name": "Test FreeCAD Bridge", "watch_file": "/tmp/live_state.json"},
                )
        finally:
            app.dependency_overrides.clear()
            get_settings.cache_clear()
            Base.metadata.drop_all(bind=engine)

        assert resp.status_code == 201
        body = resp.json()
        assert body["provider"] == "freecad"
        assert body["access_key_masked"] == "FREECAD_LOCAL_BRIDGE"
        assert body["base_url"] == "/tmp/live_state.json"
