import os
import shutil
import subprocess
import stat
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = os.path.join(ROOT, "release")
BASH = shutil.which("bash")


def sh(*args, **kw):
    p = subprocess.run([BASH] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, **kw)
    return p.returncode, p.stdout


@unittest.skipUnless(BASH and os.name == "posix", "release scripts need bash on POSIX")
class Lifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.dist = os.path.join(cls.tmp, "dist")
        rc, out = sh(os.path.join(REL, "build-package.sh"), cls.dist)
        assert rc == 0, out
        cls.pkg = [os.path.join(cls.dist, f) for f in os.listdir(cls.dist) if f.endswith(".tar.gz")][0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def prefix(self):
        return os.path.join(tempfile.mkdtemp(dir=self.tmp), "hh")

    def test_build_has_checksum_and_no_state(self):
        self.assertTrue(os.path.exists(self.pkg + ".sha256"))
        rc, out = sh("-c", "tar -tzf '%s' | grep -E '/(state|evidence|dist)/' | head -1" % self.pkg)
        self.assertEqual(out.strip(), "")

    def test_install_verify_upgrade_rollback(self):
        p = self.prefix()
        rc, out = sh(os.path.join(REL, "install.sh"), self.pkg, "--prefix", p)
        self.assertEqual(rc, 0, out)
        rc, out = sh(os.path.join(p, "current", "release", "verify-deployment.sh"), p)
        self.assertEqual(rc, 0, out)
        # operator edits config; an upgrade must keep it
        with open(os.path.join(p, "config", "operator-note.txt"), "w") as fh:
            fh.write("keep me\n")
        with open(os.path.join(p, "state", "ledger.json"), "w") as fh:
            fh.write("{}")
        rc, out = sh(os.path.join(REL, "upgrade.sh"), self.pkg, "--prefix", p)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.exists(os.path.join(p, "config", "operator-note.txt")))
        self.assertTrue(os.path.exists(os.path.join(p, "state", "ledger.json")))
        self.assertTrue([f for f in os.listdir(os.path.join(p, "backups")) if f.startswith("pre-upgrade")])
        rc, out = sh(os.path.join(REL, "rollback.sh"), "--prefix", p)
        self.assertIn(rc, (0, 1))          # same version twice: no distinct previous release exists

    def test_second_version_rolls_back_to_first(self):
        p = self.prefix()
        self.assertEqual(sh(os.path.join(REL, "install.sh"), self.pkg, "--prefix", p)[0], 0)
        first = os.readlink(os.path.join(p, "current"))
        # build a second package with a different version
        work = os.path.join(self.tmp, "v2")
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", "state", "dist", ".git"))
        init = os.path.join(work, "hwh", "__init__.py")
        with open(init) as fh:
            t = fh.read()
        with open(init, "w") as fh:
            fh.write(t.replace("0.3.1-rc2", "0.3.1-rc3"))
        rc, out = sh(os.path.join(work, "release", "build-package.sh"), os.path.join(work, "dist"))
        self.assertEqual(rc, 0, out)
        pkg2 = os.path.join(work, "dist", "netops-hardware-health-0.3.1-rc3.tar.gz")
        rc, out = sh(os.path.join(REL, "upgrade.sh"), pkg2, "--prefix", p)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.readlink(os.path.join(p, "current")).endswith("0.3.1-rc3"))
        rc, out = sh(os.path.join(REL, "rollback.sh"), "--prefix", p)
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.readlink(os.path.join(p, "current")), first)

    def test_tampered_package_refused(self):
        p = self.prefix()
        bad = os.path.join(self.tmp, "bad.tar.gz")
        shutil.copy(self.pkg, bad)
        shutil.copy(self.pkg + ".sha256", bad + ".sha256")
        with open(bad, "ab") as fh:
            fh.write(b"x")
        rc, out = sh(os.path.join(REL, "install.sh"), bad, "--prefix", p)
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(p, "current")))

    def test_tampered_release_fails_verification(self):
        p = self.prefix()
        sh(os.path.join(REL, "install.sh"), self.pkg, "--prefix", p)
        target = os.path.join(p, "current", "hwh", "expr.py")
        os.chmod(target, 0o644)
        with open(target, "a") as fh:
            fh.write("# tamper\n")
        rc, out = sh(os.path.join(p, "current", "release", "verify-deployment.sh"), p)
        self.assertNotEqual(rc, 0)
        self.assertIn("manifest", out)

    def test_missing_checksum_file_refused(self):
        p = self.prefix()
        lone = os.path.join(self.tmp, "lone.tar.gz")
        shutil.copy(self.pkg, lone)
        self.assertNotEqual(sh(os.path.join(REL, "install.sh"), lone, "--prefix", p)[0], 0)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(BASH and os.name == "posix", "release scripts need bash on POSIX")
class StateAndReproducibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        env = dict(os.environ, SOURCE_DATE_EPOCH="1700000000")
        for n in ("a", "b"):
            p = subprocess.run([BASH, os.path.join(REL, "build-package.sh"), os.path.join(cls.tmp, n)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
            assert p.returncode == 0, p.stdout
        cls.pkg = [os.path.join(cls.tmp, "a", f) for f in os.listdir(os.path.join(cls.tmp, "a")) if f.endswith(".tar.gz")][0]
        cls.pkg_b = [os.path.join(cls.tmp, "b", f) for f in os.listdir(os.path.join(cls.tmp, "b")) if f.endswith(".tar.gz")][0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_package_is_reproducible(self):
        with open(self.pkg, "rb") as a, open(self.pkg_b, "rb") as b:
            self.assertEqual(a.read(), b.read())
        with open(self.pkg + ".sha256") as a, open(self.pkg_b + ".sha256") as b:
            self.assertEqual(a.read().split()[0], b.read().split()[0])

    def test_ownership_state_and_immutable_backups_survive_install_upgrade_and_rollback(self):
        p = os.path.join(self.tmp, "prefix")
        self.assertEqual(sh(os.path.join(REL, "install.sh"), self.pkg, "--prefix", p)[0], 0)
        own = os.path.join(p, "state", "ownership")
        bak = os.path.join(p, "state", "backups")
        os.makedirs(own, mode=0o700)
        os.makedirs(bak, mode=0o700)
        rec = os.path.join(own, "template-lab-cisco-iosxe.json")
        bf = os.path.join(bak, "template-lab-cisco-iosxe-20261009T000000Z-aaaaaa-update.json")
        with open(rec, "w") as fh:
            fh.write('{"nonce":"x"}')
        os.chmod(rec, 0o600)
        with open(bf, "w") as fh:
            fh.write('{"export":"original"}')
        os.chmod(bf, 0o400)
        before = {rec: _read(rec), bf: _read(bf)}
        modes = {rec: stat.S_IMODE(os.stat(rec).st_mode), bf: stat.S_IMODE(os.stat(bf).st_mode)}
        # a second release (upgrade), then rollback of the code
        work = os.path.join(self.tmp, "v2")
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", "state", "dist", ".git"))
        init = os.path.join(work, "hwh", "__init__.py")
        with open(init) as fh:
            t = fh.read()
        with open(init, "w") as fh:
            fh.write(t.replace("0.3.1-rc2", "0.3.1-rc9"))
        self.assertEqual(sh(os.path.join(work, "release", "build-package.sh"), os.path.join(work, "dist"))[0], 0)
        pkg2 = os.path.join(work, "dist", "netops-hardware-health-0.3.1-rc9.tar.gz")
        rc, out = sh(os.path.join(REL, "upgrade.sh"), pkg2, "--prefix", p)
        self.assertEqual(rc, 0, out)
        self.assertEqual(sh(os.path.join(REL, "rollback.sh"), "--prefix", p)[0], 0)
        for path, text in before.items():
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(_read(path), text)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), modes[path])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(p, "state")).st_mode), 0o700)
        # the pre-upgrade backup holds the ownership state and the immutable backups
        bk = [f for f in os.listdir(os.path.join(p, "backups")) if f.startswith("pre-upgrade")]
        self.assertTrue(bk)
        listing = subprocess.run(["tar", "-tzf", os.path.join(p, "backups", bk[0])], stdout=subprocess.PIPE, universal_newlines=True).stdout
        self.assertIn("template-lab-cisco-iosxe.json", listing)
        self.assertIn("-update.json", listing)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(p, "backups", bk[0])).st_mode), 0o600)
        # verify-deployment still passes, and flags loosened permissions on ownership state
        rc, out = sh(os.path.join(p, "current", "release", "verify-deployment.sh"), p)
        self.assertEqual(rc, 0, out)
        os.chmod(rec, 0o644)
        rc, out = sh(os.path.join(p, "current", "release", "verify-deployment.sh"), p)
        self.assertNotEqual(rc, 0)
        self.assertIn("ownership", out)


def _read(path):
    with open(path) as fh:
        return fh.read()
