"""Guarded plan / apply / rollback of the generated NETOPS-HW templates (LAB only in this release).

OWNERSHIP is a conjunction, never a text marker alone:
  (1) a persistent local ownership record (state/ownership/template-<env>-<definition>.json, 0600) holding the EXACT template id, a random per-deployment
      nonce, the live-export hash taken right after our own import, and a stack of the steps this deployment performed (create / update + backup);
  (2) the live template found BY THAT ID carries that nonce in its description (a copied marker line has no nonce);
  (3) its normalized live export still hashes to the recorded value (any GUI edit, link change inside the template, or foreign import is DRIFT).
A same-named / same-uuid / marker-carrying template without all three is a CONFLICT: never adopted, updated, rolled back or deleted.
Ownership is re-validated immediately before every write, and a rollback acts only on the recorded id.

CHANGE PLANNING uses configuration.importcompare: every created / updated / removed object (items, triggers, discovery rules, prototypes, value maps) is
listed. Removals need an explicit approval reference; updating a template that is linked to hosts needs one too; anything outside the template is refused.
The pre-change export is stored with its SHA-256, re-read from disk and verified before the import; a restore must reproduce that exact hash.
Nothing here links a template to a host."""
import datetime
import hashlib
import json
import os
import re
import secrets
import tempfile

from . import importcheck, template
from .api import AuditError

DESC_RE = re.compile(r"managed_by=netops-hardware-health version=(\S+) definition=(\S+) hash=([0-9a-f]*)(?: nonce=([0-9a-f]+))?")
FIELDS = ["templateid", "host", "name", "uuid", "description"]
OPS = ("added", "removed", "updated")
ALLOWED_TOP = ("templates", "template_groups")
MIN_REF = 3


# ----------------------------------------------------------------------------------------------------------------------- helpers
def parse_desc(live):
    m = DESC_RE.search((live or {}).get("description", "") or "")
    return m.groups() if m else None


def normalize_export(text):
    """Canonical text of an export (sorted keys, the volatile 'date' dropped) -> (canonical string, sha256)."""
    try:
        obj = json.loads(text) if isinstance(text, str) else text
    except ValueError as exc:
        raise AuditError("configuration.export did not return JSON: %s" % exc)
    if not isinstance(obj, dict) or "zabbix_export" not in obj:
        raise AuditError("configuration.export did not return a zabbix_export document")
    obj["zabbix_export"].pop("date", None)
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return canon, hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _get(api, flt):
    p = {"output": FIELDS, "selectHosts": ["hostid", "host"]}
    p.update(flt)
    return api.call("template.get", p)


def get_by_name(api, name):
    r = _get(api, {"filter": {"host": [name]}})
    return r[0] if r else None


def get_by_id(api, tid):
    r = _get(api, {"templateids": [str(tid)]})
    return r[0] if r else None


def get_by_uuid(api, uuid):
    r = _get(api, {"filter": {"uuid": [uuid]}})
    return r[0] if r else None


def export_live(api, tid):
    text = api.call("configuration.export", {"format": "json", "options": {"templates": [str(tid)]}})
    return normalize_export(text)


# ----------------------------------------------------------------------------------------------------------------------- ownership record
def record_path(base, env, defid):
    return os.path.join(base, "state", "ownership", "template-%s-%s.json" % (env, defid))


def load_record(base, env, defid):
    path = record_path(base, env, defid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as exc:
        raise AuditError("ownership record %s is unreadable: %s (ownership cannot be established; nothing will be changed)" % (path, exc))
    if rec.get("definition") != defid or rec.get("env") != env or not rec.get("nonce"):
        raise AuditError("ownership record %s is malformed or belongs to another definition/environment" % path)
    return rec


def _atomic_write(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save_record(base, env, defid, rec):
    _atomic_write(record_path(base, env, defid), rec)


def archive_record(base, env, defid, reason):
    path = record_path(base, env, defid)
    if os.path.isfile(path):
        dest = path + ".archived-" + _stamp()
        os.replace(path, dest)
        return dest


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ownership_problems(live, rec, defn, api, accept_drift=False):
    """[] = this deployment demonstrably owns `live`. `live` MUST have been read by the recorded id."""
    p = []
    name = template.template_name(defn)
    if live is None:
        return ["the recorded template id %s no longer exists" % rec.get("templateid")]
    if rec.get("templateid") and str(live["templateid"]) != str(rec["templateid"]):
        p.append("template id %s is not the recorded id %s" % (live["templateid"], rec["templateid"]))
    if live.get("host") != name:
        p.append("the live template is named %r, expected %r" % (live.get("host"), name))
    d = parse_desc(live)
    if d is None or d[1] != defn["id"]:
        p.append("the live description carries no ownership marker for definition %s" % defn["id"])
    elif d[3] != rec["nonce"]:
        p.append("the live description does not carry this deployment's nonce (a copied marker is not ownership)")
    if not p and not accept_drift:
        if not rec.get("live_export_sha256"):
            p.append("no recorded export hash: drift cannot be excluded")
        else:
            _, sha = export_live(api, live["templateid"])
            if sha != rec["live_export_sha256"]:
                p.append("DRIFT: the live configuration no longer matches what this deployment last wrote (export hash %s.. != recorded %s..); "
                         "someone changed the template, or it was re-imported. Review it, then re-run with --accept-drift only if overwriting is intended" % (
                             sha[:12], rec["live_export_sha256"][:12]))
    return p


# ----------------------------------------------------------------------------------------------------------------------- importcompare
def run_compare(api, source):
    """-> (available, result-or-None, error-or-None). 'Method not found' = unsupported; any other rejection is a real signal about the file."""
    try:
        return True, api.call("configuration.importcompare", {"format": "json", "rules": template.IMPORT_RULES, "source": source}), None
    except AuditError as exc:
        if re.search(r"incorrect method|method.*not found|not supported|-32601", str(exc), re.I):
            return False, None, None
        return True, None, str(exc)


def _label(entry):
    d = entry.get("after") or entry.get("before") or {}
    nm, ky = d.get("name"), d.get("key")
    if nm and ky and nm != ky:
        return ("%s (%s)" % (nm, ky))[:160]
    return str(nm or ky or d.get("template") or d.get("expression") or d.get("uuid") or "?")[:160]


def summarize_compare(result):
    """Flatten an importcompare result into [{'op','path','label'}] (every created / updated / removed object, however deeply nested)."""
    ops = []

    def walk(node, path):
        if not isinstance(node, dict):
            return
        for key, val in node.items():
            if key in OPS and isinstance(val, list):
                for e in val:
                    ops.append({"op": key, "path": "/".join(path), "label": _label(e) if isinstance(e, dict) else "?", "entry": e if isinstance(e, dict) else {}})
                    for ck, cv in (e.items() if isinstance(e, dict) else []):
                        if ck not in ("before", "after") and isinstance(cv, dict):
                            walk(cv, path + [ck])
            elif isinstance(val, dict):
                walk(val, path + [key])

    walk(result if isinstance(result, dict) else {}, [])
    return ops


def judge_compare(ops, action, name, approve_removals):
    """-> (problems, notes). Pure policy over the flattened operations."""
    problems, notes = [], []
    removed = [o for o in ops if o["op"] == "removed"]
    for o in ops:
        top = o["path"].split("/")[0] if o["path"] else ""
        if top not in ALLOWED_TOP:
            problems.append("the import would also touch %s outside the template (%s %s %s)" % (top or "?", o["op"], o["path"], o["label"]))
        elif top == "templates" and o["path"] == "templates":
            e = o["entry"]
            ident = ((e.get("after") or e.get("before") or {}).get("template"))
            if ident != name:
                problems.append("the import would %s a template other than %s: %s" % (o["op"], name, ident))
            if o["op"] == "removed":
                problems.append("the import would remove template %s" % name)
            if o["op"] == "updated" and (e.get("before") or {}).get("template") != (e.get("after") or {}).get("template"):
                problems.append("the import would RENAME the template")
    if action == "create":
        extra = [o for o in ops if not (o["op"] == "added")]
        if extra:
            problems.append("a create must only add objects, but the comparison shows %s" % "; ".join("%s %s %s" % (o["op"], o["path"], o["label"]) for o in extra[:6]))
    if removed and action != "create":
        ref = (approve_removals or "").strip()
        listing = "; ".join("%s: %s" % (o["path"], o["label"]) for o in removed[:12]) + (" ..." if len(removed) > 12 else "")
        if len(ref) < MIN_REF:
            problems.append("%d object(s) would be DELETED (%s). Refused unless --approve-removals <reference> is given" % (len(removed), listing))
        else:
            notes.append("removals approved by %r: %s" % (ref, listing))
    return problems, notes


def counts(ops):
    c = {}
    for o in ops:
        k = "%s %s" % (o["op"], o["path"].split("/")[-1] if o["path"] else "?")
        c[k] = c.get(k, 0) + 1
    return c


# ----------------------------------------------------------------------------------------------------------------------- plan
def plan(api, env, defn, base, approve_linked=None, approve_removals=None, accept_drift=False):
    name = template.template_name(defn)
    out = {"template": name, "action": None, "conflicts": [], "notes": [], "hash": template.content_hash(defn), "compare": {"available": None, "operations": [], "counts": {}},
           "linked_hosts": 0, "ownership": None}
    if env != "lab":
        out["conflicts"].append("template management is LAB only in this release (environment is %s)" % env)
        return out
    doc = template.build(defn)
    bad = importcheck.check(doc)
    if bad:
        out["conflicts"].extend("generated template failed the import check: " + b for b in bad)
        return out
    rec = load_record(base, env, defn["id"])
    by_name = get_by_name(api, name)
    by_uuid = get_by_uuid(api, doc["zabbix_export"]["templates"][0]["uuid"])
    if by_uuid and (by_name is None or str(by_uuid["templateid"]) != str(by_name["templateid"])):
        out["conflicts"].append("a template with this definition's UUID already exists under another name/id (%s, id %s): importing would overwrite it" % (by_uuid.get("host"), by_uuid["templateid"]))
    if rec is None:
        if by_name is not None:
            out["conflicts"].append("a template named %s already exists and there is NO ownership record for it here: it is never adopted, updated or deleted by this tool "
                                    "(a marker in its description is not ownership)" % name)
        if out["conflicts"]:
            return out
        out["action"] = "create"
        nonce_for_compare = ""
        live = None
    else:
        live = get_by_id(api, rec["templateid"]) if rec.get("templateid") else None
        if live is None:
            if by_name is not None:
                out["conflicts"].append("the recorded template id %s no longer exists but a template named %s does (id %s): it was recreated or is foreign - not touched" % (
                    rec.get("templateid"), name, by_name["templateid"]))
            else:
                out["notes"].append("the recorded template id %s no longer exists; the stale ownership record will be archived and the template created anew" % rec.get("templateid"))
                out["action"] = "create"
                nonce_for_compare = ""
        else:
            out["ownership"] = ownership_problems(live, rec, defn, api, accept_drift)
            if out["ownership"]:
                out["conflicts"].extend("ownership not established: " + x for x in out["ownership"])
            if by_name is not None and str(by_name["templateid"]) != str(live["templateid"]):
                out["conflicts"].append("another template named %s exists (id %s)" % (name, by_name["templateid"]))
            out["linked_hosts"] = len(live.get("hosts", []))
            if not out["conflicts"]:
                d = parse_desc(live)
                out["action"] = "noop" if d and d[2] == out["hash"] else "update"
            nonce_for_compare = rec["nonce"]
    if out["conflicts"] or out["action"] == "noop":
        return out
    if out["action"] == "update" and out["linked_hosts"] and len((approve_linked or "").strip()) < MIN_REF:
        out["conflicts"].append("template %s is linked to %d host(s); updating it changes their monitoring. Refused unless --approve-linked-update <reference> is given" % (name, out["linked_hosts"]))
    avail, result, err = run_compare(api, json.dumps(template.build(defn, nonce_for_compare)))
    out["compare"]["available"] = avail
    if err:
        out["conflicts"].append("configuration.importcompare rejected the generated template: " + err)
        return out
    if not avail:
        if out["action"] == "update":
            out["conflicts"].append("configuration.importcompare is not available on this Zabbix: the effect of an UPDATE cannot be shown, so it is refused")
        else:
            out["notes"].append("configuration.importcompare is not available; a create only adds objects (existence of the name and UUID was checked above)")
        return out
    ops = summarize_compare(result)
    out["compare"]["operations"] = [dict((k, o[k]) for k in ("op", "path", "label")) for o in ops]
    out["compare"]["counts"] = counts(ops)
    probs, notes = judge_compare(ops, out["action"], name, approve_removals)
    out["conflicts"].extend(probs)
    out["notes"].extend(notes)
    return out


# ----------------------------------------------------------------------------------------------------------------------- apply
def _need_writes(api):
    if not getattr(api, "write_templates", False):
        raise AuditError("template writes were not enabled on this API client")


def _import(api, doc):
    api.call("configuration.import", {"format": "json", "rules": template.IMPORT_RULES, "source": json.dumps(doc)})


def apply(api, env, defn, base, approve_linked=None, approve_removals=None, accept_drift=False):
    _need_writes(api)
    p = plan(api, env, defn, base, approve_linked, approve_removals, accept_drift)
    if p["conflicts"]:
        raise AuditError("refusing to apply: " + "; ".join(p["conflicts"]))
    if p["action"] == "noop":
        return {"result": "unchanged", "plan": p}
    name = p["template"]
    rec = load_record(base, env, defn["id"])
    if p["action"] == "create":
        if rec is not None:
            archive_record(base, env, defn["id"], "stale")
        # revalidate absence immediately before the write
        if get_by_name(api, name) is not None or get_by_uuid(api, template.build(defn)["zabbix_export"]["templates"][0]["uuid"]) is not None:
            raise AuditError("REFUSED at the write: the template (or its UUID) appeared after planning; nothing was imported")
        nonce = secrets.token_hex(12)
        rec = {"env": env, "definition": defn["id"], "template": name, "nonce": nonce, "templateid": None, "state": "pending", "steps": [], "live_export_sha256": None,
               "created_at": _stamp()}
        save_record(base, env, defn["id"], rec)                     # pending: a failed import is still recoverable by nonce
        _import(api, template.build(defn, nonce))
        live = get_by_name(api, name)
        if live is None or (parse_desc(live) or (None,) * 4)[3] != nonce:
            raise AuditError("template import did not produce a template carrying this deployment's nonce; the pending record %s was kept for manual recovery" % record_path(base, env, defn["id"]))
        _, sha = export_live(api, live["templateid"])
        rec.update(templateid=str(live["templateid"]), state="owned", live_export_sha256=sha, content_hash=p["hash"])
        rec["steps"].append({"kind": "create", "at": _stamp()})
        save_record(base, env, defn["id"], rec)
        return {"result": "applied", "plan": p, "record": record_path(base, env, defn["id"])}
    # update: re-read by the recorded id and re-validate ownership + drift IMMEDIATELY before writing
    live = get_by_id(api, rec["templateid"])
    probs = ownership_problems(live, rec, defn, api, accept_drift)
    if probs:
        raise AuditError("REFUSED at the write: ownership no longer holds: " + "; ".join(probs))
    live = get_by_id(api, rec["templateid"])                       # fresh read: the link state must be current at the moment of the write
    if live is None or (live.get("hosts") and len((approve_linked or "").strip()) < MIN_REF):
        raise AuditError("REFUSED at the write: the template became linked to host(s); --approve-linked-update is required")
    canon, sha = export_live(api, rec["templateid"])
    bpath = os.path.join(base, "state", "backups", "template-%s-%s-%s.json" % (env, defn["id"], _stamp()))
    backup = {"template": name, "templateid": str(rec["templateid"]), "export": canon, "export_sha256": sha, "taken_at": _stamp()}
    _atomic_write(bpath, backup)
    with open(bpath, encoding="utf-8") as fh:                       # verify the stored original, from disk, before touching anything
        back = json.load(fh)
    if hashlib.sha256(back["export"].encode("utf-8")).hexdigest() != sha or normalize_export(back["export"])[1] != sha:
        raise AuditError("the stored backup does not reproduce the original export hash; nothing was imported")
    if export_live(api, rec["templateid"])[1] != sha:
        raise AuditError("the live template changed while it was being backed up; nothing was imported")
    _import(api, template.build(defn, rec["nonce"]))
    after = get_by_id(api, rec["templateid"])
    d = parse_desc(after)
    if after is None or d is None or d[2] != p["hash"] or d[3] != rec["nonce"]:
        raise AuditError("template import did not produce the expected owned template (id %s); restore with 'template rollback' (backup %s)" % (rec["templateid"], bpath))
    _, nsha = export_live(api, rec["templateid"])
    rec.update(live_export_sha256=nsha, content_hash=p["hash"])
    rec["steps"].append({"kind": "update", "backup": bpath, "backup_export_sha256": sha, "at": _stamp()})
    save_record(base, env, defn["id"], rec)
    return {"result": "applied", "plan": p, "backup": bpath, "backup_export_sha256": sha}


# ----------------------------------------------------------------------------------------------------------------------- rollback
def rollback(api, env, defn, base, approve_linked=None, approve_removals=None, accept_drift=False):
    _need_writes(api)
    if env != "lab":
        raise AuditError("template rollback is LAB only in this release")
    name = template.template_name(defn)
    rec = load_record(base, env, defn["id"])
    if rec is None:
        raise AuditError("no ownership record for %s: this deployment did not create it, so it will not roll anything back (a same-named template is never touched)" % name)
    pending = rec.get("templateid") is None
    live = get_by_name(api, name) if pending else get_by_id(api, rec["templateid"])
    if live is None:
        other = get_by_name(api, name)
        archive_record(base, env, defn["id"], "gone")
        return {"result": "already-absent", "note": ("a template named %s exists (id %s) but it is not the recorded one; it was NOT touched" % (name, other["templateid"])) if other else ""}
    probs = ownership_problems(live, rec, defn, api, accept_drift or pending)
    if probs:
        raise AuditError("REFUSED: ownership of the live template is not established: " + "; ".join(probs))
    steps = rec.get("steps") or []
    last = steps[-1] if steps else {"kind": "create"}
    if last["kind"] == "create":
        if live.get("hosts"):
            raise AuditError("template %s is linked to %d host(s); unlink it first (rollback never unlinks)" % (name, len(live["hosts"])))
        api.call("template.delete", [str(live["templateid"])])
        archive_record(base, env, defn["id"], "deleted")
        return {"result": "deleted", "templateid": str(live["templateid"])}
    if live.get("hosts") and len((approve_linked or "").strip()) < MIN_REF:
        raise AuditError("template %s is linked to %d host(s); restoring changes their monitoring. Refused unless --approve-linked-update <reference> is given" % (name, len(live["hosts"])))
    with open(last["backup"], encoding="utf-8") as fh:
        backup = json.load(fh)
    if hashlib.sha256(backup["export"].encode("utf-8")).hexdigest() != last["backup_export_sha256"] or backup.get("export_sha256") != last["backup_export_sha256"]:
        raise AuditError("the stored original export fails its SHA-256 check (%s): refusing to restore from a modified backup" % last["backup"])
    avail, result, err = run_compare(api, backup["export"])
    if err:
        raise AuditError("configuration.importcompare rejected the stored export: " + err)
    if avail:
        probs2, _ = judge_compare(summarize_compare(result), "update", name, approve_removals or "rollback restores the previous generated version")
        if probs2:
            raise AuditError("REFUSED: " + "; ".join(probs2))
    # re-validate immediately before the write
    live2 = get_by_id(api, rec["templateid"])
    probs = ownership_problems(live2, rec, defn, api, accept_drift)
    if probs:
        raise AuditError("REFUSED at the write: ownership no longer holds: " + "; ".join(probs))
    _import(api, json.loads(backup["export"]))
    _, sha = export_live(api, rec["templateid"])
    if sha != last["backup_export_sha256"]:
        raise AuditError("the restored template does not reproduce the original export (live %s.. vs original %s..); inspect before continuing" % (sha[:12], last["backup_export_sha256"][:12]))
    rec["steps"] = steps[:-1]
    rec["live_export_sha256"] = sha
    save_record(base, env, defn["id"], rec)
    return {"result": "restored", "export_sha256": sha}
