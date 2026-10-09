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
