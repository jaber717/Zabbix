"""E-mail delivery with layered safeguards against reaching real recipients by accident.

Mail is sent only when ALL of these hold: suite delivery.enabled is true, the command line has --send (and not
--no-email), and the SMTP settings exist. Recipients are delivery.test_recipients unless delivery.mode is "live",
in which case the environment variable ZRS_ALLOW_LIVE_DELIVERY=YES is also required and every recipient must be
inside delivery.allowed_recipient_domains. A delivery ledger makes repeated runs idempotent.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .output import atomic_write
from .util import canonical_json, sha256_text

LEDGER = "delivery-ledger.json"


class DeliveryRefused(RuntimeError):
    pass


def decide_recipients(suite_delivery, send_flag, no_email, environ=None):
    """Returns (recipients, reason). recipients == [] means: do not send (reason says why)."""
    environ = os.environ if environ is None else environ
    d = suite_delivery
    if no_email:
        return [], "--no-email"
    if not send_flag:
        return [], "no --send flag (delivery is explicit)"
    if not d["enabled"]:
        return [], "delivery.enabled is false"
    if d["mode"] == "test":
        if not d["test_recipients"]:
            return [], "delivery.mode is test but delivery.test_recipients is empty"
        return list(d["test_recipients"]), "test mode: test_recipients only"
    if environ.get("ZRS_ALLOW_LIVE_DELIVERY") != "YES":
        return [], "live mode requires ZRS_ALLOW_LIVE_DELIVERY=YES in the environment"
    if not d["recipients"]:
        return [], "delivery.recipients is empty"
    doms = [x.lower() for x in d["allowed_recipient_domains"]]
    bad = [a for a in d["recipients"] if a.split("@")[-1].lower() not in doms]
    if bad:
        raise DeliveryRefused("recipients outside allowed domains: %s" % ", ".join(bad))
    return list(d["recipients"]), "live mode"


def delivery_key(report, period_label, dataset_sha, recipients, file_hashes):
    return sha256_text(canonical_json([report, period_label, dataset_sha, sorted(recipients), sorted(file_hashes)]))


def already_delivered(ledger_dir, key):
    p = Path(ledger_dir) / LEDGER
    if not p.is_file():
        return False
    try:
        return key in json.loads(p.read_text()).get("delivered", {})
    except ValueError:
        return False


def record(ledger_dir, key, info, mode=0o640):
    p = Path(ledger_dir) / LEDGER
    data = {"delivered": {}}
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except ValueError:
            pass
    data["delivered"][key] = info
    atomic_write(p, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode(), mode)


def build_message(sender, recipients, subject, body, attachments, max_mb):
    total = sum(len(b) for _, _, b in attachments)
    if total > max_mb * 1024 * 1024:
        raise DeliveryRefused("attachments total %.1f MB exceed delivery.max_attachment_mb=%s" % (total / 1048576.0, max_mb))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(recipients)
    msg.set_content(body)
    for name, mime, data in attachments:
        main, sub = mime.split("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg


def smtp_send(report_cfg_delivery, msg, environ=None, smtp_factory=smtplib.SMTP):
    environ = os.environ if environ is None else environ
    d = report_cfg_delivery
    with smtp_factory(d["smtp_host"], int(d["smtp_port"]), timeout=30) as smtp:
        if d.get("smtp_starttls"):
            smtp.starttls(context=ssl.create_default_context())       # certificate verification stays on
        if d.get("smtp_username"):
            smtp.login(d["smtp_username"], environ.get("DAILY_REPORT_SMTP_PASSWORD", ""))
        smtp.send_message(msg)
