import os
import shutil
import tempfile

from slaas import cli
from tests.fake_sla import SlaMock

LAB_ENV = """\
environment: lab
inventory: inventory/lab.yaml
zabbix: {url_env: ZABBIX_SLA_URL_LAB, token_env: ZABBIX_SLA_TOKEN_LAB, api_version: "7.0"}
"""
PROD_ENV = r"""environment: production
production: true
inventory: inventory/production.yaml
zabbix:
  url_env: ZABBIX_SLA_URL_PRODUCTION
  token_env: ZABBIX_SLA_TOKEN_PRODUCTION
  api_version: "7.0"
  url_regex: '^https://zbx\.prod\.example$'
  forbid_url_regex: '(lab|test)'
"""

# Small topology: two redundant paths (a: x+y, b: z) to the internet, plus an active verified probe on RTR-01.
MINI = """\
schema: zabbix-sla-inventory-v1
environment: lab
tag_semantics: and
components:
  c.x: {kind: link, link_id: lx}
  c.y: {kind: link, link_id: ly}
  c.z: {kind: link, link_id: lz}
paths:
  p.a: {components: [c.x, c.y]}
  p.b: {components: [c.z]}
connectivity:
  conn.net: {redundancy: parallel, members: [p.a, p.b]}
business:
  svc.net: {tier: T2, requires: [conn.net], sla_class: std}
  svc.net.verified: {tier: T3, requires: [conn.net, probe.net], sla_class: ver}
probes:
  probe.net:
    status: active
    runner: RTR-01
    verification: pinned_destination
    quorum: 2
    interval: 30s
    stale_after: 5m
    destinations:
      - {name: d1, address: 192.0.2.1, check: icmp}
      - {name: d2, address: 192.0.2.2, check: icmp}
      - {name: d3, address: 192.0.2.3, check: icmp}
slas:
  std: {title: Standard, slo: 99.9, approved: true, effective_date: 2026-01-01, timezone: Asia/Riyadh}
  ver: {title: Verified, slo: 99.5, approved: true, effective_date: 2026-01-01, timezone: Asia/Riyadh}
planned_downtime: []
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class World(object):
    """Temp project + SlaMock + the real CLI wired to it through the transport."""

    def __init__(self, inventory_text=MINI, env_name="lab", identity="lab", prod_inventory=None, token="tok"):
        self.base = tempfile.mkdtemp(prefix="sla-test-")
        write(os.path.join(self.base, "config", "environments", "lab.yaml"), LAB_ENV)
        write(os.path.join(self.base, "config", "environments", "production.yaml"), PROD_ENV)
        write(os.path.join(self.base, "inventory", "lab.yaml"), inventory_text)
        write(os.path.join(self.base, "inventory", "production.yaml"), prod_inventory or inventory_text.replace("environment: lab", "environment: production"))
        self.mock = SlaMock(token=token)
        if identity:
            self.mock.set_identity(identity)
        self.mock.add_host("RTR-01", ["Gi0/0"])
        self.env_vars = {"ZABBIX_SLA_URL_LAB": "https://zbx.lab.example", "ZABBIX_SLA_TOKEN_LAB": token,
                         "ZABBIX_SLA_URL_PRODUCTION": "https://zbx.prod.example", "ZABBIX_SLA_TOKEN_PRODUCTION": token}
        self.env_name = env_name

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def set_inventory(self, text, name="lab"):
        write(os.path.join(self.base, "inventory", name + ".yaml"), text)

    def run(self, *argv):
        lines = []
        args = list(argv)
        if "--env" not in args:
            args = ["--env", self.env_name] + args
        rc = cli.run(args, environ=self.env_vars, out=lines.append, base=self.base,
                     transport_factory=lambda url, token, verify: self.mock.transport(token))
        return rc, "\n".join(lines)

    def backups(self):
        d = os.path.join(self.base, "state", "backups")
        return sorted(os.path.join(d, f) for f in os.listdir(d)) if os.path.isdir(d) else []
