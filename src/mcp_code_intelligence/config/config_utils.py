"""Utilities for storing and retrieving API keys.

Provides generic `get_api_key(provider, project_root)` and
`save_api_key(provider, key, project_root)` helpers. Backwards-compatible
aliases are provided for existing convenience functions and emit
DeprecationWarning when used.
"""
from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any


_KNOWN_PROVIDERS = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _credentials_path(project_root: Path | None = None) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    dirp = root / ".mcp-code-intelligence"
    dirp.mkdir(parents=True, exist_ok=True)
    return dirp / "credentials.json"


def _read_credentials(project_root: Path | None = None) -> dict[str, Any]:
    p = _credentials_path(project_root)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_credentials(data: dict[str, Any], project_root: Path | None = None) -> None:
    p = _credentials_path(project_root)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get_api_key(provider: str, project_root: Path | None = None) -> str | None:
    """Get API key for a provider.

    Order of lookup: environment variable -> credentials file. Returns None if
    not found.
    """
    prov = provider.lower()
    env_var = _KNOWN_PROVIDERS.get(prov)
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val

    creds = _read_credentials(project_root)
    return creds.get(prov)


def save_api_key(provider: str, key: str, project_root: Path | None = None) -> None:
    """Save API key for a provider to the credentials file.

    Note: environment variables are still respected and take precedence.
    """
    prov = provider.lower()
    creds = _read_credentials(project_root)
    creds[prov] = key
    _write_credentials(creds, project_root)


# Backwards-compatible aliases
def _deprecated_alias(old_name: str, new_func):
    def wrapper(*a, **kw):
        warnings.warn(f"{old_name} is deprecated; use {new_func.__name__} instead", DeprecationWarning)
        return new_func(*a, **kw)

    wrapper.__name__ = old_name
    return wrapper


def _get_openai_api_key(project_root: Path | None = None) -> str | None:
    return get_api_key("openai", project_root)


def _get_openrouter_api_key(project_root: Path | None = None) -> str | None:
    return get_api_key("openrouter", project_root)


def _save_openai_api_key(key: str, project_root: Path | None = None) -> None:
    return save_api_key("openai", key, project_root)


def _save_openrouter_api_key(key: str, project_root: Path | None = None) -> None:
    return save_api_key("openrouter", key, project_root)


# Public deprecated names (kept for compatibility)
get_openai_api_key = _deprecated_alias("get_openai_api_key", _get_openai_api_key)
get_openrouter_api_key = _deprecated_alias("get_openrouter_api_key", _get_openrouter_api_key)
save_openai_api_key = _deprecated_alias("save_openai_api_key", _save_openai_api_key)
save_openrouter_api_key = _deprecated_alias("save_openrouter_api_key", _save_openrouter_api_key)

__all__ = [
    "get_api_key",
    "save_api_key",
    "get_openai_api_key",
    "get_openrouter_api_key",
    "save_openai_api_key",
    "save_openrouter_api_key",
]
