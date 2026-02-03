"""Compatibility wrapper: use the admin version under `scripts/admin/`.

This file remains as a thin compatibility shim to avoid breaking external
invocations that expect `scripts/simulate_force_reindex.py`.
"""
from importlib import import_module

_mod = import_module("scripts.admin.simulate_force_reindex")

if __name__ == "__main__":
    # Delegate to admin script
    _mod.__name__ = "__main__"
    # Execute module-level main if present
    try:
        _mod.__dict__.get("main") and __import__("asyncio").run(_mod.main())
    except Exception as e:
        raise
