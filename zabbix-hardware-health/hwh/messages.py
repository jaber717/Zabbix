"""Render the action's REAL Problem / Recovery message templates against sample events and check the notification contract offline.
No message is sent anywhere. This proves the template text (macros, required fields, length), not Telegram delivery."""
import re

from . import action as A

TELEGRAM_LIMIT = 4096
REQUIRED_FIELDS = ("Status:", "Severity:", "Host:", "Model:", "Vendor:", "Site:", "Component:", "Time:", "Event ID:")
RECOVERY_FIELDS = ("Resolved:", "Duration:")
MACRO = re.compile(r"\{[A-Z0-9_.]+(?:\.[A-Z]+)?(?:\"[^\"]*\")?\}|\{EVENT\.TAGS\.\"[^\"]+\"\}")

SAMPLE = {
    "problem": {"{EVENT.STATUS}": "PROBLEM", "{EVENT.SEVERITY}": "High", "{HOST.NAME}": "SW-CORE-01", "{EVENT.NAME}": "cisco-iosxe: Fan failed: Switch#1 Fan 1",
                "{EVENT.DATE}": "2026.10.09", "{EVENT.TIME}": "14:03:11", "{EVENT.ID}": "123456",
                "{EVENT.TAGS}": "netops_hardware: 1, hardware_component: fan, hardware_vendor: cisco"},
    "recovery": {"{EVENT.STATUS}": "RESOLVED", "{EVENT.SEVERITY}": "High", "{HOST.NAME}": "SW-CORE-01", "{EVENT.NAME}": "cisco-iosxe: Fan failed: Switch#1 Fan 1",
                 "{EVENT.DATE}": "2026.10.09", "{EVENT.TIME}": "14:03:11", "{EVENT.ID}": "123456", "{EVENT.RECOVERY.DATE}": "2026.10.09",
                 "{EVENT.RECOVERY.TIME}": "14:11:40", "{EVENT.DURATION}": "8m 29s",
                 "{EVENT.TAGS}": "netops_hardware: 1, hardware_component: fan, hardware_vendor: cisco"},
}
TAGS = {"hardware_vendor": "cisco", "hardware_model": "Catalyst 9300-48P", "hardware_site": "DC1", "hardware_component": "fan", "hardware_slot": "Switch#1 Fan 1"}


def render(text, event):
    out = text
    for k, v in event.items():
        out = out.replace(k, v)
    for t, v in TAGS.items():
        out = out.replace(A.tag_macro(t), v)
    return out


def templates():
    return {"problem": (A.SUBJECT, A.MESSAGE), "recovery": (A.R_SUBJECT, A.R_MESSAGE)}


def check():
    """-> list of contract violations (empty = contract met)."""
    problems = []
    for kind, (subject, body) in templates().items():
        text = render(body, SAMPLE[kind])
        subj = render(subject, SAMPLE[kind])
        leftover = MACRO.findall(text + subj)
        if leftover:
            problems.append("%s: unresolved macro(s) after rendering: %s" % (kind, sorted(set(leftover))))
        for f in REQUIRED_FIELDS + (RECOVERY_FIELDS if kind == "recovery" else ()):
            if f not in text:
                problems.append("%s: required field %s missing" % (kind, f))
        if len(subj) + len(text) > TELEGRAM_LIMIT:
            problems.append("%s: rendered message exceeds %d characters" % (kind, TELEGRAM_LIMIT))
        if kind == "problem" and "Resolved:" in text:
            problems.append("problem message carries recovery fields")
        if "cisco" not in text or "Catalyst 9300-48P" not in text or "DC1" not in text or "Switch#1 Fan 1" not in text:
            problems.append("%s: vendor / model / site / component slot not rendered from event tags" % kind)
        if "netops_alert" in body:
            problems.append("%s: message text references the Interface Alerting tag" % kind)
    return problems


def render_examples():
    out = []
    for kind, (subject, body) in templates().items():
        out.append("--- %s ---\nSubject: %s\n%s" % (kind.upper(), render(subject, SAMPLE[kind]), render(body, SAMPLE[kind]).replace("\r\n", "\n")))
    return "\n".join(out)
