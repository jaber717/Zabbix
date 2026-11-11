"""Negative regression tests for the independent follow-up review of v1.1.0-rc2 (31ffc94).

Each test reproduces one reviewed case and asserts the SAFE behaviour; run against 31ffc94 they fail (see
docs/REMEDIATION-v1.1-rc3.md). Offline: an in-memory Zabbix 7.0 model and real temporary git repositories.
Nothing here proves real Zabbix API behaviour or e-mail delivery; that is LAB acceptance.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from netalert import apirecord, coverage, discovery, exprcheck, netbox, onboard_cli
from netalert import onboarding as ob
from netalert.zbx import ZabbixClient
from tests.discovery_fixture import NOW, add_netops, stock_link, stock_util
from tests.helpers import LAB_YAML, PROD_YAML
from tests.test_onboarding import World, row_no

PORT = "EDGE-RTR-01|Hu0/0/0/0"


def cls(w, rid=PORT):
    return coverage.port_coverage(w.snapshot(), w.model()["by_id"][rid])


def stock_trigger(w):
    return [t for t in w.z.triggers.values() if "(stock)" in t["description"]][0]


class Base(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def assertNotProtected(self, rid=PORT):
        c, why, _ = cls(self.w, rid)
        self.assertNotIn(c, coverage.PROTECTED_CLASSES, why)
        return c, why


# ================================================================== F1 (P0) managed item data quality

class ManagedItemQuality(Base):
    """Protection claimed ONLY through the NETOPS triggers; the stock status item stays fresh throughout."""

    def setUp(self):
        Base.setUp(self)
        stock_trigger(self.w)["status"] = "1"
        self.own, self.trig = add_netops(self.w.z, "EDGE-RTR-01", "Hu0/0/0/0", "1",
                                         alerts=("link_down", "util_rx", "util_tx"))
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG, why)                          # baseline: everything proven

    def _break(self, kind, how):
        it = self.w.z.items[self.own[kind]]
        if how == "stale":
            it["lastclock"] = str(NOW - 86400)
        elif how == "disabled":
            it["status"] = "1"
        elif how == "unsupported":
            it["state"] = "1"
        elif how == "never":
            it["lastclock"] = "0"

    def test_netops_status_item_stale_disabled_unsupported_never(self):
        for how in ("stale", "disabled", "unsupported", "never"):
            with self.subTest(how=how):
                self.setUp()
                self._break("oper", how)
                c, why = self.assertNotProtected()
                self.assertEqual(c, coverage.STALE, why)
                self.assertIn("netops.if.oper[1]", " ".join(why))
                self.tearDown()

    def test_netops_utilization_items_stale_disabled_unsupported(self):
        for kind in ("in", "out", "speed"):
            for how in ("stale", "disabled", "unsupported"):
                with self.subTest(kind=kind, how=how):
                    self.setUp()
                    self._break(kind, how)
                    c, why = self.assertNotProtected()
                    self.assertIn("utilization alert", " ".join(why))
                    self.tearDown()

    def test_dependent_capacity_item_judged_by_its_master(self):
        z = self.w.z
        master = z.nid()
        z.items[master] = dict(z.items[self.own["speed"]], itemid=master, key_="netops.if.hspeed[1]",
                               lastclock=str(NOW - 86400), delay="60s")
        z.items[self.own["speed"]].update({"type": "18", "master_itemid": master, "delay": "0"})
        c, why = self.assertNotProtected()
        self.assertIn("master item stale", " ".join(why))

    def test_fault_test_record_does_not_survive_stale_data(self):
        self.w.z.add_delivery(self.trig["link_down"], self.w.ids["action"])
        rc, out = self.w.run("--record-fault-test", PORT)
        self.assertEqual(rc, 0, out)
        self.assertEqual(cls(self.w)[0], coverage.PROT)
        self._break("oper", "stale")
        self.assertNotProtected()

    def test_item_unreadable_with_this_token(self):
        self.w.z.items[self.own["oper"]]["hostid"] = "nonexistent"     # trigger references an item we cannot read
        self.assertNotProtected()


# ================================================================== F2 (P0) expression semantics

class ExpressionValidation(Base):
    def setUp(self):
        Base.setUp(self)
        add_netops(self.w.z, "EDGE-RTR-01", "Hu0/0/0/0", "1")              # policy utilization alerts (RX+TX)
        self.assertEqual(cls(self.w)[0], coverage.CONFIG)
        self.t = stock_trigger(self.w)

    def test_reviewer_case_constant_false_conjunct(self):
        self.t["expression"] = "last(/EDGE-RTR-01/net.if.status[ifOperStatus.1])=2 and 0=1"
        c, why = self.assertNotProtected()
        self.assertEqual(c, coverage.NOTC)
        self.assertIn("constant condition '0=1' is never true", " ".join(why))

    def test_unknown_extra_condition_is_unproven(self):
        for extra in ("nodata(/EDGE-RTR-01/net.if.status[ifOperStatus.1],5m)=1", "{$IFCONTROL}>5",
                      "1={$IFCONTROL}", "last(/EDGE-RTR-01/net.if.speed[ifHighSpeed.1])<0"):
            with self.subTest(extra=extra):
                self.t["expression"] = stock_link("EDGE-RTR-01", "Hu0/0/0/0", "1") + " and " + extra
                self.assertNotProtected()

    def test_top_level_or_and_not_are_unknown_logic(self):
        base = "last(/EDGE-RTR-01/net.if.status[ifOperStatus.1])=2"
        for e in (base + " or 0=1", "not " + base, "(" + base + " or 1=1) and 0=1"):
            with self.subTest(expr=e):
                self.t["expression"] = e
                self.assertNotProtected()

    def test_recovery_that_can_never_happen(self):
        k = "/EDGE-RTR-01/net.if.status[ifOperStatus.1]"
        self.t.update({"recovery_mode": "1", "recovery_expression": "last(%s)=1 and 0=1" % k})
        self.assertNotProtected()
        self.t.update({"recovery_mode": "1", "recovery_expression": "last(%s)=2" % k})   # no link-up test
        self.assertNotProtected()
        self.t.update({"recovery_mode": "2", "recovery_expression": ""})                  # manual close only
        self.assertNotProtected()
        self.t.update({"recovery_mode": "1", "recovery_expression": "last(%s)<>2 or {$IFCONTROL:\"Hu0/0/0/0\"}=0" % k})
        self.assertEqual(cls(self.w)[0], coverage.CONFIG)                                 # stock recovery shape

    def test_discovery_never_lets_zabbix_expand_macros(self):
        rec = apirecord.RecordingTransport(self.w.z.transport("tok"))
        discovery.discover(ZabbixClient(rec, read_only=True), now=NOW)
        params = [c["params"] for c in rec.calls if c["method"] == "trigger.get"]
        self.assertTrue(params)
        for p in params:
            self.assertFalse(p.get("expandExpression"), p)
            self.assertIn("selectFunctions", p)
        snap = self.w.snapshot()
        exprs = [t["expression"] for t in snap["hosts"]["EDGE-RTR-01"]["triggers"]]
        self.assertTrue(any('{$IFCONTROL:"Hu0/0/0/0"}=1' in e for e in exprs), exprs)   # gate kept, then resolved

    def test_unknown_function_reference_fails_closed(self):
        e = discovery.rebuild("{1}=2 and {99}=1", {"1": {"itemid": "5", "name": "last", "parameter": "$"}},
                              {"5": {"host": "R", "key": "net.if.status[ifOperStatus.1]"}})
        self.assertEqual(e, "last(/R/net.if.status[ifOperStatus.1])=2 and {UNKNOWN}=1")
        self.assertIsNone(exprcheck.conjuncts(e))

    # ---- utilization must be the approved 70%/65% policy, not "any > on traffic" --------------------------
    def _fresh_world(self, **kw):
        self.w.close()
        self.w = World()
        add_netops(self.w.z, "EDGE-RTR-01", "Hu0/0/0/0", "1", **kw)

    def test_stock_bandwidth_trigger_is_not_the_policy(self):
        self.w.close()
        self.w = World()
        hid = self.w.z.host_id("EDGE-RTR-01")
        ids = [i for i, it in self.w.z.items.items() if it["hostid"] == hid and ".1]" in it["key_"]]
        self.w.z.add_trigger("bw", ids, expression=stock_util("EDGE-RTR-01", "Hu0/0/0/0", "1"))   # 90%, stock
        c, why = self.assertNotProtected()
        self.assertIn("not the approved 70%/65% policy", " ".join(why))

    def test_netops_threshold_or_hysteresis_differs_from_policy(self):
        for kw, msg in ((dict(thr="90"), "approved policy is 70%"), (dict(rec="68"), "approved policy is 65%")):
            with self.subTest(**kw):
                self._fresh_world(**kw)
                c, why = self.assertNotProtected()
                self.assertIn(msg, " ".join(why))

    def test_netops_utilization_without_recovery_or_one_direction(self):
        self._fresh_world(alerts=("util_rx",))
        c, why = self.assertNotProtected()
        self.assertIn("no proven TX utilization alert", " ".join(why))
        self._fresh_world()
        for t in self.w.z.triggers.values():
            if "util_" in t["description"]:
                t.update({"recovery_mode": "0", "recovery_expression": ""})
        c, why = self.assertNotProtected()
        self.assertIn("hysteresis 65% not implemented", " ".join(why))

    def test_any_traffic_comparison_is_not_utilization(self):
        self._fresh_world()
        for t in self.w.z.triggers.values():
            if "util_rx" in t["description"]:
                t["expression"] = "last(/EDGE-RTR-01/netops.if.in[1])>0"
        c, why = self.assertNotProtected()
        self.assertIn("RX utilization", " ".join(why))


# ================================================================== F4 (P1) delivery correlation

class DeliveryCorrelation(Base):
    def setUp(self):
        Base.setUp(self)
        add_netops(self.w.z, "EDGE-RTR-01", "Hu0/0/0/0", "1")
        self.tid, self.act = stock_trigger(self.w)["triggerid"], self.w.ids["action"]

    def test_problem_and_recovery_from_unrelated_events_are_not_a_pair(self):
        z = self.w.z
        z.add_delivery(self.tid, self.act, recovery=False)                    # problem A, never recovered
        _, rB = z.add_delivery(self.tid, self.act, clock=NOW - 80 * 86400)    # old pair B ...
        for e in z.events:                                                    # ... whose problem message failed
            if e["value"] == "1" and e["r_eventid"] == rB:
                e["alerts"][0]["status"] = "2"
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG)
        self.assertIn("no correlated SENT Problem+Recovery pair", " ".join(why))

    def test_pair_to_a_user_who_is_no_longer_a_recipient(self):
        z = self.w.z
        gone = z.add_user("former-noc", [z.add_usergroup("Former NOC")], medias=[
            {"mediatypeid": self.w.ids["email"], "active": "0", "severity": "60", "period": "1-7,00:00-24:00"}])
        z.add_delivery(self.tid, self.act, userid=gone)
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG)
        self.assertIn("no correlated SENT Problem+Recovery pair", " ".join(why))

    def test_history_is_reported_as_historical_never_as_a_current_test(self):
        self.w.z.add_delivery(self.tid, self.act, clock=NOW - 60 * 86400)
        c, why, _ = cls(self.w)
        self.assertEqual(c, coverage.CONFIG)
        self.assertIn("historical delivery evidence only", " ".join(why))
        rc, out = self.w.run("--record-fault-test", PORT)                     # 60 days old: not a fault test now
        self.assertEqual(rc, 1, out)
        self.assertIn("no correlated Problem + Recovery message pair", out)

    def test_fault_test_record_is_invalidated_by_configuration_changes(self):
        z = self.w.z
        z.add_delivery(self.tid, self.act)
        self.assertEqual(self.w.run("--record-fault-test", PORT)[0], 0)
        self.assertEqual(cls(self.w)[0], coverage.PROT)
        changes = (
            lambda: z.actions[self.act]["filter"]["conditions"].append(
                {"conditiontype": "4", "operator": "5", "value": "2", "formulaid": "B"}),
            lambda: [u["medias"][0].update({"severity": "48"}) for u in z.users.values()],   # still high+disaster
            lambda: stock_trigger(self.w).update({"priority": "5"}),                          # still delivered
        )
        for change in changes:
            with self.subTest(change=change):
                snapshot = json.dumps([z.actions, z.users, z.triggers], sort_keys=True, default=str)
                change()
                c, why, _ = cls(self.w)
                self.assertEqual(c, coverage.CONFIG, why)
                self.assertIn("no longer matches the configuration", " ".join(why))
                a, u, t = json.loads(snapshot)
                for live, saved in ((z.actions, a), (z.users, u), (z.triggers, t)):
                    live.clear()
                    live.update(saved)
                self.assertEqual(cls(self.w)[0], coverage.PROT)

    def test_record_refused_when_not_config_verified(self):
        stock_trigger(self.w)["status"] = "1"
        rc, out = self.w.run("--record-fault-test", PORT)
        self.assertEqual(rc, 1)
        self.assertIn("can only be recorded for a CONFIG VERIFIED port", out)


# ================================================================== F3 (P1) pin vs. site configuration

def sh(cwd, *cmd, check=True):
    r = subprocess.run(list(cmd), cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if check and r.returncode != 0:
        raise AssertionError("%s failed: %s" % (" ".join(cmd), r.stderr))
    return r


def bash(cwd, script):
    r = subprocess.run(["bash", "-e", "-c", script], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    if r.returncode != 0:
        raise AssertionError("script failed:\n%s\n%s" % (script, r.stderr))
    return r


# The git part of docs/ONBOARDING.md section 2, verbatim (asserted below), with $URL for the GitHub URL.
INSTALL = [
    'mkdir -p ~/Zabbix && cd ~/Zabbix && git init -q && git remote add origin https://github.com/jaber717/Zabbix.git',
    'git config user.name "netops-$(hostname -s)" && git config user.email "netops@$(hostname -f)"   # local site commits',
    'git config http.lowSpeedLimit 1000 && git config http.lowSpeedTime 60   # abort stalled transfers instead of hanging',
    'for i in 1 2 3 4 5; do git fetch --depth 1 origin "$PIN" && break; echo "fetch failed (proxy 504?) retry $i"; sleep $((i*20)); done',
    'git checkout -q -b prod-local FETCH_HEAD && git remote set-url --push origin no-push   # nothing ever pushed from here',
]
COMMIT_SETTINGS = 'git add config && git commit -q -m "site: production settings"'
COMMIT_INVENTORY = 'git add config && git commit -q -m "onboarding: approved production inventory"'
UPDATE = 'cd ~/Zabbix/zabbix-alerting && ./onboard.sh --env production --update <new validated commit or tag>'


class PinnedDeployment(unittest.TestCase):
    """install -> configure (--setup) -> commit -> review/write -> commit -> --verify -> --deploy, on real git."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pin-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        up = self.up = os.path.join(self.tmp, "upstream")
        os.makedirs(os.path.join(up, "zabbix-alerting", "config", "environments"))
        os.makedirs(os.path.join(up, "zabbix-alerting", "netalert"))
        files = {"config/environments/lab.yaml": LAB_YAML, "config/environments/production.yaml": PROD_YAML,
                 "config/interfaces.production.yaml": "hosts: {}\n",
                 "config/network-health.production.yaml": "devices: {}\n", "config/REVIEW-REQUIRED.md": "x\n",
                 ".gitignore": ".env\nstate/\n", "netalert/code.py": "VERSION = 1\n", "docs.md": "v1\n"}
        for rel, text in files.items():
            with open(os.path.join(up, "zabbix-alerting", rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        sh(up, "git", "init", "-q")
        sh(up, "git", "config", "user.email", "dev@example"), sh(up, "git", "config", "user.name", "dev")
        sh(up, "git", "add", "-A"), sh(up, "git", "commit", "-q", "-m", "c1")
        self._upstream_commit("netalert/code.py", "VERSION = 2\n")
        self.pin = self.head(up)
        self.w = World()                                                 # mock Zabbix + its environment

    def tearDown(self):
        self.w.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _upstream_commit(self, rel, text):
        with open(os.path.join(self.up, "zabbix-alerting", rel), "w", encoding="utf-8") as fh:
            fh.write(text)
        sh(self.up, "git", "commit", "-q", "-am", "change " + rel)

    def head(self, d):
        return sh(d, "git", "rev-parse", "HEAD").stdout.strip()

    def env(self, extra=""):
        return "export HOME=%s PIN=%s\n%s\n" % (self.home, self.pin, extra)

    def install(self):
        script = self.env() + "\n".join(INSTALL).replace("https://github.com/jaber717/Zabbix.git",
                                                          "file://" + self.up)
        bash(self.tmp, script)
        self.base = os.path.join(self.home, "Zabbix", "zabbix-alerting")
        return self.base

    def run_cli(self, *argv, lines=None, ask=None):
        out = []
        rc = onboard_cli.run(["--env", "production"] + list(argv), environ=dict(self.w.env), out=out.append,
                             lines=lines, base=self.base, transport_factory=lambda u, t, v: self.w.z.transport(t),
                             now=NOW, ask=ask, secret=lambda q: "tok")
        return rc, "\n".join(out)

    def documented_sequence(self):
        self.install()
        answers = iter(["https://zbx.prod.example", "", "y"])
        rc, out = self.run_cli("--setup", ask=lambda q: next(answers))           # pins the installed commit
        self.assertEqual(rc, 0, out)
        self.assertIn("deploy_pin set to %s" % self.pin[:12], out)
        bash(self.base, COMMIT_SETTINGS)
        rc, out = self.run_cli(lines=["l"])
        rc, out = self.run_cli(lines=["l", "a %s" % row_no(out, "EDGE-RTR-01", "Hu0/0/0/0"), "w", "q"])
        self.assertIn("written:", out)
        bash(self.base, COMMIT_INVENTORY)
        self.assertNotEqual(self.head(self.base), self.pin)                       # HEAD is a local config commit

    def verify(self):
        rc, out = self.run_cli("--verify")
        token = [l.split()[2] for l in out.splitlines() if l.startswith("APPROVAL TOKEN:")]
        return rc, out, (token[0] if token else None)

    def test_documented_sequence_deploys_with_local_config_commits(self):
        self.documented_sequence()
        rc, out, token = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertIn("DEPLOY GATE: PASS", out)
        rc, out = self.run_cli("--deploy", "--approve", token, "--confirm", "production")
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.w.z.writes())

    def test_documented_commands_are_the_ones_in_the_docs(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "docs", "ONBOARDING.md"), encoding="utf-8") as fh:
            doc = fh.read()
        for line in INSTALL + [COMMIT_SETTINGS, UPDATE]:
            self.assertIn(line, doc)

    def test_local_code_change_blocks_deploy_committed_or_not(self):
        self.documented_sequence()
        code = os.path.join(self.base, "netalert", "code.py")
        with open(code, "a", encoding="utf-8") as fh:
            fh.write("PATCHED = True\n")
        rc, out, _ = self.verify()
        self.assertEqual(rc, 1)
        self.assertIn("uncommitted or untracked changes outside the site configuration", out)
        sh(self.base, "git", "commit", "-q", "-am", "hotfix")
        rc, out, _ = self.verify()
        self.assertEqual(rc, 1)
        self.assertIn("change files outside the site configuration: zabbix-alerting/netalert/code.py", out)

    def test_untracked_code_file_blocks_deploy(self):
        self.documented_sequence()
        with open(os.path.join(self.base, "netalert", "extra.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        rc, out, _ = self.verify()
        self.assertEqual(rc, 1)
        self.assertIn("netalert/extra.py", out)

    def test_repinning_a_local_commit_is_refused(self):
        self.documented_sequence()
        sh(self.base, "git", "commit", "-q", "--allow-empty", "-m", "local")
        local = self.head(self.base)
        prod = os.path.join(self.base, "config", "environments", "production.yaml")
        with open(prod, encoding="utf-8") as fh:
            text = fh.read()
        with open(prod, "w", encoding="utf-8") as fh:
            fh.write(text.replace(self.pin, local))
        sh(self.base, "git", "commit", "-q", "-am", "re-pin to local")
        rc, out, _ = self.verify()
        self.assertEqual(rc, 1)
        self.assertIn("is not a commit fetched from GitHub", out)
        answers = iter(["https://zbx.prod.example", ""])                   # --setup does not even offer it
        rc, out = self.run_cli("--setup", ask=lambda q: next(answers))
        self.assertIn("deploy_pin not offered", out)

    def test_update_carries_site_configuration_and_repins(self):
        self.documented_sequence()
        before = open(os.path.join(self.base, "config", "interfaces.production.yaml"), encoding="utf-8").read()
        self._upstream_commit("netalert/code.py", "VERSION = 3\n")
        new = self.head(self.up)
        out = []
        rc = onboard_cli.update_checkout(self.base, new, os.path.join(self.base, "config", "environments",
                                                                      "production.yaml"), out.append, sleep=lambda s: 0)
        self.assertEqual(rc, 0, out)
        self.assertEqual(open(os.path.join(self.base, "netalert", "code.py"), encoding="utf-8").read(), "VERSION = 3\n")
        self.assertEqual(open(os.path.join(self.base, "config", "interfaces.production.yaml"), encoding="utf-8").read(),
                         before)
        self.pin = new
        rc, out, _ = self.verify()
        self.assertEqual(rc, 0, out)

    def test_update_refuses_conflicting_site_file(self):
        self.documented_sequence()
        self._upstream_commit("config/interfaces.production.yaml", "hosts: {}\n# upstream format change\n")
        head = self.head(self.base)
        out = []
        rc = onboard_cli.update_checkout(self.base, self.head(self.up), os.path.join(
            self.base, "config", "environments", "production.yaml"), out.append, sleep=lambda s: 0)
        self.assertEqual(rc, 1, out)
        self.assertIn("merge by hand", "\n".join(out))
        self.assertEqual(self.head(self.base), head)                              # nothing changed

    def test_plain_merge_of_a_shallow_fetch_fails(self):
        """Why the old documented update ('git merge FETCH_HEAD') was replaced."""
        self.documented_sequence()
        self._upstream_commit("netalert/code.py", "VERSION = 3\n")
        bash(self.base, "git fetch -q --depth 1 origin %s" % self.head(self.up))
        r = sh(self.base, "git", "merge", "--no-edit", "FETCH_HEAD", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unrelated histories", r.stderr)


# ================================================================== F5 (P1) recorder / NetBox

class RecorderSecurity(unittest.TestCase):
    SECRETS = ("acme-bank.local", "ACME-BANK escalation", "ACME HQ Olaya", "Customer ACME", "jdoe@acme",
               "Cannot connect to 10.9.8.7", "edge1.acme", "ACME-SMTP", "Riyadh", "Treasury")

    def test_every_free_text_field_is_pseudonymized(self):
        w = World()
        try:
            z = w.z
            z.hosts[w.ids["r1"]]["interfaces"][0]["dns"] = "edge1.acme-bank.local"
            for a in z.actions.values():
                a["name"] = "ACME-BANK escalation"
            z.mediatypes[w.ids["email"]]["name"] = "ACME-SMTP"
            z.add_macro(w.ids["r1"], "{$SITE.NAME}", "ACME HQ Olaya")
            z.hosts[w.ids["r1"]]["tags"].append({"tag": "customer", "value": "Customer ACME"})
            for t in z.triggers.values():
                t["description"] = "Link to Treasury down"
                t["error"] = "Cannot connect to 10.9.8.7"
            z.groups["2"] = "Riyadh/Network devices"
            z.add_user("jdoe@acme", [w.ids["noc"]])
            rec = apirecord.RecordingTransport(z.transport("tok"))
            live = discovery.discover(ZabbixClient(rec, read_only=True), now=NOW)
            calls, _ = apirecord.sanitize(rec.calls)
            text = json.dumps(calls)
            for s in self.SECRETS:
                self.assertNotIn(s, text)
            self.assertEqual(apirecord.leaks(rec.calls, calls), [])
            replay = discovery.discover(ZabbixClient(apirecord.ReplayTransport(calls), read_only=True), now=NOW)
            self.assertEqual(len(replay["hosts"]), len(live["hosts"]))
            self.assertEqual(sorted(len(h["triggers"]) for h in replay["hosts"].values()),
                             sorted(len(h["triggers"]) for h in live["hosts"].values()))
            audit = lambda snap: coverage.counts(coverage.audit(snap, ob.build(
                snap, ob.load_rules("/nonexistent"), {}, {}, ob.load_decisions("/nonexistent"), NOW)))
            self.assertEqual(audit(replay), audit(live))                  # pseudonyms keep the semantics
        finally:
            w.close()

    def test_leak_check_catches_a_survivor(self):
        calls = [{"method": "host.get", "params": {}, "result": [{"hostid": "1", "host": "SECRET-RTR"}], "error": None}]
        bad = [{"method": "host.get", "params": {}, "result": [{"hostid": "1", "host": "SECRET-RTR"}], "error": None}]
        self.assertEqual(apirecord.leaks(calls, bad), ["SECRET-RTR"])

    def test_capture_script_refuses_to_write_into_the_repository(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "scripts", "capture-api-fixtures.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("is inside the Git work tree", src)
        self.assertIn("apirecord.leaks(", src)
        with open(os.path.join(here, ".gitignore"), encoding="utf-8") as fh:
            self.assertIn("tests/fixtures/recorded/", fh.read())

    def test_netbox_same_origin_repeated_next_is_refused(self):
        n = [0]

        def opener(url):
            n[0] += 1
            if n[0] > 50:
                raise AssertionError("pagination loop not stopped")
            return {"results": [{"id": n[0]}], "next": "https://netbox.example/api/dcim/devices/?offset=0"}
        with self.assertRaises(netbox.NetBoxError):
            netbox.NetBox("https://netbox.example", "T", opener=opener).get_all("dcim/devices", {})
        self.assertLessEqual(n[0], 2)

    def test_netbox_empty_page_with_next_and_page_cap(self):
        pages = iter(range(10 ** 6))

        def opener(url):
            i = next(pages)
            return {"results": [] if i == 1 else [{"id": i}],
                    "next": "https://netbox.example/api/dcim/devices/?offset=%d" % (i + 1)}
        with self.assertRaises(netbox.NetBoxError):
            netbox.NetBox("https://netbox.example", "T", opener=opener).get_all("dcim/devices", {})


if __name__ == "__main__":
    unittest.main()
