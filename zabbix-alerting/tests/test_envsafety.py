"""LAB / PRODUCTION separation: the controls that stop one environment acting on the other."""
import glob
import json
import os
import unittest

from netalert import envsafety
from netalert.zbx import ReadOnlyViolation, ZabbixClient
from tests.fake_zabbix import MockZabbix
from tests.helpers import World


class IdentityFailsClosed(unittest.TestCase):
    def test_lab_run_against_production_identified_server_is_refused(self):
        w = World()
        try:
            w.mock.gmacros["1"] = {"globalmacroid": "1", "macro": "{$NETOPS.ENVIRONMENT}",
                                   "value": "production", "description": ""}
            for args in (("--check",), ("--dry-run",), ()):
                rc, out = w.run(*args)
                self.assertEqual(rc, 3, args)
                self.assertIn("IDENTITY MISMATCH", out)
            self.assertEqual(w.mock.writes(), [])
        finally:
            w.close()

    def test_matching_identity_passes(self):
        w = World()
        try:
            w.mock.gmacros["1"] = {"globalmacroid": "1", "macro": "{$NETOPS.ENVIRONMENT}",
                                   "value": "lab", "description": ""}
            rc, out = w.run("--check")
            self.assertEqual(rc, 0, out)
            self.assertIn("=lab matches --env", out)
        finally:
            w.close()

    def test_api_version_mismatch_is_refused(self):
        w = World(mock=MockZabbix(token="tok-lab", version="6.0.28"))
        try:
            rc, out = w.run("--check")
            self.assertEqual(rc, 3)
            self.assertIn("does not match required 7.0", out)
        finally:
            w.close()

    def test_lab_claims_itself_once_and_never_overwrites(self):
        w = World()
        try:
            self.assertEqual(w.run()[0], 0)
            self.assertEqual([g["value"] for g in w.mock.gmacros.values()], ["lab"])
            # later someone repoints the macro; the next run must refuse, not "fix" it
            list(w.mock.gmacros.values())[0]["value"] = "production"
            rc, out = w.run()
            self.assertEqual(rc, 3)
            self.assertEqual([g["value"] for g in w.mock.gmacros.values()], ["production"])
        finally:
            w.close()


class UrlGuards(unittest.TestCase):
    def test_production_url_must_match_regex(self):
        w = World(env_name="production")
        try:
            w.env_vars["ZABBIX_URL_PRODUCTION"] = "https://zbx.somewhere-else.example"
            rc, out = w.run("--check")
            self.assertEqual(rc, 3)
            self.assertIn("does not match zabbix.url_regex", out)
        finally:
            w.close()

    def test_production_forbid_regex(self):
        w = World(env_name="production")
        try:
            w.env_vars["ZABBIX_URL_PRODUCTION"] = "https://zbx.prod.example"
            found = envsafety.url_findings(w.base, envsafety.load_env(w.base, "production"),
                                           "https://zbx.prod.example/lab", w.env_vars)
            self.assertTrue(any("forbid_url_regex" in f for f in found), found)
        finally:
            w.close()

    def test_same_url_for_two_environments_is_refused(self):
        w = World(env_name="lab")
        try:
            w.env_vars["ZABBIX_URL_LAB"] = w.env_vars["ZABBIX_URL_PRODUCTION"]      # misconfigured .env
            rc, out = w.run("--check")
            self.assertEqual(rc, 3)
            self.assertIn("also the configured target of environment 'production'", out)
        finally:
            w.close()

    def test_missing_variables_stop_before_any_call(self):
        w = World()
        try:
            del w.env_vars["ZABBIX_TOKEN_LAB"]
            rc, out = w.run("--check")
            self.assertEqual(rc, 2)
            self.assertIn("ZABBIX_TOKEN_LAB", out)
            self.assertEqual(w.mock.calls, [])
        finally:
            w.close()

    def test_environment_uses_only_its_own_variables(self):
        w = World(env_name="production")
        try:
            w.env_vars["ZABBIX_TOKEN_PRODUCTION"] = ""
            rc, out = w.run("--check")
            self.assertEqual(rc, 2)         # does NOT fall back to the LAB token
            self.assertIn("ZABBIX_TOKEN_PRODUCTION", out)
        finally:
            w.close()

    def test_env_file_must_agree_with_selected_name(self):
        w = World()
        try:
            p = os.path.join(w.base, "config", "environments", "lab.yaml")
            with open(p) as fh:
                txt = fh.read().replace("environment: lab", "environment: production")
            with open(p, "w") as fh:
                fh.write(txt)
            rc, out = w.run("--check")
            self.assertEqual(rc, 2)
            self.assertIn("refusing", out)
        finally:
            w.close()

    def test_bad_environment_names(self):
        w = World()
        try:
            for name in ("../etc", "LAB", "", "a b"):
                self.assertEqual(w.run("--env", name, "--check")[0], 2, name)
        finally:
            w.close()


class ProductionGate(unittest.TestCase):
    def setUp(self):
        self.w = World(env_name="production")

    def tearDown(self):
        self.w.close()

    def test_banner_and_dry_run_read_only(self):
        rc, out = self.w.run("--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("ENVIRONMENT : PRODUCTION", out)
        self.assertIn("ZABBIX      : https://zbx.prod.example", out)
        self.assertIn("PLANNED", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_apply_refuses_unclaimed_server(self):
        rc, out = self.w.run("--confirm", "production")
        self.assertEqual(rc, 3)
        self.assertIn("--init-identity", out)
        self.assertEqual(self.w.mock.writes(), [])

    def test_init_identity_needs_confirmation(self):
        rc, out = self.w.run("--init-identity")
        self.assertEqual(rc, 3)
        self.assertEqual(self.w.mock.writes(), [])
        rc, out = self.w.run("--init-identity", "--confirm", "production")
        self.assertEqual(rc, 0, out)
        self.assertEqual([g["value"] for g in self.w.mock.gmacros.values()], ["production"])

    def test_apply_needs_explicit_confirm(self):
        self.w.run("--init-identity", "--confirm", "production")
        rc, out = self.w.run()
        self.assertEqual(rc, 3)
        self.assertIn("re-run with --confirm production", out)
        self.assertIn("ENVIRONMENT : PRODUCTION", out)
        self.assertEqual(self.w.mock.writes(), ["usermacro.createglobal"])      # identity only
        rc, out = self.w.run("--confirm", "wrong")
        self.assertEqual(rc, 3)
        rc, out = self.w.run("--confirm", "production")
        self.assertEqual(rc, 0, out)
        self.assertIn("verification plan is empty", out)

    def test_backup_written_before_production_change(self):
        self.w.run("--init-identity", "--confirm", "production")
        self.w.run("--confirm", "production")
        files = glob.glob(os.path.join(self.w.base, "state", "backups", "production-*.json"))
        self.assertEqual(len(files), 1)
        with open(files[0]) as fh:
            data = json.load(fh)
        self.assertEqual(data["environment"], "production")
        self.assertTrue(data["planned"])
        self.assertNotIn("tok-lab", json.dumps(data))             # no secrets in backups
        self.assertEqual(oct(os.stat(files[0]).st_mode & 0o777)[-3:], "600") if os.name == "posix" else None

    def test_backup_records_previous_managed_state(self):
        self.w.run("--init-identity", "--confirm", "production")
        self.w.run("--confirm", "production")
        from tests.helpers import BASIC
        self.w.set_yaml(BASIC.replace("threshold: 70, recovery: 65", "threshold: 80, recovery: 75"))
        self.w.run("--confirm", "production")
        newest = sorted(glob.glob(os.path.join(self.w.base, "state", "backups", "production-*.json")))[-1]
        with open(newest) as fh:
            data = json.load(fh)
        vals = dict((m["macro"], m["value"]) for m in data["owned_macros"])
        self.assertEqual(vals['{$NETOPS.UTIL.MAX:"Gi0/0"}'], "70")       # what was there before this run


class ClientGuards(unittest.TestCase):
    def test_read_only_client_refuses_every_write_method(self):
        z = MockZabbix()
        c = ZabbixClient(z.transport(), read_only=True)
        for m in ("usermacro.create", "usermacro.update", "usermacro.delete", "usermacro.createglobal",
                  "host.massadd", "host.massremove", "host.update", "configuration.import",
                  "action.create", "action.update", "task.create", "template.delete"):
            with self.assertRaises(ReadOnlyViolation, msg=m):
                c.call(m, {})
        self.assertEqual(z.calls, [])
        self.assertEqual(c.writes_made(), [])

    def test_reads_are_allowed_read_only(self):
        c = ZabbixClient(MockZabbix().transport(), read_only=True)
        self.assertEqual(c.version(), "7.0.30")
        self.assertEqual(c.call("host.get", {"output": ["hostid"]}), [])
        self.assertEqual(c.call("configuration.export", {"format": "json", "options": {"templates": []}})[:1], "{")


class NoSecretsInTree(unittest.TestCase):
    def test_env_example_has_no_token_values_and_env_is_ignored(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".env.example")) as fh:
            for line in fh:
                if line.startswith("ZABBIX_TOKEN"):
                    self.assertEqual(line.strip().split("=", 1)[1], "")
        with open(os.path.join(root, ".gitignore")) as fh:
            self.assertIn(".env", fh.read().split())
        self.assertFalse(os.path.exists(os.path.join(root, ".env")))

    def test_shipped_environment_files_carry_no_urls_or_tokens(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "config", "environments", "production.yaml"), encoding="utf-8") as fh:
            if "CHANGE-ME-TO-YOUR-PRODUCTION-URL-REGEX" not in fh.read():
                self.skipTest("site-configured deployment: production.yaml has been filled in by the operator")
        for fn in glob.glob(os.path.join(root, "config", "environments", "*.yaml")):
            with open(fn) as fh:
                txt = fh.read()
            self.assertNotRegex(txt, r"https?://\S*\.\S+", fn)
            self.assertNotRegex(txt, r"\b\d{1,3}(\.\d{1,3}){3}\b", fn)


if __name__ == "__main__":
    unittest.main()


class PerEnvironmentInventory(unittest.TestCase):
    def test_each_environment_reads_only_its_own_inventory(self):
        from tests.helpers import BASIC, write
        w = World(env_name="production")
        try:
            cfg = os.path.join(w.base, "config")
            os.remove(os.path.join(cfg, "interfaces.yaml"))                    # no legacy single-file layout
            write(os.path.join(cfg, "interfaces.lab.yaml"), BASIC)           # LAB inventory exists...
            write(os.path.join(cfg, "interfaces.production.yaml"), "hosts: {}\n")
            rc, out = w.run("--dry-run", "--config", os.path.join(cfg, "interfaces.production.yaml"))
            self.assertEqual(rc, 0, out)
            # production default must be the production file, never the LAB one
            from netalert import cli
            self.assertTrue(cli.default_policy(w.base, "production").endswith("interfaces.production.yaml"))
            self.assertTrue(cli.default_policy(w.base, "lab").endswith("interfaces.lab.yaml"))
            rc, out = w.run("--check")                                         # default policy = production's (empty)
            self.assertNotIn("RTR-01", out)
            rc, out = w.run("--confirm", "production")
            self.assertNotEqual(rc, 0)
            self.assertEqual(w.mock.writes(), [])
        finally:
            w.close()

    def test_shipped_production_inventory_is_empty_and_has_no_lab_objects(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "config", "interfaces.production.yaml"), encoding="utf-8") as fh:
            text = fh.read()
        if "RTR" in text or "Gi" in text or "hosts: {}" not in text:
            self.skipTest("site-configured deployment: the operator has added production interfaces")
        self.assertNotIn("PNET", text)
        import yaml as _y
        self.assertEqual(_y.safe_load(text), {"hosts": {}})
