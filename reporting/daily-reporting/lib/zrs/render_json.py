"""JSON renderer: the document itself (KPIs, tables, charts, dictionary, audit) plus, optionally, the normalized dataset."""
from __future__ import annotations

import json


def render_json(doc, dataset=None):
    payload = dict(doc)
    if dataset is not None:
        payload["dataset"] = dataset
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode("utf-8")
