#!/usr/bin/env python3
"""Render runtime-only Zabbix database configuration from a systemd credential."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import tempfile

try:
    import grp
except ImportError:  # pragma: no cover - enables platform-neutral unit tests
    grp = None


SAFE_SECRET = re.compile(r"^[A-Za-z0-9_!@%^+=.,:-]{24,128}$")


def validate_secret(value: str) -> str:
    secret = value.rstrip("\r\n")
    if not SAFE_SECRET.fullmatch(secret):
        raise ValueError("credential does not meet the safe transport policy")
    return secret


def php_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def render(mode: str, secret: str, db: dict[str, str]) -> str:
    if mode == "zabbix-server":
        return f"DBPassword={secret}\n"
    if mode == "zabbix-web":
        tls = "true" if db["tls"] == "1" else "false"
        return (
            "<?php\n"
            "$DB['TYPE'] = 'POSTGRESQL';\n"
            f"$DB['SERVER'] = {php_quote(db['host'])};\n"
            f"$DB['PORT'] = {php_quote(db['port'])};\n"
            f"$DB['DATABASE'] = {php_quote(db['name'])};\n"
            f"$DB['USER'] = {php_quote(db['user'])};\n"
            f"$DB['PASSWORD'] = {php_quote(secret)};\n"
            "$DB['SCHEMA'] = '';\n"
            f"$DB['ENCRYPTION'] = {tls};\n"
            "$ZBX_SERVER = '127.0.0.1';\n"
            f"$ZBX_SERVER_PORT = {php_quote(db['server_port'])};\n"
            f"$ZBX_SERVER_NAME = {php_quote(db['server_name'])};\n"
        )
    raise ValueError(f"unsupported render mode: {mode}")


def atomic_write(path: Path, content: str, group_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        if grp is not None:
            os.chown(temporary, 0, grp.getgrnam(group_name).gr_gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("zabbix-server", "zabbix-web"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    credential_directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    secret = validate_secret((credential_directory / "db-password").read_text(encoding="utf-8"))
    db = {
        "host": os.environ.get("ZABBIX_DB_HOST", "127.0.0.1"),
        "port": os.environ.get("ZABBIX_DB_PORT", "5432"),
        "name": os.environ.get("ZABBIX_DB_NAME", "zabbix"),
        "user": os.environ.get("ZABBIX_DB_USER", "zabbix"),
        "tls": os.environ.get("ZABBIX_DB_TLS", "0"),
        "server_port": os.environ.get("ZABBIX_SERVER_PORT", "10051"),
        "server_name": os.environ.get("ZABBIX_SERVER_NAME", "Zabbix"),
    }
    if args.mode == "zabbix-server":
        output = args.output or Path("/run/zabbix-server-credentials/db.conf")
        group_name = "zabbix"
    else:
        output = args.output or Path("/run/zabbix-web/zabbix.conf.php")
        group_name = "apache"
    atomic_write(output, render(args.mode, secret, db), group_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
