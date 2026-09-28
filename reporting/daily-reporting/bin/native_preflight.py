#!/usr/bin/env python3
"""Read-only native Zabbix scheduled-report prerequisite check."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def rpm_installed(name: str) -> bool:
    if not shutil.which("rpm"):
        return False
    return subprocess.run(
        ["rpm", "-q", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0


def directive(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    try:
        content = path.read_text(errors="replace")
    except OSError:
        return ""
    for line in content.splitlines():
        match = re.match(rf"^\s*{re.escape(name)}\s*=\s*(.*?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            return match.group(1)
    return ""


def inspect(server_config: Path, web_config: Path) -> dict:
    chrome = next(
        (candidate for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser") if shutil.which(candidate)),
        "",
    )
    writers = directive(server_config, "StartReportWriters")
    web_service_url = directive(server_config, "WebServiceURL")
    result = {
        "server_config_readable": server_config.is_file() and os.access(server_config, os.R_OK),
        "zabbix_web_service_package": rpm_installed("zabbix-web-service"),
        "chrome_executable": chrome,
        "web_service_url": web_service_url,
        "start_report_writers": writers,
        "web_service_config_present": web_config.is_file(),
        "allowed_ip": directive(web_config, "AllowedIP"),
    }
    result["native_pdf_ready"] = bool(
        result["zabbix_web_service_package"]
        and chrome
        and web_service_url.endswith("/report")
        and writers.isdigit()
        and int(writers) > 0
        and result["web_service_config_present"]
    )
    blockers = []
    if not result["zabbix_web_service_package"]:
        blockers.append("zabbix-web-service RPM is not installed")
    if not chrome:
        blockers.append("Chrome/Chromium executable is not installed")
    if not web_service_url.endswith("/report"):
        blockers.append("WebServiceURL is missing or does not end in /report")
    if not writers.isdigit() or int(writers or 0) < 1:
        blockers.append("StartReportWriters is not configured above zero")
    if not result["web_service_config_present"]:
        blockers.append("zabbix_web_service.conf is absent")
    if server_config.is_file() and not result["server_config_readable"]:
        blockers.append("zabbix_server.conf is not readable by the current account")
    result["blockers"] = blockers
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-config", default="/etc/zabbix/zabbix_server.conf")
    parser.add_argument("--web-service-config", default="/etc/zabbix/zabbix_web_service.conf")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = inspect(Path(args.server_config), Path(args.web_service_config))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            if key != "blockers":
                print(f"{key.upper()}={value}")
        for blocker in result["blockers"]:
            print(f"WARNING={blocker}")
        print("RESULT=" + ("PASS" if result["native_pdf_ready"] else "WARNING"))
    return 0 if result["native_pdf_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
