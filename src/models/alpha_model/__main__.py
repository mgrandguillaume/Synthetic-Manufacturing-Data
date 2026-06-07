#!/usr/bin/env python3
"""
Assembly Factory — UI entry point.

Launches the Dash UI on http://127.0.0.1:8501

Usage
-----
  python __main__.py            # from the model root directory
  python -m alpha_model   # from src/models/
"""

import os
import sys

_MODEL_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_PY     = os.path.join(_MODEL_ROOT, "ui", "app.py")

# Add ui/ and model root to path so app.py can import store, pages, etc.
_UI_DIR = os.path.join(_MODEL_ROOT, "ui")
if _UI_DIR     not in sys.path: sys.path.insert(0, _UI_DIR)
if _MODEL_ROOT not in sys.path: sys.path.insert(0, _MODEL_ROOT)


def main() -> None:
    # Import and run the Dash app directly (avoids subprocess path issues)
    import importlib.util
    spec = importlib.util.spec_from_file_location("app", _APP_PY)
    app_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_module)
    app_module.app.run(debug=False, host="127.0.0.1", port=8501)


if __name__ == "__main__":
    main()
