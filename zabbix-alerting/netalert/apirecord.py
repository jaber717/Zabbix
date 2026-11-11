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


# ------------------------------------------------------------------------------------------- sanitizing
#
# ALLOWLIST: a string survives only if it is structural (numbers, IDs, enum values, intervals, item keys rebuilt
# from safe parts, macro NAMES, known tag names, stock template names, the project's own public names) or a
# role-detection word. Every other string - host/visible names, user names, IP/DNS, action/media/group/template
# names, event names, error and message text, macro values, tag values, trigger names - is replaced by a stable
# pseudonym (same input -> same pseudonym within one capture, so equality-based logic still replays).

NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")
SAFE_DELAY = re.compile(r"^(\d+[smhdw]?|[0-9a-z;/,:.\-]+|\{\$[A-Z0-9_.]+(:\"[^\"]*\")?\})$")
SAFE_PERIOD = re.compile(r"^[0-9,:;\- ]+$")
IFNAME = re.compile(r"^[A-Za-z][A-Za-z-]{0,24}\d+([/.:]\d+)*$")
KEY_PART = re.compile(r"^(|\d+|[A-Za-z]+\.\d+(\.\d+)*|\{#[A-Z0-9_]+\}|\{\$[A-Z0-9_.]+\}|[0-9.]+|"
                      r"if[A-Za-z]+|walk|get|ifOperStatus|ifHighSpeed)$")
KEY_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
MACRO_NAME = re.compile(r'^\{\$[A-Z0-9_.]+\}$')
KNOWN_FUNCS = {"last", "min", "max", "avg", "sum", "count", "find", "nodata", "changecount", "change", "diff",
               "percentile", "trendavg", "trendmax", "trendmin", "fuzzytime", "lastclock"}
KNOWN_TAGS = {"interface", "component", "description", "site", "netops_alert", "if_name", "if_descr", "if_role",
              "link_id", "direction", "threshold", "severity_label", "managed_by", "scope", "class", "target",
              "noalert", "nhealth_alert", "protocol", "peer", "neighbor"}
PUBLIC_NAME = re.compile(r"(?i)\bby (SNMP|Zabbix agent|HTTP|ICMP)\b|^(NETOPS|NHEALTH|Network Health|Interface Alerting)"
                         r"|^Template |^Email$|^Email \(HTML\)$")
ENUMISH = {"api_jsonrpc", "Invalid params.", "Application error.", "No permissions to referred object or it does "
           "not exist!"}
FREE_TEXT_KEYS = {"sendto", "passwd", "password", "message", "subject", "data", "error", "description", "comments",
                  "opdata", "url", "event_name", "dns", "ip", "username", "name", "host", "macro_value"}


class Sanitizer(object):
    def __init__(self):
        self.alias, self.counts = {}, {}

    def pseudo(self, value, kind="S"):
        if value not in self.alias:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.alias[value] = "%s-%04d" % (kind, self.counts[kind])
        return self.alias[value]

    def ifname(self, v):
        return v if IFNAME.match(v) else self.pseudo(v, "IF")

    def group(self, name):                                # keep the nesting ("A/B" -> "G1/G2"), hide the words
        return "/".join(self.pseudo(seg, "G") for seg in str(name).split("/"))

    def key(self, k):
        m = re.match(r"^([^\[]+)(?:\[(.*)\])?$", k or "")
        if not m or not KEY_NAME.match(m.group(1)):
            return self.pseudo(k, "KEY")
        if m.group(2) is None:
            return k
        parts = [x.strip('"') for x in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", m.group(2))]
        safe = [x if KEY_PART.match(x) else self.ifname(x) if IFNAME.match(x) else self.pseudo(x, "P") for x in parts]
        return "%s[%s]" % (m.group(1), ",".join(safe))

    def expression(self, e):
        def q(mm):
            return '"%s"' % self.ifname(mm.group(1))
        e = re.sub(r'"((?:[^"\\]|\\.)*)"', q, e or "")
        e = re.sub(r"\((/)([^/()]+)/([^,()]+(?:\[[^\]]*\])?)", lambda mm: "(/%s/%s" % (
            self.pseudo(mm.group(2), "HOST"), self.key(mm.group(3))), e)
        return e

    def text(self, k, v, obj, parent):
        if v == "" or NUMERIC.match(v) or v in ENUMISH:
            return v
        if k == "key_":
            return self.key(v)
        if k in ("expression", "recovery_expression", "formula"):
            return self.expression(v) if k != "formula" else (v if re.match(r"^[A-Z()\s]+(and|or|not|[A-Z()\s])*$", v) else self.pseudo(v))
        if k == "macro":
            m = re.match(r'^(\{\$[A-Z0-9_.]+)(?::"((?:[^"\\]|\\.)*)")?\}$', v)
            if not m:
                return self.pseudo(v, "M")
            return m.group(1) + (':"%s"' % self.ifname(m.group(2)) if m.group(2) is not None else "") + "}"
        if k == "value" and "macro" in obj:
            return "***" if SECRET_MACRO.search(str(obj.get("macro", ""))) else self.pseudo(v, "V")
        if k == "tag":
            return v if v in KNOWN_TAGS else self.pseudo(v, "TAG")
        if k == "value" and "tag" in obj:
            if obj.get("tag") == "description":
                return _words(v)
            if obj.get("tag") in ("interface", "if_name"):
                return self.ifname(v)
            return self.pseudo(v, "TV")
        if k == "value" and "conditiontype" in obj:
            return self.pseudo(v, "CV")
        if k == "delay":
            return v if SAFE_DELAY.match(v) else self.pseudo(v, "D")
        if k == "period":
            return v if SAFE_PERIOD.match(v) else self.pseudo(v, "PER")
        if k == "name" and "functionid" in obj:
            return v if v in KNOWN_FUNCS else self.pseudo(v, "FN")
        if k == "parameter":
            return "$" + ",".join(x if KEY_PART.match(x) or re.match(r"^#?\d+[smhdw]?$", x) else self.pseudo(x, "P")
                                  for x in v[1:].split(",")) if v.startswith("$") else self.pseudo(v, "P")
        if k == "lastvalue":
            return _words(v)
        if k == "name" and parent in ("hostgroups", "hostgroup.get"):
            return self.group(v)
        if k in ("name", "host") and PUBLIC_NAME.search(v):
            return v
        if k == "name":
            m = re.match(r"^Interface (.+?)\((.*)\): (Operational status|Bits received|Bits sent|Speed|"
                         r"Interface type|Inbound packets discarded|Outbound packets discarded|"
                         r"Inbound packets with errors|Outbound packets with errors)$", v)
            if m:
                return "Interface %s(%s): %s" % (self.ifname(m.group(1)), _words(m.group(2)), m.group(3))
        if k in ("host", "name", "username") and parent in (None, "result", "hosts") and obj.get("hostid"):
            return self.pseudo(v, "HOST")
        if k == "username":
            return self.pseudo(v, "user")
        if k in ("sendto", "passwd", "password"):
            return "***"
        return self.pseudo(v)

    def params(self, p):
        """Request parameters are this tool's own structure; only filter/search values carry site names."""
        if not isinstance(p, dict):
            return p
        out = dict(p)
        for fk in ("filter", "search"):
            if isinstance(p.get(fk), dict):
                out[fk] = {}
                for k, v in p[fk].items():
                    conv = (lambda x: self.pseudo(x, "HOST")) if k == "host" else (
                        self.group if k == "name" else (lambda x: x if NUMERIC.match(str(x)) or k == "key_" else self.pseudo(x)))
                    out[fk][k] = [conv(x) for x in v] if isinstance(v, list) else conv(v)
        return out

    def scrub(self, obj, parent=None, owner=None, key=None):
        if isinstance(obj, dict):
            return dict((k, self.scrub(v, key if key is not None else parent, obj, k)) for k, v in obj.items())
        if isinstance(obj, list):
            return [self.scrub(x, parent, owner, key) for x in obj]
        if isinstance(obj, str):
            return self.text(key, obj, owner or {}, parent)
        return obj


def sanitize(calls):
    """Return (sanitized calls, mapping summary). Deterministic for the same input."""
    sz = Sanitizer()
    out = []
    for c in calls:
        c2 = dict(c)
        c2["params"] = sz.params(c.get("params"))
        c2["result"] = sz.scrub(c.get("result"), "hostgroup.get" if c["method"] == "hostgroup.get" else "result")
        c2["error"] = sz.scrub(c.get("error"))
        out.append(c2)
    summary = dict(sz.counts)
    summary["hosts"] = sz.counts.get("HOST", 0)
    return out, summary


def leaks(original, sanitized):
    """Strings from the original capture that still appear in the sanitized one, apart from structural strings
    the allowlist keeps on purpose. Empty list = no leak found. The capture script refuses to write otherwise."""
    kept = set()
    found = set()

    def walk(o, k=None):
        if isinstance(o, dict):
            for kk, v in o.items():
                walk(v, kk)
        elif isinstance(o, list):
            for x in o:
                walk(x, k)
        elif isinstance(o, str) and len(o) >= 4 and not NUMERIC.match(o):
            found.add(o)
    walk([{"r": c.get("result"), "e": c.get("error"),
           "f": (c.get("params") or {}).get("filter") if isinstance(c.get("params"), dict) else None}
          for c in original])                      # request structure is this tool's own; filter values are not
    values = []

    def collect(o):
        if isinstance(o, dict):
            for v in o.values():
                collect(v)
        elif isinstance(o, list):
            for x in o:
                collect(x)
        elif isinstance(o, str):
            values.append(o)
    collect([{"r": c.get("result"), "e": c.get("error"), "p": c.get("params")} for c in sanitized])
    text = "\x00".join(values)
    for v in sorted(found):
        if v in text and not _structural(v):
            kept.add(v)
    return sorted(kept)


def _structural(v):
    return bool(KEY_NAME.match(v.split("[")[0]) and ("[" in v or "." in v) and " " not in v) or \
        bool(MACRO_NAME.match(v)) or v in KNOWN_TAGS or v in ENUMISH or bool(PUBLIC_NAME.search(v)) or \
        bool(IFNAME.match(v)) or bool(SAFE_PERIOD.match(v)) or bool(re.match(r"^\d+[smhdw]$", v)) or \
        all(KEEP_WORDS.match(w) for w in re.split(r"[\s_/-]+", v) if w) or \
        bool(re.match(r"^[a-z]+(\.[a-z_]+)+$", v)) or v in KNOWN_FUNCS or bool(re.match(r"^\$(,#?\d+[smhdw]?)*$", v))


def _words(text):
    return " ".join(w if KEEP_WORDS.match(w) else "x" for w in re.split(r"[\s_/-]+", str(text)) if w)
