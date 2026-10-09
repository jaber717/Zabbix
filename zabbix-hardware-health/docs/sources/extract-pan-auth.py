import json, sys, yaml, hashlib
raw = open("template_net_paloalto_pa440_http.yaml", "rb").read()
d = yaml.safe_load(raw)
t = d["zabbix_export"]["templates"][0]
want = {"pan.pa440.environmentals.get": "env", "pan.pa440.ha.get": "ha"}
out = {"source": {"file": "templates/net/paloalto/paloalto_pa440/template_net_paloalto_pa440_http.yaml",
                  "commit": "4a89781bcdc9f7cc59c721786baa8f95c3dd7135", "sha256_of_file": hashlib.sha256(raw).hexdigest(),
                  "template_name": t["name"], "extracted_by": "docs/sources/extract-pan-auth.py equivalent (yaml.safe_load, fields below verbatim)"},
       "items": {}, "macros": {}}
for it in t["items"]:
    if it["key"] in want:
        out["items"][it["key"]] = dict((k, it.get(k)) for k in ("type", "authtype", "username", "password", "url", "timeout", "query_fields", "status_codes", "http_proxy", "preprocessing", "request_method", "post_type", "verify_peer", "verify_host"))
for m in t["macros"]:
    if m["macro"] in ("{$PAN.PA440.API.URL}", "{$PAN.PA440.USER}", "{$PAN.PA440.PASSWORD}", "{$PAN.PA440.TIMEOUT}", "{$PAN.PA440.HTTP_PROXY}"):
        out["macros"][m["macro"]] = dict((k, m.get(k)) for k in ("value", "type", "description"))
print(json.dumps(out, indent=2, sort_keys=True))
