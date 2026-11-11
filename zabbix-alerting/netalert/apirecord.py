"""Record real Zabbix API responses (read-only) and replay them as regression fixtures.

The offline model in tests/ was written from documentation. Recordings from a real Zabbix 7.0 LAB make the
discovery/coverage code run against what the server actually returns (selectHostGroups, selectHostGroupRights,
user media, trigger expressions, item tags, permission errors). Recordings are sanitized before they are written:
host names, visible names, user names and IP/DNS become stable pseudonyms everywhere in the file (including
trigger expressions), secret-looking macro values are redacted, and free-text descriptions keep only words that
matter to role detection.
"""
import copy
import json
import re

from .zbx import ZabbixError

SECRET_MACRO = re.compile(r"(?i)(pass|secret|community|auth|priv|token|key|user|credential)")
KEEP_WORDS = re.compile(r"(?i)^(isp|internet|transit|upstream|dci|inter-?dc|wan|mpls|l2vpn|vpls|metro|p2p|ptp|"
                        r"point-to-point|to|uplink|link|core|edge|stc|mobily|zain|salam|\d+g)$")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class RecordingTransport(object):
    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def send(self, payload, authenticated=True):
        resp = self.inner.send(payload, authenticated)
        self.calls.append({"method": payload["method"], "params": payload.get("params"),
                           "result": resp.get("result"), "error": resp.get("error")})
        return resp


class ReplayTransport(object):
    """Answers exactly the recorded (method, params); anything else is a regression signal."""

    def __init__(self, calls):
        self.calls = {}
        for c in calls:
            self.calls.setdefault(_key(c["method"], c["params"]), []).append(c)

    def send(self, payload, authenticated=True):
        k = _key(payload["method"], payload.get("params"))
        if k not in self.calls:
            raise ZabbixError(payload["method"], {"code": -1, "message": "NOT RECORDED",
                                                  "data": "call not in the recording - re-capture fixtures"})
        c = self.calls[k][0]
        out = {"jsonrpc": "2.0", "id": payload["id"]}
        if c.get("error"):
            out["error"] = c["error"]
        else:
            out["result"] = copy.deepcopy(c["result"])
        return out


def _key(method, params):
    return method + " " + json.dumps(params, sort_keys=True, default=str)


def sanitize(calls):
    """Return (sanitized calls, mapping summary). Deterministic for the same input."""
    names, users, segs = {}, {}, {}
    for c in calls:
        res = c.get("result") if isinstance(c.get("result"), list) else []
        if c["method"] == "host.get":
            for h in res:
                for f in ("host", "name"):
                    if h.get(f) and h[f] not in names:
                        names[h[f]] = "HOST-%03d" % (len(names) + 1)
        if c["method"] == "user.get":
            for u in res:
                if u.get("username") and u["username"] not in users:
                    users[u["username"]] = "user-%03d" % (len(users) + 1)
    ips = {}

    def ip(m):
        v = m.group(0)
        if v not in ips:
            ips[v] = "192.0.2.%d" % (len(ips) % 250 + 1)
        return ips[v]

    def group(name):                                  # keep the nesting ("A/B" -> "G1/G2"), hide the words
        out = []
        for seg in str(name).split("/"):
            if seg not in segs:
                segs[seg] = "G%d" % (len(segs) + 1)
            out.append(segs[seg])
        return "/".join(out)

    def text(v):
        v = IPV4.sub(ip, v)
        m = re.match(r"^(Interface .+?\()(.*)(\): .*)$", v)            # stock item name carries the ifAlias
        if m:
            v = m.group(1) + _words(m.group(2)) + m.group(3)
        for real, alias in sorted(list(names.items()) + list(users.items()), key=lambda x: -len(x[0])):
            if v == real:
                return alias
            v = v.replace("/%s/" % real, "/%s/" % alias)
            if len(real) >= 4:
                v = re.sub(r"(?<![A-Za-z0-9_.-])%s(?![A-Za-z0-9_.-])" % re.escape(real), alias, v)
        return v

    def scrub(obj, parent_key=None):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "value" and isinstance(v, str) and SECRET_MACRO.search(str(obj.get("macro", ""))):
                    out[k] = "***"
                elif k in ("sendto", "passwd", "password"):
                    out[k] = "***"
                elif (k == "value" and obj.get("tag") == "description") or (
                        k == "lastvalue" and isinstance(v, str) and not re.match(r"^-?[\d.]+$", v)):
                    out[k] = _words(v)
                elif k == "name" and parent_key in ("hostgroups", "hostgroup.get"):
                    out[k] = group(v)
                else:
                    out[k] = scrub(v, k)
            return out
        if isinstance(obj, list):
            return [scrub(x, parent_key) for x in obj]
        if isinstance(obj, str):
            return text(obj)
        return obj

    out = []
    for c in calls:
        c2 = dict(c)
        c2["params"] = scrub(c.get("params"))
        c2["result"] = scrub(c.get("result"), "hostgroup.get" if c["method"] == "hostgroup.get" else None)
        c2["error"] = scrub(c.get("error"))
        out.append(c2)
    return out, {"hosts": len(names), "users": len(users), "ips": len(ips), "group_segments": len(segs)}


def _words(text):
    return " ".join(w if KEEP_WORDS.match(w) else "x" for w in re.split(r"[\s_/-]+", str(text)) if w)
