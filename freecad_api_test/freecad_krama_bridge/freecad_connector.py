"""FreeCAD → KRAMA Connector re-export and bridge wrapper.

Re-exports FreeCADConnector from app.connectors.freecad.adapter for the standalone
freecad_api_test bridge environment.
"""

from __future__ import annotations

import glob
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_KRAMA_ROOT = None
for candidate in [
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_connector")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_onshape_connector")),
]:
    if os.path.exists(os.path.join(candidate, "app", "schemas")):
        _KRAMA_ROOT = candidate
        break

if not _KRAMA_ROOT:
    _KRAMA_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "krama_connector"))

if _KRAMA_ROOT not in sys.path:
    sys.path.insert(0, _KRAMA_ROOT)

_venv_site_packages = glob.glob(os.path.join(_KRAMA_ROOT, ".venv", "lib", "python*", "site-packages"))
for _sp in _venv_site_packages:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

sys.path.insert(0, _THIS_DIR)

from app.connectors.freecad.adapter import (  # noqa: E402
    FreeCADConnector,
    _bbox_mm_to_m,
    _mm_vec_to_m,
    _transform_mm_to_m,
    _version_id_from_data,
)

__all__ = [
    "FreeCADConnector",
    "_bbox_mm_to_m",
    "_mm_vec_to_m",
    "_transform_mm_to_m",
    "_version_id_from_data",
]
