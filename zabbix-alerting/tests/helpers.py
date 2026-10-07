import os
import shutil
import tempfile
import textwrap

from netalert import cli
from tests.fake_zabbix import MockZabbix

LAB_YAML = """\
environment: lab
auto_init_identity: true
zabbix:
  url_env: ZABBIX_URL_LAB
  token_env: ZABBIX_TOKEN_LAB
  api_version: "7.0"
"""
PROD_YAML = r"""environment: production
production: true
auto_init_identity: false
zabbix:
  url_env: ZABBIX_URL_PRODUCTION
  token_env: ZABBIX_TOKEN_PRODUCTION
  api_version: "7.0"
  url_regex: '^https://zbx\.prod\.example$'
  forbid_url_regex: '(lab|test)'
"""

BASIC = """\
hosts:
  RTR-01:
    site: HQ
    interfaces:
      Gi0/0:
        description: STC Internet
        role: ISP
        severity: disaster
        utilization: {enabled: true, threshold: 70, recovery: 65}
      Gi0/1:
        description: Core link
        role: CORE
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text) if text.startswith("\n") or text.startswith(" ") else text)


class World(object):
    """A temp project dir + a MockZabbix + the real CLI wired to it through the transport."""

    def __init__(self, env_name="lab", yaml_text=BASIC, mock=None, lab_extra="", token="tok-lab"):
        self.base = tempfile.mkdtemp(prefix="netalert-test-")
        write(os.path.join(self.base, "config", "environments", "lab.yaml"), LAB_YAML + lab_extra)
        write(os.path.join(self.base, "config", "environments", "production.yaml"), PROD_YAML)
        self.set_yaml(yaml_text)
        self.mock = mock or MockZabbix(token=token)
        if not mock:
            self.mock.add_host("RTR-01", ["Gi0/0", "Gi0/1", "HundredGigE0/0/0/0"])
            self.mock.add_host("RTR-02", ["Gi0/0", "TenGigE0/0/0/3"])
        self.env_vars = {
            "ZABBIX_URL_LAB": "https://zbx.lab.example", "ZABBIX_TOKEN_LAB": token,
            "ZABBIX_URL_PRODUCTION": "https://zbx.prod.example", "ZABBIX_TOKEN_PRODUCTION": token,
        }
        self.env_name = env_name

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def set_yaml(self, text):
        write(os.path.join(self.base, "config", "interfaces.yaml"), text)

    def run(self, *argv):
        lines = []
        args = list(argv)
        if "--env" not in args:
            args = ["--env", self.env_name] + args
        rc = cli.run(args, environ=self.env_vars, out=lines.append, base=self.base,
                     transport_factory=lambda url, token, verify: self.mock.transport(token))
        return rc, "\n".join(lines)
