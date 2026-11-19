#!/usr/bin/env python3
"""KRAMA Live Watcher for FreeCAD Bridge.

Runs in a normal terminal (outside FreeCAD). Polls live_state.json for
changes written by the FreeCAD observer macro, then:

  1. Calls FreeCADConnector.extract_snapshot() to build a KRAMA Snapshot.
  2. On first file: stores it as the baseline.
  3. On subsequent files: calls SnapshotDiffEngine.compare(baseline, new).
  4. Sends the snapshot to intake_files() (KRAMA ingestion stub).
  5. Prints a detailed, human-readable change report to the terminal.

Usage
-----
  cd /Users/vaishnav/Desktop/freecad_api_test/freecad_krama_bridge
  python krama_watcher.py

Then in FreeCAD:
  1. Open AssemblyExample1.FCStd
  2. Run freecad_observer_bridge.FCMacro  (Macro → Execute Macro…)
  3. Move any component in the 3D view
  4. Watch this terminal detect and report the change automatically.

Flags
-----
  --poll-interval N   Seconds between file-stat checks (default 0.5)
  --no-baseline-lock  Re-baseline on every file update (useful for demos)
  --verbose           Print full Snapshot JSON on each update
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import sys
import time
import uuid
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Resolve KRAMA package and its .venv dependencies on sys.path
# ---------------------------------------------------------------------------
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
_KRAMA_ROOT = None
for candidate in [
    os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "..")),
    os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "..", "krama_connector")),
    os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "..", "krama_onshape_connector")),
]:
    if os.path.exists(os.path.join(candidate, "app", "schemas")):
        _KRAMA_ROOT = candidate
        break

if not _KRAMA_ROOT:
    _KRAMA_ROOT = os.path.normpath(os.path.join(_BRIDGE_DIR, "..", "..", "krama_onshape_connector"))

if _KRAMA_ROOT not in sys.path:
    sys.path.insert(0, _KRAMA_ROOT)

_venv_site_packages = glob.glob(os.path.join(_KRAMA_ROOT, ".venv", "lib", "python*", "site-packages"))
for _sp in _venv_site_packages:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

# Now import KRAMA and bridge modules
from app.ingestion.intake import intake_files  # noqa: E402
from app.schemas.diff import SnapshotDiff  # noqa: E402
from app.schemas.snapshot import Snapshot  # noqa: E402
from app.services.diff_service import SnapshotDiffEngine  # noqa: E402

sys.path.insert(0, _BRIDGE_DIR)
from freecad_connector import FreeCADConnector  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WATCH_FILE = os.path.join(_BRIDGE_DIR, "live_state.json")
_PROJECT_ID = uuid.UUID("00000000-cafe-babe-beef-ca0da000001a")

# ANSI colour codes
_GRN = "\033[92m"
_RED = "\033[91m"
_YEL = "\033[93m"
_CYN = "\033[96m"
_BLD = "\033[1m"
_DIM = "\033[2m"
_RST = "\033[0m"

SEPARATOR = f"{_DIM}{'─' * 72}{_RST}"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S UTC")


def _fmt_vec(v: list[float] | None, precision: int = 6) -> str:
    if v is None:
        return "None"
    return "[" + ", ".join(f"{x:.{precision}f}" for x in v) + "]"


def _fmt_transform(t: list[float] | None) -> str:
    """Pretty-print a 4×4 row-major transform matrix."""
    if not t or len(t) != 16:
        return str(t)
    rows = []
    for i in range(4):
        row = t[i * 4:(i + 1) * 4]
        rows.append("  [" + ", ".join(f"{v:9.5f}" for v in row) + "]")
    return "\n" + "\n".join(rows)


def _euclidean(v1: list[float], v2: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def _translation_from_transform(t: list[float]) -> list[float]:
    """Extract [tx, ty, tz] from row-major 4×4 (indices 3, 7, 11)."""
    return [t[3], t[7], t[11]]


def _print_diff_report(diff: SnapshotDiff, verbose: bool = False) -> None:
    print(SEPARATOR)
    print(f"{_BLD}{_CYN}KRAMA CHANGE REPORT  [{_ts()}]{_RST}")
    print(SEPARATOR)
    print(f"  Base snapshot  : {diff.base_snapshot_id[:8]}…  ({diff.base_version_name})")
    print(f"  New snapshot   : {diff.target_snapshot_id[:8]}…  ({diff.target_version_name})")
    print()

    # ── Summary ──────────────────────────────────────────────────────────
    s = diff.summary
    any_change = any(v > 0 for v in s.values())
    if not any_change:
        print(f"  {_GRN}✓ No changes detected.{_RST}")
        print(SEPARATOR)
        return

    print(f"  {_BLD}Summary{_RST}")
    for key, val in s.items():
        colour = _GRN if val == 0 else _YEL
        print(f"    {key:35s}: {colour}{val}{_RST}")
    print()

    # ── Moved instances ───────────────────────────────────────────────────
    if diff.moved_instances:
        print(f"  {_BLD}{_YEL}MOVED COMPONENTS ({len(diff.moved_instances)}){_RST}")
        for mi in diff.moved_instances:
            old_t = mi.old_transform or []
            new_t = mi.new_transform or []

            # Translation shift in metres
            if len(old_t) == 16 and len(new_t) == 16:
                old_pos_m = _translation_from_transform(old_t)
                new_pos_m = _translation_from_transform(new_t)
                shift_m = _euclidean(old_pos_m, new_pos_m)
                shift_mm = shift_m * 1000.0
                print(f"    {_BLD}{mi.name}{_RST}  (instance_id: {mi.instance_id})")
                print(f"      component_id : {mi.component_id}")
                print(f"      Δ translation: {shift_mm:.3f} mm  ({shift_m:.6f} m)")
                print(f"      Old position : {_fmt_vec(old_pos_m)} m")
                print(f"      New position : {_fmt_vec(new_pos_m)} m")
                if verbose:
                    print(f"      Old transform: {_fmt_transform(old_t)}")
                    print(f"      New transform: {_fmt_transform(new_t)}")
            else:
                print(f"    {_BLD}{mi.name}{_RST}  — transform changed")
            print()

    # ── Added instances ───────────────────────────────────────────────────
    if diff.added_instances:
        print(f"  {_BLD}{_GRN}ADDED COMPONENTS ({len(diff.added_instances)}){_RST}")
        for ai in diff.added_instances:
            print(f"    + {ai.name}  (instance_id: {ai.instance_id})")
        print()

    # ── Removed instances ─────────────────────────────────────────────────
    if diff.removed_instances:
        print(f"  {_BLD}{_RED}REMOVED COMPONENTS ({len(diff.removed_instances)}){_RST}")
        for ri in diff.removed_instances:
            print(f"    - {ri.name}  (instance_id: {ri.instance_id})")
        print()

    # ── Component-level changes ───────────────────────────────────────────
    if diff.changed_components:
        print(f"  {_BLD}COMPONENT DEFINITION CHANGES ({len(diff.changed_components)}){_RST}")
        for cd in diff.changed_components:
            print(f"    {_BLD}{cd.name}{_RST}  ({cd.component_id})")
            if cd.mass_change:
                mc = cd.mass_change
                print(f"      mass: {mc.old_value} → {mc.new_value}  [{mc.classification}]")
            if cd.center_of_mass_change:
                cc = cd.center_of_mass_change
                print(f"      CoM : {_fmt_vec(cc.old_value, 4)} → {_fmt_vec(cc.new_value, 4)}  [{cc.classification}]")
            if cd.bounding_box_change:
                print(f"      Bounding box changed  [{cd.bounding_box_change.classification}]")
            for pch in cd.property_changes:
                print(f"      {pch.property_name}: {pch.old_value!r} → {pch.new_value!r}")
            for cpch in cd.custom_property_changes:
                print(f"      custom.{cpch.property_name}: {cpch.old_value!r} → {cpch.new_value!r}")
        print()

    # ── Assembly-level delta ──────────────────────────────────────────────
    ad = diff.assembly_delta
    if ad.extents_changed:
        print(f"  {_BLD}ASSEMBLY EXTENTS CHANGED{_RST}")
        if ad.old_extents:
            print(f"    Old: {_fmt_vec(ad.old_extents.min_point, 4)} → {_fmt_vec(ad.old_extents.max_point, 4)}")
        if ad.new_extents:
            print(f"    New: {_fmt_vec(ad.new_extents.min_point, 4)} → {_fmt_vec(ad.new_extents.max_point, 4)}")
        print()

    if ad.center_of_mass_shift_distance is not None:
        shift_mm = ad.center_of_mass_shift_distance * 1000.0
        cls_label = ad.center_of_mass_classification
        print(f"  {_BLD}GEOMETRIC CENTROID SHIFT{_RST}: {shift_mm:.3f} mm  [{cls_label}]")
        print(f"    {_DIM}(Geometric centroid = volume-weighted B-Rep centroid, not physical CoM){_RST}")
        print()

    # ── Indeterminate properties ──────────────────────────────────────────
    if diff.indeterminate_properties and verbose:
        print(f"  {_DIM}INDETERMINATE ({len(diff.indeterminate_properties)} properties could not be compared){_RST}")

    if diff.warnings:
        for w in diff.warnings:
            print(f"  {_YEL}⚠  {w}{_RST}")
        print()

    print(SEPARATOR)


def _print_snapshot_summary(snap: Snapshot, label: str = "Snapshot") -> None:
    """Print a compact snapshot summary."""
    print(SEPARATOR)
    print(f"{_BLD}{_CYN}{label}  [{_ts()}]{_RST}")
    print(SEPARATOR)
    print(f"  snapshot_id  : {snap.snapshot_id[:8]}…")
    print(f"  source       : {snap.source}")
    print(f"  document     : {snap.document.document_name}")
    print(f"  version      : {snap.document.version_name}")
    print(f"  instances    : {len(snap.assembly.instances)}")
    print(f"  components   : {len(snap.components)}")
    if snap.assembly_mass_properties:
        vol = snap.assembly_mass_properties.volume
        com = snap.assembly_mass_properties.center_of_mass
        if vol is not None:
            print(f"  total volume : {vol * 1e9:.2f} mm³  ({vol:.6e} m³)")
        if com is not None:
            com_mm = [v * 1000 for v in com]
            print(f"  geom. CoM    : {_fmt_vec(com_mm, 2)} mm  (geometric centroid)")
    if snap.assembly.overall_extents:
        ext = snap.assembly.overall_extents
        dims_mm = [d * 1000 for d in ext.dimensions]
        print(f"  extents      : {_fmt_vec(dims_mm, 1)} mm  (W×D×H)")
    print(f"  warnings     : {len(snap.warnings)}")
    print(SEPARATOR)


# ---------------------------------------------------------------------------
# Watcher main loop
# ---------------------------------------------------------------------------

class LiveWatcher:
    """Polls live_state.json and fires KRAMA diff on every detected change."""

    def __init__(
        self,
        poll_interval: float = 0.5,
        rebaseline: bool = False,
        verbose: bool = False,
    ):
        self.poll_interval = poll_interval
        self.rebaseline = rebaseline
        self.verbose = verbose
        self.connector = FreeCADConnector(watch_file=_WATCH_FILE)
        self.diff_engine = SnapshotDiffEngine(
            spatial_tolerance=1e-5,   # 10 µm in metres ≈ 0.01 mm
            mass_tolerance=1e-4,
        )
        self._baseline_snap: Snapshot | None = None
        self._last_mtime: float = 0.0
        self._update_count: int = 0

    def _get_mtime(self) -> float:
        try:
            return os.stat(_WATCH_FILE).st_mtime
        except FileNotFoundError:
            return 0.0

    def _ingest(self, snap: Snapshot) -> None:
        """Send snapshot to KRAMA intake_files (ingestion stub)."""
        try:
            files = snap.partition_for_intake()
            metadata = {
                f_name: {
                    "source": "freecad",
                    "snapshot_id": snap.snapshot_id,
                    "version_id": snap.document.version_id,
                    "extracted_at": snap.extracted_at.isoformat(),
                }
                for f_name, _ in files
            }
            run = intake_files(
                project_id=_PROJECT_ID,
                files=files,
                source="connector",
                metadata_by_source_file=metadata,
            )
            status_colour = _GRN if run.status == "completed" else _DIM
            print(
                f"  {_DIM}KRAMA intake:{_RST} run_id={str(run.run_id)[:8]}…  "
                f"status={status_colour}{run.status}{_RST}  "
                f"files={run.file_count}"
            )
        except Exception as exc:
            print(f"  {_YEL}⚠  intake_files error: {exc}{_RST}")

        # Persist snapshot audit record to SQLAlchemy database
        try:
            from app.database import SessionLocal, init_db
            from app.models.connection import Connection
            from app.models.document import LinkedDocument
            from app.models.project import Project
            from app.models.snapshot import SnapshotRecord

            init_db()
            with SessionLocal() as db:
                conn_id = "conn_freecad_live"
                if not db.query(Connection).filter(Connection.id == conn_id).first():
                    db.add(Connection(
                        id=conn_id,
                        name="FreeCAD Desktop Bridge",
                        base_url="local://freecad",
                        access_key_masked="FREECAD_LOCAL",
                    ))
                    db.commit()

                proj_id = str(_PROJECT_ID)
                if not db.query(Project).filter(Project.id == proj_id).first():
                    db.add(Project(id=proj_id, name="FreeCAD Bridge Project"))
                    db.commit()

                doc_id = snap.document.document_id or "freecad_live_doc"
                if not db.query(LinkedDocument).filter(LinkedDocument.id == doc_id).first():
                    db.add(LinkedDocument(
                        id=doc_id,
                        project_id=proj_id,
                        connection_id=conn_id,
                        document_id=doc_id,
                        element_id="live_assembly",
                    ))
                    db.commit()

                record = SnapshotRecord(
                    id=snap.snapshot_id,
                    project_id=proj_id,
                    document_id=doc_id,
                    version_id=snap.document.version_id,
                    version_name=snap.document.version_name,
                    element_id="live_assembly",
                    total_mass=snap.assembly_mass_properties.mass if snap.assembly_mass_properties else None,
                    instance_count=len(snap.assembly.instances),
                    component_count=len(snap.components),
                    payload_json=snap.to_deterministic_json(),
                    extracted_at=snap.extracted_at,
                )
                db.add(record)
                db.commit()
                print(f"  {_DIM}Database:{_RST} Snapshot persisted to SQLite ({_BLD}krama_connector.db{_RST})")
        except Exception:
            pass

    def _handle_update(self) -> None:
        """Read the new watch file, build Snapshot, run diff."""
        self._update_count += 1
        try:
            snap = self.connector.extract_snapshot(
                document_reference=_WATCH_FILE,
                version_reference="live",
            )
        except Exception as exc:
            print(f"{_RED}[{_ts()}] Snapshot build error: {exc}{_RST}")
            return

        if self._baseline_snap is None:
            # First snapshot — establish baseline
            print()
            _print_snapshot_summary(snap, label="INITIAL SNAPSHOT — BASELINE ESTABLISHED")
            self._ingest(snap)
            self._baseline_snap = snap
            print(f"\n{_GRN}✓ Baseline set. Now move a component in FreeCAD…{_RST}\n")
            return

        # Subsequent snapshot — diff against baseline
        diff = self.diff_engine.compare(self._baseline_snap, snap)
        self._ingest(snap)
        _print_diff_report(diff, verbose=self.verbose)

        any_change = any(v > 0 for v in diff.summary.values())
        if any_change and self.rebaseline:
            self._baseline_snap = snap
            print(f"{_DIM}  [rebaseline mode] New snapshot promoted to baseline.{_RST}\n")

    def run(self) -> None:
        print(f"\n{_BLD}{'=' * 72}{_RST}")
        print(f"{_BLD}  KRAMA FreeCAD Live Watcher{_RST}")
        print(f"{'=' * 72}")
        print(f"  Watch file   : {_WATCH_FILE}")
        print(f"  KRAMA root   : {_KRAMA_ROOT}")
        print(f"  Poll interval: {self.poll_interval}s")
        print(f"  Project ID   : {_PROJECT_ID}")
        print(f"{'=' * 72}\n")

        if not self.connector.connect():
            print(f"{_YEL}⚠  Watch file not found yet: {_WATCH_FILE}{_RST}")
            print("   Run the observer macro in FreeCAD first.\n   Waiting…\n")

        print(f"{_DIM}[{_ts()}] Polling started. Press Ctrl+C to stop.{_RST}")

        try:
            while True:
                mtime = self._get_mtime()
                if mtime != self._last_mtime and mtime > 0:
                    self._last_mtime = mtime
                    self._handle_update()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print(f"\n{_DIM}[{_ts()}] Watcher stopped by user. "
                  f"Processed {self._update_count} update(s).{_RST}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="KRAMA FreeCAD Live Watcher — detects FreeCAD changes via KRAMA diff engine"
    )
    parser.add_argument(
        "--poll-interval", type=float, default=0.5,
        help="Seconds between file-stat checks (default: 0.5)"
    )
    parser.add_argument(
        "--rebaseline", action="store_true",
        help="Promote each new snapshot to baseline (shows incremental diffs)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print full transform matrices and all indeterminate properties"
    )
    args = parser.parse_args()
    LiveWatcher(
        poll_interval=args.poll_interval,
        rebaseline=args.rebaseline,
        verbose=args.verbose,
    ).run()


if __name__ == "__main__":
    main()
