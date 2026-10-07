#!/usr/bin/env bash
# Offline test suite (no Zabbix needed).
cd "$(dirname "${BASH_SOURCE[0]}")/.." && exec python3 -m unittest discover -s tests -t . "$@"
