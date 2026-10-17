"""Compatibility shim for legacy Forge namespace."""

import sys
import alberto

# Mirror alberto into forge
sys.modules["forge"] = alberto
__version__ = alberto.__version__
