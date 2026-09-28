#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,html,json,re,ssl,time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor,HTTPSHandler,Request,build_opener,urlopen
class Api:
    def __init__(self,url,ctx):self.url,self.ctx,self.i=url,ctx,0
    def call(self,method,params,auth=None):
        self.i+=1;body={'jsonrpc':'2.0','method':method,'params':params,'id':self.i}
        if auth is not None:body['auth']=auth
        with urlopen(Request(self.url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json-rpc'}),context=self.ctx,timeout=30) as r:result=json.load(r)
        if 'error'in result:raise RuntimeError(f"{method}: {result['error']}")
        return result['result']
class Web:
    def __init__(self,base,ctx):self.base=base.rstrip('/');self.opener=build_opener(HTTPCookieProcessor(CookieJar()),HTTPSHandler(context=ctx))
    def login(self,user,password):
        body=self.opener.open(Request(self.base+'/index.php',data=urlencode({'name':user,'password':password,'enter':'Sign in'}).encode()),timeout=30).read().decode('utf-8','replace')
        if 'name="password"'in body:raise RuntimeError('web login failed')
    def get(self,action):return self.opener.open(self.base+'/zabbix.php?'+urlencode({'action':action}),timeout=30).read().decode('utf-8','replace')
    def scan(self):
        page=self.get('module.list');m=re.search(r'name="_csrf_token" value="([^"]+)"',page)
        if not m:raise RuntimeError('module scan CSRF unavailable')
        self.opener.open(Request(self.base+'/zabbix.php',data=urlencode({'action':'module.scan','_csrf_token':html.unescape(m.group(1)),'form':'Scan directory'}).encode()),timeout=30).read()
    def action(self,action,payload):
        with self.opener.open(Request(self.base+'/zabbix.php?'+urlencode({'action':action}),data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'}),timeout=60) as r:return r.status,json.load(r)
def response_body(r):return r.get('body')or r.get('main_block')or''
def attr(page,name):
    m=re.search(rf'data-{re.escape(name)}="([^"]*)"',page)
    if not m:raise RuntimeError('missing data-'+name)
    return html.unescape(m.group(1))
def decoded(page,name):return json.loads(base64.b64decode(attr(page,name)))
def main():
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--ca',type=Path,required=True);p.add_argument('--password-file',type=Path,required=True);p.add_argument('--scan-enable',action='store_true');p.add_argument('--browser-output',type=Path);a=p.parse_args()
    ctx=ssl.create_default_context(cafile=str(a.ca));password=a.password_file.read_text().strip();api=Api(a.base_url.rstrip('/')+'/api_jsonrpc.php',ctx);auth=api.call('user.login',{'username':'Admin','password':password});web=Web(a.base_url,ctx);web.login('Admin',password)
    if a.scan_enable:web.scan()
    modules=api.call('module.get',{'output':'extend','filter':{'id':['netops_device_health']}},auth)
    if not modules:raise RuntimeError('Device Health module not discovered')
    if a.scan_enable and str(modules[0]['status'])!='1':api.call('module.update',{'moduleid':modules[0]['moduleid'],'status':1},auth);modules=api.call('module.get',{'output':'extend','filter':{'id':['netops_device_health']}},auth)
    start=time.perf_counter();status,response=web.action('widget.netops_device_health.view',{});elapsed=(time.perf_counter()-start)*1000;page=response_body(response)
    if status!=200 or 'netops-device-health'not in page:raise RuntimeError(f'widget render failed HTTP {status}: {page[:500]!r}')
    snap=decoded(page,'snapshot');inst=decoded(page,'instrumentation')
    print(f"MODULE_STATUS={modules[0]['status']} MODULE_VERSION={modules[0].get('version','1.0.0')}")
    print(f"WIDGET_HTTP={status} REQUEST_MS={elapsed:.3f}")
    print(f"DEVICES={len(snap['devices'])} ATTENTION={len(snap['needs_attention'])} SITES={len(snap['sites'])}")
    print('SUMMARY='+json.dumps(snap['summary'],sort_keys=True,separators=(',',':')))
    print('PROFILES='+','.join(sorted({d['profile'] for d in snap['devices']})))
    print('INSTRUMENTATION='+json.dumps(inst,sort_keys=True,separators=(',',':')))
    if inst.get('api_call_count')!=4:raise RuntimeError('API call budget changed')
    if inst.get('history_rows')!=0 or inst.get('trend_rows')!=0:raise RuntimeError('unexpected history/trend collection')
    if a.browser_output:
        module=Path('/usr/share/zabbix/modules/DeviceHealth')
        bootstrap="class CWidget{constructor(){this._contents=document.getElementById('mount')}setContents(h){this._contents.innerHTML=h}onClearContents(){}}"
        document='<!doctype html><html><head><meta charset="utf-8"><title>Device Health live LAB render</title><style>body{margin:0;padding:8px;font:13px Arial;background:#fff}body.dark{background:#20272d}#mount{width:100%}button,input,select{font:inherit}</style><style>'+ (module/'assets/css/device-health.css').read_text()+'</style></head><body><div id="mount"></div><template id="markup">'+page+'</template><script>'+bootstrap+'</script><script>'+(module/'assets/js/class.widget.js').read_text()+'</script><script>window.widget=new CWidgetDeviceHealth();window.widget.setContents(document.getElementById("markup").innerHTML)</script></body></html>'
        a.browser_output.write_text(document)
        print(f'BROWSER_OUTPUT={a.browser_output}')
    print('RESULT=PASS');return 0
if __name__=='__main__':raise SystemExit(main())
