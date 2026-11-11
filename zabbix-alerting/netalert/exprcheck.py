"""Conservative trigger-expression validation (fail closed).

Coverage must never infer "this trigger alerts on link down / 70% utilization" from a fragment of an
expression. An expression is accepted only when EVERY condition in it is recognised:

  * it is a plain conjunction ("A and B and C") - any top-level "or" / "not" is unknown logic;
  * each conjunct is one of: a user-macro gate ({$M:"ctx"}=N / <>N, resolved and holding), a numeric constant
    comparison (evaluated - "0=1" closes the trigger), the test itself, or a known companion condition of the
    same item (stock change detection, NETOPS speed guard);
  * anything else ("and nodata(...)=1", "and {$X}>3", a reversed comparison, ...) makes the trigger UNPROVEN.

Expressions are the raw form fetched with selectFunctions and rebuilt by discovery (user macros are NOT expanded
by Zabbix in that form), so a gate is evaluated here with the resolved macro value, never silently pre-expanded.

Verdicts: "ok" | "off" (cannot fire / cannot recover) | "unknown" (might work, cannot be proven) | "none" (the
expression does not use the port's items in a test of this kind at all).
"""
import re

GATE = re.compile(r'^(\{\$[A-Z0-9_.]+(?::"(?:[^"\\]|\\.)*")?\})\s*(=|<>)\s*"?(-?\d+(?:\.\d+)?)"?$')
CONST = re.compile(r'^"?(-?\d+(?:\.\d+)?)"?\s*(=|<>|<=|>=|<|>)\s*"?(-?\d+(?:\.\d+)?)"?$')
MACRO = re.compile(r'\{\$[A-Z0-9_.]+(?::"(?:[^"\\]|\\.)*")?\}')
UNKNOWN_REF = "{UNKNOWN}"


# ------------------------------------------------------------------------------------------------ parsing

def _scan(expr):
    """Yield (index, char, depth) outside quoted strings; depth counts () and []."""
    depth, q, esc = 0, False, False
    for i, ch in enumerate(expr):
        if q:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                q = False
            continue
        if ch == '"':
            q = True
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        yield i, ch, depth


def strip_parens(expr):
    e = (expr or "").strip()
    while e.startswith("(") and e.endswith(")"):
        closes = [i for i, ch, d in _scan(e) if ch == ")" and d == 0]
        if closes and closes[0] == len(e) - 1:
            e = e[1:-1].strip()
        else:
            break
    return e


def split_top(expr, word):
    """Split at top-level occurrences of the logical operator `word` ('and' / 'or')."""
    e = strip_parens(expr)
    parts, start = [], 0
    pat = re.compile(r"(?<![A-Za-z0-9_.])%s(?![A-Za-z0-9_.])" % word)
    positions = []
    for i, ch, d in _scan(e):
        if d == 0 and ch == word[0] and pat.match(e, i) and (i == 0 or not re.match(r"[A-Za-z0-9_.]", e[i - 1])):
            positions.append(i)
    for p in positions:
        parts.append(e[start:p].strip())
        start = p + len(word)
    parts.append(e[start:].strip())
    return [strip_parens(x) for x in parts]


def has_top(expr, word):
    return len(split_top(expr, word)) > 1


def conjuncts(expr):
    """List of top-level conjuncts, or None when the expression uses top-level or/not (unknown logic)."""
    e = strip_parens(expr)
    if not e or UNKNOWN_REF in e:
        return None
    if has_top(e, "or") or re.search(r"(?<![A-Za-z0-9_.])not(?![A-Za-z0-9_.])", e):
        return None
    return split_top(e, "and")


def call(fn, key, params=None):
    """Regex for fn(/host/key[,params]) - params None = no parameters (or '#1' for last)."""
    p = r"(?:,\s*#1)?" if params is None else params
    return r"%s\(/[^/()]+/%s%s\)" % (fn, re.escape(key), p)


def uses(expr, keys):
    return any(re.search(r"/[^/()]+/%s(?:[,)])" % re.escape(k), expr or "") for k in keys)


# ----------------------------------------------------------------------------------- shared term checks

def _gate_or_const(term, resolve):
    """('ok'|'off'|'unknown', reason) for a gate or a constant comparison; None if the term is neither."""
    m = GATE.match(term)
    if m:
        macro, op, val = m.groups()
        v = resolve(macro)
        if v is None:
            return "unknown", "gate %s cannot be resolved" % macro
        try:
            same = float(str(v).strip()) == float(val)
        except ValueError:
            same = str(v).strip() == val
        if same == (op == "="):
            return "ok", ""
        return "off", "gated off by %s=%s" % (macro, v)
    m = CONST.match(term)
    if m:
        a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
        val = {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        return ("ok", "") if val else ("off", "constant condition '%s' is never true" % term)
    return None


def _num(resolve, macro):
    v = resolve(macro)
    try:
        return float(str(v).strip()) if v is not None else None
    except ValueError:
        return None


def _combine(results):
    """Worst verdict wins: off > unknown > ok."""
    reasons = [r for _, r in results if r]
    if any(v == "off" for v, _ in results):
        return "off", reasons
    if any(v == "unknown" for v, _ in results):
        return "unknown", reasons
    return "ok", reasons


# ---------------------------------------------------------------------------------------------- link down

def link_test(term, keys):
    """The term compares the oper-status item with down(2) / not-up(1)."""
    for k in keys:
        if re.match(r"^%s\s*(=\s*\"?2\"?|<>\s*\"?1\"?|>=\s*\"?2\"?|>\s*\"?1\"?)$" % call("last", k), term):
            return True
    return False


def _stock_change(term, keys):
    """Stock template companion: (last(K,#1)<>last(K,#2)) - same item, change detection."""
    return any(re.match(r"^%s\s*<>\s*%s$" % (call("last", k, r",\s*#1"), call("last", k, r",\s*#2")), term)
               for k in keys)


def _up_test(term, keys):
    return any(re.match(r"^%s\s*(=\s*\"?1\"?|<>\s*\"?2\"?)$" % call("last", k), term) for k in keys)


def _changecount_quiet(term, keys):
    return any(re.match(r"^changecount\(/[^/()]+/%s,[^()]*\)\s*<\s*\S+$" % re.escape(k), term) for k in keys)


def _possible(expr, keys, resolve, need_up):
    """Can this (recovery) expression become true? Every disjunct is checked; one viable disjunct suffices."""
    reasons = []
    for disj in split_top(expr, "or"):
        if re.search(r"(?<![A-Za-z0-9_.])not(?![A-Za-z0-9_.])", disj) or UNKNOWN_REF in disj:
            reasons.append("unrecognised recovery logic")
            continue
        verdicts, has_up = [], False
        for t in split_top(disj, "and"):
            if has_top(t, "or"):
                ok, why = _possible(t, keys, resolve, False)
                verdicts.append(("ok", "") if ok else ("unknown", "; ".join(why)))
                continue
            if need_up and _up_test(t, keys):
                has_up = True
                continue
            if not need_up and (_up_test(t, keys) or _changecount_quiet(t, keys)):
                continue
            g = _gate_or_const(t, resolve)
            if g is not None:
                verdicts.append(g)
                continue
            verdicts.append(("unknown", "unrecognised recovery condition '%s'" % t))
        v, why = _combine(verdicts)
        if need_up and not has_up:
            why = why + ["recovery does not test link up"]
            v = "unknown" if v == "ok" else v
        if v == "ok":
            return True, []
        reasons += why
    return False, reasons or ["recovery expression can never become true"]


def assess_link(trig, status_keys, resolve):
    """(verdict, [reasons]) for 'this trigger raises a Problem when the port goes down, and recovers'."""
    expr = trig.get("expression", "")
    if not uses(expr, status_keys):
        return "none", []
    terms = conjuncts(expr)
    if terms is None:
        return "unknown", ["expression logic not recognised (top-level or/not, or an unknown item reference)"]
    tests = [t for t in terms if link_test(t, status_keys)]
    if not tests:
        return "none", ["expression does not prove a link-down test"]
    results = []
    for t in terms:
        if t in tests or _stock_change(t, status_keys):
            continue
        g = _gate_or_const(t, resolve)
        results.append(g if g is not None else ("unknown", "unrecognised condition '%s'" % t))
    v, why = _combine(results)
    mode = str(trig.get("recovery_mode", "0"))
    if mode == "2":
        return "off", why + ["trigger never recovers automatically (recovery mode: none)"]
    if mode == "1":
        ok, rwhy = _possible(trig.get("recovery_expression", ""), status_keys, resolve, True)
        if not ok:
            return ("off" if v == "off" else "unknown"), why + rwhy
    return v, why


# ------------------------------------------------------------------------------------------- utilization

def assess_util(trig, traffic, speed_keys, resolve, policy):
    """(verdict, direction or None, [reasons]) for 'this trigger implements the approved utilization policy':
    NETOPS shape last(TRAFFIC)*100 > {$NETOPS.UTIL.MAX:ctx}*last(SPEED) with MAX == policy threshold, recovery
    last(TRAFFIC)*100 < {$NETOPS.UTIL.RECOVER:ctx}*last(SPEED) with RECOVER == policy recovery.
    `traffic` = {key: 'rx'|'tx'}. Any other traffic expression is not proof of the policy."""
    expr = trig.get("expression", "")
    if not uses(expr, list(traffic)):
        return "none", None, []
    thr, rec = policy
    terms = conjuncts(expr)
    if terms is None:
        return "unknown", None, ["utilization expression is not the approved %g%%/%g%% policy shape "
                                 "(top-level or/not)" % (thr, rec)]
    found, results = [], []
    for t in terms:
        hit = None
        for k, d in traffic.items():
            for s in speed_keys:
                m = re.match(r"^%s\s*\*\s*100\s*>\s*(%s)\s*\*\s*%s$" % (
                    call("last", k), r'\{\$NETOPS\.UTIL\.MAX(?::"(?:[^"\\]|\\.)*")?\}', call("last", s)), t)
                if m:
                    hit = (k, d, s, m.group(1))
        if hit:
            found.append(hit)
            continue
        if any(re.match(r"^%s\s*>\s*0$" % call("last", s), t) for s in speed_keys):
            continue
        g = _gate_or_const(t, resolve)
        results.append(g if g is not None else ("unknown", "unrecognised condition '%s'" % t))
    if len(found) != 1:
        return "unknown", None, ["utilization expression is not the approved %g%%/%g%% policy shape" % (thr, rec)]
    k, d, s, macro = found[0]
    mx = _num(resolve, macro)
    if mx is None:
        results.append(("unknown", "threshold %s cannot be resolved" % macro))
    elif mx != float(thr):
        results.append(("unknown", "threshold %s=%g, approved policy is %g%%" % (macro, mx, thr)))
    if str(trig.get("recovery_mode", "0")) != "1":
        results.append(("unknown", "no recovery expression: hysteresis %g%% not implemented" % rec))
    else:
        rterms = conjuncts(trig.get("recovery_expression", ""))
        rm = None
        if rterms and len(rterms) == 1:
            rm = re.match(r"^%s\s*\*\s*100\s*<\s*(%s)\s*\*\s*%s$" % (
                call("last", k), r'\{\$NETOPS\.UTIL\.RECOVER(?::"(?:[^"\\]|\\.)*")?\}', call("last", s)), rterms[0])
        if not rm:
            results.append(("unknown", "recovery expression is not the approved %g%% hysteresis shape" % rec))
        else:
            rv = _num(resolve, rm.group(1))
            if rv is None:
                results.append(("unknown", "recovery threshold %s cannot be resolved" % rm.group(1)))
            elif rv != float(rec):
                results.append(("unknown", "recovery %s=%g, approved policy is %g%%" % (rm.group(1), rv, rec)))
    v, why = _combine(results)
    return v, d, why
