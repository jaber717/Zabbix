"""Tag taxonomy. Everything this project creates is namespaced and carries the ownership marker."""

MANAGED_KEY = "managed_by"
MANAGED_VALUE = "zabbix-sla"
ID_KEY = "sla_id"                     # stable service identity (names may change)
SERVICE_TAGS = ("layer", "site", "provider", "tier", "sla_class")
LAYERS = ("component", "path", "connectivity", "business", "probe", "quality")
TIERS = ("T1", "T2", "T3")

# problem tags emitted by the NETOPS alerting framework (read-only knowledge, see evidence/tag-audit-lab.json)
NETOPS_ALERT = "netops_alert"
NETOPS_LINK_ID = "link_id"
NETOPS_AVAILABILITY_ALERTS = ("link_down",)                       # the ONLY netops alert that means "unavailable"
NETOPS_NON_AVAILABILITY = ("util_rx", "util_tx", "errors", "discards", "flapping", "speed_degraded")

# problem tags owned by this project (probe triggers); one unique tag per signal, so no AND/OR dependence
PROBE_DOWN = "sla_probe"
PROBE_STALE = "sla_probe_stale"

# tags that must never appear in a service condition (volatile or not identity-bearing)
FORBIDDEN_IN_CONDITIONS = ("threshold", "direction", "if_descr", "severity_label", "site", "scope", "class", "component", "target")
FORBIDDEN_PREFIXES = ("__telegram", "__")

OP_EQUALS, OP_LIKE = 0, 2

NAME_PREFIX = "NETOPS-SLA: "
SLA_DESC_MARKER = "managed_by=zabbix-sla"
TRIGGER_MARKER = "[NETOPS-SLA] "


def owned_tags(sla_id, **extra):
    t = {MANAGED_KEY: MANAGED_VALUE, ID_KEY: sla_id}
    t.update(dict((k, v) for k, v in extra.items() if v))
    return t


def condition_ok(tag):
    if tag in FORBIDDEN_IN_CONDITIONS or tag.startswith(FORBIDDEN_PREFIXES):
        return False
    return True
