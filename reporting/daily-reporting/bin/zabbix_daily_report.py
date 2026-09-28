#!/usr/bin/env python3
from __future__ import annotations
import argparse,html,json,os,re,smtplib,ssl,sys,time
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

SEVERITY={"not_classified":0,"information":1,"warning":2,"average":3,"high":4,"disaster":5}
class Api:
    def __init__(self,cfg):
        self.url=cfg['api_url'];self.timeout=int(cfg.get('request_timeout_seconds',30));self.serial=0
        cafile=cfg.get('ca_file') or None;self.context=ssl.create_default_context(cafile=cafile)
        self.token=os.environ.get('ZABBIX_API_TOKEN','').strip();self.user=os.environ.get('ZABBIX_API_USER','').strip();self.password=os.environ.get('ZABBIX_API_PASSWORD','')
    def call(self,method,params,auth=True):
        self.serial+=1;payload={'jsonrpc':'2.0','method':method,'params':params,'id':self.serial}
        headers={'Content-Type':'application/json-rpc'}
        if auth:
            if self.token:headers['Authorization']='Bearer '+self.token
            elif not self.user or not self.password:raise RuntimeError('ZABBIX_API_TOKEN or ZABBIX_API_USER/ZABBIX_API_PASSWORD is required')
        request=Request(self.url,data=json.dumps(payload,separators=(',',':')).encode(),headers=headers)
        with urlopen(request,context=self.context,timeout=self.timeout) as response:result=json.load(response)
        if 'error'in result:raise RuntimeError(f"{method}: {result['error'].get('data',result['error'].get('message'))}")
        return result['result']
    def authenticate(self):
        if not self.token:self.token=self.call('user.login',{'username':self.user,'password':self.password},False)

def load_config(path):
    data=json.loads(Path(path).read_text());required=['report','zabbix','scope','severity','thresholds','classification','delivery','native_pdf']
    if data.get('schema')!='zabbix-daily-reporting-v1' or any(k not in data for k in required):raise ValueError('configuration does not match zabbix-daily-reporting-v1')
    if data['report'].get('period')!='previous_day':raise ValueError('only previous_day is supported in v1')
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',data['report'].get('schedule_local','')):raise ValueError('schedule_local must be HH:MM')
    if int(data['report'].get('retention_days',0))<1:raise ValueError('retention_days must be positive')
    for key in ['cpu_percent','memory_percent','interface_utilization_percent']:
        if not 0<float(data['thresholds'][key])<=100:raise ValueError(key+' must be within 0..100')
    writers=data['native_pdf'].get('report_writers')
    if not isinstance(writers,int)or not 1<=writers<=100:raise ValueError('native_pdf.report_writers must be an integer within 1..100')
    web_service_url=data['native_pdf'].get('web_service_url','')
    if '\n'in web_service_url or '\r'in web_service_url or not web_service_url.endswith('/report'):raise ValueError('native_pdf.web_service_url must end in /report')
    return data
def site(host,cfg):
    tag=cfg['scope'].get('site_tag','site').lower()
    for row in host.get('tags',[]):
        if row.get('tag','').lower()==tag and row.get('value','').strip():return row['value'].strip()
    groups=[g['name'] for g in host.get('hostgroups',[]) if g.get('name')!='Discovered hosts']
    return groups[0] if groups else 'Unassigned'
def matches_any(text,patterns):return any(p.lower()in text.lower() for p in patterns)
def visible_host(host,cfg):
    groups={g['name'] for g in host.get('hostgroups',[])};include=set(cfg['scope'].get('include_host_groups',[]));exclude=set(cfg['scope'].get('exclude_host_groups',[]))
    if exclude&groups:return False
    if include and not include&groups:return False
    sites=set(cfg['scope'].get('sites',[]));return not sites or site(host,cfg)in sites
def host_availability(host):
    states={str(i.get('available','0')) for i in host.get('interfaces',[])}
    if '2'in states:return'DOWN'
    if '1'in states:return'UP'
    return'UNKNOWN'
def metric_kind(item):
    key=item.get('key_','').lower();name=item.get('name','').lower()
    if key=='system.cpu.util'or key.startswith('system.cpu.util[')or'cpu utilization'in name:return'cpu'
    if key=='vm.memory.util'or key.startswith('vm.memory.util[')or'memory utilization'in name:return'memory'
    return None
def rows_for_problems(problems,triggers,hosts):
    trigger_map={str(t['triggerid']):t for t in triggers};result=[]
    for p in problems:
        t=trigger_map.get(str(p.get('objectid','')),{});hostids=[str(h['hostid']) for h in t.get('hosts',[])]
        names=[hosts[h]['name'] for h in hostids if h in hosts]
        result.append(dict(p,hostids=hostids,hosts=names))
    return result
def collect(cfg,now=None):
    api=Api(cfg['zabbix']);api.authenticate();tz=ZoneInfo(cfg['report']['timezone']);current=now or datetime.now(tz);today=current.replace(hour=0,minute=0,second=0,microsecond=0);start=today-timedelta(days=1);end=today
    z=cfg['zabbix'];hosts_raw=api.call('host.get',{'output':['hostid','host','name'],'selectInterfaces':['available','type','error'],'selectTags':['tag','value'],'selectHostGroups':['groupid','name'],'monitored_hosts':True,'limit':int(z['maximum_hosts']),'preservekeys':True})
    hosts={str(k):dict(v,hostid=str(k)) for k,v in hosts_raw.items()};hosts={k:v for k,v in hosts.items() if visible_host(v,cfg)};ids=list(hosts)
    current_problems=api.call('problem.get',{'output':['eventid','objectid','clock','name','severity','acknowledged','suppressed'],'hostids':ids,'suppressed':None,'symptom':False,'limit':int(z['maximum_problems'])}) if ids else []
    previous=api.call('problem.get',{'output':['eventid','objectid','clock','r_eventid','r_clock','name','severity','acknowledged','suppressed'],'hostids':ids,'recent':True,'time_from':int(start.timestamp()),'time_till':int(end.timestamp())-1,'symptom':False,'limit':int(z['maximum_problems'])}) if ids else []
    resolved_events=api.call('event.get',{'output':['eventid','clock','name','severity','cause_eventid'],'source':0,'object':0,'value':0,'hostids':ids,'time_from':int(start.timestamp()),'time_till':int(end.timestamp())-1,'selectHosts':['hostid','name'],'sortfield':['clock','eventid'],'sortorder':'ASC','limit':int(z['maximum_problems'])}) if ids else []
    triggerids=sorted({str(p['objectid']) for p in current_problems+previous});triggers=api.call('trigger.get',{'output':['triggerid','description','priority'],'triggerids':triggerids,'selectHosts':['hostid'],'preservekeys':False}) if triggerids else []
    items=api.call('item.get',{'output':['itemid','hostid','name','key_','units','lastvalue','lastclock','state'],'hostids':ids,'filter':{'status':0},'limit':int(z['maximum_items'])}) if ids else []
    current_rows=rows_for_problems(current_problems,triggers,hosts);previous_rows=rows_for_problems(previous,triggers,hosts)
    severity_ids={SEVERITY[x.lower()] for x in cfg['severity']};high=[p for p in current_rows if int(p['severity'])in severity_ids]
    down=[h for h in hosts.values() if host_availability(h)=='DOWN'];unknown=[h for h in hosts.values() if host_availability(h)=='UNKNOWN'];up=[h for h in hosts.values() if host_availability(h)=='UP']
    downtime_patterns=cfg['classification']['downtime_problem_patterns'];down_events=[p for p in previous_rows if matches_any(p['name'],downtime_patterns)];downtime_devices=sorted({n for p in down_events for n in p['hosts']})
    new=[p for p in previous_rows if start.timestamp()<=int(p['clock'])<end.timestamp()];resolved=[dict(p,hosts=[h['name'] for h in p.get('hosts',[])],hostids=[str(h['hostid']) for h in p.get('hosts',[])]) for p in resolved_events]
    flap_counts=Counter(n for p in down_events for n in p['hosts']);flapping=[{'device':n,'events':c} for n,c in flap_counts.items() if c>=int(cfg['thresholds']['flapping_events'])]
    latest=defaultdict(int);raw={'cpu':{},'memory':{}}
    for item in items:
        hostid=str(item['hostid']);latest[hostid]=max(latest[hostid],int(item.get('lastclock')or 0));kind=metric_kind(item)
        if kind and item.get('lastclock') and str(item.get('state','0'))=='0':raw[kind][hostid]=float(item['lastvalue']) if str(item.get('lastvalue','')).replace('.','',1).isdigit() else None
    stale_seconds=int(cfg['thresholds']['stale_data_minutes'])*60;stale=[h for h in hosts.values() if latest[h['hostid']]==0 or int(current.timestamp())-latest[h['hostid']]>stale_seconds]
    raw_exceptions=[]
    if cfg['thresholds'].get('raw_metric_evaluation',False):
        for kind,values in raw.items():
            threshold=float(cfg['thresholds'][kind+'_percent'])
            for hostid,value in values.items():
                if value is not None and value>=threshold:raw_exceptions.append({'device':hosts[hostid]['name'],'metric':kind,'value':value,'threshold':threshold})
    utilization=[p for p in previous_rows if matches_any(p['name'],cfg['classification']['utilization_problem_patterns'])]
    ha=[p for p in current_rows if matches_any(p['name'],cfg['classification']['ha_problem_patterns'])]
    return {'schema':'zabbix-daily-report-v1','name':cfg['report']['name'],'generated_at':current.isoformat(),'period':{'start':start.isoformat(),'end':end.isoformat()},'summary':{'available':len(up),'monitored':len(hosts),'currently_down':len(down),'unknown':len(unknown),'high_disaster':len(high),'flapping':len(flapping),'stale':len(stale),'utilization_violations_previous_day':len(utilization)},'current_down':[h['name'] for h in down],'availability_by_site':dict(Counter(site(h,cfg)+':'+host_availability(h) for h in hosts.values())),'downtime_devices_previous_day':downtime_devices,'high_disaster_problems':high,'new_problems_previous_day':new,'resolved_problems_previous_day':resolved,'flapping':flapping,'stale_devices':[h['name'] for h in stale],'ha_problems':ha,'utilization_exceptions':utilization,'raw_metric_exceptions':raw_exceptions,'api_calls':api.serial}
def render_html(report):
    esc=lambda v:html.escape(str(v));s=report['summary']
    def listing(title,rows,formatter):return f'<section><h2>{esc(title)}</h2>'+('<ul>'+''.join('<li>'+formatter(r)+'</li>'for r in rows)+'</ul>'if rows else'<p class="quiet">None</p>')+'</section>'
    body=f'''<!doctype html><html><head><meta charset="utf-8"><title>{esc(report['name'])}</title><style>body{{font:14px Arial,sans-serif;color:#263238;max-width:1100px;margin:24px auto;padding:0 16px}}h1{{margin-bottom:2px}}.meta,.quiet{{color:#65737e}}.summary{{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0}}.chip{{border:1px solid #d5dce1;border-left:4px solid #71808b;padding:8px 12px;min-width:135px}}.bad{{border-left-color:#cf3c3f}}.warn{{border-left-color:#c87500}}h2{{font-size:16px;border-bottom:1px solid #d5dce1;padding-bottom:4px}}li{{margin:4px 0}}footer{{margin-top:24px;color:#65737e;font-size:12px}}</style></head><body><h1>{esc(report['name'])}</h1><div class="meta">Previous day: {esc(report['period']['start'])} — {esc(report['period']['end'])}</div><div class="summary"><div class="chip"><b>{s['available']}/{s['monitored']}</b><br>devices available</div><div class="chip bad"><b>{s['currently_down']}</b><br>currently down</div><div class="chip bad"><b>{s['high_disaster']}</b><br>High / Disaster</div><div class="chip warn"><b>{s['flapping']}</b><br>flapping</div><div class="chip warn"><b>{s['stale']}</b><br>stale data</div><div class="chip warn"><b>{s['utilization_violations_previous_day']}</b><br>utilization events</div></div>'''
    body+=listing('Availability by site',sorted(report['availability_by_site'].items()),lambda x:esc(f'{x[0]} · {x[1]}'))
    body+=listing('Devices currently DOWN',report['current_down'],lambda x:esc(x));body+=listing('Devices with downtime during previous day',report['downtime_devices_previous_day'],lambda x:esc(x));body+=listing('High / Disaster problems',report['high_disaster_problems'],lambda p:esc(' · '.join(p['hosts']+[p['name']])));body+=listing('New problems during previous day',report['new_problems_previous_day'],lambda p:esc(' · '.join(p['hosts']+[p['name']])));body+=listing('Resolved problems during previous day',report['resolved_problems_previous_day'],lambda p:esc(' · '.join(p['hosts']+[p['name']])));body+=listing('Flapping devices',report['flapping'],lambda x:esc(f"{x['device']} · {x['events']} events"));body+=listing('Devices with stale monitoring data',report['stale_devices'],lambda x:esc(x));body+=listing('HA exceptions',report['ha_problems'],lambda p:esc(' · '.join(p['hosts']+[p['name']])));body+=listing('Critical interface / utilization exceptions',report['utilization_exceptions'],lambda p:esc(' · '.join(p['hosts']+[p['name']])));body+=listing('Configured raw CPU / memory exceptions',report['raw_metric_exceptions'],lambda x:esc(f"{x['device']} · {x['metric']} {x['value']:.1f}% ≥ {x['threshold']:.1f}%"));return body+f'<footer>Generated {esc(report["generated_at"])} · API calls {report["api_calls"]}</footer></body></html>'
def deliver(cfg,subject,html_body):
    d=cfg['delivery'];msg=EmailMessage();msg['Subject']=subject;msg['From']=d['sender'];msg['To']=', '.join(d['recipients']);msg.set_content('HTML report attached.');msg.add_alternative(html_body,subtype='html')
    with smtplib.SMTP(d['smtp_host'],int(d['smtp_port']),timeout=30)as smtp:
        if d.get('smtp_starttls'):smtp.starttls(context=ssl.create_default_context())
        password=os.environ.get('DAILY_REPORT_SMTP_PASSWORD','');username=d.get('smtp_username','')
        if username:smtp.login(username,password)
        smtp.send_message(msg)
def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output-directory');p.add_argument('--no-email',action='store_true');p.add_argument('--stdout-json',action='store_true');a=p.parse_args();cfg=load_config(a.config);report=collect(cfg);out=Path(a.output_directory or cfg['report']['output_directory']);out.mkdir(parents=True,exist_ok=True);stamp=report['period']['start'][:10];j=out/f'daily-network-health-{stamp}.json';h=out/f'daily-network-health-{stamp}.html';j.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');markup=render_html(report);h.write_text(markup)
    cutoff=time.time()-int(cfg['report']['retention_days'])*86400
    for f in out.glob('daily-network-health-*.*'):
        if f.stat().st_mtime<cutoff:f.unlink()
    if cfg['delivery']['custom_email_enabled']and not a.no_email:deliver(cfg,f"{cfg['report']['name']} · {stamp}",markup)
    if a.stdout_json:print(json.dumps(report['summary'],sort_keys=True))
    print(f'JSON={j}\nHTML={h}\nRESULT=PASS')
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(f'RESULT=FAIL ERROR={e}',file=sys.stderr);raise SystemExit(1)
