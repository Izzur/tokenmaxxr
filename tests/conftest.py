"""pytest config."""
import sys
from pathlib import Path

# Make `tokenmaxxr` importable when running tests from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
