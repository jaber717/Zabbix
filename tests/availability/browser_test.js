/* Chromium interaction/layout regression against real PHP-rendered Availability components. */
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');const assert=require('node:assert/strict');
const fixture=path.resolve(process.argv[2]||'');const evidence=path.resolve(process.argv[3]||path.join(os.tmpdir(),'na-browser-evidence'));
const singleFixture=process.argv[4]?path.resolve(process.argv[4]):null;const doubleFixture=process.argv[5]?path.resolve(process.argv[5]):null;
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
if(!fs.existsSync(fixture)||!fs.existsSync(chrome)||singleFixture&&!fs.existsSync(singleFixture)||doubleFixture&&!fs.existsSync(doubleFixture))throw new Error('Fixture HTML or Chrome missing');
fs.mkdirSync(evidence,{recursive:true});const profile=fs.mkdtempSync(path.join(os.tmpdir(),'na-chrome-'));
const labTlsSmoke=process.env.NA_LAB_TLS_SMOKE==='1';
const chromeArgs=['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`];
if(labTlsSmoke)chromeArgs.push('--ignore-certificate-errors'); // Isolated private LAB login-page smoke only.
const child=spawn(chrome,[...chromeArgs,'about:blank'],{stdio:'ignore'});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));let ws,serial=0;const pending=new Map(),exceptions=[];
function command(method,params={}){return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(new Error(`${method} timed out`));}},15000);});}
async function evaluate(expression){const r=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;}
async function waitFor(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await pause(100);}throw new Error(`Timed out: ${expression}`);}
const check=(name,actual,expected)=>{assert.deepEqual(actual,expected,`${name}: ${JSON.stringify(actual)}`);console.log(`PASS ${name}`);};
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);}
async function screenshot(name){const shot=await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(shot.data,'base64'));}
async function layout(){return evaluate(`(()=>{const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
  const overlap=(a,b)=>a.x<b.right-1&&b.x<a.right-1&&a.y<b.bottom-1&&b.y<a.bottom-1;
  const rows=[...document.querySelectorAll('.na-attention__row:not(.is-hidden):not(.is-filtered-out)')];
  const root=rect(document.querySelector('.netops-availability')),content=rect(document.querySelector('.na-content')),
    down=document.querySelector('.na-attention__row.is-down'),neutral=document.querySelector('.na-attention__row.is-visibility_lost'),open=rect(down.querySelector('.na-attention__open')),
    state=rect(down.querySelector('.na-attention__state')),downStyle=getComputedStyle(down),neutralStyle=getComputedStyle(neutral),
    cent=document.querySelector('.na-site[data-site-id="cent"]'),grid=rect(cent.querySelector('.na-site__healthy-grid')),
    problem=rect(cent.querySelector('.na-site__problem-list .na-node.is-problem')),body=rect(cent.querySelector('.na-site__body')),
    healthyRects=[...cent.querySelectorAll('.na-site__healthy-grid .na-node.is-healthy')].map(rect),
    firstY=Math.min(...healthyRects.map(r=>r.y)),search=rect(document.querySelector('.na-search'));
  return {overflow:document.documentElement.scrollWidth>innerWidth+1,
    collision:rows.some(r=>{const name=rect(r.querySelector('.na-attention__name')),
      badges=rect(r.querySelector('.na-attention__badges')),summary=rect(r.querySelector('.na-attention__summary'));
      return overlap(name,badges)||overlap(name,summary)||overlap(badges,summary);}),contentWidth:content.width,
    contentCentered:Math.abs((content.x-root.x)-(root.width-content.width)/2)<2,
    kpiMax:Math.max(...[...document.querySelectorAll('.na-summary__tile')].map(x=>rect(x).width)),
    attentionOpenWidth:open.width,attentionRowWidth:rect(down).width,attentionStateOffset:state.right-rect(down).x,
    downBorder:parseFloat(downStyle.borderLeftWidth),downTint:downStyle.backgroundColor!==neutralStyle.backgroundColor,
    healthyHeights:[...document.querySelectorAll('.na-node.is-healthy')].map(x=>rect(x).height),
    centHealthyCount:healthyRects.length,centColumns:healthyRects.filter(r=>Math.abs(r.y-firstY)<2).length,
    problemBelowGrid:problem.y>=grid.bottom-1,problemFullWidth:Math.abs(problem.width-grid.width)<2,
    siteHeaderGrouped:[...cent.querySelectorAll('.na-site__name,.na-site__count,.na-site__issues')].every(x=>x.closest('.na-site__header')===cent.querySelector('.na-site__header')),
    searchWidth:search.width,bodyWidth:body.width,
    panel:document.querySelector('.na-details-panel').classList.contains('is-hidden')?null:
      (()=>{const p=document.querySelector('.na-details-panel');return {width:p.scrollWidth<=p.clientWidth+1,right:rect(p).right<=innerWidth+1};})()};})()`);}

(async()=>{
  for(let i=0;i<100&&!fs.existsSync(path.join(profile,'DevToolsActivePort'));i++)await pause(100);
  const port=Number(fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').split('\n')[0]);
  const target=(await(await fetch(`http://127.0.0.1:${port}/json`)).json()).find(x=>x.type==='page');assert.ok(target);
  ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);};
  await command('Page.enable');await command('Runtime.enable');await command('Page.navigate',{url:'file:///'+fixture.replaceAll('\\','/')});
  await waitFor('!!document.querySelector(".netops-availability .na-attention__row")');
  check('UP is note, not KPI',await evaluate(`!document.querySelector('.na-summary__tile.is-up') && !!document.querySelector('.na-up-note')`),true);
  check('priority order from real resolver',await evaluate(`[...document.querySelectorAll('.na-attention__row .na-attention__open')].map(x=>x.dataset.nodeId)`),['down','hidden-down','unassigned-down','degraded','unknown']);
  check('tier-unset incident explicit',await evaluate(`document.querySelector('.na-attention__open[data-node-id="unassigned-down"]').textContent.includes('No tier') && document.querySelector('.na-attention__open[data-node-id="unassigned-down"]').textContent.includes('P?')`),true);
  check('hidden outage still attention',await evaluate(`!!document.querySelector('.na-attention__open[data-node-id="hidden-down"]') && getComputedStyle(document.querySelector('.na-node[data-node-id="hidden-down"]')).display==='none'`),true);
  check('unassigned DOWN in attention and neutral section',await evaluate(`!!document.querySelector('.na-attention__open[data-node-id="unassigned-down"]') && !!document.querySelector('.na-unassigned__row[data-node-id="unassigned-down"][data-state="DOWN"]')`),true);
  check('UP partial availability/visibility separated',await evaluate(`(()=>{const n=document.querySelector('.na-node[data-node-id="partial"]');
    const probe=document.createElement('span');probe.style.backgroundColor='var(--green)';n.append(probe);
    const expected=getComputedStyle(probe).backgroundColor;probe.remove();
    return n.dataset.state==='UP'&&n.dataset.visibility==='PARTIAL'&&!!n.querySelector('.na-badge.is-visibility')&&
      getComputedStyle(n.querySelector('.na-state-dot')).backgroundColor===expected;})()`),true);
  check('maintenance and flapping overlays',await evaluate(`!!document.querySelector('.na-node[data-node-id="maint"] .na-badge.is-maintenance')&&!!document.querySelector('.na-node[data-node-id="degraded"] .na-badge.is-flapping')`),true);
  check('healthy single-member row removes redundant signals',await evaluate(`(()=>{const n=document.querySelector('.na-node[data-node-id="cent-rtr-1"]');return !n.textContent.includes('UP')&&n.querySelectorAll('.na-state-dot').length===1&&!n.querySelector('.na-member-glyphs');})()`),true);
  check('7-member summary',await evaluate(`document.querySelector('.na-node[data-node-id="many"] .na-member-glyphs').textContent.includes('7/7 available')`),true);
  check('native acknowledgement action',await evaluate(`(()=>{const b=document.querySelector('.na-attention__row [data-ack-node-id="down"]');b.click();return window.__nativeAck?.action==='acknowledge.edit'&&window.__nativeAck.params.eventids[0]==='7001'&&b.textContent==='Unacknowledged';})()`),true);
  check('affected site starts open',await evaluate(`document.querySelector('.na-site[data-site-id="cent"]').classList.contains('is-open')`),true);
  await click('.na-site[data-site-id="cent"] .na-site__header');check('affected site manual collapse',await evaluate(`document.querySelector('.na-site[data-site-id="cent"]').classList.contains('is-collapsed')`),true);
  await click('.na-site[data-site-id="cent"] .na-site__header');check('affected site reopen',await evaluate(`document.querySelector('.na-site[data-site-id="cent"]').classList.contains('is-open')`),true);
  check('configured site order',await evaluate(`[...document.querySelectorAll('.na-site')].map(s=>s.dataset.siteId)`),['cent','dr','healthy']);
  await click('.na-healthy-chip[data-site-open="healthy"]');
  check('healthy Site expands from compact chip',await evaluate(`document.querySelector('.na-site[data-site-id="healthy"]').classList.contains('is-open')`),true);
  await click('.na-summary__tile[data-filter="DOWN"]');
  check('KPI DOWN filters attention',await evaluate(`[...document.querySelectorAll('.na-attention__row:not(.is-filtered-out)')].every(r=>r.dataset.state==='DOWN')`),true);
  check('KPI DOWN filters nodes',await evaluate(`[...document.querySelectorAll('.na-node:not(.is-filtered-out)')].every(r=>r.dataset.state==='DOWN')`),true);
  check('KPI DOWN filters sites',await evaluate(`document.querySelector('.na-site[data-site-id="healthy"]').classList.contains('is-filtered-out')`),true);
  await click('.na-filter-clear');check('KPI clear restores attention',await evaluate(`document.querySelectorAll('.na-attention__row.is-filtered-out').length`),0);
  await click('.na-summary__tile[data-filter="VISIBILITY_LOSS"]');
  check('KPI visibility loss filters incidents and nodes',await evaluate(`(()=>{const a=[...document.querySelectorAll('.na-attention__row:not(.is-filtered-out)')];const n=[...document.querySelectorAll('.na-node:not(.is-filtered-out)')];return a.length>0&&a.every(r=>r.dataset.visibility==='LOST')&&n.every(r=>r.dataset.visibility==='LOST');})()`),true);
  await click('.na-filter-clear');
  await click('.na-summary__tile[data-filter="IMPACTED_SITES"]');
  check('KPI impacted sites filters operational view',await evaluate(`(()=>{const a=[...document.querySelectorAll('.na-attention__row:not(.is-filtered-out)')];return a.length>0&&a.every(r=>r.dataset.impactedSite==='1')&&document.querySelector('.na-site[data-site-id="healthy"]').classList.contains('is-filtered-out');})()`),true);
  await click('.na-filter-clear');
  await evaluate(`(()=>{const input=document.querySelector('.na-search');input.value='unassigned';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  check('search filters attention and Sites',await evaluate(`document.querySelectorAll('.na-attention__row:not(.is-filtered-out)').length===1 && document.querySelector('.na-site[data-site-id="cent"]').classList.contains('is-filtered-out')`),true);
  await evaluate(`(()=>{const input=document.querySelector('.na-search');input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await click('.na-attention__open[data-node-id="down"]');
  check('Details paired rows',await evaluate(`[...document.querySelectorAll('.na-detail-row')].every(r=>r.querySelectorAll('span').length===1&&r.querySelectorAll('strong').length===1)`),true);
  check('Details selected Node',await evaluate(`document.querySelector('.na-details-panel h3').textContent.includes('Fortigate-DMZ-CENT')`),true);
  await click('.na-details-panel .na-panel-close');check('Details close',await evaluate(`document.querySelector('.na-details-panel').classList.contains('is-hidden')`),true);
  await click('.na-attention__open[data-node-id="unknown"]');check('Details missing/freshness value pairing',await evaluate(`[...document.querySelectorAll('.na-detail-row')].every(r=>r.querySelectorAll('span').length===1&&r.querySelectorAll('strong').length===1)`),true);
  await click('.na-details-panel .na-panel-close');
  for(const theme of ['blue','dark']){
    await evaluate(`document.body.classList.toggle('dark',${theme==='dark'});document.querySelector('.netops-availability').classList.toggle('is-dark-theme',${theme==='dark'})`);
    for(const width of [1200,1440,1920,2200,900,640,420]){
      await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await evaluate('scrollTo(0,0)');await pause(150);
      const d=await layout();check(`${theme} ${width} no overflow`,d.overflow,false);check(`${theme} ${width} no attention collision`,d.collision,false);
      check(`${theme} ${width} content centered`,d.contentCentered,true);check(`${theme} ${width} content max width`,d.contentWidth<=1481,true);
      if(width>=1440){check(`${theme} ${width} KPI controlled width`,d.kpiMax<=165,true);check(`${theme} ${width} cohesive attention width`,d.attentionRowWidth<=1081,true);check(`${theme} ${width} attention state adjacency`,d.attentionStateOffset<=1000,true);check(`${theme} ${width} search controlled width`,d.searchWidth<=481,true);}
      if(width>=1200){check(`${theme} ${width} healthy rows <=34px`,d.healthyHeights.length>0&&d.healthyHeights.every(h=>h<=34),true);}
      check(`${theme} ${width} fixture has eight healthy Site Nodes`,d.centHealthyCount,8);
      check(`${theme} ${width} healthy Site grid columns`,d.centColumns,width>=1440?3:(width>=900?2:1));
      check(`${theme} ${width} affected Node below healthy grid`,d.problemBelowGrid,true);
      check(`${theme} ${width} affected Node full grid width`,d.problemFullWidth,true);
      check(`${theme} ${width} Site header grouped`,d.siteHeaderGrouped,true);
      check(`${theme} ${width} DOWN severity border`,d.downBorder>=4,true);check(`${theme} ${width} DOWN tint differs`,d.downTint,true);
      await click('.na-attention__open[data-node-id="down"]');const p=await layout();check(`${theme} ${width} details contained`,p.panel,{width:true,right:true});
      if(width===2200||width===420)await screenshot(`network-availability-details-${theme}-${width}`);
      await click('.na-details-panel .na-panel-close');
      if([1200,1440,1920,2200,640,420].includes(width)){await evaluate('scrollTo(0,0)');await screenshot(`network-availability-${theme}-${width}`);}
    }
  }
  await command('Emulation.setDeviceMetricsOverride',{width:900,height:900,deviceScaleFactor:1,mobile:false});
  await click('.na-edit-start');check('edit starts clean',await evaluate(`document.querySelector('.na-editor-title h3').textContent.includes('0 unsaved changes')`),true);
  await evaluate(`(()=>{const e=document.querySelector('.na-editor-row input');e.value+='X';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  check('edit real diff increments',await evaluate(`document.querySelector('.na-editor-title h3').textContent.includes('1 unsaved changes')`),true);
  await evaluate(`(()=>{const e=document.querySelector('.na-editor-row input');e.value=e.value.slice(0,-1);e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  check('edit real diff returns zero',await evaluate(`document.querySelector('.na-editor-title h3').textContent.includes('0 unsaved changes')`),true);
  check('explicit not-set tier choice',await evaluate(`(()=>{const d=document.querySelector('.na-node-editor');d.open=true;return [...d.querySelectorAll('select')].some(s=>[...s.options].some(o=>o.value===''&&o.textContent.includes('Not set')));})()`),true);
  await click('.na-editor-title .na-editor-actions button:first-child');check('edit discard',await evaluate(`document.querySelector('.na-editor-panel').classList.contains('is-hidden')`),true);
  await click('.na-edit-start');await evaluate(`(()=>{const e=document.querySelector('.na-editor-row input');e.value='RENAMED SITE';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  for(const width of [1200,900,640,420]){
    await command('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await pause(150);
    check(`editor ${width} controls contained`,await evaluate(`(()=>{const p=document.querySelector('.na-editor-panel'),a=[...p.querySelectorAll('.na-editor-title .na-editor-actions button')],r=p.getBoundingClientRect();return document.documentElement.scrollWidth<=innerWidth+1&&a.every(b=>{const x=b.getBoundingClientRect();return x.left>=r.left&&x.right<=r.right&&x.bottom<=innerHeight;})&&a[0].getBoundingClientRect().right<=a[1].getBoundingClientRect().left;})()`),true);
    if(width===900||width===420)await screenshot(`network-availability-editor-dark-${width}`);
  }
  await click('.na-editor-title .na-editor-actions button:nth-child(2)');await waitFor('!!window.__lastSavedConfig');
  check('edit save actual handler',await evaluate(`window.__lastSavedConfig.sites[0].name`),'RENAMED SITE');
  check('edit save closes',await evaluate(`document.querySelector('.na-editor-panel').classList.contains('is-hidden')`),true);
  if(singleFixture&&doubleFixture){
    await command('Page.navigate',{url:'file:///'+singleFixture.replaceAll('\\','/')});await waitFor('!!document.querySelector(".na-section-count")');
    check('singular incident grammar',await evaluate(`document.querySelector('.na-section-count').textContent`),'1 item');
    await command('Page.navigate',{url:'file:///'+doubleFixture.replaceAll('\\','/')});await waitFor('!!document.querySelector(".na-section-count")');
    check('plural incident grammar',await evaluate(`document.querySelector('.na-section-count').textContent`),'2 items');
  }
  check('uncaught browser exceptions',exceptions,[]);
  if(labTlsSmoke){
    await command('Page.navigate',{url:'https://192.168.1.91:8443/'});
    await waitFor('!!document.querySelector("input[type=password]")');
    check('isolated LAB TLS browser login page',await evaluate(`document.location.host==='192.168.1.91:8443'`),true);
  }
  console.log('BROWSER=PASS EVIDENCE='+evidence);
})().catch(e=>{console.error('BROWSER=FAIL',e.stack||e);process.exitCode=1;}).finally(()=>{try{ws?.close();child.kill();}catch{}});
