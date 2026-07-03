"""Pytest conftest. Ensures web/ and this checkout's src/ are importable.

The src/ insertion makes tests exercise THIS checkout's package even when
the venv's editable install points at another checkout (main vs. a git
worktree) -- the venv is shared, checkouts are not.
"""
import sys
from pathlib import Path

_repo_root = Path(__file__).parent.parent
for _p in (str(_repo_root / "src"), str(_repo_root)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
