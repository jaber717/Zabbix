#!/usr/bin/env python3
"""Authenticated LAB-only validation for Network Utilization v1.2."""
from __future__ import annotations

import argparse, base64, html, json, re, ssl, time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener, urlopen

class Api:
    def __init__(self, endpoint, context): self.endpoint, self.context, self.serial = endpoint, context, 0
    def call(self, method, params, auth=None):
        self.serial += 1
        data = {"jsonrpc":"2.0","method":method,"params":params,"id":self.serial}
        if auth is not None: data["auth"] = auth
        with urlopen(Request(self.endpoint, data=json.dumps(data).encode(), headers={"Content-Type":"application/json-rpc"}), context=self.context, timeout=30) as response: result=json.load(response)
        if "error" in result: raise RuntimeError(f"{method}: {result['error'].get('data', result['error'])}")
        return result["result"]

class Web:
    def __init__(self, base, context): self.base=base.rstrip('/'); self.opener=build_opener(HTTPCookieProcessor(CookieJar()),HTTPSHandler(context=context))
    def login(self, username, password):
        request=Request(self.base+'/index.php',data=urlencode({'name':username,'password':password,'enter':'Sign in'}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
        body=self.opener.open(request,timeout=30).read().decode('utf-8','replace')
        if 'name="password"' in body: raise RuntimeError('administrator web login failed')
    def get(self, action): return self.opener.open(self.base+'/zabbix.php?'+urlencode({'action':action}),timeout=30).read().decode('utf-8','replace')
    def scan_modules(self):
        page=self.get('module.list'); match=re.search(r'name="_csrf_token" value="([^"]+)"',page)
        if not match: raise RuntimeError('module list did not expose its native CSRF token')
        request=Request(self.base+'/zabbix.php',data=urlencode({'action':'module.scan','_csrf_token':html.unescape(match.group(1)),'form':'Scan directory'}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
        self.opener.open(request,timeout=30).read()
    def action(self, action, payload):
        request=Request(self.base+'/zabbix.php?'+urlencode({'action':action}),data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'})
        with self.opener.open(request,timeout=60) as response: return response.status,json.load(response)

def body(response): return response.get('body') or response.get('main_block') or ''
def attribute(page, name):
    match=re.search(rf'data-{re.escape(name)}="([^"]*)"',page)
    if not match: raise RuntimeError(f'missing data-{name}')
    return html.unescape(match.group(1))
def decoded(page,name): return json.loads(base64.b64decode(attribute(page,name)))
def percentile(values):
    if len(values)<20:return None
    values=sorted(values); rank=(len(values)-1)*.95; low=int(rank); high=min(low+1,len(values)-1); return values[low]+(values[high]-values[low])*(rank-low)
def document(revision, capacity=None):
    link={'id':'lab-zabbix-ens18','display_name':'LAB Zabbix ens18','site_id':'lab','host':'ZABBIX-01','interface':{'if_name':'ens18','if_alias':'','if_descr':''},'role':'SERVER','order':0,'visible':True,'required':True}
    if capacity is not None: link.update({'capacity_source':'service_override','service_capacity_in_bps':capacity,'service_capacity_out_bps':capacity})
    return {'schema':'network-utilization-config-v1','revision':revision,'settings':{'warning_util_pct':80,'critical_util_pct':90,'capacity_risk_p95_pct':80,'sustained_window_min':5},'sites':[{'id':'lab','name':'LAB','order':0}],'links':[link]}
def save(web, token, config):
    status,response=web.action('networkutilization.config.update',{'_csrf_token':token,'expected_revision':config['revision'],'payload':json.dumps(config,separators=(',',':'))})
    block=body(response); parsed=json.loads(block) if block else response
    if status!=200 or 'error' in parsed: raise RuntimeError(f'configuration save failed: {parsed}')
    return parsed['configuration']
def render(web):
    started=time.perf_counter(); status,response=web.action('widget.netops_network_utilization.view',{}); elapsed=(time.perf_counter()-started)*1000; page=body(response)
    if status!=200 or 'netops-utilization' not in page: raise RuntimeError(f'widget render failed HTTP {status}: shape={[(key,type(value).__name__) for key,value in response.items()]} page={page[:400]!r} response={str(response)[:800]}')
    return page,elapsed

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--base-url',required=True); parser.add_argument('--ca',type=Path,required=True); parser.add_argument('--admin-password-file',type=Path,required=True); parser.add_argument('--scan-enable',action='store_true'); parser.add_argument('--exercise',action='store_true'); parser.add_argument('--chart-evidence-path',type=Path); args=parser.parse_args()
    context=ssl.create_default_context(cafile=str(args.ca)); password=args.admin_password_file.read_text().strip(); api=Api(args.base_url.rstrip('/')+'/api_jsonrpc.php',context)
    auth=api.call('user.login',{'username':'Admin','password':password}); web=Web(args.base_url,context); web.login('Admin',password)
    if args.scan_enable: web.scan_modules()
    modules=api.call('module.get',{'output':'extend','filter':{'id':['netops_network_utilization']}},auth)
    if not modules: raise RuntimeError('module scan did not discover Network Utilization')
    if args.scan_enable and str(modules[0]['status'])!='1': api.call('module.update',{'moduleid':modules[0]['moduleid'],'status':1},auth); modules=api.call('module.get',{'output':'extend','filter':{'id':['netops_network_utilization']}},auth)
    listing=web.get('module.list')
    print(f"MODULE_ID={modules[0]['moduleid']} MODULE_STATUS={modules[0]['status']} MODULE_PATH={modules[0].get('relative_path')} LISTED={'Network Utilization' in listing}")
    plain=re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',listing))); position=plain.find('Network Utilization')
    print('MODULE_LIST_CONTEXT='+plain[max(0,position-120):position+300])
    dashboard=web.get('dashboard.view')
    chart_pos=dashboard.find('traffic-chart.js'); widget_pos=dashboard.find('class.widget.js',chart_pos)
    print(f"CHART_ASSET_ORDER={'PASS' if 0<=chart_pos<widget_pos else 'NOT_CONFIRMED'}")
    page,elapsed=render(web); configuration=decoded(page,'configuration'); candidates=decoded(page,'candidates'); instrumentation=decoded(page,'instrumentation'); token=attribute(page,'csrf-token')
    ens18=next((candidate for candidate in candidates if candidate['host']=='ZABBIX-01' and candidate['if_name']=='ens18'),None)
    if ens18 is None: raise RuntimeError('live ZABBIX-01 ens18 candidate was not discovered')
    print(f"EMPTY_RENDER_HTTP=200 REQUEST_MS={elapsed:.3f} CANDIDATES={len(candidates)} ENS18=PASS")
    print('INSTRUMENTATION_EMPTY='+json.dumps(instrumentation,sort_keys=True,separators=(',',':')))
    if not args.exercise: print('RESULT=PASS'); return 0
    original=configuration
    try:
        phase1=save(web,token,document(configuration['revision']))
        page,elapsed=render(web); snap=decoded(page,'snapshot'); token=attribute(page,'csrf-token'); link=snap['links'][0]
        if link['capacity_in_bps'] is not None or link['capacity_out_bps'] is not None or link['worst_util_pct'] is not None: raise RuntimeError('unknown capacity produced a fabricated utilization')
        if 'Not configured' not in page or 'Capacity required' not in page: raise RuntimeError('missing-capacity presentation is ambiguous')
        print(f"UNKNOWN_CAPACITY=PASS CURRENT_IN_BPS={link['current_in_bps']} CURRENT_OUT_BPS={link['current_out_bps']} UTILIZATION=UNKNOWN")
        phase2=save(web,token,document(phase1['revision'],50_000_000))
        page,elapsed=render(web); snap=decoded(page,'snapshot'); instrumentation=decoded(page,'instrumentation'); token=attribute(page,'csrf-token'); link=snap['links'][0]
        for direction in ('in','out'):
            bps=link[f'current_{direction}_bps']; pct=link[f'{direction}_util_pct']
            if bps is not None and abs(pct-(bps/50_000_000*100))>1e-9: raise RuntimeError(f'{direction} utilization mismatch')
            metric=link['metrics'][direction]; rows=api.call('history.get',{'output':['clock','value'],'history':metric['value_type'],'itemids':[metric['itemid']],'time_from':snap['generated_at']-86400,'sortfield':'clock','sortorder':'ASC','limit':60000},auth)
            expected=percentile([float(row['value'])*metric['factor'] for row in rows])
            actual=link[f'p95_{direction}_bps']
            if expected is not None and abs(actual-expected)>max(1e-6,expected*1e-9): raise RuntimeError(f'{direction} P95 mismatch')
            native={(int(row['clock']),float(row['value'])*metric['factor']) for row in rows}
            if not all((int(row['clock']),float(row['value'])) in native for row in metric['history']): raise RuntimeError(f'{direction} chart history differs from native Zabbix values')
            trends=api.call('trend.get',{'output':['clock','value_avg'],'itemids':[metric['itemid']],'time_from':snap['generated_at']-7*86400,'sortfield':'clock','sortorder':'ASC','limit':20000},auth)
            native_trends={(int(row['clock']),float(row['value_avg'])*metric['factor']) for row in trends}
            if not all(any(clock==int(row['clock']) and abs(value-float(row['value']))<max(1e-6,abs(value)*1e-9) for clock,value in native_trends) for row in metric['trends_7d']): raise RuntimeError(f'{direction} chart trends differ from native Zabbix averages')
        if link['capacity_source']!='service_override' or link['capacity_in_bps']!=50_000_000 or link['capacity_out_bps']!=50_000_000: raise RuntimeError('service capacity was not preserved')
        if '50 Mbps' not in page or 'Service override' not in page or not re.search(r'\d+(?:\.\d+)?\s(?:bps|Kbps|Mbps|Gbps)',page): raise RuntimeError('rendered traffic or service capacity lacks explicit unit/source')
        print(f"SERVICE_ANALYTICS=PASS CAPACITY_IN={link['capacity_in_bps']:.0f} CAPACITY_OUT={link['capacity_out_bps']:.0f} PORT_SPEED={link['port_speed_bps']} IN_PCT={link['in_util_pct']} OUT_PCT={link['out_util_pct']} P95_IN={link['p95_in_pct']} P95_OUT={link['p95_out_pct']}")
        print(f"SOURCES_IN={link['metrics']['in']['key']} OUT={link['metrics']['out']['key']} CAPACITY_SOURCE={link['capacity_source']}")
        print(f"QUALITY_SOURCES={','.join(sorted(key for key in link['metrics'] if 'errors' in key or 'discards' in key))}")
        print(f"DATA_STATE={link['data_state']} DATA_AGE_S={link['data_age_s']} ADMIN={link['admin_status']} OPER={link['oper_status']}")
        print(f"REMAINING_IN_BPS={link['remaining_in_bps']} REMAINING_OUT_BPS={link['remaining_out_bps']} WORST_REMAINING_BPS={link['worst_headroom_bps']} ERRORS={link['errors_total']} DISCARDS={link['discards_total']}")
        print('CHART_NATIVE_HISTORY_AND_TRENDS=PASS')
        if args.chart_evidence_path:
            args.chart_evidence_path.write_text(json.dumps({'generated_at':snap['generated_at'],'link':link},separators=(',',':')))
            print(f"CHART_EVIDENCE={args.chart_evidence_path}")
        print('INSTRUMENTATION='+json.dumps(instrumentation,sort_keys=True,separators=(',',':')))
        print(f"UI_CONTRACTS={'PASS' if all(value in page for value in ['Needs attention','Top utilized links','Edit links','P95 24H','nu-panel','nu-sites']) else 'FAIL'}")
        bad=document(phase2['revision'],0); status,response=web.action('networkutilization.config.update',{'_csrf_token':token,'expected_revision':phase2['revision'],'payload':json.dumps(bad)})
        invalid_block=body(response); invalid_result=json.loads(invalid_block) if invalid_block else response
        if 'error' not in invalid_result: raise RuntimeError('invalid zero service capacity was accepted')
        print('INVALID_CONFIG_REJECTION=PASS')
    finally:
        page,_=render(web); current=decoded(page,'configuration'); token=attribute(page,'csrf-token'); empty={'schema':'network-utilization-config-v1','revision':current['revision'],'settings':original['settings'],'sites':[],'links':[]}; restored=save(web,token,empty); print(f"EMPTY_CONFIG_RESTORED=PASS REVISION={restored['revision']}")
    print('RESULT=PASS'); return 0
if __name__=='__main__': raise SystemExit(main())
