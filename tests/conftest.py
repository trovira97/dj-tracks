"""
tests/conftest.py
==================
Shared pytest fixtures and path bootstrap.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable.
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
