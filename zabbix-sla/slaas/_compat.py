"""Reuse of the published zabbix-alerting release (v1.0.1): imported, never modified or copied.

Zabbix API client, read-only guard, environment identity protection and the strict YAML loader come from there so the
two projects cannot drift apart on safety behaviour.
"""
import os
import sys

_ALERTING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "zabbix-alerting")
if os.path.isdir(_ALERTING) and _ALERTING not in sys.path:
    sys.path.insert(0, _ALERTING)

from netalert import config as _nconfig            # noqa: E402,F401
from netalert import envsafety                      # noqa: E402,F401
from netalert.zbx import (ApiUnavailable, HttpTransport, ReadOnlyViolation, ZabbixClient,   # noqa: E402,F401
                          ZabbixError, is_write_method)

UniqueKeyLoader = _nconfig.UniqueKeyLoader
ConfigError = _nconfig.ConfigError
