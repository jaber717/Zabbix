"""Exercise the GENERATED trigger expressions against simulated series. This yields the SIMULATED_TESTED evidence level - it proves the
alert logic (confirmation, glitch suppression, recovery, stale handling) of the expressions that are actually written into the template.
It says nothing about what any real device reports."""
from . import expr
from . import template as T
from . import vendordefs as VD

STEP = 60
SCENARIOS = ("normal", "fault", "glitch", "recovery", "stale")


def _series(raws_before, raws_after, n_before, n_after):
    pts, t = [], 0
    for _ in range(n_before):
        t += STEP
        pts.append((t, raws_before))
    for _ in range(n_after):
        t += STEP
        pts.append((t, raws_after))
    return pts


def run_sensor(defn, sn):
    """-> list of result dicts, one per (trigger, scenario). Each: {trigger, scenario, expected, observed, ok}."""
    out = []
    if not sn.get("triggers"):
        return out
    tpl = T.template_name(defn)
    key = "k"
    sem_id = sn["value"]["semantics"]
    normal = int(VD.raw_values_for(defn, sem_id, ["normal"])[0])
    for trg in sn.get("triggers") or []:
        alarm_raws = VD.raw_values_for(defn, sem_id, trg["states"])
        other = [r for r in VD.raw_values_for(defn, sem_id, ["failed", "degraded", "absent", "unknown"]) if r not in alarm_raws]
        p = expr.problem_expression(tpl, key, alarm_raws, trg["confirm_samples"])
        r = expr.recovery_expression(tpl, key, [str(normal)], trg["recover_samples"])
        c, rc = trg["confirm_samples"], trg["recover_samples"]
        alarm = int(alarm_raws[0])

        def run(vals):
            ser = {key: [(i * STEP + STEP, v) for i, v in enumerate(vals)]}
            times = [i * STEP + STEP for i in range(len(vals))]
            return [s for _, s in expr.run_trigger(p, r, ser, times)]

        cases = []
        cases.append(("normal", [normal] * (c + rc + 2), lambda s: all(x == "OK" for x in s)))
        cases.append(("fault", [normal] * 3 + [alarm] * (c + 1), lambda s: s[-1] == "PROBLEM" and (c == 1 or s[2 + c - 1] == "OK")))
        if c > 1:
            cases.append(("glitch", [normal] * 3 + [alarm] * (c - 1) + [normal] * 3, lambda s: all(x == "OK" for x in s)))
        cases.append(("recovery", [normal] * 2 + [alarm] * c + [normal] * rc, lambda s: s[-1] == "OK" and s[-rc - 1] == "PROBLEM"))
        if rc > 1:
            cases.append(("recovery-flap", [normal] * 2 + [alarm] * c + [normal] * (rc - 1) + [alarm] * 1, lambda s: s[-1] == "PROBLEM"))
        if other:
            cases.append(("other-state-not-this-trigger", [normal] * 3 + [int(other[0])] * (c + 2), lambda s: all(x == "OK" for x in s)))
        for name, vals, check in cases:
            states = run(vals)
            out.append({"sensor": sn["id"], "trigger": trg["id"], "scenario": name, "observed": states[-1], "ok": bool(check(states))})
    return out


def run_stale(defn):
    """The stale trigger must fire only on silence and must be a different tag value (sensor_stale), never a hardware alarm."""
    tpl = T.template_name(defn)
    e = expr.stale_expression(tpl, "k", "15m")
    tree = expr.parse(e)
    ser = {"k": [(i * 60, 1) for i in range(1, 11)]}
    return [{"scenario": "stale-silent-after-data", "ok": expr.evaluate(tree, ser, 10 * 60 + 15 * 60 + 1) == 1},
            {"scenario": "stale-quiet-while-data-flows", "ok": expr.evaluate(tree, ser, 10 * 60) == 0}]


def run_definition(defn):
    results = []
    for sn in defn.get("sensors") or []:
        results.extend(run_sensor(defn, sn))
    if defn.get("sensors"):
        for s in run_stale(defn):
            results.append(dict(s, sensor="*", trigger="sensor_stale"))
    return results


def summary(defs):
    """-> {definition id: {'cases': n, 'failed': [..]}}; a definition with no trigger cases is not SIMULATED_TESTED."""
    out = {}
    for did, d in defs.items():
        res = run_definition(d)
        out[did] = {"cases": len(res), "failed": [r for r in res if not r["ok"]]}
    return out
