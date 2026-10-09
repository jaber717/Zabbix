"""Independent, ephemeral LAB read-only acceptance runner. Password arrives on stdin.

No credential is printed or written. This runner never exposes a Zabbix write
method; configuration.importcompare is the documented read-only comparison API.
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://192.168.1.91:8443/api_jsonrpc.php"
CERT = "/etc/pki/tls/certs/zabbix-web.crt"
ALLOWED = {
    "apiinfo.version", "user.login", "usermacro.get", "configuration.importcompare",
}


def rpc(method, params, token=""):
    if method not in ALLOWED:
        raise RuntimeError("read-only method allowlist refused " + method)
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    headers = {"Content-Type": "application/json-rpc"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=CERT), timeout=20) as response:
        result = json.load(response)
    if "error" in result:
        err = result["error"]
        return {"error": {"code": err.get("code"), "message": err.get("message"), "data": err.get("data")}}
    return {"result": result["result"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("identity", "labsim", "audit-probe", "action-plan", "template-plan", "validate-lab", "importcompare"))
    parser.add_argument("--definition", default="cisco-iosxe")
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        raise SystemExit("No password supplied on stdin")
    version = rpc("apiinfo.version", {})
    if version.get("result") != "7.0.30":
        raise SystemExit("LAB API version mismatch: " + str(version))
    login = rpc("user.login", {"username": "nbzsync", "password": password})
    password = None
    if "result" not in login:
        raise SystemExit("nbzsync login failed: " + str(login))
    token = login["result"]
    identity = rpc("usermacro.get", {"output": ["macro", "value"], "globalmacro": True,
                                    "filter": {"macro": "{$NETOPS.ENVIRONMENT}"}}, token)
    if "result" not in identity:
        raise SystemExit("Bearer authorization failed: " + str(identity))
    if len(identity["result"]) != 1 or identity["result"][0]["value"] != "lab":
        raise SystemExit("LAB identity macro did not confirm lab")
    print("LAB_IDENTITY=PASS API_VERSION=7.0.30 AUTH=nbzsync_ephemeral_session", flush=True)
    if args.mode == "identity":
        return
    if args.mode == "importcompare":
        sys.path.insert(0, str(ROOT))
        from hwh import template, vendordefs
        definition = vendordefs.load_dir(str(ROOT / "vendors"))[args.definition]
        source = json.dumps(template.build(definition))
        result = rpc("configuration.importcompare", {"format": "json", "rules": template.IMPORT_RULES,
                                                     "source": source}, token)
        if "error" in result:
            print("IMPORTCOMPARE_ERROR=" + json.dumps(result["error"], sort_keys=True))
            raise SystemExit(1)
        value = result["result"]
        print("IMPORTCOMPARE_PASS definition=%s result_type=%s result_count=%s" % (
            args.definition, type(value).__name__, len(value) if hasattr(value, "__len__") else "n/a"))
        print("IMPORTCOMPARE_RESULT=" + json.dumps(value, sort_keys=True)[:1000])
        return
    env = os.environ.copy()
    env["ZABBIX_HARDWARE_URL_LAB"] = URL
    env["ZABBIX_HARDWARE_TOKEN_LAB"] = token
    env["SSL_CERT_FILE"] = CERT
    py = sys.executable
    common = [py, str(ROOT / "hardware_audit.py"), "--base", str(ROOT), "--env", "lab"]
    commands = {
        "labsim": common + ["labsim"],
        "audit-probe": common + ["synthetic", "audit-probe"],
        "action-plan": common + ["action", "plan"],
        "template-plan": common + ["template", "plan", "--definition", args.definition],
        "validate-lab": ["bash", str(ROOT / "release" / "validate-lab.sh"), str(ROOT)],
    }
    completed = subprocess.run(commands[args.mode], cwd=str(ROOT), env=env, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
