#!/usr/bin/env python3
"""
Assembly Factory — UI entry point.

Launches the Streamlit UI.

Usage
-----
  python -m 2026-05-18_validation_model   # from src/models/
  streamlit run ui/home.py                # equivalent, from model root
"""

import os
import subprocess
import sys

_MODEL_ROOT = os.path.dirname(os.path.abspath(__file__))
_HOME_PY    = os.path.join(_MODEL_ROOT, "ui", "home.py")


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "streamlit", "run", _HOME_PY],
        cwd=_MODEL_ROOT,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
