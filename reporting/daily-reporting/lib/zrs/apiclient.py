"""Zabbix 7.0 API access: TLS-verified, retrying, with truncation-aware bulk helpers.

Every helper records what it could NOT fully read in `Notes` (truncation, failed batches) so the
reports can say so instead of presenting partial data as complete.
"""
from __future__ import annotations

import json
import os
import socket
import ssl
import time
import urllib.error
from urllib.request import Request, urlopen

from .util import chunks


class ApiError(RuntimeError):
    pass


class Notes(object):
    """Collector diagnostics carried into the dataset audit trail."""

    def __init__(self):
        self.truncated = []     # [{"what":..., "limit":..., "detail":...}]
        self.failed = []        # [{"what":..., "error":...}]
        self.warnings = []      # [str]

    def to_dict(self):
        return {"truncated": self.truncated, "failed": self.failed, "warnings": sorted(set(self.warnings))}


class ApiClient(object):
    RETRYABLE_HTTP = (429, 500, 502, 503, 504)

    def __init__(self, cfg, retries=3, backoff=1.0, sleep=time.sleep):
        self.url = cfg["api_url"]
        self.timeout = int(cfg.get("request_timeout_seconds", 30))
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self.serial = 0
        self.stats = {}
        self.context = ssl.create_default_context(cafile=cfg.get("ca_file") or None)   # verification is never disabled
        self.token = os.environ.get("ZABBIX_API_TOKEN", "").strip()
        self.user = os.environ.get("ZABBIX_API_USER", "").strip()
        self.password = os.environ.get("ZABBIX_API_PASSWORD", "")

    # -- transport (replaced in tests) -------------------------------------------
    def _open(self, request):
        with urlopen(request, context=self.context, timeout=self.timeout) as response:
            return json.load(response)

    def call(self, method, params, auth=True):
        headers = {"Content-Type": "application/json-rpc"}
        if auth:
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            elif not (self.user and self.password):
                raise ApiError("ZABBIX_API_TOKEN or ZABBIX_API_USER/ZABBIX_API_PASSWORD is required")
        last = None
        for attempt in range(self.retries + 1):
            self.serial += 1
            payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self.serial}
            request = Request(self.url, data=json.dumps(payload, separators=(",", ":")).encode(), headers=headers)
            try:
                result = self._open(request)
            except urllib.error.HTTPError as exc:
                last = "HTTP %s" % exc.code
                if exc.code not in self.RETRYABLE_HTTP:
                    raise ApiError("%s: %s" % (method, last))
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError) as exc:
                last = "%s" % (exc,)
            else:
                if "error" in result:           # an API-level error is final: retrying cannot fix it
                    err = result["error"]
                    raise ApiError("%s: %s" % (method, err.get("data") or err.get("message")))
                self.stats[method] = self.stats.get(method, 0) + 1
                return result["result"]
            if attempt < self.retries:
                self._sleep(self.backoff * (2 ** attempt))
        raise ApiError("%s failed after %d attempts: %s" % (method, self.retries + 1, last))

    def authenticate(self):
        if not self.token:
            self.token = self.call("user.login", {"username": self.user, "password": self.password}, False)

    def version(self):
        return self.call("apiinfo.version", {}, False)


# ------------------------------------------------------------------ bulk helpers
def get_limited(api, notes, method, params, limit, what):
    """Run a *.get with limit+1 so truncation is detected, not silently accepted."""
    rows = api.call(method, dict(params, limit=limit + 1))
    if len(rows) > limit:
        notes.truncated.append({"what": what, "limit": limit,
                                "detail": "more rows exist than the configured maximum; result is partial"})
        rows = rows[:limit]
    return rows


def get_chunked(api, notes, method, params, id_key, ids, size, limit, what):
    out = []
    for part in chunks(ids, size):
        out.extend(get_limited(api, notes, method, dict(params, **{id_key: part}), limit, "%s[%d ids]" % (what, len(part))))
    return out


def fetch_time_split(api, notes, method, params, t0, t1, limit, what, key, min_span=3600):
    """Fetch rows in [t0, t1) (epoch). If a window returns more than `limit` rows it is halved
    until it fits or reaches `min_span`; only then is the remainder reported as truncated.
    Rows are de-duplicated by `key` (a field name) because windows are inclusive in Zabbix."""
    seen, out = set(), []

    def run(a, b):
        rows = api.call(method, dict(params, time_from=a, time_till=b - 1, limit=limit + 1))
        if len(rows) > limit:
            if b - a > min_span:
                mid = a + (b - a) // 2
                run(a, mid)
                run(mid, b)
                return
            notes.truncated.append({"what": what, "limit": limit,
                                    "detail": "window %d-%d still exceeds the limit at the minimum span" % (a, b)})
            rows = rows[:limit]
        for r in rows:
            k = r.get(key)
            if k not in seen:
                seen.add(k)
                out.append(r)
    if t1 > t0:
        run(t0, t1)
    return out
