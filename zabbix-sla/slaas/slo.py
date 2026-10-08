"""SLI / SLO / error budget with an explicit data-quality qualification. Pure functions.

Core rule: a number is only reported as compliance when the data behind it is trustworthy. Zabbix computes an SLI from the service
status history, so "no problem recorded" and "nothing was watching" look identical to it. We therefore never turn the former into
a clean 100%:

    state           meaning
    COMPLIANT       SLI >= SLO and the data is sufficient
    BREACHED        SLI < SLO, or the downtime already recorded exceeds the whole budget (a breach is certain even if data is incomplete)
    INSUFFICIENT_DATA   the data cannot support a statement (no SLI, low coverage, blind component, stale probe)

`signal_quality` (full | partial | blind) describes the monitoring behind the service: partial = a caveat travels with the number,
blind = a component can never raise a problem, so the figure is an upper bound and is not stated as compliance.
"""
COMPLIANT, BREACHED, INSUFFICIENT = "COMPLIANT", "BREACHED", "INSUFFICIENT_DATA"
DEFAULT_MIN_COVERAGE = 0.98
DEFAULT_MAX_STALE_FRACTION = 0.02


def budget_seconds(slo_pct, window_seconds):
    return max(0.0, window_seconds * (1.0 - float(slo_pct) / 100.0))


def assess(row, slo, period_seconds, window_seconds, signal_quality="full", stale_seconds=None, caveats=(),
           min_coverage=DEFAULT_MIN_COVERAGE, max_stale_fraction=DEFAULT_MAX_STALE_FRACTION, tier="T2"):
    """row: one sla.getsli cell {uptime, downtime, sli, error_budget, excluded_downtime} (seconds, percent).
    period_seconds: the whole reporting period; window_seconds: the part of it that is measurable (elapsed since the SLA's effective
    date, and not beyond now). stale_seconds: seconds the probe feeding a T3 service had no fresh data (None for T2)."""
    row = row or {}
    up, down, excl = _num(row.get("uptime")), _num(row.get("downtime")), _num(row.get("excluded_downtime"))
    sli = row.get("sli")
    sli = None if sli is None or float(sli) < 0 else float(sli)
    seen = up + down + excl
    coverage = (seen / window_seconds) if window_seconds > 0 else 0.0
    counted = up + down
    reasons, cav = [], list(caveats)

    budget_total = budget_seconds(slo, period_seconds)
    consumed = down
    out = {
        "sli_pct": sli, "slo_pct": float(slo), "uptime_s": up, "downtime_s": down, "excluded_downtime_s": excl,
        "budget_total_s": budget_total, "budget_consumed_s": consumed, "budget_remaining_s": budget_total - consumed,
        "budget_consumed_pct": (100.0 * consumed / budget_total) if budget_total > 0 else None,
        "coverage": round(coverage, 4), "window_s": window_seconds, "period_s": period_seconds, "signal_quality": signal_quality,
        "partial_period": window_seconds < period_seconds,
        "burn_rate": ((down / counted) / (1.0 - float(slo) / 100.0)) if counted > 0 and slo < 100 else None,
    }

    insufficient = False
    if sli is None or counted <= 0:
        insufficient = True
        reasons.append("Zabbix returned no SLI for this period (no status history)")
    if coverage < min_coverage:
        insufficient = True
        reasons.append("only %.1f%% of the measurable window has recorded status (need %.0f%%)" % (100 * coverage, 100 * min_coverage))
    if signal_quality == "blind":
        insufficient = True
        reasons.append("a component of this service has no working availability signal, so its failures cannot be seen")
    elif signal_quality == "partial":
        cav.append("partial signal coverage: one end of at least one link is not monitored; far-end failures may be missed")
    if tier == "T3":
        if stale_seconds is None:
            insufficient = True
            reasons.append("probe freshness is unknown")
        elif window_seconds > 0 and stale_seconds / window_seconds > max_stale_fraction:
            insufficient = True
            reasons.append("the probe had no fresh data for %.1f%% of the window" % (100.0 * stale_seconds / window_seconds))
    out["stale_s"] = stale_seconds

    certain_breach = down > budget_total
    if certain_breach:
        state = BREACHED
        if insufficient:
            cav.append("breach is certain from the downtime already recorded; the true figure may be worse")
    elif insufficient:
        state = INSUFFICIENT
    elif sli < float(slo):
        state = BREACHED
    else:
        state = COMPLIANT
    out.update({"state": state, "reasons": reasons, "caveats": cav})
    if state == INSUFFICIENT:
        out["sli_pct_reportable"] = None              # never printed as a clean figure
    else:
        out["sli_pct_reportable"] = sli
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def link_quality(found, expected_ends):
    """found: list of {"status": "0"|"1" (0 enabled), "state": "0"|"1" (1 = unknown), "error": str} for the link_down triggers of ONE link_id.
    -> (quality, detail) where quality in OK | PARTIAL | UNKNOWN | DISABLED | MISSING"""
    if not found:
        return "MISSING", "no link_down trigger carries this link_id: the link can never raise a problem"
    enabled = [t for t in found if str(t.get("status", "0")) == "0"]
    if not enabled:
        return "DISABLED", "every link_down trigger for this link is disabled"
    bad = [t for t in enabled if str(t.get("state", "0")) == "1" or t.get("error")]
    if len(bad) == len(enabled):
        return "UNKNOWN", "all link_down triggers are in the UNKNOWN state (%s)" % (bad[0].get("error") or "no data")
    good = len(enabled) - len(bad)
    if good < expected_ends:
        return "PARTIAL", "%d of %d expected link ends produce a working link_down signal" % (good, expected_ends)
    return "OK", "%d link end(s) monitored" % good


def service_signal_quality(component_qualities, has_partial_declared):
    """Worst of the components. MISSING/DISABLED/UNKNOWN = blind; PARTIAL = partial; a declared partial-coverage link is partial."""
    q = set(component_qualities)
    if q & {"MISSING", "DISABLED", "UNKNOWN"}:
        return "blind"
    if "PARTIAL" in q or has_partial_declared:
        return "partial"
    return "full"
