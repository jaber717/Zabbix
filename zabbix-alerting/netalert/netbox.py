"""Optional, read-only NetBox enrichment (GET only). NetBox is never required.

Used for one thing that Zabbix cannot prove: which two ports are cabled together. A NetBox cable between
two ports that both exist in Zabbix is VERIFIED pairing evidence; nothing else is. Device and interface
names must match exactly or, for interface names, through an unambiguous abbreviation (Gi0/0 =
GigabitEthernet0/0). Any ambiguity = no match.
"""
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .zbx import NoRedirect

ABBREV = (("hundredgigabitethernet", "hundredgige"), ("fortygigabitethernet", "fortygige"),
          ("twentyfivegigabitethernet", "twentyfivegige"), ("tengigabitethernet", "tengige"),
          ("gigabitethernet", "gigabitethernet"), ("fastethernet", "fastethernet"), ("port-channel", "port-channel"),
          ("bundle-ether", "bundle-ether"), ("ethernet", "ethernet"))
SHORT = {"hu": "hundredgige", "hundredgige": "hundredgige", "fo": "fortygige", "fortygige": "fortygige",
         "twe": "twentyfivegige", "twentyfivegige": "twentyfivegige", "te": "tengige", "tengige": "tengige",
         "gi": "gigabitethernet", "ge": "gigabitethernet", "gigabitethernet": "gigabitethernet",
         "fa": "fastethernet", "fastethernet": "fastethernet", "po": "port-channel", "port-channel": "port-channel",
         "be": "bundle-ether", "bundle-ether": "bundle-ether", "eth": "ethernet", "et": "ethernet",
         "ethernet": "ethernet"}
NAME_RE = re.compile(r"^([a-z-]+?)(\d.*)$")


class NetBoxError(Exception):
    pass


def canonical(ifname):
    """Comparable interface name; unknown prefixes are kept as-is (lowercased)."""
    s = str(ifname).strip().lower().replace(" ", "")
    for long_name, canon in ABBREV:
        if s.startswith(long_name):
            return canon + s[len(long_name):]
    m = NAME_RE.match(s)
    if m and m.group(1) in SHORT:
        return SHORT[m.group(1)] + m.group(2)
    return s


class NetBox(object):
    def __init__(self, url, token, verify_tls=True, timeout=20, opener=None):
        self.base = url.rstrip("/")
        if not self.base.endswith("/api"):
            self.base += "/api"
        self.token = token
        self.timeout = timeout
        self._ctx = None if verify_tls else ssl._create_unverified_context()
        handlers = [NoRedirect()] + ([urllib.request.HTTPSHandler(context=self._ctx)] if self._ctx else [])
        self._opener = urllib.request.build_opener(*handlers)
        self._open = opener or self._http
        u = urllib.parse.urlsplit(self.base)
        self._origin, self._prefix = (u.scheme.lower(), u.netloc.lower()), u.path.rstrip("/") + "/"
        self.calls = []

    def _http(self, url):
        req = urllib.request.Request(url, headers={"Authorization": "Token " + self.token,
                                                   "Accept": "application/json"}, method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise NetBoxError("NetBox answered HTTP %s%s" % (exc.code, " (redirect refused)" if 300 <= exc.code < 400 else ""))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise NetBoxError("NetBox read failed: %s" % exc)

    def get_all(self, path, params):
        url = "%s/%s/?%s" % (self.base, path.strip("/"), urllib.parse.urlencode(params, doseq=True))
        out = []
        while url:
            self.calls.append(("GET", url.split("?")[0]))
            data = self._open(url)
            out += data.get("results", [])
            url = data.get("next")
            if url:
                n = urllib.parse.urlsplit(url)
                if (n.scheme.lower(), n.netloc.lower()) != self._origin or not n.path.startswith(self._prefix):
                    raise NetBoxError("NetBox pagination pointed outside %s%s - refused" % ("://".join(self._origin), self._prefix))
        return out


def enrich(snap, nb, limits):
    """Adds host['netbox'] = {'device': name, 'site', 'role'} and port['netbox_peer'] = (host, port) where a
    NetBox cable proves it. Failures are recorded in `limits`; they never abort discovery."""
    names = sorted(snap["hosts"])
    devices = {}
    try:
        for i in range(0, len(names), 50):
            for d in nb.get_all("dcim/devices", {"name": names[i:i + 50], "limit": 1000}):
                devices.setdefault(d["name"], []).append(d)
    except NetBoxError as exc:
        limits.append("NetBox enrichment skipped: %s" % exc)
        return
    snap["netbox_used"] = True
    by_device = {}
    for hname, h in snap["hosts"].items():
        found = devices.get(hname, [])
        if len(found) != 1:
            if len(found) > 1:
                limits.append("NetBox: %d devices named '%s' - not used" % (len(found), hname))
            continue
        d = found[0]
        h["netbox"] = {"device": d["name"], "site": ((d.get("site") or {}).get("name") or ""),
                       "role": ((d.get("role") or d.get("device_role") or {}).get("name") or "")}
        try:
            ifs = nb.get_all("dcim/interfaces", {"device_id": d["id"], "limit": 1000})
        except NetBoxError as exc:
            limits.append("NetBox interfaces of %s not read: %s" % (hname, exc))
            continue
        by_device[hname] = ifs
    # map NetBox interface -> Zabbix port (exact, else unique canonical match)
    zmap = {}
    for hname, ifs in by_device.items():
        ports = snap["hosts"][hname]["ports"]
        canon = {}
        for pn in ports:
            canon.setdefault(canonical(pn), []).append(pn)
        for i in ifs:
            if i["name"] in ports:
                zmap[(hname, i["name"])] = i["name"]
            elif len(canon.get(canonical(i["name"]), [])) == 1:
                zmap[(hname, i["name"])] = canon[canonical(i["name"])][0]
    for hname, ifs in by_device.items():
        for i in ifs:
            local = zmap.get((hname, i["name"]))
            if not local:
                continue
            peers = [p for p in (i.get("link_peers") or []) if isinstance(p, dict) and p.get("device")]
            if not i.get("cable") or len(peers) != 1:
                continue
            pdev, pif = peers[0]["device"].get("name"), peers[0].get("name")
            remote = zmap.get((pdev, pif))
            if pdev in snap["hosts"] and remote:
                snap["hosts"][hname]["ports"][local]["netbox_peer"] = [pdev, remote]
