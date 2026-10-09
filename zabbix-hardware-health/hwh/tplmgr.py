"""Guarded plan / apply / rollback of the generated NETOPS-HW templates (LAB only in this release).

A template is OWNED only when the live template carries the ownership marker AND the same definition id in its description. A same-named template
without them is a CONFLICT and is never updated, deleted or adopted. Applying never links the template to any host (linking is an operator step).
Rollback restores the exact pre-change export, or deletes the template only if it is owned, was created by this tool (backup says so) and is linked
to no host."""
import json
import os
import re

from . import importcheck, template
from .api import AuditError

DESC_RE = re.compile(r"managed_by=netops-hardware-health version=(\S+) definition=(\S+) hash=([0-9a-f]*)")


def _desc(live):
    m = DESC_RE.search(live.get("description", "") or "")
    return m.groups() if m else None


def get_live(api, name):
    r = api.call("template.get", {"filter": {"host": [name]}, "output": ["templateid", "host", "description"], "selectHosts": ["hostid", "host"],
                                  "selectParentTemplates": ["templateid"]})
    return r[0] if r else None


def plan(api, env, defn):
    out = {"template": template.template_name(defn), "action": None, "conflicts": [], "notes": [], "hash": template.content_hash(defn)}
    if env != "lab":
        out["conflicts"].append("template management is LAB only in this release (environment is %s)" % env)
        return out
    doc = template.build(defn)
    bad = importcheck.check(doc)
    if bad:
        out["conflicts"].extend("generated template failed the import check: " + b for b in bad)
        return out
    live = get_live(api, out["template"])
    if live is None:
        out["action"] = "create"
        return out
    d = _desc(live)
    if d is None or d[1] != defn["id"]:
        out["conflicts"].append("a template named %s exists and is NOT owned by this tool (no matching ownership marker); it is never modified" % out["template"])
        return out
    out["action"] = "noop" if d[2] == out["hash"] else "update"
    out["notes"].append("linked to %d host(s); an update changes them" % len(live.get("hosts", [])))
    return out


def _backup_path(base, env, name):
    d = os.path.join(base, "state", "backups")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "template-%s-%s.json" % (env, re.sub(r"[^A-Za-z0-9._-]", "_", name)))


def apply(api, env, defn, base):
    """Re-reads the live template immediately before writing; refuses on conflict."""
    if not getattr(api, "write_templates", False):
        raise AuditError("template writes were not enabled on this API client")
    p = plan(api, env, defn)
    if p["conflicts"]:
        raise AuditError("refusing to apply: " + "; ".join(p["conflicts"]))
    if p["action"] == "noop":
        return {"result": "unchanged", "plan": p}
    name = p["template"]
    live = get_live(api, name)
    backup = {"template": name, "created_by_tool": live is None, "export": None}
    if live is not None:
        backup["export"] = api.call("configuration.export", {"format": "json", "options": {"templates": [live["templateid"]]}})
    path = _backup_path(base, env, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(backup, fh, indent=2, sort_keys=True)
    api.call("configuration.import", {"format": "json", "rules": template.IMPORT_RULES, "source": json.dumps(template.build(defn))})
    after = get_live(api, name)
    if after is None or _desc(after) is None or _desc(after)[2] != p["hash"]:
        raise AuditError("template import did not produce the expected owned template; run rollback with " + path)
    return {"result": "applied", "plan": p, "backup": path}


def rollback(api, env, name, base):
    if not getattr(api, "write_templates", False):
        raise AuditError("template writes were not enabled on this API client")
    if env != "lab":
        raise AuditError("template rollback is LAB only in this release")
    path = _backup_path(base, env, name)
    if not os.path.exists(path):
        raise AuditError("no backup for %s at %s" % (name, path))
    with open(path, encoding="utf-8") as fh:
        backup = json.load(fh)
    live = get_live(api, name)
    if live is None:
        return {"result": "already-absent"}
    if _desc(live) is None:
        raise AuditError("the live template %s is not owned by this tool; refusing to touch it" % name)
    if backup["created_by_tool"]:
        if live.get("hosts"):
            raise AuditError("template %s is linked to %d host(s); unlink it first (rollback never unlinks)" % (name, len(live["hosts"])))
        api.call("template.delete", [live["templateid"]])
        return {"result": "deleted"}
    api.call("configuration.import", {"format": "json", "rules": template.IMPORT_RULES, "source": backup["export"]})
    return {"result": "restored"}
