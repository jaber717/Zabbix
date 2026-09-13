#!/usr/bin/env python3
"""Verify Admin API login without putting credentials in argv or output."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Optional


def request(args: argparse.Namespace, method: str, params: object, auth: Optional[str] = None) -> dict:
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    if auth:
        body["auth"] = auth
    host = args.server_name if args.scheme == "https" else "127.0.0.1"
    url = f"{args.scheme}://{host}:{args.port}/api_jsonrpc.php"
    command = [
        "/usr/bin/curl", "--fail-with-body", "--silent", "--show-error",
        "--noproxy", "*",
        "--header", "Content-Type: application/json-rpc", "--data-binary", "@-",
    ]
    if args.scheme == "https":
        command.extend(["--resolve", f"{args.server_name}:{args.port}:127.0.0.1", "--cacert", args.ca_file])
    command.append(url)
    completed = subprocess.run(
        command,
        input=json.dumps(body).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("frontend API request failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("frontend API returned invalid JSON") from exc


def login(args: argparse.Namespace, password: str) -> dict:
    return request(args, "user.login", {"username": "Admin", "password": password})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-name", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--scheme", required=True, choices=("http", "https"))
    parser.add_argument("--ca-file", default="")
    args = parser.parse_args()
    password = sys.stdin.read().rstrip("\r\n")
    if not password or "\x00" in password:
        raise SystemExit("FAIL: protected Admin input is invalid")
    successful = login(args, password)
    password = ""
    auth = successful.get("result")
    if not isinstance(auth, str) or not auth:
        raise SystemExit("FAIL: configured Admin credential was rejected")
    logout = request(args, "user.logout", [], auth)
    auth = ""
    if logout.get("result") is not True:
        raise SystemExit("FAIL: Admin API session cleanup failed")
    factory = "".join(chr(value) for value in (122, 97, 98, 98, 105, 120))
    rejected = login(args, factory)
    factory = ""
    if "result" in rejected:
        raise SystemExit("FAIL: factory Admin credential is still accepted")
    print("PASS: configured Admin login accepted; factory credential rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
