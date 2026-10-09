import importlib.util
import io
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hwh import audit as AU          # noqa: E402
from hwh import policy, semantics    # noqa: E402
from tests.fakes import NOW, FakeZabbix   # noqa: E402,F401

_spec = importlib.util.spec_from_file_location("hardware_audit_cli", ROOT / "hardware_audit.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

CATALOGUE = policy.load_catalogue(str(ROOT / "config" / "vendors.yaml"))

# TEST-ONLY mapping. It is a synthetic fixture to exercise the code paths; it asserts nothing about any vendor's real status codes.
SYNTHETIC = semantics.validate({"semantics": {
    "test-status": {"vendor": "cisco", "evidence": "synthetic test fixture - not vendor data", "verified": True,
                    "states": {"10": "normal", "20": "degraded", "30": "failed", "40": "absent"}},
    "test-status-unverified": {"vendor": "cisco", "evidence": "synthetic test fixture - not vendor data", "verified": False, "states": {"10": "normal"}},
    "test-status-huawei": {"vendor": "huawei", "evidence": "synthetic test fixture - not vendor data", "verified": True, "states": {"10": "normal"}},
}})

TAGS_FAN = (("netops_hardware", "1"), ("hardware_component", "fan"))


def cisco_policy(sensors, expected=("fan",), **extra):
    h = {"site": "SITE-A", "vendor": "cisco", "family": "cisco-nxos", "model": "TEST-MODEL-1", "expected": list(expected), "sensors": sensors,
         "max_sensor_age_minutes": 10}
    h.update(extra)
    return h


def fan_sensor(key="sensor.fan.status[1]"):
    return {"category": "fan", "key": key, "slot": "Fan tray 1", "semantics": "test-status"}


def good_fake(lastvalue="10", **item_kw):
    """Host NX-01 with one concrete, fresh, mapped fan status item and a correctly tagged trigger bound to it, plus a raw walk input."""
    fz = FakeZabbix()
    hid = fz.add_host("NX-01", templates=["Cisco Nexus 9000 Series by SNMP"], inventory={"model": "N9K-TEST"})
    raw = fz.add_item(hid, "sensor.fans.walk", snmp_oid="walk[1.2.3]", lastclock=0, value_type="4")
    iid = fz.add_item(hid, "sensor.fan.status[1]", name="Fan 1: operational status", lastvalue=lastvalue, snmp_oid="get[1.2.3.1]",
                      preprocessing=[{"type": "1", "params": "1"}], master=raw, valuemap={"name": "test", "mappings": [{"value": "10", "newvalue": "ok"}]}, **item_kw)
    fz.add_trigger(hid, "Fan 1 failed", [iid], tags=TAGS_FAN)
    return fz, hid, iid


def audit_host(fz, settings, reg=SYNTHETIC, name="NX-01", now=NOW):
    from hwh.api import ZabbixAPI
    api = ZabbixAPI("https://fake.example", "tok", transport=fz)
    return AU.verify_host(api, name, settings, reg, now)


def create_owned_action(project, status="1"):
    """Create the hardware action the way the tool really does (so ownership record + nonce exist); status is then forced for the scenario."""
    from hwh import action as A
    project.write("config/notifications.lab.yaml", "media_type: Telegram\nusergroups: [Network Operations]\napproved_by: noc-lead\napproval_reference: T-1\n")
    rc, out, err = project.run("--env", "lab", "action", "apply")
    assert rc == 0, out + err
    aid = [a for a in project.fake.actions.values() if a["name"] == A.ACTION_NAME][0]["actionid"]
    project.fake.actions[aid]["status"] = status
    return aid


def add_evidence(fz, ledger, ids, case, t_before, t_after, sent=None, event_clock=None, status="0", disabled_between=False):
    """Record the per-case action-state evidence a tester would capture with `synthetic observe` / `ledger-mark --event sent` (ledger data only)."""
    from hwh import action as A
    core = A.core_sha256(fz.actions[ids["aid"]])
    obs = ledger.data.setdefault("observations", [])
    obs.append({"case": case, "phase": "before", "utc": t_before, "actionid": ids["aid"], "status": status, "core_sha256": core})
    if disabled_between:
        obs.append({"case": "X", "phase": "before", "utc": (t_before + t_after) // 2, "actionid": ids["aid"], "status": "1", "core_sha256": core})
    obs.append({"case": case, "phase": "after", "utc": t_after, "actionid": ids["aid"], "status": status, "core_sha256": core})
    if sent is not None:
        ledger.data.setdefault("sent", {}).setdefault(case, []).append(sent)
    if event_clock is not None and ids.get("t" + case.lower()):
        for e in fz.events:
            pass
        fz.events.append({"eventid": "x%s1" % case, "r_eventid": "x%s2" % case, "objectid": ids["t" + case.lower()], "value": "1", "clock": str(event_clock)})
    ledger.save()


def seed_audit(fz, aid, created, enable=None, disable=None, extra=None):
    """Server-side audit rows for the hardware action, as auditlog.get would return them (resourcetype 5). Keeps the fake live status consistent."""
    import json as _json
    rows = fz.auditlog
    n = len(rows) + 1
    rows.append({"auditid": "au%d" % n, "clock": str(created), "action": "0", "resourcetype": "5", "resourceid": str(aid), "resourcename": "NETOPS-HW Hardware Health",
                 "details": _json.dumps({"action.status": ["add", "1"], "action.name": ["add", "NETOPS-HW Hardware Health"]})})
    status = "1"
    if enable is not None:
        rows.append({"auditid": "au%d" % (n + 1), "clock": str(enable), "action": "1", "resourcetype": "5", "resourceid": str(aid), "resourcename": "NETOPS-HW Hardware Health",
                     "details": _json.dumps({"action.status": ["update", "0", "1"]})})
        status = "0"
    if disable is not None:
        rows.append({"auditid": "au%d" % (n + 2), "clock": str(disable), "action": "1", "resourcetype": "5", "resourceid": str(aid), "resourcename": "NETOPS-HW Hardware Health",
                     "details": _json.dumps({"action.status": ["update", "1", "0"]})})
        status = "1"
    for r in extra or []:
        rows.append(r)
    fz.actions[aid]["status"] = status


def seed_history(fz, itemid, samples):
    for clock, value in samples:
        fz.history.append({"itemid": str(itemid), "clock": str(clock), "ns": "0", "value": str(value)})


def deletion_ids(plan):
    """The ids a cleanup plan would DELETE, as a parsed set - never a substring search of serialised output (which may contain hashes)."""
    out = set()
    for step in plan:
        if str(step["method"]).endswith(".delete"):
            out.update(str(i) for i in step["params"])
    return out


class Project(object):
    """A temp project directory with the shipped catalogue/registry and an editable policy, driven through the real CLI."""

    def __init__(self, env="lab", hosts_yaml="hosts: {}\n", fake=None, identity="lab", semantics_yaml=None, extra_top=""):
        self.base = tempfile.mkdtemp(prefix="hwh-test-")
        os.makedirs(os.path.join(self.base, "config"))
        for f in ("vendors.yaml", "status-semantics.yaml", "action-validation.yaml"):
            shutil.copy(str(ROOT / "config" / f), os.path.join(self.base, "config", f))
        if semantics_yaml is not None:
            with open(os.path.join(self.base, "config", "status-semantics.yaml"), "w") as fh:
                fh.write(semantics_yaml)
        self.fake = fake or FakeZabbix(identity=identity)
        self.env = env
        self.write_policy(env, hosts_yaml, extra_top)
        self.environ = {"ZABBIX_HARDWARE_URL_LAB": "https://zbx.lab.example", "ZABBIX_HARDWARE_TOKEN_LAB": "lab-token-aaa",
                        "ZABBIX_HARDWARE_URL_PRODUCTION": "https://zbx.prod.example", "ZABBIX_HARDWARE_TOKEN_PRODUCTION": "prod-token-bbb"}

    def write_policy(self, env, hosts_yaml, extra_top=""):
        with open(os.path.join(self.base, "config", "hardware.%s.yaml" % env), "w") as fh:
            fh.write("environment: %s\n%s%s" % (env, extra_top, hosts_yaml))

    def write(self, rel, text):
        p = os.path.join(self.base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
        return p

    def run(self, *argv, **kw):
        clock = kw.get("clock")
        out = []
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            rc = cli.main(list(argv), environ=kw.get("environ", self.environ), transport=self.fake, base=self.base, now=NOW, out=out.append, clock=clock)
        finally:
            sys.stderr = old
        return rc, "\n".join(out), err.getvalue()

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)
