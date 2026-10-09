# Template management design (v0.3.1-rc2)

Replaces the v0.3.0-rc1 design, which Codex rejected (NO-GO) for five reproduced defects. Code: `hwh/tplmgr.py`, `hwh/template.py` (rules). Nothing here links a template to a host, and nothing runs against a live Zabbix unless an operator invokes `template apply|rollback` with a LAB token.

## 1. Ownership (defects 1 and 2)

A description marker is **text anyone can copy**, so it is evidence of nothing. Ownership is the conjunction of:

| # | Fact | Where it lives | Checked how |
|---|---|---|---|
| 1 | exact **template id**, **UUID**, per-deployment **nonce**, **deployment id**, hash of the definition (`definition_sha256`) and of the generated content (`content_hash`) | persistent local record `state/ownership/template-<env>-<definition>.json` (0600, directory 0700), written before the import as `pending` | record must exist; unreadable / malformed / foreign record blocks everything |
| 2 | the live template **read by that id** has that name, UUID, definition marker and nonce | live `template.get` by id | all must match; a recreated template (new id) is "recreated or foreign" even if it copies marker and nonce |
| 3 | the template's **real exported content** equals the **verified baseline** | `configuration.export` of exactly that id, canonicalised (sorted keys, volatile `date` dropped) | SHA-256 equality; otherwise **DRIFT**, reported object by object |

*Baseline*: taken from the export right after this tool's own import, and only recorded after the exported content's object identities (`item:`, `trigger:`, `rule:`, `item_prototype:`, `trigger_prototype:`, `valuemap:`, `macro:`) equal the intended content. A per-object hash inventory is stored, so a drift report says `ADDED item:x`, `REMOVED ...`, `CHANGED macro:{$Y}` (any changed field, preprocessing step, expression, value-map entry...). **There is no override flag.** An operator who edited the template must review it and restore it by hand or handle it through a separate approved procedure.

*Never adopt*: with no record, any existing template with the name (or the definition UUID under another name) is a CONFLICT for plan, apply and rollback. Nothing is ever selected by name for a write or delete.

*Create-time races* are closed three ways: absence (name and UUID) is re-checked immediately before the write; the create uses `CREATE_RULES` (`updateExisting=false` everywhere), so it cannot overwrite something that appeared meanwhile; after the import the template now carrying the name must have the nonce, UUID and intended content, else the operation fails closed with a `pending` record (never "assumed owned").

*Revalidation*: every write re-reads the template by id and re-exports it **immediately before** the write (ownership + drift + linked state), after the backup was written and re-read from disk.

## 2. Linked templates (defect 4)

The plan prints the linked-host count and **exact host ids**. A template linked to any host is **never updated, restored or deleted** by this tool, and there is no override (the earlier `--approve-linked-update` was removed). The link state is read again as the very last read before a write. A linked template that is already current is simply `noop`. Hosts are never unlinked. The LAB import candidate stays unlinked until a separately approved procedure says otherwise.

## 3. Import rules and `importcompare` (defect 5)

* `IMPORT_RULES` (update) and `CREATE_RULES` (create) contain **no** `deleteMissing=true`; it is spelled out as `false` for value maps, discovery rules, items and triggers; `templateLinkage` is create/delete=false. A definition upgrade therefore never deletes a child; obsolete children are listed by the plan as "LEFT IN PLACE" (a diagnostic compare, informational only) and cleaned up by a separately approved procedure.
* `RESTORE_RULES` (`deleteMissing=true`) exists **only** for `template rollback` of an owned, unlinked, un-drifted template, and only removes objects that the very operation being rolled back added (bounded by `live identities - backup identities`; the compare must not show more removals than that, nor anything outside the template).
* `configuration.importcompare` is **mandatory** for create and update. The plan/apply refuses when it is unavailable, rejected, or when its result is not exactly the expected shape: create = one template added (+ template groups), nothing else; update = this template updated, only added/updated children, **no removal, no rename, nothing outside the template**. Every operation (created / updated / removed, any nesting depth) is printed.

## 4. Immutable operation backups and rollback (defect 3)

Each operation writes a uniquely named file `state/backups/template-<env>-<definition>-<op_id>-<kind>.json` (`kind` = `create-intent`, `create`, `update`) with `O_EXCL` (an existing file is never overwritten), mode 0400, directory 0700. It carries: operation id, kind, env, definition, **deployment id, nonce, exact template id and UUID**, and for an update the **original export, its SHA-256 and object identities**. The record stores each file's SHA-256 and the operation state (`pending` -> `done`). Backups are never deleted by rollback, upgrade or install (`state/` is preserved; the pre-upgrade archive contains it).

| Rollback of | Requires | Does |
|---|---|---|
| a completed **create** | record; backup binding + SHA-256; live template read by the recorded id with name/UUID/nonce; content un-drifted; **unlinked**; a last fresh read right before the call | `template.delete` with exactly `[recorded id]`, verifies it is gone, archives the record |
| the id no longer exists but another template carries the name | - | reports `already-absent`, **touches nothing** |
| an **interrupted create** (`pending`) | the intent backup; a template with the name that carries the **nonce**, the intended **UUID** and exactly the **intended content**; unlinked | deletes that exact id; otherwise refuses and leaves the template alone; no template at all -> `nothing-to-roll-back` |
| a completed **update** | as above + backup SHA-256/binding | `importcompare` with `RESTORE_RULES` (bounded removals), re-validates, imports the stored original, then **requires the live export to equal the original export hash** |
| an **interrupted update** | `pending` step | live == pre-update export -> discard the step (the import never happened); live == recorded post-import hash -> normal restore; anything else -> refuse (no guessing) |

## 5. Safe `importcompare` procedure (read-only until the last step)

1. `template plan --definition D`: reads `template.get`, `configuration.export`, `configuration.importcompare` only. Read the printed operations.
2. Expected for the first deployment: `CREATE`, `added templates: 1` (+ `added templates/items ...`, `.../discovery_rules`, ...), no `updated`/`removed`, `linked_hosts: 0`.
3. Any `CONFLICT` line stops the procedure; none can be overridden from the command line.
4. Only after separate human approval: `template apply --definition D` (LAB token with write permission), then `template plan` again must say `noop`.
5. Undo: `template rollback --definition D` (refuses when linked/drifted/foreign).

## 6. What this does **not** prove

All of it is exercised against an offline stateful fake of the Zabbix API (`tests/test_v03_tplmgr.py`, 65 tests, plus `tests/test_v031_sequences.py`). Codex's read-only run showed that the real `configuration.importcompare` accepts the generated payload on 7.0.30; the **real** `configuration.export` / `configuration.import` behaviour (field normalisation, whether an unchanged re-export hashes identically, response shapes of `importcompare` for nested children) has not been observed. If a real re-export of an unchanged template does not hash identically, apply will fail closed (post-import verification) and leave a `pending` record that `template rollback` handles - it will not guess.
