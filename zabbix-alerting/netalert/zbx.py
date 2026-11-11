"""Zabbix JSON-RPC client.

Every call to Zabbix, read or write, goes through ZabbixClient.call(). Only the
*transport* underneath is swappable (HTTP in production, an in-memory Zabbix
7.0 model in the tests), so the mutation code path is the one that runs for real.
"""
import json
import ssl
import urllib.error
import urllib.request


class ZabbixError(Exception):
    """The API answered with a JSON-RPC error object."""

    def __init__(self, method, error):
        self.method = method
        self.code = error.get("code")
        self.message = error.get("message", "")
        self.data = error.get("data", "")
        Exception.__init__(self, "%s: %s %s" % (method, self.message, self.data))


class ApiUnavailable(Exception):
    """Network/TLS/HTTP problem: the API could not be reached at all."""


class ReadOnlyViolation(Exception):
    """A write method was attempted on a client opened read-only (check / dry-run)."""


READ_ONLY_METHODS = {"apiinfo.version", "user.checkAuthentication", "configuration.export"}


def is_write_method(method):
    return not (method.endswith(".get") or method in READ_ONLY_METHODS)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: urllib would re-send the Authorization header to whatever host the Location
    names. A 3xx then surfaces as an HTTP error and the call fails closed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpTransport(object):
    def __init__(self, url, token, verify_tls=True, timeout=30):
        base = url.rstrip("/")
        if not base.endswith("api_jsonrpc.php"):
            base += "/api_jsonrpc.php"
        self.endpoint = base
        self._token = token
        self.timeout = timeout
        self._ctx = None
        if not verify_tls:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE
        handlers = [NoRedirect()]
        if self._ctx is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self._ctx))
        self._opener = urllib.request.build_opener(*handlers)

    def send(self, payload, authenticated=True):
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated and self._token:
            headers["Authorization"] = "Bearer " + self._token
        req = urllib.request.Request(self.endpoint, json.dumps(payload).encode("utf-8"), headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise ApiUnavailable("HTTP %s redirect from %s refused (the token is never sent to another URL); "
                                     "use the final frontend URL" % (exc.code, self.endpoint))
            raise ApiUnavailable("HTTP %s from %s" % (exc.code, self.endpoint))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ApiUnavailable("cannot reach %s (%s)" % (self.endpoint, exc))


class ZabbixClient(object):
    def __init__(self, transport, read_only=False):
        self.transport = transport
        self.read_only = read_only
        self._id = 0
        self.log = []          # [(method, is_write)] — audit trail, never params

    def call(self, method, params=None):
        write = is_write_method(method)
        if write and self.read_only:
            raise ReadOnlyViolation("refusing %s: this run is read-only" % method)
        self._id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params if params is not None else {},
                   "id": self._id}
        self.log.append((method, write))
        resp = self.transport.send(payload, authenticated=(method != "apiinfo.version"))
        if "error" in resp:
            raise ZabbixError(method, resp["error"])
        return resp["result"]

    # -- convenience read helpers ------------------------------------------------
    def version(self):
        return self.call("apiinfo.version")

    def writes_made(self):
        return [m for m, w in self.log if w]
