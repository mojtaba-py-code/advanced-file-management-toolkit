"""Configuration loading with sensible, secure defaults.

Configuration is layered: built-in defaults are always present, and an
optional ``settings.yaml`` (or a user-supplied file) can override individual
keys. Missing files never crash the toolkit — the defaults simply win.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from utils.exceptions import ConfigError

# PyYAML is a declared dependency, but the loader degrades gracefully when it
# is missing. The name is typed as Any deliberately: whether mypy treats the
# None fallback as an error depends on whether PyYAML ships type information on
# the platform being checked, which differs between Linux, macOS and Windows.
yaml: Any
try:  # pragma: no cover - the except branch only runs without PyYAML
    import yaml as _pyyaml

    yaml = _pyyaml
except ImportError:  # pragma: no cover - exercised only without PyYAML
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

# The single source of truth for defaults. Everything the toolkit reads has an
# entry here so behaviour is predictable even with no config file present.
DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "dry_run": False,
        "recursive": True,
        "threads": 4,
        "skip_hidden": False,
        "follow_symlinks": False,
    },
    "security": {
        # When non-empty, all operations are confined to these roots.
        "allowed_roots": [],
    },
    "hashing": {
        "algorithm": "sha256",
        # Read files in chunks so multi-GB files never load into memory.
        "chunk_size": 1048576,  # 1 MiB
    },
    "backup": {
        "destination": "backups",
        "compression": True,
        "verify": True,
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
        "file": "toolkit.log",
        "max_bytes": 5242880,  # 5 MiB
        "backup_count": 5,
        "console": True,
    },
    "reporting": {
        "directory": "reports",
        "default_format": "json",
    },
    "database": {
        "path": "database/history.db",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load configuration, merging any YAML file over the built-in defaults.

    Parameters
    ----------
    path:
        Optional explicit config file. When ``None`` the default
        ``config/settings.yaml`` is used if it exists.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        if path is not None:
            # A path the user explicitly asked for must exist.
            raise ConfigError(f"Config file not found: {config_path}")
        return copy.deepcopy(DEFAULT_CONFIG)

    if yaml is None:  # pragma: no cover
        raise ConfigError("PyYAML is required to read configuration files")

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Failed to read config {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError(f"Config root must be a mapping: {config_path}")

    return _deep_merge(DEFAULT_CONFIG, loaded)


class Config:
    """Convenience wrapper offering dotted access with fallbacks."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data if data is not None else copy.deepcopy(DEFAULT_CONFIG)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        return cls(load_config(path))

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Fetch ``"section.key"`` returning *default* when absent."""
        node: Any = self._data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self._data.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def data(self) -> dict[str, Any]:
        return self._data
