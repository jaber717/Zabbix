"""Strict JSON configuration loader (JSON is valid YAML 1.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union


class ConfigError(ValueError):
    pass


def load_json(path: Union[str, Path]) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"invalid configuration: {Path(path).name}") from exc
    if not isinstance(data, dict):
        raise ConfigError("configuration root must be an object")
    return data


def validate_runtime(config: dict[str, Any]) -> None:
    required = ("netbox_url", "zabbix_url", "zabbix_user", "tls", "policy")
    missing = [name for name in required if name not in config]
    if missing:
        raise ConfigError(f"missing runtime keys: {','.join(missing)}")
    if not str(config["zabbix_url"]).startswith("https://"):
        raise ConfigError("zabbix_url must use https")
    if not str(config["netbox_url"]).startswith("https://"):
        allowed = bool(config["tls"].get("allow_insecure_netbox_http", False))
        if not (allowed and str(config["netbox_url"]).startswith("http://")):
            raise ConfigError("NetBox HTTP requires an explicit lab-only exception")
    budget = float(config["policy"].get("change_budget", 0.10))
    if not 0 <= budget <= 1:
        raise ConfigError("change budget must be between 0 and 1")
    required_endpoints = config["policy"].get("required_endpoints", [])
    if not required_endpoints:
        raise ConfigError("required_endpoints must fail closed, not be empty")


def validate_mappings(mappings: dict[str, Any]) -> None:
    required = ("object_types", "roles", "platforms", "sites", "eligibility")
    missing = [name for name in required if name not in mappings]
    if missing:
        raise ConfigError(f"missing mapping keys: {','.join(missing)}")
    if mappings["eligibility"].get("tag") is None and mappings["eligibility"].get("custom_field") is None:
        raise ConfigError("an explicit eligibility tag or custom field is required")
