class CWidgetDeviceHealth extends CWidget {
	#snapshot=null;#lastUpdate=0;#timer=null;#filter='';
	setContents(response){super.setContents(response);const root=this._contents?.querySelector('.netops-device-health');if(!root)return;this.#snapshot=this.#decode(root.dataset.snapshot);this.#lastUpdate=Date.now();this.#bind(root);clearInterval(this.#timer);this.#timer=setInterval(()=>this.#freshness(root),5000);}
	onClearContents(){clearInterval(this.#timer);this.#timer=null;super.onClearContents?.();}
	#bind(root){const search=root.querySelector('.dh-search'),site=root.querySelector('.dh-site-filter'),sort=root.querySelector('.dh-sort');
		search?.addEventListener('input',()=>this.#apply(root));site?.addEventListener('change',()=>this.#apply(root));sort?.addEventListener('change',()=>this.#apply(root));
		for(const button of root.querySelectorAll('[data-summary-filter]'))button.addEventListener('click',()=>{this.#filter=this.#filter===button.dataset.summaryFilter?'':button.dataset.summaryFilter;for(const b of root.querySelectorAll('[data-summary-filter]')){const active=b.dataset.summaryFilter===this.#filter;b.classList.toggle('is-selected',active);b.setAttribute('aria-pressed',String(active));}this.#apply(root);});
		for(const button of root.querySelectorAll('.dh-site__header'))button.addEventListener('click',()=>{const siteBox=button.closest('.dh-site'),collapsed=siteBox.classList.toggle('is-collapsed');button.setAttribute('aria-expanded',String(!collapsed));});
		for(const button of root.querySelectorAll('[data-device-details]'))button.addEventListener('click',event=>{event.stopPropagation();this.#details(root,button.dataset.deviceDetails);});
		root.querySelector('.dh-panel-backdrop')?.addEventListener('click',()=>this.#close(root));
	}
	#apply(root){const q=root.querySelector('.dh-search')?.value.trim().toLowerCase()??'',site=root.querySelector('.dh-site-filter')?.value??'',sort=root.querySelector('.dh-sort')?.value??'configured';
		for(const tr of root.querySelectorAll('tbody tr')){const device=this.#find(tr.dataset.deviceId),match=tr.dataset.search.includes(q)&&(!site||tr.dataset.siteName===site)&&this.#summaryMatch(device,this.#filter);tr.hidden=!match;}
		for(const tbody of root.querySelectorAll('tbody')){const rows=[...tbody.querySelectorAll('tr')];rows.sort((a,b)=>this.#compare(this.#find(a.dataset.deviceId),this.#find(b.dataset.deviceId),sort));for(const row of rows)tbody.append(row);}
		for(const box of root.querySelectorAll('.dh-site'))box.hidden=![...box.querySelectorAll('tbody tr')].some(row=>!row.hidden);
	}
	#compare(a,b,sort){if(sort==='configured')return Number(a.hostid)-Number(b.hostid);let av,bv;if(sort==='severity'){av=a.severity;bv=b.severity;}else{av=a.columns[sort]?.value??-Infinity;bv=b.columns[sort]?.value??-Infinity;}return bv-av||a.name.localeCompare(b.name);}
	#summaryMatch(d,f){if(!f)return true;if(f==='CRITICAL')return d.state==='CRITICAL';if(f==='WARNING')return d.state==='WARNING';if(f==='UNKNOWN_STALE')return d.state==='UNKNOWN';const cats=f==='RESOURCE'?['cpu','memory','storage']:f==='HARDWARE'?['temperature','power_fan']:['ha'];return cats.some(c=>d.columns[c]?.severity>0);}
	#details(root,id){const d=this.#find(id),panel=root.querySelector('.dh-details');if(!d||!panel)return;panel.replaceChildren();panel.append(this.#button('×','dh-panel-close',()=>this.#close(root)),this.#el('h3',d.name),this.#el('p',`${d.site} · ${d.host}`,'dh-detail-meta'));
		this.#section(panel,'Identity',[['Capability profile',d.profile==='unknown'?'Not mapped':d.profile.replaceAll('_',' ')],['Profile status',d.profile_status],['Availability',d.availability],['Maintenance',d.maintenance?'Yes':'No']]);
		for(const [key,label] of Object.entries({cpu:'CPU',memory:'Memory',temperature:'Temperature',storage:'Storage',power_fan:'Power / Fan',ha:'HA'})){const m=d.columns[key];const rows=[['State',m.data_state],['Current',this.#metric(m)]];this.#section(panel,label,rows);for(const item of m.details??[]){const sub=this.#el('div','', 'dh-detail-item');sub.append(this.#el('strong',item.mount??item.name),this.#el('span',`${item.value}${item.units?' '+item.units:''} · ${item.freshness.state}`));panel.append(sub);}}
		if(d.issues.length){this.#section(panel,'Active Zabbix problems',d.issues.map(i=>[i.name,`${this.#severity(i.severity)} · ${i.acknowledged?'Acknowledged':'Unacknowledged'}`]));}
		panel.classList.remove('is-hidden');root.querySelector('.dh-panel-backdrop').classList.remove('is-hidden');
	}
	#metric(m){if(m.data_state==='NOT_APPLICABLE')return '—';if(m.data_state!=='CURRENT')return m.data_state;if(m.value===null)return '—';return `${Number(m.value).toLocaleString(undefined,{maximumFractionDigits:1})}${m.units?' '+m.units:''}`;}
	#section(panel,title,rows){panel.append(this.#el('h4',title));const group=this.#el('div','', 'dh-detail-group');for(const [label,value] of rows){const row=this.#el('div','', 'dh-detail-row');row.append(this.#el('span',label),this.#el('strong',String(value)));group.append(row);}panel.append(group);}
	#close(root){root.querySelector('.dh-details')?.classList.add('is-hidden');root.querySelector('.dh-panel-backdrop')?.classList.add('is-hidden');}
	#find(id){return this.#snapshot.devices.find(d=>String(d.hostid)===String(id));}
	#freshness(root){const age=Math.floor((Date.now()-this.#lastUpdate)/1000),stale=age>Math.max(20,Number(root.dataset.refreshSeconds||30)*2);root.classList.toggle('is-view-stale',stale);const banner=root.querySelector('.dh-self-stale');banner?.classList.toggle('is-hidden',!stale);if(stale)banner.querySelector('.dh-self-stale__age').textContent=`Last update ${age}s ago`;root.querySelector('.dh-updated').textContent=age<5?'Updated just now':`Updated ${age}s ago`;}
	#severity(n){return ['Not classified','Information','Warning','Average','High','Disaster'][n]??'Unknown';}
	#decode(v){try{return JSON.parse(decodeURIComponent(escape(atob(v))));}catch{return {devices:[]};}}
	#el(tag,text='',cls=''){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;}
	#button(text,cls,fn){const b=this.#el('button',text,cls);b.type='button';b.addEventListener('click',fn);return b;}
}
