"""
Shared utilities for the Simple Assembly Factory model.

Import from any script:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import utils

    cfg = utils.load_config()          # default: config.yaml next to this file
    cfg = utils.load_config(some_path) # explicit path
"""

import os

import yaml

_MODEL_ROOT     = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_MODEL_ROOT, "config.yaml")


def load_config(config_path: str = _DEFAULT_CONFIG) -> dict:
    """
    Load and return the parsed YAML config.

    Parameters
    ----------
    config_path : path to the YAML file.
                  Defaults to config.yaml in the model root directory.
    """
    try:
        with open(config_path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"config.yaml not found at {config_path} — "
            "run from the model root or pass an explicit config_path."
        ) from None
