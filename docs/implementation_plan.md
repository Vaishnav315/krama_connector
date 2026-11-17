# KRAMA Onshape Engineering Connector — Implementation Plan & Handoff Guide

## Mission & Scope
This project implements a production-grade, read-only CAD connector for Onshape that interfaces with KRAMA's engineering ingestion pipeline (`intake_files`).
It extracts nested assembly structures, part identities, mass properties (with explicit units and provenance), geometric bounding boxes, custom properties, and version tracking. It performs deterministic snapshot diffing and change detection.

---

## Architecture Overview
```
krama_onshape_connector/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── connections.py    # POST /connections/onshape
│   │   │   ├── projects.py       # POST /projects/{project_id}/documents
│   │   │   ├── sync.py           # POST /projects/{project_id}/sync
│   │   │   ├── snapshots.py      # GET /projects/{project_id}/snapshots, GET /snapshots/{id}
│   │   │   └── diffs.py          # GET /snapshots/{id}/diff/{other_id}, GET /projects/{id}/changes
│   │   └── router.py             # Main API router
│   ├── config.py                 # Pydantic Settings & env config
│   ├── database.py               # SQLAlchemy async/sync session management (SQLite/PostgreSQL)
│   ├── connectors/
│   │   ├── base.py               # CADConnector abstract base class
│   │   └── onshape/
│   │       ├── client.py         # Concrete Onshape REST client (HMAC + OAuth + rate limiting)
│   │       ├── auth.py           # Onshape HMAC-SHA256 signature generator & OAuth handler
│   │       ├── documents.py      # Document & workspace metadata extraction
│   │       ├── assemblies.py     # Assembly hierarchy, repeated instances, occurrence flattening
│   │       ├── properties.py     # Part metadata & custom properties
│   │       ├── mass_properties.py# Mass, CoM, inertia, units & provenance tracker
│   │       └── versions.py       # Version / microversion tracking
│   ├── models/
│   │   ├── base.py               # Declarative base & timestamps
│   │   ├── connection.py         # Onshape connection records (safe credential refs)
│   │   ├── project.py            # KRAMA project representation
│   │   ├── document.py           # Linked Onshape document
│   │   ├── sync_run.py           # Sync audit trail & status
│   │   └── snapshot.py           # Snapshot metadata & file references
│   ├── schemas/
│   │   ├── assembly.py           # Assembly & Component hierarchy schemas
│   │   ├── component.py          # Part identity, material, extents
│   │   ├── mass_properties.py    # Mass, CoM, Moments of Inertia, Provenance
│   │   ├── snapshot.py           # Canonical Snapshot JSON schema
│   │   └── diff.py               # Snapshot diff schema
│   ├── services/
│   │   ├── sync_service.py       # Sync orchestration & snapshot ingestion
│   │   ├── snapshot_service.py   # Snapshot assembly, storage & retrieval
│   │   ├── diff_service.py       # Deterministic snapshot comparison engine
│   │   └── change_detection.py   # Version/microversion polling & webhook handling
│   ├── ingestion/
│   │   └── intake.py             # KRAMA intake_files stub interface
│   └── main.py                   # FastAPI application initialization & OpenAPI docs
├── tests/
│   ├── conftest.py               # Pytest fixtures, test DB, mock clients
│   ├── fixtures/                 # Realistic recorded JSON fixtures
│   │   ├── assembly_v1.json      # Public robot arm/suspension (nested >=2 levels, >=15 parts)
│   │   ├── assembly_v2.json      # Modified version (changed mass, modified parts, added/removed)
│   │   ├── assembly_v3.json      # Further version (material changes, altered extents)
│   │   ├── parts_metadata.json   # Part properties & materials
│   │   └── mass_properties.json  # Raw Onshape mass properties responses
│   ├── unit/                     # Schemas, diff engine, hierarchy parser, provenance
│   └── integration/              # FastAPI endpoints, DB persistence, intake stub, mock client
├── examples/
│   └── snapshots/                # Representative output JSON snapshots
│       ├── snapshot_v1.json
│       └── snapshot_v2.json
├── docs/
│   ├── design_note.md            # Comprehensive 3-page engineering design note
│   └── implementation_plan.md    # This plan & execution tracker
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions: lint (ruff) + test (pytest)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Detailed Milestone Checklist & Status

### Legend:
- [ ] Not started
- [x] Completed and verified
- [>] Currently in progress

---

### Module 1: Project Setup, Configuration & Dependencies
- [x] Requirements specification (`requirements.txt`) with exact dependency bounds.
- [x] `.gitignore` configuration ensuring `.env`, `.venv`, `*.db`, caches are ignored.
- [x] Application configuration in `app/config.py` using `pydantic-settings`.
- [x] Ruff configuration (`pyproject.toml` or `ruff.toml`).
- [x] Test runner setup (`pytest.ini` in `pyproject.toml`).

### Module 2: Core Domain Schemas & Ingestion Interface
- [ ] Canonical snapshot schema (`app/schemas/snapshot.py`):
  - Document & exact version identity (`document_id`, `version_id`, `version_name`, `microversion_id`, `element_id`, `extracted_at`).
  - Units specification (`length`, `mass`, `inertia`).
  - Assembly tree hierarchy (`children`, instance counts, occurrences).
  - Component definitions (stable id, name, part_number, revision, material).
  - Mass properties (mass, centre of mass, moments of inertia, explicit provenance, missing values without zero substitution).
  - Spatial extents / bounding box (local vs world-space).
  - Custom properties (name, value, type, source).
  - Warnings & missing value explanations.
- [ ] Snapshot Diff schema (`app/schemas/diff.py`).
- [ ] KRAMA Intake stub (`app/ingestion/intake.py`) with exact signature:
  `intake_files(*, project_id: uuid.UUID, files: list[tuple[str, bytes]], source: Literal["connector"], metadata_by_source_file: dict[str, dict[str, Any]] | None = None) -> IngestionRun`

### Module 3: CAD Connector Abstraction & Onshape Client
- [ ] Abstract base class `CADConnector` (`app/connectors/base.py`).
- [ ] Onshape Authentication (`app/connectors/onshape/auth.py`):
  - HMAC-SHA256 request signing per Onshape specifications (`On-Nonce`, `Date`, Authorization header).
  - OAuth2 bearer token support.
- [ ] Onshape REST Client (`app/connectors/onshape/client.py`):
  - Base URL, timeout handling, error handling, rate limiting (HTTP 429 backoff).
  - Document and version metadata retrieval.
  - Assembly definition retrieval (`/api/assemblies/d/...`).
  - Metadata and custom properties retrieval (`/api/metadata/d/...`).
  - Mass properties retrieval (`/api/assemblies/d/.../massproperties`).
  - Bounding box retrieval (`/api/assemblies/d/.../boundingboxes`).

### Module 4: Realistic Onshape Assembly Fixtures & Parsing
- [ ] Recorded fixtures for an authentic public Onshape assembly:
  - Nested subassemblies (at least 2 levels).
  - At least 15 part instances.
  - Realistic materials, part numbers, bounding boxes, mass properties.
- [ ] Version 1, Version 2 (modified mass, parts, subassemblies), Version 3 fixtures.
- [ ] Assembly tree transformer:
  - Distinction between part definitions and instances.
  - Correct parent-child occurrence path resolution.
  - Aggregated instance counts alongside separate individual instances.
  - Unit preservation and provenance recording.
  - Handling of missing properties (never default to 0).

### Module 5: Deterministic Snapshot Diff Engine
- [ ] Diff engine (`app/services/diff_service.py`):
  - Added / removed / changed instances.
  - Quantity modifications.
  - Material, part number, revision changes.
  - Mass, center of mass, moments of inertia changes with numerical tolerance.
  - Bounding box extents changes.
  - Provenance & source distinction (detected from source vs inferred vs missing).
  - Comprehensive warnings when source data is missing.

### Module 6: Persistence Layer (SQLAlchemy Models & Database)
- [ ] `app/database.py`: Session engine supporting SQLite (local/test) and PostgreSQL (production).
- [ ] Models (`app/models/`):
  - `Connection`: Stored credentials reference (no raw secrets logged).
  - `Project`: KRAMA project linking.
  - `Document`: Linked Onshape document & element.
  - `SyncRun`: Status, duration, records synced, error logs.
  - `Snapshot`: Versioned snapshot record and file references.

### Module 7: Sync Orchestration & Change Detection
- [ ] Change detection service (`app/services/change_detection.py`):
  - Microversion and version tracking.
  - Polling mechanism to detect changes without unnecessary syncs.
  - Webhook payload validator and event handling structure.
- [ ] Sync service (`app/services/sync_service.py`):
  - Orchestrates fetching from connector adapter.
  - Generates canonical snapshot JSON & partitioned files (`assembly_snapshot.json`, `components.json`, `properties.json`, `provenance.json`, `diff.json`).
  - Calls `intake_files` stub with strict contract.
  - Persists snapshot and updates sync status.

### Module 8: FastAPI Application & Endpoints
- [ ] `GET /health`
- [ ] `POST /connections/onshape`
- [ ] `POST /projects/{project_id}/documents`
- [ ] `POST /projects/{project_id}/sync`
- [ ] `GET /projects/{project_id}/snapshots`
- [ ] `GET /snapshots/{snapshot_id}`
- [ ] `GET /snapshots/{snapshot_id}/diff/{other_snapshot_id}`
- [ ] `GET /projects/{project_id}/changes`
- [ ] Interactive Swagger UI at `/docs`.

### Module 9: Comprehensive Test Suite
- [ ] Snapshot schema validation tests.
- [ ] Hierarchy parsing & repeated instance preservation tests.
- [ ] Missing property tests (unavailable mass property remains missing, NOT zero).
- [ ] Diff engine tests (additions, removals, property changes, unchanged snapshots).
- [ ] KRAMA intake stub contract tests.
- [ ] SQLAlchemy persistence & CRUD tests.
- [ ] FastAPI endpoint integration tests.
- [ ] Mocked Onshape API tests (error handling, 429 rate limit, HMAC signing).
- [ ] Single test command `pytest` passes with 100% green without credentials.

### Module 10: CI/CD Workflow & Engineering Hygiene
- [ ] GitHub Actions workflow (`.github/workflows/ci.yml`).
- [ ] Ruff linting passing with zero errors.
- [ ] `.env.example` verified with safe placeholders.
- [ ] Verification that no secrets exist in Git.

### Module 11: Documentation & Design Note
- [ ] `examples/snapshots/`: Realistic example snapshots generated and committed.
- [ ] `README.md`: Comprehensive documentation covering setup, architecture, endpoints, testing, live vs mocked status, and limitations.
- [ ] `docs/design_note.md`: 3-page rigorous engineering design note addressing Flow Engineering research, Onshape API evaluation, alternatives, risks & mitigations, production monitoring, and heavier CAD/PLM systems.

---

## Instructions for Resuming Agents
If this execution context is interrupted or transferred to another agent:
1. Consult this file (`docs/implementation_plan.md`) to inspect current module status.
2. Run `pytest` and `ruff check .` to verify current health.
3. Check Git log (`git log -n 5 --oneline`) to inspect the last milestone commit.
4. Pick up the next unchecked task, implement it, test it, update the checklist in this file, and commit using conventional commit format.
