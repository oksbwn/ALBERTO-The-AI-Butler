"""Alberto API - local-first AI Home Butler."""

__version__ = "0.1.0"

import sys
import importlib

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
