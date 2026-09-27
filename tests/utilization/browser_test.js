/* Real Chromium regression of production NetworkUtilization markup, CSS and JavaScript. */
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const fixture=path.resolve(process.argv[2]||''),evidence=path.resolve(process.argv[3]||path.join(os.tmpdir(),'nu-browser-evidence'));
const readonlyFixture=process.argv[4]?path.resolve(process.argv[4]):null;
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
if(!fs.existsSync(fixture)||!fs.existsSync(chrome)||readonlyFixture&&!fs.existsSync(readonlyFixture))throw new Error('Fixture or Chrome missing');
fs.mkdirSync(evidence,{recursive:true});const profile=fs.mkdtempSync(path.join(os.tmpdir(),'nu-chrome-'));
const child=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:'ignore'});
const pause=ms=>new Promise(r=>setTimeout(r,ms));let ws,sequence=0;const pending=new Map(),exceptions=[];
function command(method,params={}){return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(new Error(`${method} timed out`));}},15000);});}
async function evaluate(expression){const r=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;}
async function waitFor(expression,timeout=10000){const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await pause(80);}throw new Error(`Timed out: ${expression}`);}
const check=(name,actual,expected)=>{assert.deepEqual(actual,expected,`${name}: ${JSON.stringify(actual)}`);console.log(`PASS ${name}`);};
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);await pause(30);}
async function order(){return evaluate(`[...document.querySelectorAll('.nu-table tbody tr:not(.is-filtered-out)')].map(r=>r.dataset.linkId)`);}
async function graphOrder(){return evaluate(`[...document.querySelectorAll('.nu-graph-card:not(.is-hidden)')].map(r=>r.dataset.graphLinkId)`);}
async function screenshot(name){const s=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(s.data,'base64'));}
async function layout(){return evaluate(`(()=>{const root=document.querySelector('.netops-utilization'),graphs=[...document.querySelectorAll('.nu-graph-card:not(.is-hidden)')];
  return {overflow:document.documentElement.scrollWidth>innerWidth+1,root:root.getBoundingClientRect().width,
    graphOverflow:graphs.some(g=>g.scrollWidth>g.clientWidth+1),tableOverflow:document.querySelector('.nu-top').scrollWidth>document.querySelector('.nu-top').clientWidth+1,
    axes:graphs.every(g=>g.querySelectorAll('.nu-chart__tick').length>=3),
    ranges:[...document.querySelectorAll('.nu-global-ranges button')].every(b=>{const r=b.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1;})};})()`);}

(async()=>{
  for(let i=0;i<100&&!fs.existsSync(path.join(profile,'DevToolsActivePort'));i++)await pause(100);
  const port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);
  const target=(await(await fetch(`http://127.0.0.1:${port}/json`)).json()).find(x=>x.type==='page');assert.ok(target);
  ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);};
  await command('Page.enable');await command('Runtime.enable');await command('Page.navigate',{url:'file:///'+fixture.replaceAll('\\','/')});
  await waitFor(`document.querySelectorAll('.nu-table tbody tr').length===5&&document.querySelectorAll('.nu-graph-card:not(.is-hidden)').length===3`);
  check('all configured Links visible',await evaluate(`document.querySelectorAll('.nu-table tbody tr').length`),5);
  check('initial explicit graph order',await graphOrder(),['a','b','c']);
  check('no automatic graph beyond configured state',await evaluate(`document.querySelectorAll('.nu-graph-card:not(.is-hidden)').length`),3);
  check('row graph actions',await evaluate(`[...document.querySelectorAll('[data-graph-toggle]')].map(b=>[b.dataset.linkId,b.dataset.graphToggle])`),
    [['a','remove'],['b','remove'],['e','add'],['c','remove'],['d','add']]);
  check('capacity required shown once',await evaluate(`(()=>{const r=document.querySelector('tr[data-link-id="d"]');return (r.textContent.match(/Capacity required/g)||[]).length;})()`),1);
  check('unknown capacity has raw traffic and no bars',await evaluate(`(()=>{const r=document.querySelector('tr[data-link-id="d"]');return r.textContent.includes('12 Mbps')&&r.textContent.includes('8 Mbps')&&r.querySelectorAll('.nu-util-bar').length===0;})()`),true);

  const graphBefore=await graphOrder();await click('[data-sort="current"]');
  check('current sort descending',await order(),['a','b','c','e','d']);check('table sort independent from graph order',await graphOrder(),graphBefore);
  await click('[data-sort="current"]');check('current sort ascending',await order(),['e','c','b','a','d']);
  await evaluate(`(()=>{const x=document.querySelector('.nu-search');x.value='STC';x.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  check('search filters Link list',await order(),['a']);check('search does not hide graphs',await graphOrder(),graphBefore);
  await evaluate(`(()=>{const x=document.querySelector('.nu-search');x.value='';x.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await evaluate(`(()=>{const s=document.querySelector('.nu-site-filter');s.value='dr';s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  check('site filter',await order(),['c','d']);check('site filter does not hide graphs',await graphOrder(),graphBefore);
  await evaluate(`(()=>{const s=document.querySelector('.nu-site-filter');s.value='';s.dispatchEvent(new Event('change',{bubbles:true}));})()`);

  for(const [hours,title] of [['1','Last hour'],['6','Last 6 hours'],['24','Last 24 hours'],['168','Last 7 days']]){
    await click(`[data-global-hours="${hours}"]`);
    check(`global ${hours} active`,await evaluate(`document.querySelector('[data-global-hours="${hours}"]').classList.contains('is-active')`),true);
    check(`all graphs use ${hours}`,await evaluate(`[...document.querySelectorAll('.nu-graph-card:not(.is-hidden) .nu-chart__heading strong')].every(x=>x.textContent.includes('${title}'))`),true);
  }
  check('range datasets differ',await evaluate(`new Set([...document.querySelectorAll('.nu-graph-card:not(.is-hidden) .nu-chart__footer')].map(x=>x.textContent)).size>0`),true);
  check('pinned chart tooltip/crosshair',await evaluate(`(()=>{const hit=document.querySelector('.nu-graph-card:not(.is-hidden) .nu-chart__hit'),r=hit.getBoundingClientRect();hit.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:r.x+r.width/2,clientY:r.y+r.height/2}));const c=hit.closest('.nu-chart');return !c.querySelector('.nu-chart__tooltip').hidden&&!!c.querySelector('.nu-chart__crosshair');})()`),true);

  await click('tr[data-link-id="e"] [data-graph-toggle]');
  check('Add to graphs persists',await evaluate(`window.__lastSavedConfig.links.find(x=>x.id==='e').show_graph`),true);
  check('Add to graphs renders without navigation',await graphOrder(),['a','b','c','e']);
  await click('tr[data-link-id="e"] [data-graph-toggle]');
  check('Remove only unpins',await evaluate(`!window.__lastSavedConfig.links.find(x=>x.id==='e').show_graph&&document.querySelectorAll('.nu-table tr[data-link-id="e"]').length===1`),true);
  check('removed graph disappears',await graphOrder(),['a','b','c']);
  await click('[data-graph-link-id="c"] [data-graph-move="up"]');check('graph move up',await graphOrder(),['a','c','b']);
  check('graph order persisted',await evaluate(`window.__lastSavedConfig.links.filter(x=>x.show_graph).sort((a,b)=>a.graph_order-b.graph_order).map(x=>x.id)`),['a','c','b']);
  await evaluate(`(()=>{const shell=document.createElement('div');shell.innerHTML=document.getElementById('markup').innerHTML;const r=shell.querySelector('.netops-utilization');r.dataset.configuration=btoa(unescape(encodeURIComponent(JSON.stringify(window.__lastSavedConfig))));window.widget.setContents(shell.innerHTML);})()`);
  await waitFor(`document.querySelectorAll('.nu-graph-card:not(.is-hidden)').length===3`);
  check('graph order survives refresh',await graphOrder(),['a','c','b']);

  for(const id of ['a','c','b'])await click(`[data-graph-link-id="${id}"] [data-graph-remove]`);
  check('zero graph empty state',await evaluate(`document.querySelectorAll('.nu-graph-card:not(.is-hidden)').length===0&&!document.querySelector('.nu-graph-empty').classList.contains('is-hidden')`),true);
  check('zero state never auto-selects highest utilization',await graphOrder(),[]);
  for(const id of ['a','b','c','d','e'])await click(`tr[data-link-id="${id}"] [data-graph-toggle]`);
  check('five selected graphs render distinct blocks',await graphOrder(),['a','b','c','d','e']);
  await click('[data-global-hours="6"]');check('five graphs update together',await evaluate(`document.querySelectorAll('.nu-graph-card:not(.is-hidden) .nu-chart__heading strong').length===5&&[...document.querySelectorAll('.nu-graph-card:not(.is-hidden) .nu-chart__heading strong')].every(x=>x.textContent.includes('Last 6 hours'))`),true);

  await click('[data-details-link-id="b"]');
  check('Details paired values',await evaluate(`[...document.querySelectorAll('.nu-detail-row')].every(r=>r.querySelectorAll('span').length===1&&r.querySelectorAll('strong').length===1)`),true);
  check('Details reuses global range',await evaluate(`document.querySelector('.nu-trend-controls [data-hours="6"]').classList.contains('is-active')`),true);
  await click('.nu-panel-close');
  check('authorized controls visible',await evaluate(`document.querySelectorAll('[data-graph-toggle]').length===5&&document.querySelectorAll('[data-graph-move]').length>0`),true);

  for(const theme of ['blue','dark']){
    await evaluate(`document.body.classList.toggle('dark',${theme==='dark'});document.querySelector('.netops-utilization').classList.toggle('is-dark-theme',${theme==='dark'})`);
    for(const width of [1200,900,640,420]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await pause(180);
      const l=await layout();check(`${theme} ${width} no page overflow`,l.overflow,false);check(`${theme} ${width} graphs contained`,l.graphOverflow,false);
      check(`${theme} ${width} Link list contained`,l.tableOverflow,false);check(`${theme} ${width} graph axes readable`,l.axes,true);check(`${theme} ${width} range controls contained`,l.ranges,true);
      if(width===1200||width===420){await evaluate(`scrollTo(0,0)`);await screenshot(`network-utilization-main-${theme}-${width}`);}
      if([1200,640,420].includes(width)){await evaluate(`document.querySelector('.nu-graphs').scrollIntoView()`);await screenshot(`network-utilization-graphs-${theme}-${width}`);}
    }
  }
  await command('Emulation.setDeviceMetricsOverride',{width:900,height:900,deviceScaleFactor:1,mobile:false});await evaluate('scrollTo(0,0)');
  await click('.nu-edit-start');await waitFor(`!document.querySelector('.nu-editor').classList.contains('is-hidden')`);
  check('Edit Links dashboard graph field',await evaluate(`({headings:[...document.querySelectorAll('.nu-editor-group h5')].map(x=>x.textContent),text:document.querySelector('.nu-editor').textContent.includes('Show persistent traffic graph')})`),
    {headings:['IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','DASHBOARD','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','DASHBOARD','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','DASHBOARD','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','DASHBOARD','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','DASHBOARD'],text:true});
  await click('.nu-editor-heading .nu-editor-actions button:first-child');check('Edit discard',await evaluate(`document.querySelector('.nu-editor').classList.contains('is-hidden')`),true);

  if(readonlyFixture){
    await command('Page.navigate',{url:'file:///'+readonlyFixture.replaceAll('\\','/')});await waitFor(`document.querySelectorAll('.nu-graph-card:not(.is-hidden)').length===3`);
    check('read-only graph controls hidden',await evaluate(`document.querySelectorAll('[data-graph-toggle],[data-graph-remove],[data-graph-move]').length`),0);
    check('read-only graphs visible',await graphOrder(),['a','b','c']);
  }
  check('browser exceptions',exceptions,[]);
  console.log('BROWSER=PASS EVIDENCE='+evidence);
})().catch(e=>{console.error('BROWSER=FAIL',e.stack||e);process.exitCode=1;}).finally(()=>{try{ws?.close();child.kill();}catch{}});
