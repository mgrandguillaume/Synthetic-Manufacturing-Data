"""
Shared helpers for the Assembly Factory Streamlit UI.

Provides:
  MODEL_ROOT   — absolute path to the model root directory
  CONFIG_PATH  — absolute path to config.yaml
  setup_path() — adds MODEL_ROOT to sys.path (idempotent)
  get(key)     — read from st.session_state
  set(key, v)  — write to st.session_state
"""

import os
import sys

import streamlit as st

# ui/ sits directly inside the model root.
MODEL_ROOT  = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CONFIG_PATH = os.path.join(MODEL_ROOT, "config.yaml")


def setup_path() -> None:
    """Add the model root to sys.path so all packages are importable."""
    if MODEL_ROOT not in sys.path:
        sys.path.insert(0, MODEL_ROOT)


def get(key: str, default=None):
    return st.session_state.get(key, default)


def set(key: str, value) -> None:
    st.session_state[key] = value
