"""Load application configuration from config.yaml."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _resolve_env_vars(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}
    return _resolve_env_vars(raw_config)


def get_embeddings_config() -> dict[str, Any]:
    cfg = load_config().get("embeddings", {})
    return {
        "model": str(cfg.get("model", "all-MiniLM-L6-v2")),
        "chroma_path": str(cfg.get("chroma_path", "./chroma_data")),
        "collection": str(cfg.get("collection", "master_resume_chunks")),
        "n_results": int(cfg.get("n_results", 5)),
    }
