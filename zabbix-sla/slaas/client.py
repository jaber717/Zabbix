"""ZabbixClient with the one extra read-only method this project needs.

netalert's guard is a whitelist (only *.get and a few named methods are reads) - the safe default, and it is not modified here.
`sla.getsli` is a pure read that does not end in `.get`, so it is added explicitly. Every other non-get method stays a write.
"""
from ._compat import ReadOnlyViolation, ZabbixClient, ZabbixError, is_write_method

EXTRA_READ_METHODS = frozenset(["sla.getsli"])


class SlaClient(ZabbixClient):
    def call(self, method, params=None):
        write = is_write_method(method) and method not in EXTRA_READ_METHODS
        if write and self.read_only:
            raise ReadOnlyViolation("refusing %s: this run is read-only" % method)
        self._id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params if params is not None else {}, "id": self._id}
        self.log.append((method, write))
        resp = self.transport.send(payload, authenticated=(method != "apiinfo.version"))
        if "error" in resp:
            raise ZabbixError(method, resp["error"])
        return resp["result"]
