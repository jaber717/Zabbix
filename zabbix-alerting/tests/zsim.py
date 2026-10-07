"""Evaluate the generated trigger expressions against simulated item data.

Not Zabbix: a small, strict evaluator for the subset of the expression language the
generated template uses (last, changecount, + - * comparisons, and/or). It exists so the
tests can prove the *shipped expression text* behaves as specified — newest-sample
utilization, hysteresis, one problem per link outage — rather than re-implementing the
logic in test code.
"""
import re

from netalert import config, model, template as tpl

MACRO_RE = re.compile(r'\{\$([A-Z0-9_.]+)(?::"([^"]*)")?\}')
CALL_RE = re.compile(r'(last|changecount)\(([^()]*)\)')


def template_defaults():
    return dict((m[2:-1], v) for m, v, _ in tpl.TEMPLATE_MACROS)


def resolve(text, host_macros, ifname, index="1"):
    """LLD macros, then user macros with Zabbix context lookup: host+context, host, template default."""
    text = text.replace("{#IFNAME}", ifname).replace("{#SNMPINDEX}", index)
    defaults = template_defaults()

    def sub(m):
        name, context = m.group(1), m.group(2)
        if context is not None and ('{$%s:"%s"}' % (name, context)) in host_macros:
            return host_macros['{$%s:"%s"}' % (name, context)]
        if "{$%s}" % name in host_macros:
            return host_macros["{$%s}" % name]
        return defaults[name]
    return MACRO_RE.sub(sub, text)


def seconds(text):
    m = re.match(r'^(\d+)([smhd])$', text)
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


class Series(object):
    """Per-key list of (timestamp, value)."""

    def __init__(self):
        self.data = {}

    def push(self, key, t, value):
        self.data.setdefault(key, []).append((t, value))

    def last(self, key):
        return self.data[key][-1][1]

    def changecount(self, key, window, now):
        pts = [v for t, v in self.data.get(key, []) if t > now - window]
        before = [v for t, v in self.data.get(key, []) if t <= now - window]
        seq = ([before[-1]] if before else []) + pts
        return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def evaluate(expr, series, now):
    """expr has macros resolved. Returns bool (or raises on anything unsupported)."""
    def call(m):
        fn, args = m.group(1), m.group(2)
        parts = args.split(",")
        key = parts[0].split("/", 2)[2]
        if fn == "last":
            return repr(float(series.last(key)))
        return repr(series.changecount(key, seconds(parts[1].strip()), now))
    py = CALL_RE.sub(call, expr)
    py = re.sub(r'(?<![<>!=])=(?!=)', '==', py).replace("<>", "!=")
    py = re.sub(r'\band\b', ' and ', py)
    stripped = re.sub(r'\d+(?:\.\d+)?(?:e[+-]?\d+)?', '0', py)
    if re.search(r'[A-Za-z_]', re.sub(r'\b(and|or|not)\b', '', stripped)):
        raise ValueError("unsupported expression after substitution: %r" % py)
    return bool(eval(py, {"__builtins__": {}}, {}))


class InterfaceSim(object):
    """One selected interface: feed samples, read problem state / events per trigger."""

    def __init__(self, host_macros, ifname, alerts=None, index="1"):
        self.macros, self.ifname, self.index = host_macros, ifname, index
        self.series = Series()
        self.t = 0
        self.state = {}      # (alert, severity) -> bool
        self.events = []     # (t, alert, 'PROBLEM'|'OK')
        sev = int(resolve('{$NETOPS.SEV:"{#IFNAME}"}', host_macros, ifname))
        self.sev_name = [n for n, p, _ in tpl.SEVERITY_VARIANTS if p == sev][0]
        self.protos = {}
        for tp in tpl.trigger_prototypes():
            tags = dict((x["tag"], x["value"]) for x in tp["tags"])
            if tags["severity_label"] == self.sev_name:
                self.protos[tags["netops_alert"]] = tp

    def sample(self, dt, oper=1, rx=0, tx=0, speed=1e9, hspeed=None, ein=0, eout=0, din=0, dout=0):
        self.t += dt
        s, i = self.series, self.index
        s.push("netops.if.oper[%s]" % i, self.t, oper)
        s.push("netops.if.in[%s]" % i, self.t, rx)
        s.push("netops.if.out[%s]" % i, self.t, tx)
        s.push("netops.if.speed[%s]" % i, self.t, speed)
        s.push("netops.if.hspeed[%s]" % i, self.t, speed / 1e6 if hspeed is None else hspeed)
        for k, v in (("errin", ein), ("errout", eout), ("discin", din), ("discout", dout)):
            s.push("netops.if.%s[%s]" % (k, i), self.t, v)
        self._evaluate()

    def _eval(self, text):
        return evaluate(resolve(text, self.macros, self.ifname, self.index), self.series, self.t)

    def _evaluate(self):
        # Zabbix semantics: no problem -> evaluate the problem expression; open problem -> it
        # recovers on the recovery expression (RECOVERY_EXPRESSION mode) or when the problem expr is false.
        for alert in self.protos:
            tp = self.protos[alert]
            key = (alert, self.sev_name)
            was = self.state.get(key, False)
            now_problem = self._eval(tp["expression"])
            if not was:
                nxt = now_problem
            elif tp.get("recovery_mode") == "RECOVERY_EXPRESSION":
                nxt = not self._eval(tp["recovery_expression"])
            else:
                nxt = now_problem
            if nxt != was:
                self.events.append((self.t, alert, "PROBLEM" if nxt else "OK"))
            self.state[key] = nxt

    def problem(self, alert):
        return self.state.get((alert, self.sev_name), False)

    def problems_opened(self, alert):
        return len([e for e in self.events if e[1] == alert and e[2] == "PROBLEM"])


def macros_for(cfg_dict, host="RTR-01", suppress=False):
    d = config.parse(cfg_dict)
    assert not d.problems, [p.message for p in d.problems]
    return model.host_macros(d.hosts[host], suppress)
