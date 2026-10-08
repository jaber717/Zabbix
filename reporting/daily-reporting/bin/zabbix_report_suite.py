#!/usr/bin/env python3
"""Entry point of the Zabbix Reporting Suite (PDF / XLSX / JSON). The RC2 daily report is unchanged beside it."""
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("vendor", "lib"):            # vendor/ holds the offline-installed ReportLab/openpyxl
    path = os.path.join(APP, sub)
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

from zrs.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:     # noqa: BLE001
        print("RESULT=FAIL ERROR=%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        raise SystemExit(1)
