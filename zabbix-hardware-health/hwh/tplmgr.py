"""Guarded plan / apply / rollback of the generated NETOPS-HW templates (LAB only in this release). v0.3.1 design.

OWNERSHIP is a conjunction - never a text marker, never a name:
  (1) a persistent local ownership record (state/ownership/template-<env>-<definition>.json, 0600) with the EXACT template id, the template UUID, a random
      per-deployment nonce, a deployment id, the hash of the definition and of the generated content, and the VERIFIED BASELINE: the SHA-256 and a per-object
      inventory of the template's real `configuration.export` taken right after this tool's own import and checked against the intended content;
  (2) the live template, read BY THAT ID, has that name, UUID and nonce;
  (3) its real exported content still equals the baseline. Any difference - an added item, a changed preprocessing step, an edited trigger, a new macro,
      a changed value map - is DRIFT and is a CONFLICT. There is no override flag.
A same-named / same-UUID / marker-carrying template without all three is never adopted, updated, rolled back or deleted. Ownership is re-validated against
a fresh read immediately before every write. A create cannot overwrite anything (updateExisting=false); a race is detected afterwards and fails closed.

CHANGES are planned with configuration.importcompare, which is MANDATORY: every created / updated / removed object is listed; the import runs only if the
expected operations (and nothing else) are shown. Import rules never contain deleteMissing. A template linked to any host is never updated or rolled back
by this tool (no override); the plan lists the linked hosts' ids. Nothing here links or unlinks a template.

EVERY operation writes an immutable, uniquely named backup (O_EXCL, 0400) bound to the deployment (env, definition, deployment id, nonce, exact template
id, operation id). Rollback deletes only the exact recorded id after a fresh re-read, and restores only from a backup whose binding and SHA-256 verify."""
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
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ----------------------------------------------------------------------------------------------------------------------- hashing / export / inventory
def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_desc(live):
    m = DESC_RE.search((live or {}).get("description", "") or "")
    return m.groups() if m else None


def normalize_export(text):
    """-> (canonical text, sha256, parsed object). Sorted keys; the volatile 'date' is dropped. Only Zabbix-volatile data is removed, nothing else."""
    try:
        obj = json.loads(text) if isinstance(text, str) else text
    except ValueError as exc:
        raise AuditError("configuration.export did not return JSON: %s" % exc)
    if not isinstance(obj, dict) or not isinstance(obj.get("zabbix_export"), dict) or not obj["zabbix_export"].get("templates"):
        raise AuditError("configuration.export did not return a zabbix_export document with a template")
    obj["zabbix_export"].pop("date", None)
    canon = _canon(obj)
    return canon, _sha(canon), obj


def inventory(obj):
    """{identity: sha256 of that object's own canonical content}. Identities: item:KEY, trigger:NAME, rule:KEY, item_prototype:KEY, trigger_prototype:NAME,
    valuemap:NAME, macro:NAME, meta. Child collections are hashed as their own entries, so a change is attributed to the exact object."""
    t = obj["zabbix_export"]["templates"][0]
    ent = {}

    def put(kind, key, entry, strip=()):
        k = "%s:%s" % (kind, key)
        n = 1
        while k in ent:
            n += 1
            k = "%s:%s#%d" % (kind, key, n)
        ent[k] = _sha(_canon(dict((a, b) for a, b in entry.items() if a not in strip)))

    for it in t.get("items", []):
        put("item", it.get("key", "?"), it, ("triggers",))
        for tr in it.get("triggers", []):
            put("trigger", tr.get("name", "?"), tr)
    for r in t.get("discovery_rules", []):
        put("rule", r.get("key", "?"), r, ("item_prototypes", "trigger_prototypes", "graph_prototypes", "host_prototypes"))
        for ip in r.get("item_prototypes", []):
            put("item_prototype", ip.get("key", "?"), ip, ("trigger_prototypes",))
            for tp in ip.get("trigger_prototypes", []):
                put("trigger_prototype", tp.get("name", "?"), tp)
        for tp in r.get("trigger_prototypes", []):
            put("trigger_prototype", tp.get("name", "?"), tp)
    for vm in t.get("valuemaps", []):
        put("valuemap", vm.get("name", "?"), vm)
    for m in t.get("macros", []):
        put("macro", m.get("macro", "?"), m)
    ent["meta"] = _sha(_canon(dict((a, b) for a, b in t.items() if a not in ("items", "discovery_rules", "valuemaps", "macros"))))
    return ent


def identity(obj):
    return sorted(k for k in inventory(obj) if k != "meta")


def diff_inventory(old, new):
    out = []
    for k in sorted(set(new) - set(old)):
        out.append("ADDED %s" % k)
    for k in sorted(set(old) - set(new)):
        out.append("REMOVED %s" % k)
    for k in sorted(set(old) & set(new)):
        if old[k] != new[k]:
            out.append("CHANGED %s" % k)
    return out


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
    """-> (canonical text, sha256, parsed object) of the REAL exported content of exactly this template id."""
    return normalize_export(api.call("configuration.export", {"format": "json", "options": {"templates": [str(tid)]}}))


# ----------------------------------------------------------------------------------------------------------------------- state files
def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def new_op_id():
    return "%s-%s" % (_stamp(), secrets.token_hex(3))


def record_path(base, env, defid):
    return os.path.join(base, "state", "ownership", "template-%s-%s.json" % (env, defid))


def backup_path(base, env, defid, op_id, kind):
    return os.path.join(base, "state", "backups", "template-%s-%s-%s-%s.json" % (env, defid, op_id, kind))


def _mkdir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def load_record(base, env, defid):
    if not base:
        return None
    path = record_path(base, env, defid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as exc:
        raise AuditError("ownership record %s is unreadable: %s (ownership cannot be established; nothing will be changed)" % (path, exc))
    if rec.get("definition") != defid or rec.get("env") != env or not rec.get("nonce") or not rec.get("deployment_id"):
        raise AuditError("ownership record %s is malformed or belongs to another definition/environment" % path)
    return rec


def save_record(base, env, defid, rec):
    path = record_path(base, env, defid)
    _mkdir(os.path.dirname(path))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, sort_keys=True)
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


def archive_record(base, env, defid):
    path = record_path(base, env, defid)
    if os.path.isfile(path):
        dest = "%s.archived-%s" % (path, new_op_id())
        os.replace(path, dest)
        return dest


def write_immutable(path, obj):
    """Create-only (O_EXCL): an existing file is never overwritten. Read-only afterwards. -> sha256 of the file bytes."""
    _mkdir(os.path.dirname(path))
    data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise AuditError("backup file %s already exists; backups are never overwritten" % path)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(path, 0o400)
    except OSError:
        pass
    return hashlib.sha256(data).hexdigest()


def read_verified(path, sha):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise AuditError("backup %s cannot be read: %s" % (path, exc))
    if hashlib.sha256(data).hexdigest() != sha:
        raise AuditError("backup %s fails its SHA-256 check: it was modified after it was written; refusing to use it" % path)
    return json.loads(data.decode("utf-8"))


def check_binding(bk, rec, defn, kind, op_id):
    p = []
    for field, want in (("env", rec["env"]), ("definition", defn["id"]), ("deployment_id", rec["deployment_id"]), ("nonce", rec["nonce"]), ("kind", kind), ("op_id", op_id)):
        if bk.get(field) != want:
            p.append("%s is %r, expected %r" % (field, bk.get(field), want))
    if kind != "create-intent" and rec.get("templateid") and str(bk.get("templateid")) != str(rec["templateid"]):
        p.append("templateid is %r, the record has %r" % (bk.get("templateid"), rec["templateid"]))
    if p:
        raise AuditError("the backup is not bound to this deployment (%s): refusing to use it" % "; ".join(p))


def definition_sha(defn):
    return _sha(_canon(defn))


def resolve_definition(arg):
    if isinstance(arg, dict):
        return arg
    from . import vendordefs
    name = str(arg)
    defid = name[len(template.TEMPLATE_PREFIX):] if name.startswith(template.TEMPLATE_PREFIX) else name
    defs = vendordefs.load_dir(os.path.join(HERE, "vendors"))
    if defid not in defs:
        raise AuditError("unknown template/definition %r" % name)
    return defs[defid]


# ----------------------------------------------------------------------------------------------------------------------- ownership
def ownership_problems(live, rec, defn, api, allow_shas=None):
    """([problems], drift-diff-or-None, live export (canon, sha, obj) or None). [] = this deployment demonstrably owns `live` AND its content is unchanged.
    `live` MUST have been read by the recorded id."""
    p = []
    name = template.template_name(defn)
    if live is None:
        return ["the recorded template id %s no longer exists" % rec.get("templateid")], None, None
    if rec.get("templateid") and str(live["templateid"]) != str(rec["templateid"]):
        p.append("template id %s is not the recorded id %s" % (live["templateid"], rec["templateid"]))
    if live.get("host") != name:
        p.append("the live template is named %r, expected %r" % (live.get("host"), name))
    if rec.get("uuid") and live.get("uuid") != rec["uuid"]:
        p.append("the live UUID %r is not the recorded UUID" % live.get("uuid"))
    d = parse_desc(live)
    if d is None or d[1] != defn["id"]:
        p.append("the live description carries no ownership marker for definition %s" % defn["id"])
    elif d[3] != rec["nonce"]:
        p.append("the live description does not carry this deployment's nonce (a copied marker is not ownership)")
    if p:
        return p, None, None
    base = rec.get("baseline") or {}
    if not base.get("export_sha256"):
        return ["no verified baseline is recorded: drift cannot be excluded"], None, None
    exp = export_live(api, live["templateid"])
    ok_shas = set(allow_shas or ()) | {base["export_sha256"]}
    if exp[1] not in ok_shas:
        dd = diff_inventory(base.get("inventory") or {}, inventory(exp[2]))
        return ["DRIFT: the live template's exported content differs from the last verified deployment state (%s). No override exists: review the template, then "
                "restore it by hand or remove it through a separately approved procedure" % ("; ".join(dd[:12]) + (" ..." if len(dd) > 12 else "") if dd else "hash differs")], dd, exp
    return [], None, exp


# ----------------------------------------------------------------------------------------------------------------------- importcompare
def run_compare(api, doc, rules):
    """-> (available, result-or-None, error-or-None). 'Method not found' = unsupported; any other rejection is a real signal about the file."""
    try:
        return True, api.call("configuration.importcompare", {"format": "json", "rules": rules, "source": json.dumps(doc)}), None
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
    """Flatten an importcompare result into [{'op','path','label','entry'}] (every created / updated / removed object, however deeply nested)."""
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


def judge_compare(ops, action, name, allow_removed=0):
    """-> problems. Pure policy over the flattened operations.
    create: only 'added' objects, the template itself exactly once. update: only 'added'/'updated' inside this template. restore: removals bounded by `allow_removed`."""
    problems = []
    tmpl_ops = [o for o in ops if o["path"] == "templates"]
    for o in ops:
        top = o["path"].split("/")[0] if o["path"] else ""
        if top not in ALLOWED_TOP:
            problems.append("the import would also touch %s outside the template (%s %s %s)" % (top or "?", o["op"], o["path"], o["label"]))
    for o in tmpl_ops:
        e = o["entry"]
        ident = (e.get("after") or e.get("before") or {}).get("template")
        if ident != name:
            problems.append("the import would %s a template other than %s: %s" % (o["op"], name, ident))
        if o["op"] == "removed":
            problems.append("the import would remove template %s" % name)
        if o["op"] == "updated" and (e.get("before") or {}).get("template") != (e.get("after") or {}).get("template"):
            problems.append("the import would RENAME the template")
    removed = [o for o in ops if o["op"] == "removed"]
    if action in ("create", "update") and removed:
        problems.append("%d object(s) would be DELETED (%s): deletions are never part of an apply" % (len(removed), "; ".join("%s: %s" % (o["path"], o["label"]) for o in removed[:8])))
    if action == "restore" and len(removed) > allow_removed:
        problems.append("a restore would delete %d object(s) but only %d were added by the operation being rolled back (%s)" % (
            len(removed), allow_removed, "; ".join("%s: %s" % (o["path"], o["label"]) for o in removed[:8])))
    if action == "create":
        extra = [o for o in ops if o["op"] != "added"]
        if extra:
            problems.append("a create must only add objects, but the comparison shows %s" % "; ".join("%s %s %s" % (o["op"], o["path"], o["label"]) for o in extra[:6]))
        if len([o for o in tmpl_ops if o["op"] == "added"]) != 1:
            problems.append("the comparison does not show exactly one template being created")
    if action == "update":
        if len([o for o in tmpl_ops if o["op"] == "updated"]) != 1:
            problems.append("the comparison does not show exactly this template being updated")
    return problems


def counts(ops):
    c = {}
    for o in ops:
        k = "%s %s" % (o["op"], o["path"].split("/")[-1] if o["path"] else "?")
        c[k] = c.get(k, 0) + 1
    return c


# ----------------------------------------------------------------------------------------------------------------------- plan
def _hosts(live):
    return sorted(str(h.get("hostid")) for h in (live or {}).get("hosts", []))


def plan(api, env, defn, base=None):
    """READ-ONLY (template.get / configuration.export / configuration.importcompare). Never writes."""
    name = template.template_name(defn)
    out = {"template": name, "action": None, "conflicts": [], "notes": [], "hash": template.content_hash(defn),
           "compare": {"available": None, "operations": [], "counts": {}, "obsolete_left_in_place": []},
           "linked_hosts": 0, "linked_host_ids": [], "ownership": None, "drift": None, "interrupted_operation": None}
    if env != "lab":
        out["conflicts"].append("template management is LAB only in this release (environment is %s)" % env)
        return out
    doc = template.build(defn)
    bad = importcheck.check(doc)
    if bad:
        out["conflicts"].extend("generated template failed the import check: " + b for b in bad)
        return out
    uuid = doc["zabbix_export"]["templates"][0]["uuid"]
    rec = load_record(base, env, defn["id"])
    by_name = get_by_name(api, name)
    by_uuid = get_by_uuid(api, uuid)
    if by_uuid and (by_name is None or str(by_uuid["templateid"]) != str(by_name["templateid"])):
        out["conflicts"].append("a template with this definition's UUID exists under another name/id (%s, id %s): importing would overwrite it" % (by_uuid.get("host"), by_uuid["templateid"]))
    live = None
    if rec is None:
        if by_name is not None:
            out["conflicts"].append("a template named %s (id %s) already exists and there is NO ownership record for it: it is never adopted, updated or deleted by this tool "
                                    "(a marker in its description is not ownership)" % (name, by_name["templateid"]))
        if base is None:
            out["notes"].append("no state directory was given: an apply would be refused (ownership cannot be recorded)")
        if out["conflicts"]:
            return out
        out["action"] = "create"
    else:
        steps = rec.get("steps") or []
        pend = [s for s in steps if s.get("state") != "done"]
        if rec.get("state") == "pending" or pend:
            op = (pend[-1] if pend else (steps[-1] if steps else {})).get("op_id")
            out["interrupted_operation"] = op
            out["conflicts"].append("an interrupted operation (%s) is recorded for this template: nothing further is planned until 'template rollback' has recovered or discarded it" % op)
            return out
        live = get_by_id(api, rec["templateid"])
        if live is None:
            if by_name is not None:
                out["conflicts"].append("the recorded template id %s no longer exists but a template named %s does (id %s): it was recreated or is foreign - not touched" % (
                    rec["templateid"], name, by_name["templateid"]))
                return out
            out["notes"].append("the recorded template id %s no longer exists; the stale ownership record will be archived and the template created anew" % rec["templateid"])
            out["action"] = "create"
        else:
            probs, dd, exp = ownership_problems(live, rec, defn, api)
            out["ownership"], out["drift"] = probs, dd
            out["conflicts"].extend("ownership not established: " + x for x in probs)
            if by_name is not None and str(by_name["templateid"]) != str(live["templateid"]):
                out["conflicts"].append("another template named %s exists (id %s)" % (name, by_name["templateid"]))
            out["linked_hosts"], out["linked_host_ids"] = len(live.get("hosts", [])), _hosts(live)
            if out["conflicts"]:
                return out
            d = parse_desc(live)
            gen_ids = set(identity(doc))
            live_ids = set(identity(exp[2]))
            if d and d[2] == out["hash"] and gen_ids <= live_ids:
                out["action"] = "noop"
                return out
            out["action"] = "update"
            if out["linked_hosts"]:
                out["conflicts"].append("template %s is linked to %d host(s) (ids %s): updating it would change their monitoring. Refused - there is no override; "
                                        "a linked-template change needs a separately approved procedure" % (name, out["linked_hosts"], ", ".join(out["linked_host_ids"])))
                return out
    nonce = rec["nonce"] if rec and out["action"] == "update" else ""
    src = template.build(defn, nonce)
    rules = template.IMPORT_RULES if out["action"] == "update" else template.CREATE_RULES
    avail, result, err = run_compare(api, src, rules)
    out["compare"]["available"] = avail
    if err:
        out["conflicts"].append("configuration.importcompare rejected the generated template: " + err)
        return out
    if not avail:
        out["conflicts"].append("configuration.importcompare is not available on this Zabbix: the effect of the import cannot be shown, so it is refused")
        return out
    ops = summarize_compare(result)
    out["compare"]["operations"] = [dict((k, o[k]) for k in ("op", "path", "label")) for o in ops]
    out["compare"]["counts"] = counts(ops)
    out["conflicts"].extend(judge_compare(ops, out["action"], name))
    if out["action"] == "update":
        # informational only: children that exist live but are absent from the generated source stay in place (apply never deletes)
        a2, r2, e2 = run_compare(api, src, template.RESTORE_RULES)
        if a2 and not e2:
            out["compare"]["obsolete_left_in_place"] = ["%s: %s" % (o["path"], o["label"]) for o in summarize_compare(r2) if o["op"] == "removed"]
    return out


# ----------------------------------------------------------------------------------------------------------------------- apply
def _need_writes(api, base):
    if not getattr(api, "write_templates", False):
        raise AuditError("template writes were not enabled on this API client")
    if not base:
        raise AuditError("a state directory is required: ownership and backups cannot be recorded without it")


def _import(api, doc, rules):
    api.call("configuration.import", {"format": "json", "rules": rules, "source": json.dumps(doc)})


def apply(api, env, defn, base):
    _need_writes(api, base)
    p = plan(api, env, defn, base)
    if p["conflicts"]:
        raise AuditError("refusing to apply: " + "; ".join(p["conflicts"]))
    if p["action"] == "noop":
        return {"result": "unchanged", "plan": p}
    if p["action"] == "create":
        return _create(api, env, defn, base, p)
    return _update(api, env, defn, base, p)


def _create(api, env, defn, base, p):
    name = p["template"]
    uuid = template.build(defn)["zabbix_export"]["templates"][0]["uuid"]
    old = load_record(base, env, defn["id"])
    # re-validate absence IMMEDIATELY before the write (create-time race window #1)
    if get_by_name(api, name) is not None or get_by_uuid(api, uuid) is not None:
        raise AuditError("REFUSED at the write: the template (or its UUID) appeared after planning; nothing was imported")
    nonce, dep, op_id = secrets.token_hex(12), secrets.token_hex(8), new_op_id()
    doc = template.build(defn, nonce)
    intended = identity(doc)
    avail, result, err = run_compare(api, doc, template.CREATE_RULES)
    if err or not avail:
        raise AuditError("REFUSED at the write: importcompare %s" % (err or "is not available"))
    probs = judge_compare(summarize_compare(result), "create", name)
    if probs:
        raise AuditError("REFUSED at the write: " + "; ".join(probs))
    if old is not None:
        archive_record(base, env, defn["id"])
    intent = {"format": 1, "kind": "create-intent", "op_id": op_id, "env": env, "definition": defn["id"], "deployment_id": dep, "nonce": nonce, "template_name": name,
              "uuid": uuid, "intended_identity": intended, "content_hash": p["hash"], "definition_sha256": definition_sha(defn), "at": _stamp()}
    ipath = backup_path(base, env, defn["id"], op_id, "create-intent")
    isha = write_immutable(ipath, intent)
    rec = {"env": env, "definition": defn["id"], "template": name, "uuid": uuid, "deployment_id": dep, "nonce": nonce, "templateid": None, "state": "pending",
           "definition_sha256": definition_sha(defn), "content_hash": p["hash"], "baseline": None, "created_at": _stamp(),
           "steps": [{"op_id": op_id, "kind": "create", "state": "pending", "intent": ipath, "intent_sha256": isha}]}
    save_record(base, env, defn["id"], rec)                      # pending BEFORE the import: an interrupted import is recoverable by nonce, never assumed owned
    try:
        _import(api, doc, template.CREATE_RULES)                  # cannot update anything that already exists
    except AuditError as exc:
        raise AuditError("template import failed (%s). The pending record %s was kept; run 'template rollback' to recover or discard it" % (exc, record_path(base, env, defn["id"])))
    live = get_by_name(api, name)
    d = parse_desc(live)
    if live is None or d is None or d[3] != nonce or live.get("uuid") != uuid:
        raise AuditError("CREATE-TIME RACE or failed import: the template now named %s does not carry this deployment's nonce/UUID. It is NOT treated as owned. "
                         "The pending record was kept; 'template rollback' will refuse to touch a template that is not demonstrably ours" % name)
    canon, sha, obj = export_live(api, live["templateid"])
    if identity(obj) != intended:
        raise AuditError("the imported template's real content does not match the intended content (%s); not recorded as a verified baseline. "
                         "Pending record kept for recovery" % "; ".join(diff_inventory(dict((k, "") for k in intended), dict((k, "") for k in identity(obj)))[:8]))
    created = {"format": 1, "kind": "create", "op_id": op_id, "env": env, "definition": defn["id"], "deployment_id": dep, "nonce": nonce, "templateid": str(live["templateid"]),
               "template_name": name, "uuid": uuid, "export_sha256": sha, "intended_identity": intended, "at": _stamp()}
    cpath = backup_path(base, env, defn["id"], op_id, "create")
    csha = write_immutable(cpath, created)
    rec.update(templateid=str(live["templateid"]), state="owned", baseline={"export_sha256": sha, "inventory": inventory(obj)})
    rec["steps"][0].update(state="done", created=cpath, created_sha256=csha)
    save_record(base, env, defn["id"], rec)
    return {"result": "applied", "plan": p, "record": record_path(base, env, defn["id"]), "backup": cpath, "templateid": str(live["templateid"])}


def _update(api, env, defn, base, p):
    name = p["template"]
    rec = load_record(base, env, defn["id"])
    live = get_by_id(api, rec["templateid"])
    probs, _, exp = ownership_problems(live, rec, defn, api)
    if probs:
        raise AuditError("REFUSED at the write: ownership no longer holds: " + "; ".join(probs))
    if live.get("hosts"):
        raise AuditError("REFUSED at the write: the template is linked to host(s) %s; this tool never updates a linked template" % ", ".join(_hosts(live)))
    canon, sha, obj = exp
    op_id = new_op_id()
    bk = {"format": 1, "kind": "update", "op_id": op_id, "env": env, "definition": defn["id"], "deployment_id": rec["deployment_id"], "nonce": rec["nonce"],
          "templateid": str(rec["templateid"]), "template_name": name, "uuid": rec["uuid"], "export": canon, "export_sha256": sha, "identity": identity(obj), "at": _stamp()}
    bpath = backup_path(base, env, defn["id"], op_id, "update")
    bsha = write_immutable(bpath, bk)
    back = read_verified(bpath, bsha)                              # re-read from disk: the stored original must reproduce the live export hash
    if _sha(back["export"]) != sha or normalize_export(back["export"])[1] != sha:
        raise AuditError("the stored backup does not reproduce the original export hash; nothing was imported")
    doc = template.build(defn, rec["nonce"])
    target = identity(doc)
    # final revalidation from FRESH reads immediately before the write
    live2 = get_by_id(api, rec["templateid"])
    probs, _, exp2 = ownership_problems(live2, rec, defn, api)
    if probs or exp2[1] != sha:
        raise AuditError("REFUSED at the write: the template changed while it was being backed up (%s); nothing was imported" % ("; ".join(probs) or "export hash differs"))
    live2 = get_by_id(api, rec["templateid"])                      # the LAST read before the write: link state must be current
    if live2 is None or live2.get("hosts"):
        raise AuditError("REFUSED at the write: the template became linked to host(s) %s (or disappeared); nothing was imported" % ", ".join(_hosts(live2)))
    avail, result, err = run_compare(api, doc, template.IMPORT_RULES)
    if err or not avail:
        raise AuditError("REFUSED at the write: importcompare %s" % (err or "is not available"))
    cp = judge_compare(summarize_compare(result), "update", name)
    if cp:
        raise AuditError("REFUSED at the write: " + "; ".join(cp))
    step = {"op_id": op_id, "kind": "update", "state": "pending", "backup": bpath, "backup_sha256": bsha, "pre_export_sha256": sha, "target_identity_sha256": _sha(_canon(target))}
    rec["steps"] = (rec.get("steps") or []) + [step]
    save_record(base, env, defn["id"], rec)                       # pending BEFORE the import
    try:
        _import(api, doc, template.IMPORT_RULES)
    except AuditError as exc:
        raise AuditError("template import failed (%s). The pending step %s was kept; 'template rollback' will verify and discard or restore it" % (exc, op_id))
    live3 = get_by_id(api, rec["templateid"])
    _, nsha, nobj = export_live(api, rec["templateid"])
    step["post_export_sha256"] = nsha                              # recorded at once: a crash after this point is recoverable
    save_record(base, env, defn["id"], rec)
    d = parse_desc(live3)
    ids = set(identity(nobj))
    if live3 is None or d is None or d[2] != p["hash"] or d[3] != rec["nonce"] or not set(target) <= ids or not ids - set(target) <= set(bk["identity"]):
        raise AuditError("template import did not produce the expected content (id %s); the pending step %s was kept - 'template rollback' restores backup %s" % (rec["templateid"], op_id, bpath))
    step["state"] = "done"
    rec["baseline"] = {"export_sha256": nsha, "inventory": inventory(nobj)}
    rec["content_hash"], rec["definition_sha256"] = p["hash"], definition_sha(defn)
    save_record(base, env, defn["id"], rec)
    return {"result": "applied", "plan": p, "backup": bpath, "backup_export_sha256": sha, "record": record_path(base, env, defn["id"])}


# ----------------------------------------------------------------------------------------------------------------------- rollback
def rollback(api, env, defn_or_name, base):
    defn = resolve_definition(defn_or_name)
    _need_writes(api, base)
    if env != "lab":
        raise AuditError("template rollback is LAB only in this release")
    name = template.template_name(defn)
    rec = load_record(base, env, defn["id"])
    if rec is None:
        raise AuditError("no ownership record for %s: this deployment did not create it, so it will not roll anything back (a same-named template is never touched, "
                         "and a template is never selected for deletion by name)" % name)
    steps = rec.get("steps") or []
    last = steps[-1] if steps else None
    if last is None:
        raise AuditError("the ownership record has no operation to roll back; refusing to guess")
    if last["kind"] == "create":
        return _rollback_create(api, env, defn, base, rec, last)
    return _rollback_update(api, env, defn, base, rec, last)


def _delete_exact(api, defn, rec, expect_sha):
    """Fresh re-read by id -> ownership + unchanged content + unlinked -> delete exactly that id -> verify."""
    live = get_by_id(api, rec["templateid"])
    if live is None:
        return False
    probs, _, exp = ownership_problems(live, rec, defn, api, allow_shas=[expect_sha] if expect_sha else None)
    if probs:
        raise AuditError("REFUSED: ownership of the live template is not established: " + "; ".join(probs))
    live = get_by_id(api, rec["templateid"])                       # the LAST read, immediately before the delete: still that id, still unlinked
    if live is None:
        return False
    if live.get("hosts"):
        raise AuditError("template %s is linked to host(s) %s; rollback never unlinks and never deletes a linked template" % (live["host"], ", ".join(_hosts(live))))
    api.call("template.delete", [str(live["templateid"])])
    if get_by_id(api, rec["templateid"]) is not None:
        raise AuditError("template %s still exists after the delete call" % rec["templateid"])
    return True


def _rollback_create(api, env, defn, base, rec, step):
    name = template.template_name(defn)
    if step.get("state") != "done":                                 # interrupted creation: ownership is NOT assumed
        intent = read_verified(step["intent"], step["intent_sha256"])
        check_binding(intent, rec, defn, "create-intent", step["op_id"])
        live = get_by_name(api, name)
        if live is None:
            archive_record(base, env, defn["id"])
            return {"result": "nothing-to-roll-back", "note": "the interrupted creation never produced a template"}
        d = parse_desc(live)
        _, sha, obj = export_live(api, live["templateid"])
        problems = []
        if d is None or d[3] != rec["nonce"]:
            problems.append("it does not carry this deployment's nonce")
        if live.get("uuid") != intent["uuid"]:
            problems.append("its UUID is not the intended one")
        if identity(obj) != intent["intended_identity"]:
            problems.append("its real content differs from the content this operation intended to create")
        if problems:
            raise AuditError("REFUSED: a template named %s (id %s) exists but is not demonstrably the one this interrupted operation created (%s). It is NOT touched" % (
                name, live["templateid"], "; ".join(problems)))
        if live.get("hosts"):
            raise AuditError("the template is linked to host(s) %s; rollback never deletes a linked template" % ", ".join(_hosts(live)))
        rec = dict(rec, templateid=str(live["templateid"]), baseline={"export_sha256": sha, "inventory": inventory(obj)})
        if not _delete_exact(api, defn, rec, sha):
            raise AuditError("the template disappeared during recovery; re-run")
        archive_record(base, env, defn["id"])
        return {"result": "deleted", "templateid": str(live["templateid"]), "note": "interrupted creation recovered (nonce, UUID and content matched)"}
    created = read_verified(step["created"], step["created_sha256"])
    check_binding(created, rec, defn, "create", step["op_id"])
    live = get_by_id(api, rec["templateid"])
    if live is None:
        other = get_by_name(api, name)
        archive_record(base, env, defn["id"])
        return {"result": "already-absent", "note": ("a template named %s exists (id %s) but it is not the recorded one; it was NOT touched" % (name, other["templateid"])) if other else ""}
    if not _delete_exact(api, defn, rec, None):
        archive_record(base, env, defn["id"])
        return {"result": "already-absent", "note": ""}
    archive_record(base, env, defn["id"])
    return {"result": "deleted", "templateid": str(rec["templateid"])}


def _rollback_update(api, env, defn, base, rec, step):
    name = template.template_name(defn)
    bk = read_verified(step["backup"], step["backup_sha256"])
    check_binding(bk, rec, defn, "update", step["op_id"])
    live = get_by_id(api, rec["templateid"])
    if live is None:
        raise AuditError("the recorded template id %s no longer exists; there is nothing to restore" % rec["templateid"])
    allow = []
    if step.get("state") != "done":                                 # interrupted update
        allow = [step["pre_export_sha256"]] + ([step["post_export_sha256"]] if step.get("post_export_sha256") else [])
    probs, _, exp = ownership_problems(live, rec, defn, api, allow_shas=allow)
    if probs:
        raise AuditError("REFUSED: " + "; ".join(probs))
    if live.get("hosts"):
        raise AuditError("template %s is linked to host(s) %s; this tool never restores a linked template" % (name, ", ".join(_hosts(live))))
    if step.get("state") != "done" and exp[1] == step["pre_export_sha256"]:
        rec["steps"] = rec["steps"][:-1]                           # the import never happened: nothing to restore
        save_record(base, env, defn["id"], rec)
        return {"result": "interrupted-update-discarded", "note": "the live template equals the pre-update export"}
    if step.get("state") != "done" and not step.get("post_export_sha256"):
        raise AuditError("REFUSED: the interrupted update left no post-import hash and the live template differs from the pre-update export; review it by hand")
    orig = json.loads(bk["export"])
    added_by_update = sorted(set(identity(exp[2])) - set(bk["identity"]))
    avail, result, err = run_compare(api, orig, template.RESTORE_RULES)
    if err or not avail:
        raise AuditError("REFUSED: importcompare %s" % (err or "is not available"))
    ops = summarize_compare(result)
    cp = judge_compare(ops, "restore", name, allow_removed=len(added_by_update))
    if cp:
        raise AuditError("REFUSED: " + "; ".join(cp))
    live2 = get_by_id(api, rec["templateid"])                     # fresh re-validation immediately before the write
    probs, _, exp2 = ownership_problems(live2, rec, defn, api, allow_shas=allow)
    live3 = get_by_id(api, rec["templateid"])
    if probs or exp2[1] != exp[1] or live3 is None or live3.get("hosts"):
        raise AuditError("REFUSED at the write: the template changed or became linked since it was checked (%s)" % ("; ".join(probs) or "export hash or links differ"))
    _import(api, orig, template.RESTORE_RULES)
    _, sha, obj = export_live(api, rec["templateid"])
    if sha != step["pre_export_sha256"]:
        raise AuditError("the restored template does not reproduce the original export (live %s.. vs original %s..); inspect before continuing" % (sha[:12], step["pre_export_sha256"][:12]))
    rec["steps"] = rec["steps"][:-1]
    rec["baseline"] = {"export_sha256": sha, "inventory": inventory(obj)}
    save_record(base, env, defn["id"], rec)
    return {"result": "restored", "export_sha256": sha, "removed_objects": added_by_update}
