'use strict';
// Drives /home/claude/build/fmc_collector_v2.js against a mocked FMC.
var fs = require('fs');
var yamlText = fs.readFileSync(require('path').join(__dirname, '..', 'zbx_template_cisco_fmc_rest_api.yaml'), 'utf8').split('\n');
var a = yamlText.indexOf('      params: |') + 1, b = a;
while (yamlText[b].indexOf('        ') === 0 || yamlText[b] === '') { b++; }
var code = yamlText.slice(a, b).map(function (l) { return l.substring(8); }).join('\n');
var assert = require('assert');

var calls = [];
var scenario = null;

function Mock() { this.h = []; this.status = 0; this.hdrs = {}; }
Mock.prototype.clearHeader = function () { this.h = []; };
Mock.prototype.addHeader = function (x) { this.h.push(x); };
Mock.prototype.getStatus = function () { return this.status; };
Mock.prototype.getHeaders = function () { return this.hdrs; };
Mock.prototype._do = function (method, url) {
    var u = url.replace(/^https:\/\/[^/]+/, '');
    var hdr = {};
    this.h.forEach(function (x) { var i = x.indexOf(':'); hdr[x.substring(0, i).trim().toLowerCase()] = x.substring(i + 1).trim(); });
    calls.push({ method: method, path: u, hdr: hdr });
    var r = scenario(method, u, hdr);
    this.status = r.status;
    this.hdrs = r.headers || {};
    return r.body === undefined ? '' : (typeof r.body === 'string' ? r.body : JSON.stringify(r.body));
};
Mock.prototype.get = function (url) { return this._do('GET', url); };
Mock.prototype.post = function (url) { return this._do('POST', url); };

globalThis.HttpRequest = Mock;
globalThis.Zabbix = { log: function () {} };

function run(params, sc) {
    calls = [];
    scenario = sc;
    var fn = new Function('value', code);
    try {
        return { out: JSON.parse(fn(JSON.stringify(params))), thrown: null };
    } catch (e) {
        return { out: null, thrown: String(e && e.message ? e.message : e) };
    }
}

var BASE = { host: 'fmc.test', port: '443', user: 'u', password: 'p', domain: '', alerts_window: '86400', revoke: '1' };
var DOM = 'e276abec-e0f2-11e3-8169-6d9ed49b625f';

function makeDevices(n) {
    var a = [];
    for (var i = 0; i < n; i++) {
        a.push({ id: 'id' + i, name: 'ftd-' + i, hostName: 'ftd-' + i + '.lab', model: 'Firepower 2110', sw_version: '7.4.2',
            healthStatus: i === 3 ? 'red' : (i === 4 ? 'yellow' : 'green'), healthMessage: 'msg' + i,
            deploymentStatus: 'DEPLOYED', isConnected: i !== 5 });
    }
    return a;
}

function happy(devCount, alerts) {
    var devs = makeDevices(devCount);
    return function (method, u, hdr) {
        if (u.indexOf('/auth/generatetoken') !== -1) {
            assert(/^basic /i.test(hdr['authorization']), 'basic auth header present');
            return { status: 204, headers: { 'X-auth-access-token': 'TOK', 'X-auth-refresh-token': 'REF', 'DOMAIN_UUID': DOM } };
        }
        if (u.indexOf('/auth/revokeaccess') !== -1) { return { status: 204 }; }
        assert.strictEqual(hdr['x-auth-access-token'], 'TOK', 'token sent on ' + u);
        var m;
        if (u.indexOf('/devices/devicerecords') !== -1) {
            m = /limit=(\d+)&offset=(\d+)/.exec(u);
            var lim = +m[1], off = +m[2];
            return { status: 200, body: { items: devs.slice(off, off + lim), paging: {} } };
        }
        if (u.indexOf('/info/serverversion') !== -1) {
            return { status: 200, body: { items: [{ serverVersion: '7.4.2 (build 172)', vdbVersion: 'build 395', sruVersion: '2024', geoVersion: 'g', lspVersion: 'lsp' }] } };
        }
        if (u.indexOf('/deployment/deployabledevices') !== -1) {
            return { status: 200, body: { items: [{ name: 'ftd-1' }, { name: 'ftd-2', canBeDeployed: false }] } };
        }
        if (u.indexOf('/health/alerts') !== -1) { return { status: 200, body: { items: alerts || [] } }; }
        return { status: 404, body: { error: { messages: [{ description: 'nope' }] } } };
    };
}

var t = 0;
function ok(name) { t++; console.log('ok ' + t + ' - ' + name); }

// 1. happy path, FMC-own alerts, RED -> RECOVERED dedupe, paging (150 devices > page 100)
(function () {
    var now = Math.floor(Date.now() / 1000);
    var alerts = [
        { deviceUUID: '0', moduleID: 'DISK_USAGE', name: 'Disk', status: 'RED', timestamp: now - 3000, description: 'Disk 95%' },
        { deviceUUID: '0', moduleID: 'CPU', name: 'CPU', status: 'RED', timestamp: now - 3000, description: 'CPU high' },
        { deviceUUID: '0', moduleID: 'CPU', name: 'CPU', status: 'RECOVERED', timestamp: now - 100, description: 'CPU ok' },
        { deviceUUID: '0', moduleID: 'NTPD', name: 'NTP', status: 'YELLOW', timestamp: now - 50, description: 'NTP drift' },
        { deviceUUID: 'abc', moduleID: 'INTERFACE', name: 'if', status: 'RED', timestamp: now - 10, description: 'if down' }
    ];
    var r = run(BASE, happy(150, alerts));
    assert.strictEqual(r.thrown, null);
    var o = r.out;
    assert.strictEqual(o.ok, 1);
    assert.strictEqual(o.domain, DOM, 'DOMAIN_UUID taken from header');
    assert.strictEqual(o.devices.total, 150);
    assert.strictEqual(o.devices.red, 1);
    assert.strictEqual(o.devices.yellow, 1);
    assert.strictEqual(o.devices.green, 148);
    assert.strictEqual(o.devices.disconnected, 1);
    assert.strictEqual(o.version.server, '7.4.2 (build 172)');
    assert.strictEqual(o.deploy.pending, 2);
    assert.strictEqual(o.alerts.fmc.red, 1, 'CPU RED cancelled by RECOVERED, Disk RED stays');
    assert.strictEqual(o.alerts.fmc.yellow, 1);
    assert.strictEqual(o.alerts.all.red, 2);
    assert(o.alerts.fmc.details.indexOf('DISK_USAGE') !== -1);
    assert.strictEqual(o.warnings.length, 0);
    var dev = calls.filter(function (c) { return c.path.indexOf('/devicerecords') !== -1; });
    assert.strictEqual(dev.length, 2, 'two device pages');
    assert(/offset=100/.test(dev[1].path), 'second page offset 100');
    var last = calls[calls.length - 1];
    assert.strictEqual(last.path, '/api/fmc_platform/v1/auth/revokeaccess', 'session revoked last');
    assert.strictEqual(last.hdr['x-auth-access-token'], 'TOK');
    var red = o.devices.items.filter(function (d) { return d.hc === 2; })[0];
    assert.strictEqual(red.hm, 'msg3', 'health message kept for red');
    var green = o.devices.items[0];
    assert.strictEqual(green.hm, '', 'empty health message for green');
    ok('happy path, paging, alert dedupe, revoke');
})();

// 2. bad credentials -> thrown AUTH (item unsupported), token never obtained, no revoke
(function () {
    var r = run(BASE, function (m, u) { return { status: 401, body: { error: { messages: [{ description: 'Invalid credentials' }] } } }; });
    assert(r.thrown && r.thrown.indexOf('AUTH:') === 0, 'AUTH thrown: ' + r.thrown);
    assert.strictEqual(calls.length, 1, 'exactly one login attempt');
    ok('401 throws AUTH after a single attempt');
})();

// 3. REST API disabled -> 403 thrown
(function () {
    var r = run(BASE, function () { return { status: 403, body: '' }; });
    assert(r.thrown && /REST API disabled/.test(r.thrown));
    ok('403 throws AUTH with REST-disabled hint');
})();

// 4. secondary sections fail -> ok stays 1, sections omitted (never zero-filled), warnings recorded
(function () {
    var base = happy(3, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/health/alerts') !== -1) { return { status: 403, body: { error: { messages: [{ description: 'Access denied' }] } } }; }
        if (u.indexOf('/deployabledevices') !== -1) { return { status: 500, body: 'boom' }; }
        return base(m, u, h);
    });
    var o = r.out;
    assert.strictEqual(o.ok, 1);
    assert.strictEqual(o.alerts, undefined, 'alerts omitted on failure');
    assert.strictEqual(o.deploy, undefined, 'deploy omitted on failure');
    assert.strictEqual(o.warnings.length, 3, 'deploy + alerts_all + alerts_fmc');
    assert(/Access denied/.test(o.warnings.join('|')));
    assert.strictEqual(o.sections.alerts_all.s, 2); assert.strictEqual(o.sections.deploy.s, 1); assert.strictEqual(o.sections.devices.s, 0);
    assert.strictEqual(calls[calls.length - 1].path, '/api/fmc_platform/v1/auth/revokeaccess');
    ok('secondary failures become warnings, sections omitted');
})();

// 5. primary data (devicerecords) fails -> ok=0 + error, token still revoked
(function () {
    var base = happy(3, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/devicerecords') !== -1) { return { status: 500, body: 'x' }; }
        return base(m, u, h);
    });
    assert.strictEqual(r.thrown, null);
    assert.strictEqual(r.out.ok, 0);
    assert(/devicerecords: HTTP 500/.test(r.out.error));
    assert.strictEqual(r.out.devices, undefined);
    assert.strictEqual(calls[calls.length - 1].path, '/api/fmc_platform/v1/auth/revokeaccess');
    assert(r.out.version && r.out.deploy && r.out.alerts, 'other sections still collected');
    assert.strictEqual(r.out.sections.devices.s, 1);
    ok('devicerecords failure => ok=0 with error, other sections still collected, session revoked');
})();

// 6. 429 on a data call
(function () {
    var base = happy(3, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/devicerecords') !== -1) { return { status: 429, body: '' }; }
        return base(m, u, h);
    });
    assert.strictEqual(r.out.ok, 0);
    assert(/429/.test(r.out.error));
    ok('429 surfaces as ok=0 with rate-limit message');
})();

// 7. revoke=0 skips revoke; alerts_window=0 skips alert call; explicit domain is used
(function () {
    var p = JSON.parse(JSON.stringify(BASE)); p.revoke = '0'; p.alerts_window = '0'; p.domain = 'my-domain';
    var r = run(p, happy(2, []));
    assert.strictEqual(r.out.ok, 1);
    assert.strictEqual(r.out.domain, 'my-domain');
    assert(!calls.some(function (c) { return c.path.indexOf('revokeaccess') !== -1; }));
    assert(!calls.some(function (c) { return c.path.indexOf('/health/alerts') !== -1; }));
    assert(calls.some(function (c) { return c.path.indexOf('/domain/my-domain/') !== -1; }));
    ok('revoke=0, alerts_window=0, explicit domain honoured');
})();

// 8. missing credentials -> AUTH thrown without any network call
(function () {
    var p = JSON.parse(JSON.stringify(BASE)); p.password = '';
    var r = run(p, happy(1, []));
    assert(r.thrown && r.thrown.indexOf('AUTH:') === 0);
    assert.strictEqual(calls.length, 0);
    ok('empty credentials => no network call');
})();

// 9. no token header in 204 response
(function () {
    var r = run(BASE, function (m, u) { return { status: 204, headers: {} }; });
    assert.strictEqual(r.out.ok, 0);
    assert(/no X-auth-access-token/.test(r.out.error));
    ok('missing token header handled');
})();

// 10. header-name case differences (lowercase headers) still parse
(function () {
    var base = happy(1, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/auth/generatetoken') !== -1) {
            return { status: 204, headers: { 'x-auth-access-token': ['TOK'], 'x-auth-refresh-token': ['REF'], 'domain_uuid': [DOM] } };
        }
        return base(m, u, h);
    });
    assert.strictEqual(r.out.ok, 1);
    assert.strictEqual(r.out.domain, DOM);
    ok('lower-case / array-valued headers accepted');
})();

// 11. size guard: 400 devices with fat health messages must stay < 64KB
(function () {
    var base = happy(400, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/devicerecords') !== -1) {
            var mm = /limit=(\d+)&offset=(\d+)/.exec(u), lim = +mm[1], off = +mm[2];
            var all = [];
            for (var i = 0; i < 400; i++) {
                all.push({ id: 'a0b1c2d3-0000-0000-0000-' + ('000000000000' + i).slice(-12), name: 'long-firewall-name-number-' + i, hostName: 'host-' + i + '.corp.example.com',
                    model: 'Cisco Firepower Threat Defense for VMware', sw_version: '7.4.2-172', healthStatus: 'red', healthMessage: new Array(200).join('x'), deploymentStatus: 'PENDING', isConnected: true });
            }
            return { status: 200, body: { items: all.slice(off, off + lim) } };
        }
        return base(m, u, h);
    });
    var size = JSON.stringify(r.out).length;
    assert(size < 65535, 'size ' + size);
    assert(r.out.warnings.some(function (w) { return /60 KB/.test(w); }));
    assert.strictEqual(r.out.devices.total, 400);
    ok('size guard keeps output under 64KB (' + size + ' bytes for 400 failing devices)');
})();


// ---------------------------------------------------------------- new scenarios (pagination / isolation)
function listServer(all, opts) {
    opts = opts || {};
    return function (u) {
        var m = /limit=(\d+)&offset=(\d+)/.exec(u);
        var lim = Math.min(+m[1], opts.clamp || 1e9), off = opts.ignoreOffset ? 0 : +m[2];
        var items = all.slice(off, off + lim);
        var body = { links: {}, paging: { offset: off, limit: lim, count: opts.count !== undefined ? opts.count : all.length, pages: Math.ceil(all.length / lim) } };
        if (opts.noPaging) { delete body.paging; }
        if (items.length || !opts.omitEmptyItems) { body.items = items; }
        return { status: 200, body: body };
    };
}
function mkAlerts(n, dev) {
    var a = [], now = Math.floor(Date.now() / 1000);
    for (var i = 0; i < n; i++) { a.push({ deviceUUID: dev === undefined ? (i % 2 ? '0' : 'dev') : dev, moduleID: 'M' + i, name: 'n' + i, status: i % 10 === 0 ? 'RED' : 'GREEN', timestamp: now - i, description: 'd' + i }); }
    return a;
}
function withAlerts(alertFn, extra) {
    var base = happy(4, []);
    return function (m, u, h) {
        if (u.indexOf('/health/alerts') !== -1) { return alertFn(u); }
        if (extra) { var r = extra(m, u, h); if (r) { return r; } }
        return base(m, u, h);
    };
}
function alertCalls() { return calls.filter(function (c) { return c.path.indexOf('/health/alerts') !== -1; }); }

// 12. 4500 alerts, honest paging metadata -> all read, exact counts, 5 pages
(function () {
    var al = mkAlerts(4500);
    var r = run(BASE, withAlerts(listServer(al)));
    assert.strictEqual(r.out.sections.alerts_all.s, 0);
    assert.strictEqual(r.out.sections.alerts_all.n, 4500);
    assert.strictEqual(r.out.sections.alerts_all.pages, 5);
    assert.strictEqual(r.out.alerts.all.red, 450);
    assert.strictEqual(r.out.alerts.fmc.red, 0, 'RED alerts (i%10==0) all belong to non-FMC devices');
    assert.strictEqual(r.out.sections.alerts_fmc.from, 'alerts_all');
    assert.strictEqual(r.out.warnings.length, 0);
    ok('4500 alerts across 5 pages read completely');
})();

// 13. server clamps limit to 25 and reports it -> offset advances by received count, everything read
(function () {
    var r = run(BASE, withAlerts(listServer(mkAlerts(260)), null));
    var base = happy(4, []);
    var devs = makeDevices(60);
    var r2 = run(BASE, function (m, u, h) {
        if (u.indexOf('/devicerecords') !== -1) { return listServer(devs, { clamp: 25 })(u); }
        return base(m, u, h);
    });
    assert.strictEqual(r2.out.devices.total, 60);
    assert.strictEqual(r2.out.sections.devices.pages, 3);
    var r3 = run(BASE, withAlerts(listServer(mkAlerts(260), { clamp: 25 })));
    assert.strictEqual(r3.out.sections.alerts_all.n, 260, 'clamped alert pages');
    assert.strictEqual(r3.out.sections.alerts_all.pages, 11);
    ok('server-clamped page size (limit 25) still read completely');
})();

// 14. offset ignored -> explicit error, no duplicate counting, other sections unaffected
(function () {
    var r = run(BASE, withAlerts(listServer(mkAlerts(5000), { ignoreOffset: true })));
    assert.strictEqual(r.out.ok, 1);
    assert.strictEqual(r.out.sections.alerts_all.s, 1);
    assert(/ignores offset/.test(r.out.sections.alerts_all.msg), r.out.sections.alerts_all.msg);
    assert.strictEqual(r.out.alerts, undefined, 'no partial alert counts published');
    assert.strictEqual(r.out.sections.devices.s, 0); assert.strictEqual(r.out.sections.deploy.s, 0); assert.strictEqual(r.out.sections.version.s, 0);
    assert(r.out.devices && r.out.deploy && r.out.version);
    assert(alertCalls().length <= 4, 'stops quickly, got ' + alertCalls().length + ' alert calls');
    ok('offset ignored by server => stops after 2 pages with clear error');
})();

// 15. huge count -> all-devices refused up front with the numbers; FMC-only narrow query still works
(function () {
    var big = listServer(mkAlerts(3), { count: 200000 });
    var fmcOnly = mkAlerts(3, '0');
    var r = run(BASE, withAlerts(function (u) {
        if (u.indexOf('deviceUUIDs') !== -1 || u.indexOf('deviceUUIDs'.replace(/./g, function (c) { return c; })) !== -1) {
            return listServer(fmcOnly)(u);
        }
        return big(u);
    }));
    assert.strictEqual(r.out.sections.alerts_all.s, 1);
    assert(/200000 records/.test(r.out.sections.alerts_all.msg) && /PAGING\.MAX\.ITEMS/.test(r.out.sections.alerts_all.msg), r.out.sections.alerts_all.msg);
    assert.strictEqual(r.out.sections.alerts_fmc.s, 0);
    assert(r.out.alerts.fmc && r.out.alerts.all === undefined, 'fmc published, all absent');
    assert.strictEqual(r.out.warnings.length, 1);
    var narrow = alertCalls().filter(function (c) { return /deviceUUIDs%3A0/.test(c.path); });
    assert.strictEqual(narrow.length, 1);
    ok('count above budget => explicit error, FMC-only fallback keeps appliance alerts');
})();

// 16. FMC says 3000 but list ends at 2000 -> incomplete error, not a smaller result
(function () {
    var r = run(BASE, withAlerts(listServer(mkAlerts(2000), { count: 3000 })));
    assert.strictEqual(r.out.sections.alerts_all.s, 1);
    assert(/incomplete list: read 2000 of 3000/.test(r.out.sections.alerts_all.msg), r.out.sections.alerts_all.msg);
    assert.strictEqual(r.out.alerts && r.out.alerts.all, undefined);
    ok('count/list mismatch refused as incomplete');
})();

// 17. empty result without "items" key but with paging = empty list; without paging = shape error
(function () {
    var r = run(BASE, withAlerts(listServer([], { omitEmptyItems: true })));
    assert.strictEqual(r.out.sections.alerts_all.s, 0);
    assert.strictEqual(r.out.alerts.all.red, 0);
    var r2 = run(BASE, withAlerts(function () { return { status: 200, body: { links: {} } }; }));
    assert.strictEqual(r2.out.sections.alerts_all.s, 1);
    assert(/unexpected FMC response shape/.test(r2.out.sections.alerts_all.msg));
    ok('missing items: empty with paging, shape error without');
})();

// 18. exact multiple of the page size: one extra (empty) request, no loss, no false error
(function () {
    var r = run(BASE, withAlerts(listServer(mkAlerts(2000))));
    assert.strictEqual(r.out.sections.alerts_all.n, 2000);
    assert.strictEqual(r.out.sections.alerts_all.pages, 3);
    assert.strictEqual(r.out.sections.alerts_all.s, 0);
    ok('full last page handled (extra empty request)');
})();

// 19. page budget: count 100000 at 1000/page => needs 100 pages > 50
(function () {
    var p = JSON.parse(JSON.stringify(BASE)); p.max_items = '500000';
    var all = mkAlerts(1000);
    var r = run(p, withAlerts(function (u) {
        var m = /offset=(\d+)/.exec(u), off = +m[1];
        var items = mkAlerts(1000).map(function (a, i) { a.name = 'p' + off + '-' + i; return a; });
        return { status: 200, body: { items: items, paging: { offset: off, limit: 1000, count: 100000, pages: 100 } } };
    }));
    assert.strictEqual(r.out.sections.alerts_all.s, 1);
    assert(/more than 50 pages/.test(r.out.sections.alerts_all.msg), r.out.sections.alerts_all.msg);
    assert(calls.filter(function (c) { return c.method === 'GET'; }).length <= 100, 'GET budget respected');
    ok('page budget stops runaway pagination with diagnostics');
})();

// 20. deployabledevices HTTP 403 (the reported production error): classified forbidden, nothing else affected
(function () {
    var r = run(BASE, withAlerts(listServer(mkAlerts(10)), function (m, u) {
        if (u.indexOf('/deployabledevices') !== -1) { return { status: 403, body: { error: { messages: [{ description: 'The user is not authorized.' }] } } }; }
    }));
    var o = r.out;
    assert.strictEqual(o.ok, 1);
    assert.strictEqual(o.sections.deploy.s, 2); assert.strictEqual(o.sections.deploy.http, 403);
    assert(/deployabledevices: HTTP 403 - The user is not authorized\./.test(o.sections.deploy.msg));
    assert(/\{\$FMC\.DEPLOY\.ENABLED\}=0/.test(o.sections.deploy.msg));
    assert.strictEqual(o.deploy, undefined);
    assert.strictEqual(o.warnings.length, 1, 'genuine error still reported');
    assert(o.devices.total === 4 && o.version && o.alerts.all, 'other data intact');
    assert.strictEqual(o.sections.alerts_all.s, 0);
    ok('deployabledevices 403 => forbidden status + warning; devices/version/alerts intact');
})();

// 21. deploy disabled by macro => no call, status 3, no warning
(function () {
    var p = JSON.parse(JSON.stringify(BASE)); p.deploy_enabled = '0';
    var r = run(p, happy(4, []));
    assert(!calls.some(function (c) { return c.path.indexOf('deployabledevices') !== -1; }));
    assert.strictEqual(r.out.sections.deploy.s, 3);
    assert.strictEqual(r.out.warnings.length, 0);
    assert.strictEqual(r.out.deploy, undefined);
    ok('{$FMC.DEPLOY.ENABLED}=0 skips the call (status 3, no warning)');
})();

// 22. alerts_all=0 => only the FMC-only query
(function () {
    var p = JSON.parse(JSON.stringify(BASE)); p.alerts_all = '0';
    var r = run(p, withAlerts(listServer(mkAlerts(6, 'x').concat(mkAlerts(4, '0')))));
    assert(alertCalls().length > 0);
    assert(alertCalls().every(function (c) { return /deviceUUIDs%3A0/.test(c.path); }));
    assert.strictEqual(r.out.sections.alerts_all.s, 3);
    assert.strictEqual(r.out.alerts.all, undefined);
    assert.strictEqual(r.out.sections.alerts_fmc.s, 0);
    ok('alerts_all=0 uses only the FMC-only query; client-side deviceUUID filter applied');
})();

// 23. no devices at all (empty fleet) is a valid, successful result
(function () {
    var base = happy(4, []);
    var r = run(BASE, function (m, u, h) {
        if (u.indexOf('/devicerecords') !== -1) { return { status: 200, body: { links: {}, paging: { offset: 0, limit: 100, count: 0, pages: 0 } } }; }
        return base(m, u, h);
    });
    assert.strictEqual(r.out.ok, 1); assert.strictEqual(r.out.devices.total, 0);
    ok('empty device list is ok=1, total 0');
})();

console.log('\nall ' + t + ' scenarios passed');
