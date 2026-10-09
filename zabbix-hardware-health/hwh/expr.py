"""The small Zabbix trigger-expression subset this project GENERATES: builders, a parser, and an evaluator over simulated value series.

Subset: last(/T/K,#n), nodata(/T/K,period), numeric literals, = <> < > <= >=, and, or, parentheses. Unknown (no sample yet) propagates
three-valued (Zabbix leaves the trigger state unchanged when an expression cannot be evaluated). The evaluator exists so the expressions that
are actually written into the template - not a paraphrase of them - can be exercised with normal / fault / glitch / recovery / stale series."""
import re

from .api import AuditError

DURATION = re.compile(r"^(\d+)([smhd]?)$")
UNIT = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def seconds(text):
    m = DURATION.match(str(text))
    if not m:
        raise AuditError("bad duration %r" % (text,))
    return int(m.group(1)) * UNIT[m.group(2)]


# ----------------------------------------------------------------------------------------------------------------------- builders
def _last(tpl, key, n):
    return "last(/%s/%s,#%d)" % (tpl, key, n)


def in_states(tpl, key, raws, n):
    return "(" + " or ".join("%s=%s" % (_last(tpl, key, n), r) for r in raws) + ")"


def problem_expression(tpl, key, raws, confirm):
    """Problem only when each of the last `confirm` samples is in the alarm set (a single glitch sample never raises it)."""
    return " and ".join(in_states(tpl, key, raws, i) for i in range(1, confirm + 1))


def recovery_expression(tpl, key, normal_raws, recover):
    """Recovers only after `recover` consecutive samples in the normal set (an unknown / absent sample does not clear a problem)."""
    return " and ".join(in_states(tpl, key, normal_raws, i) for i in range(1, recover + 1))


def stale_expression(tpl, key, period):
    return "nodata(/%s/%s,%s)=1" % (tpl, key, period)


# ----------------------------------------------------------------------------------------------------------------------- parser
TOKEN = re.compile(r"\s*(?:(?P<num>-?\d+(?:\.\d+)?)|(?P<op><>|<=|>=|=|<|>)|(?P<par>[()])|(?P<word>and|or)\b|(?P<func>(?:last|nodata)\())")


def _split_args(text, pos):
    """text[pos:] begins right after 'func('. -> (args list, index after the closing paren)."""
    depth_b, args, cur, i = 0, [], "", pos
    while i < len(text):
        c = text[i]
        if c == "[":
            depth_b += 1
        elif c == "]":
            depth_b -= 1
        if depth_b == 0 and c == ",":
            args.append(cur)
            cur = ""
        elif depth_b == 0 and c == ")":
            args.append(cur)
            return args, i + 1
        else:
            cur += c
        i += 1
    raise AuditError("unterminated function call in expression")


def parse(text):
    """-> nested tuples. Raises AuditError on anything outside the subset (so a generated expression can never silently be something else)."""
    pos = [0]

    def peek():
        m = TOKEN.match(text, pos[0])
        return m

    def take():
        m = peek()
        if not m:
            raise AuditError("unexpected text at %d in %r" % (pos[0], text))
        pos[0] = m.end()
        return m

    def p_or():
        a = p_and()
        while True:
            m = peek()
            if m and m.group("word") == "or":
                take()
                a = ("or", a, p_and())
            else:
                return a

    def p_and():
        a = p_cmp()
        while True:
            m = peek()
            if m and m.group("word") == "and":
                take()
                a = ("and", a, p_cmp())
            else:
                return a

    def p_cmp():
        a = p_term()
        m = peek()
        if m and m.group("op"):
            take()
            return ("cmp", m.group("op"), a, p_term())
        return a

    def p_term():
        m = take()
        if m.group("num") is not None:
            return ("num", float(m.group("num")))
        if m.group("par") == "(":
            e = p_or()
            c = take()
            if c.group("par") != ")":
                raise AuditError("missing ) in %r" % text)
            return e
        if m.group("func"):
            name = m.group("func")[:-1]
            args, end = _split_args(text, pos[0])
            pos[0] = end
            ref = args[0].strip()
            mm = re.match(r"^/([^/]+)/(.+)$", ref)
            if not mm:
                raise AuditError("item reference %r is not /template/key" % ref)
            if name == "last":
                nn = re.match(r"^#(\d+)$", args[1].strip()) if len(args) == 2 else None
                if not nn:
                    raise AuditError("last() needs #N, got %r" % (args[1:],))
                return ("last", mm.group(1), mm.group(2), int(nn.group(1)))
            if name == "nodata":
                if len(args) != 2:
                    raise AuditError("nodata() needs a period")
                return ("nodata", mm.group(1), mm.group(2), args[1].strip())
        raise AuditError("unexpected token in %r" % text)

    tree = p_or()
    if text[pos[0]:].strip():
        raise AuditError("trailing text %r in expression" % text[pos[0]:])
    return tree


def references(tree):
    """(template, key) pairs an expression reads."""
    if tree[0] in ("last", "nodata"):
        return {(tree[1], tree[2])}
    if tree[0] in ("and", "or"):
        return references(tree[1]) | references(tree[2])
    if tree[0] == "cmp":
        return references(tree[2]) | references(tree[3])
    return set()


# ----------------------------------------------------------------------------------------------------------------------- evaluator
def evaluate(tree, series, t):
    """series: {key: [(timestamp, value), ...] ascending}. -> True / False / None (cannot be evaluated)."""
    op = tree[0]
    if op == "num":
        return tree[1]
    if op == "last":
        vals = [v for ts, v in series.get(tree[2], []) if ts <= t]
        n = tree[3]
        return vals[-n] if len(vals) >= n else None
    if op == "nodata":
        recent = [ts for ts, v in series.get(tree[2], []) if t - seconds(tree[3]) < ts <= t]
        return 0 if recent else 1
    if op == "cmp":
        a, b = evaluate(tree[2], series, t), evaluate(tree[3], series, t)
        if a is None or b is None:
            return None
        return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[tree[1]]
    a, b = evaluate(tree[1], series, t), evaluate(tree[2], series, t)
    if op == "and":
        if a is False or b is False:
            return False
        return None if (a is None or b is None) else True
    if a is True or b is True:
        return True
    return None if (a is None or b is None) else False


def run_trigger(expression, recovery, series, times, state="OK"):
    """Zabbix 'recovery expression' mode: PROBLEM when the problem expression is true; back to OK only when the recovery expression is true;
    None (cannot evaluate) leaves the state unchanged. -> list of (t, state)."""
    pt = parse(expression)
    rt = parse(recovery) if recovery else None
    out = []
    for t in times:
        p = evaluate(pt, series, t)
        if p is True:
            state = "PROBLEM"
        elif state == "PROBLEM":
            r = evaluate(rt, series, t) if rt else (True if p is False else None)
            if r is True:
                state = "OK"
        out.append((t, state))
    return out
