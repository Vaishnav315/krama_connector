# KRAMA Onshape Engineering Connector

A production-grade, read-only CAD/PLM engineering connector between **Onshape** and **KRAMA's engineering knowledge graph ingestion pipeline**.

This connector extracts multi-level nested assembly hierarchies, unique component definitions, instance occurrences, mass properties (with explicit units and provenance tracking), 3D spatial extents, and custom properties. It computes deterministic snapshot diffs across design revisions and submits structured, partitioned file artifacts to KRAMA's `intake_files` ingestion interface.

---

## Architecture Overview

```
                                  +-----------------------------+
                                  |   FastAPI REST Service      |
                                  |   (Health, Sync, Diffs)     |
                                  +--------------+--------------+
                                                 |
                                  +--------------v--------------+
                                  |   CADConnector Interface    |
                                  +--------------+--------------+
                                                 |
                    +----------------------------+----------------------------+
                    |                                                         |
     +--------------v--------------+                           +--------------v--------------+
     |   Onshape REST Client       |                           |   Offline Fixture Adapter   |
     |   - HMAC-SHA256 Signing     |                           |   - 6-DOF Robot Manipulator |
     |   - OAuth2 Bearer Tokens    |                           |   - 2+ Subassembly Levels   |
     |   - 429 Rate Limit Backoff  |                           |   - 22 Part Instances       |
     +--------------+--------------+                           +--------------+--------------+
                    |                                                         |
                    +----------------------------+----------------------------+
                                                 |
                                  +--------------v--------------+
                                  |  Canonical Snapshot Engine  |
                                  |  - Assembly Hierarchy       |
                                  |  - Provenance & Units       |
                                  |  - Missing Values Audit     |
                                  +--------------+--------------+
                                                 |
                                  +--------------v--------------+
                                  | Partitioned File Artifacts  |
                                  | - assembly_snapshot.json    |
                                  | - components.json           |
                                  | - properties.json           |
                                  | - provenance.json           |
                                  +--------------+--------------+
                                                 |
                                  +--------------v--------------+
                                  |   KRAMA Ingestion Stub      |
                                  |   intake_files()            |
                                  +-----------------------------+
```

---

## Repository Structure

```
krama_onshape_connector/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── connections.py    # POST /connections/onshape
│   │   │   ├── diffs.py          # GET /snapshots/{id}/diff/{other_id}, GET /projects/{id}/changes
│   │   │   ├── health.py         # GET /health
│   │   │   ├── projects.py       # POST /projects/{project_id}/documents
│   │   │   ├── snapshots.py      # GET /projects/{project_id}/snapshots, GET /snapshots/{id}
│   │   │   └── sync.py           # POST /projects/{project_id}/sync
│   │   └── router.py             # Main API router
│   ├── config.py                 # Pydantic Settings & environment loader
│   ├── database.py               # SQLAlchemy SQLite/PostgreSQL session management
│   ├── main.py                   # FastAPI application initialization & OpenAPI docs
│   ├── connectors/
│   │   ├── base.py               # Abstract CADConnector interface
│   │   └── onshape/
│   │       ├── adapter.py        # Concrete Onshape CADConnector implementation
│   │       ├── assemblies.py     # Assembly hierarchy, occurrences, and transform mapping
│   │       ├── auth.py           # HMAC-SHA256 signature generator & OAuth2 headers
│   │       ├── client.py         # HTTP REST client with 429 rate limit backoff
│   │       ├── mass_properties.py# Mass, CoM, inertia, units, and provenance parsing
│   │       └── properties.py     # Component metadata and missing value auditor
│   ├── ingestion/
│   │   └── intake.py             # KRAMA intake_files stub interface
│   ├── models/                   # SQLAlchemy ORM models (Connection, Document, Project, Snapshot, SyncRun)
│   ├── schemas/                  # Pydantic v2 domain schemas (Assembly, Component, Diff, Snapshot)
│   └── services/
│       ├── change_detection.py   # Polling-based version/microversion detector & webhook validator
│       ├── diff_service.py       # Deterministic snapshot comparison engine
│       ├── snapshot_service.py   # Snapshot querying and diff orchestration
│       └── sync_service.py       # Snapshot extraction and KRAMA intake dispatcher
├── docs/
│   ├── design_note.md            # Comprehensive 3-page engineering design note
│   └── implementation_plan.md    # Multi-agent handoff tracker and milestone checklist
├── examples/
│   └── snapshots/                # Representative canonical snapshot and diff outputs
│       ├── diff_v1_v2.json
│       ├── snapshot_v1.json
│       └── snapshot_v2.json
├── tests/
│   ├── fixtures/                 # Realistic recorded Onshape assembly JSON fixtures
│   │   ├── assembly_v1.json      # Base 6-DOF robotic arm (22 instances, 2 subassembly levels)
│   │   ├── assembly_v2.json      # Modified assembly (Ti elbow joint, F/T sensor, -2 screws)
│   │   ├── bounding_boxes_v1.json
│   │   ├── bounding_boxes_v2.json
│   │   ├── mass_properties_v1.json
│   │   ├── mass_properties_v2.json
│   │   ├── metadata_v1.json
│   │   └── versions.json
│   ├── integration/              # FastAPI endpoint and DB persistence tests
│   └── unit/                     # Unit tests for client, diffs, hierarchy, schemas, intake
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions: Ruff linting + Pytest matrix
├── requirements.txt              # Production and test dependencies
├── pyproject.toml                # Ruff and Pytest configuration
├── .env.example                  # Safe configuration template
└── README.md
```

---

## Technology Choices

* **Language**: Python 3.11+ (tested on Python 3.14).
* **Web Framework**: **FastAPI** — high performance, type-safe validation, interactive OpenAPI/Swagger documentation.
* **Data Validation & Schemas**: **Pydantic v2** — strict type enforcement, deterministic JSON serialization, explicit provenance tracking.
* **Persistence**: **SQLAlchemy 2.0** — clean ORM mapping, dialect independence supporting **SQLite** (local development and automated testing) and **PostgreSQL** (production).
* **HTTP Client**: **httpx** — modern HTTP transport supporting connection pooling, timeouts, and automated 429 rate limit backoff.
* **Testing & Quality**: **Pytest** and **Ruff** — lightning-fast linting and comprehensive automated testing.

---

## Installation & Setup

### 1. Clone Repository & Setup Virtual Environment
```bash
git clone https://github.com/Vaishnav315/krama_onshape_connector.git
cd krama_onshape_connector

# Activate the virtual environment
source .venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to create your local `.env`:
```bash
cp .env.example .env
```
*(The repository is configured to safely fall back to recorded fixtures if no live credentials are provided).*

---

## Running the Automated Test Suite

Run the entire test suite with one single command without requiring Onshape credentials or an external database:

```bash
pytest
```

To run with Ruff code quality inspection:
```bash
ruff check .
pytest -v
```

---

## Starting the FastAPI Server

Start the API server locally using Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Accessing Swagger & OpenAPI Documentation
* **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
* **OpenAPI JSON Specification**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## API Usage Guide

### 1. Check Service Health
```bash
curl -X GET "http://localhost:8000/health"
```

### 2. Connect an Onshape Account
```bash
curl -X POST "http://localhost:8000/connections/onshape" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering Team Onshape",
    "base_url": "https://cad.onshape.com",
    "access_key": "YOUR_ACCESS_KEY",
    "secret_key": "YOUR_SECRET_KEY"
  }'
```
*Note: Secret keys are masked in database storage and never exposed in responses (`ABCD...1234`).*

### 3. Link an Onshape Document to a KRAMA Project
```bash
curl -X POST "http://localhost:8000/projects/b0e5d8a0-2f3b-4896-857c-2e6f42b8cf1a/documents" \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": "<CONNECTION_UUID>",
    "document_id": "doc-robot-arm-001",
    "element_id": "elem-asm-top-001"
  }'
```

### 4. Trigger Synchronization & Ingestion
```bash
curl -X POST "http://localhost:8000/projects/b0e5d8a0-2f3b-4896-857c-2e6f42b8cf1a/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "doc-robot-arm-001",
    "version_id": "ver-release-1.0",
    "force": false
  }'
```
* The connector extracts the assembly, computes mass properties, audits missing values, saves the snapshot, partitions artifacts (`assembly_snapshot.json`, `components.json`, `properties.json`, `provenance.json`), and calls KRAMA's `intake_files` stub.
* Re-syncing the same version returns `status: "deduplicated"` without redundant processing.

### 5. Retrieve Snapshots
```bash
# List all snapshots for a project
curl -X GET "http://localhost:8000/projects/b0e5d8a0-2f3b-4896-857c-2e6f42b8cf1a/snapshots"

# Get a complete canonical snapshot by ID
curl -X GET "http://localhost:8000/snapshots/<SNAPSHOT_UUID>"
```

### 6. Compare Two Snapshots (Diff Engine)
```bash
curl -X GET "http://localhost:8000/snapshots/<BASE_SNAPSHOT_UUID>/diff/<TARGET_SNAPSHOT_UUID>"
```
Returns structured differences:
* Added / removed instances.
* Changed quantities per component.
* Material and revision modifications.
* Delta in total assembly mass and center-of-mass shift.
* Indeterminate properties resulting from missing source data.

### 7. Check for Upstream Source Changes
```bash
curl -X GET "http://localhost:8000/projects/b0e5d8a0-2f3b-4896-857c-2e6f42b8cf1a/changes"
```

---

## Implementation Status & Transparency

| Capability | Status | Description |
| :--- | :--- | :--- |
| **CADConnector Abstraction** | **Implemented & Tested** | Abstract base class in `app/connectors/base.py`. Rest of application is vendor-agnostic. |
| **Assembly Hierarchy Parsing** | **Implemented & Tested** | Recursive subassembly resolution (2 levels), 22 part occurrences, occurrence transforms. |
| **Repeated Instances & Aggregation** | **Implemented & Tested** | Preserves individual instances distinctly while providing aggregated instance counts. |
| **Mass Properties & Provenance** | **Implemented & Tested** | Mass, volume, centroid, inertia tensor. Explicit provenance (`computed_from_geometry`, etc.). |
| **Missing Values Auditing** | **Implemented & Tested** | Missing mass/material/revision remains `None` (never 0.0) with explicit explanation records. |
| **Deterministic Diff Engine** | **Implemented & Tested** | Compares added/removed parts, quantity shifts, mass deltas, and CoM shifts. |
| **KRAMA Ingestion Stub** | **Implemented & Tested** | Submits partitioned files to `intake_files(*, project_id, files, source="connector")`. |
| **FastAPI REST Endpoints** | **Implemented & Tested** | All 8 required endpoints implemented and covered with integration tests. |
| **SQLAlchemy Persistence** | **Implemented & Tested** | SQLite supported out of the box; PostgreSQL supported via `DATABASE_URL`. |
| **Onshape HMAC & OAuth2 Client** | **Implemented & Tested** | Authentic HMAC-SHA256 signature calculation, nonce generation, and 429 rate limit backoff. |
| **Live Onshape API Verification** | **Unverified Live** | Student and Free Onshape accounts cannot provision API keys or OAuth apps ("account not currently available to create API keys"). Tested against authentic recorded fixtures. |

---

## Known Limitations

1. **Live Onshape API Credentials**: Onshape Free and Student tier accounts currently display plan restrictions preventing the creation of API keys and Developer Applications. The REST client implementation is fully authentic and complies with Onshape's signing specification, but live network requests against Onshape production servers have not been executed.
2. **Webhooks in Local Environments**: Real-time webhook reception requires a public HTTPS URL (e.g. ngrok or cloud hosting). In local environments, polling `/versions` serves as the primary change detection mechanism.
3. **Flexible/Dynamic Subassemblies**: Part positions within flexible subassemblies are resolved using Onshape's top-level occurrence transform table; subassemblies with internal mechanical degrees of freedom reflect the default configured state.
