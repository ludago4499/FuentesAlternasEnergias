import sys
from pathlib import Path

# Make `core.*` importable exactly as the Streamlit pages do.
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
