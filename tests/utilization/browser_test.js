/* Real Chromium regression of the production NetworkUtilization markup, CSS and JS. */
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');

const fixture = path.resolve(process.argv[2] || '');
const evidence = path.resolve(process.argv[3] || path.join(os.tmpdir(), 'nu-browser-evidence'));
const chrome = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
if (!fs.existsSync(fixture) || !fs.existsSync(chrome)) throw new Error('Fixture HTML or Chrome missing');
fs.mkdirSync(evidence, {recursive: true});
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nu-chrome-'));
const child = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {stdio:'ignore'});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws, sequence=0; const pending=new Map(); const exceptions=[];
function command(method, params={}) {
  return new Promise((resolve,reject)=>{
    const id=++sequence; pending.set(id,{resolve,reject}); ws.send(JSON.stringify({id,method,params}));
    setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(new Error(`${method} timed out`));}},15000);
  });
}
async function evaluate(expression) {
  const result=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails) throw new Error(result.exceptionDetails.text+' '+(result.exceptionDetails.exception?.description||''));
  return result.result.value;
}
async function waitFor(expression, timeout=10000) {
  const end=Date.now()+timeout;
  while(Date.now()<end){if(await evaluate(expression))return;await pause(100);}
  throw new Error(`Timed out waiting for ${expression}`);
}
const check=(name, actual, expected)=>{assert.deepEqual(actual,expected,`${name}: ${JSON.stringify(actual)}`); console.log(`PASS ${name}`);};
async function order(){return evaluate('[...document.querySelectorAll(".nu-table tbody tr:not(.is-filtered-out)")].map(row=>row.dataset.linkId)');}
async function click(selector){return evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);}
async function dimensions(){return evaluate(`(()=>{
  const box=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
  const rows=[...document.querySelectorAll('.nu-attention__row:not(.is-hidden)')];
  const overlap=(a,b)=>a.x<b.right-1&&b.x<a.right-1&&a.y<b.bottom-1&&b.y<a.bottom-1;
  const attention=rows.map((r,i)=>{const badge=box(r.querySelector('.nu-attention__badge')),
    main=box(r.querySelector('.nu-attention__main')),summary=box(r.querySelector('.nu-attention__summary'));
    return {index:i,collision:overlap(badge,main)||overlap(main,summary)||overlap(badge,summary),
      row:box(r),badge,main,summary,position:getComputedStyle(r.querySelector('.nu-attention__main')).position};});
  return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,
    root:box(document.querySelector('.netops-utilization')),attention,
    controls:[...document.querySelectorAll('.nu-sort button,.nu-toolbar>*')].map(box),
    tableWidth:box(document.querySelector('.nu-table')).width};})()`);}
async function screenshot(name,full=false){const shot=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:full});fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(shot.data,'base64'));}

(async()=>{
  for(let i=0;i<100&&!fs.existsSync(path.join(profile,'DevToolsActivePort'));i++)await pause(100);
  const port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);
  const targets=await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const target=targets.find(x=>x.type==='page'); assert.ok(target,'Chrome page target');
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=event=>{const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){const request=pending.get(msg.id);pending.delete(msg.id);msg.error?request.reject(new Error(JSON.stringify(msg.error))):request.resolve(msg.result);}
    if(msg.method==='Runtime.exceptionThrown')exceptions.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
  };
  await command('Page.enable');await command('Runtime.enable');
  await command('Page.navigate',{url:'file:///'+fixture.replaceAll('\\','/')});
  await waitFor('!!document.querySelector(".netops-utilization .nu-table tbody tr")');
  check('fixture row count',await evaluate('document.querySelectorAll(".nu-table tbody tr").length'),5);
  check('attention structure',await evaluate(`[...document.querySelectorAll('.nu-attention__row')].every(r=>
    ['badge','main','name','meta','reason','summary'].every(s=>r.querySelector('.nu-attention__'+s)))`),true);
  check('long alias retained in attention title',await evaluate(`document.querySelector('.nu-attention__row[data-link-id="b"] .nu-attention__meta').title.includes('A very long connected-to description')`),true);

  const values={current:{a:95,b:85,c:50,d:null,e:10},p95:{a:70,b:90,c:60,d:null,e:20},
    headroom:{a:5,b:20,c:40,d:null,e:90},errors:{a:0,b:3,c:1,d:0,e:8},discards:{a:5,b:0,c:2,d:0,e:1}};
  const fields=['current','p95','headroom','errors','discards'];
  // Current is the default active sort; its first click intentionally reverses it.
  await click('[data-sort="current"]');
  for(const field of fields){
    for(const direction of ['desc','asc']){
      await click(`[data-sort="${field}"]`);
      const expected=Object.keys(values[field]).sort((a,b)=>{
        const av=values[field][a],bv=values[field][b];if(av===null)return bv===null?a.localeCompare(b):1;
        if(bv===null)return -1;return (direction==='desc'?bv-av:av-bv)||a.localeCompare(b);});
      check(`${field} ${direction}`,await order(),expected);
      check(`${field} active arrow`,await evaluate(`document.querySelector('[data-sort="${field}"] .nu-sort-direction').textContent`),direction==='desc'?'↓':'↑');
    }
  }
  await evaluate(`(()=>{const input=document.querySelector('.nu-search');input.value='EDGE';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await click('[data-sort="current"]');check('search + sort',await order(),['a','e','d']);
  await evaluate(`(()=>{const input=document.querySelector('.nu-search');input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await evaluate(`(()=>{const select=document.querySelector('.nu-site-filter');select.value='dr';select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  check('site filter + sort',await order(),['c','d']);
  await evaluate(`(()=>{const select=document.querySelector('.nu-site-filter');select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));
    const role=document.querySelector('.nu-role-filter');role.value='WAN';role.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  check('role filter + sort',await order(),['a','b']);
  await evaluate(`(()=>{const role=document.querySelector('.nu-role-filter');role.value='';role.dispatchEvent(new Event('change',{bubbles:true}));})()`);

  await click('.nu-table tbody tr[data-link-id="b"] .nu-link-open');
  check('details paired rows',await evaluate(`[...document.querySelectorAll('.nu-detail-row')].every(r=>r.querySelectorAll('span').length===1&&r.querySelectorAll('strong').length===1)`),true);
  check('details long alias present',await evaluate(`document.querySelector('.nu-panel').textContent.includes('A very long connected-to description')`),true);
  check('service capacity details',await evaluate(`document.querySelector('.nu-panel').textContent.includes('Service / circuit override')`),true);
  const ranges=[['1','Last hour'],['6','Last 6 hours'],['24','Last 24 hours'],['168','Last 7 days']];
  const rangeFooters=[];
  for(const [range,title] of ranges){await click(`.nu-trend-controls [data-hours="${range}"]`);
    check(`range ${range} active`,await evaluate(`document.querySelector('.nu-trend-controls [data-hours="${range}"]').classList.contains('is-active')`),true);
    check(`range ${range} title`,await evaluate(`document.querySelector('.nu-chart__heading').textContent.includes('${title}')`),true);
    check(`range ${range} axis`,await evaluate(`document.querySelectorAll('.nu-chart__tick').length > 2`),true);
    rangeFooters.push(await evaluate(`document.querySelector('.nu-chart__footer').textContent`));
  }
  check('range time windows differ',new Set(rangeFooters).size,4);
  check('chart tooltip/crosshair',await evaluate(`(()=>{const hit=document.querySelector('.nu-chart__hit');const rect=hit.getBoundingClientRect();
    hit.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:rect.x+rect.width/2,clientY:rect.y+rect.height/2}));
    return !document.querySelector('.nu-chart__tooltip').hidden && !!document.querySelector('.nu-chart__crosshair');})()`),true);
  await click('.nu-panel .nu-panel-close');
  await click('.nu-table tbody tr[data-link-id="d"] .nu-link-open');
  check('missing capacity details',await evaluate(`document.querySelector('.nu-panel').textContent.includes('Not configured') && document.querySelector('.nu-panel').textContent.includes('Capacity required')`),true);
  check('missing capacity label pairing',await evaluate(`[...document.querySelectorAll('.nu-detail-row')].every(r=>r.querySelectorAll('span').length===1&&r.querySelectorAll('strong').length===1)`),true);
  await click('.nu-panel .nu-panel-close');

  for(const theme of ['blue','dark']){
    await evaluate(`document.body.classList.toggle('dark',${theme==='dark'});document.querySelector('.netops-utilization').classList.toggle('is-dark-theme',${theme==='dark'})`);
    for(const width of [1200,900,640,420]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await pause(150);
      await click('.nu-panel .nu-panel-close');
      const layout=await dimensions();
      check(`${theme} ${width} viewport overflow`,layout.scroll<=width+1,true);
      check(`${theme} ${width} attention collision`,layout.attention.some(x=>x.collision),false);
      check(`${theme} ${width} primary flow`,layout.attention.every(x=>x.position!=='absolute'),true);
      if([1200,640,420].includes(width))await screenshot(`network-utilization-${theme}-${width}`);
      if(width===1200){
        check(`${theme} site order`,await evaluate(`[...document.querySelectorAll('.nu-site')].map(x=>x.dataset.siteId)`),['cent','dr']);
        await evaluate(`document.querySelector('.nu-sites').scrollIntoView()`);
        await screenshot(`network-utilization-sites-${theme}-${width}`);
        await evaluate(`scrollTo(0,0)`);
      }
      await click('.nu-table tbody tr[data-link-id="b"] .nu-link-open');
      check(`${theme} ${width} details width`,await evaluate(`(()=>{const p=document.querySelector('.nu-panel');return p.scrollWidth<=p.clientWidth+1&&p.getBoundingClientRect().right<=innerWidth+1})()`),true);
      if(width===1200||width===420)await screenshot(`network-utilization-details-${theme}-${width}`);
    }
  }
  await click('.nu-panel .nu-panel-close');
  await command('Emulation.setDeviceMetricsOverride',{width:900,height:900,deviceScaleFactor:1,mobile:false});
  await click('.nu-edit-start');
  check('edit groups',await evaluate(`[...document.querySelectorAll('.nu-editor-group h5')].map(x=>x.textContent)`),['IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','VISIBILITY','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','VISIBILITY','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','VISIBILITY','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','VISIBILITY','IDENTITY','INTERFACE','CAPACITY','THRESHOLDS','VISIBILITY']);
  check('edit actions visible',await evaluate(`!!document.querySelector('.nu-editor-actions button') && document.querySelector('.nu-editor').scrollWidth<=document.querySelector('.nu-editor').clientWidth+1`),true);
  await click('.nu-editor-create button:nth-child(2)');
  check('add link opens',await evaluate(`!!document.querySelector('.nu-add-link')`),true);
  await command('Emulation.setDeviceMetricsOverride',{width:420,height:900,deviceScaleFactor:1,mobile:false});
  check('edit narrow controls contained',await evaluate(`(()=>{const p=document.querySelector('.nu-editor'),r=p.getBoundingClientRect();
    return p.scrollWidth<=p.clientWidth+1 && [...p.querySelectorAll('button')].every(b=>{const q=b.getBoundingClientRect();return q.left>=r.left-1&&q.right<=r.right+1});})()`),true);
  await screenshot('network-utilization-editor-dark-420');
  await command('Emulation.setDeviceMetricsOverride',{width:900,height:900,deviceScaleFactor:1,mobile:false});
  await click('.nu-editor-heading .nu-editor-actions button:first-child');
  check('discard closes editor',await evaluate(`document.querySelector('.nu-editor').classList.contains('is-hidden')`),true);
  await click('.nu-edit-start');
  await evaluate(`(()=>{const box=document.querySelector('.nu-link-editor');box.open=true;const name=box.querySelector('input[placeholder="Display name"]');name.value='Renamed in fixture';name.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await screenshot('network-utilization-editor-dark-900');
  await click('.nu-editor-heading .nu-editor-actions button:nth-child(2)');
  await waitFor('!!window.__lastSavedConfig');
  check('save persisted through actual handler',await evaluate(`window.__lastSavedConfig.links[0].display_name`),'Renamed in fixture');
  check('save closes editor',await evaluate(`document.querySelector('.nu-editor').classList.contains('is-hidden')`),true);
  check('browser exceptions',exceptions,[]);
  console.log('BROWSER=PASS EVIDENCE='+evidence);
})().catch(error=>{console.error('BROWSER=FAIL',error.stack||error);process.exitCode=1;}).finally(async()=>{try{ws?.close();child.kill();}catch{}});
