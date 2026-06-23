"""Empty conftest — module discovery only."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so `import bol_bot` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
