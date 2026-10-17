import importlib
import json
import sys
from pathlib import Path


def _get_version() -> str:
    # Try repo root, then backend/ or container paths
    candidates = [
        Path(__file__).resolve().parents[2] / "version.json",
        Path(__file__).resolve().parents[1] / "version.json",
        Path(__file__).resolve().parent / "version.json",
        Path("/app/version.json"),
    ]
    for p in candidates:
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                    if "version" in data:
                        return data["version"]
            except Exception:
                pass
    return "0.1.0"


__version__ = _get_version()

# Register sys.modules alias for backward compatibility
sys.modules.setdefault("forge", sys.modules[__name__])


class _ForgeImportHook:
    """Redirect legacy `forge.*` imports to `alberto.*` transparently."""

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname == "forge" or fullname.startswith("forge."):
            alberto_name = "alberto" + fullname[5:]
            try:
                mod = importlib.import_module(alberto_name)
                sys.modules[fullname] = mod
                return getattr(mod, "__spec__", None)
            except ImportError:
                return None
        return None


if not any(isinstance(x, _ForgeImportHook) for x in sys.meta_path):
    sys.meta_path.insert(0, _ForgeImportHook())
