class CWidgetNetworkUtilization extends CWidget {
	#filter = '';
	#search = '';
	#site = '';
	#role = '';
	#sort = 'current';
	#detailsLinkId = '';
	#editing = false;
	#workingConfig = null;
	#unsavedChanges = 0;
	#lastSuccessfulUpdate = 0;
	#staleTimer = null;
	#snapshot = null;
	#configuration = null;
	#candidates = [];

	onStart() { this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000); }
	onActivate() { if (this.#staleTimer === null) this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000); }
	onDeactivate() { if (this.#staleTimer !== null) clearInterval(this.#staleTimer); this.#staleTimer = null; }

	setContents(response) {
		if (this.#editing) return;
		const scrollTop = this._contents.scrollTop;
		super.setContents(response);
		const root = this._contents.querySelector('.netops-utilization');
		if (root === null || !root.dataset.snapshot) return;
		this.#lastSuccessfulUpdate = Date.now();
		this.#snapshot = this.#decode(root.dataset.snapshot);
		this.#configuration = this.#decode(root.dataset.configuration);
		this.#candidates = this.#decode(root.dataset.candidates);
		root.classList.toggle('is-dark-theme', [...document.querySelectorAll('link[rel="stylesheet"]')]
			.some(link => /(?:dark-theme|hc-dark)\.css(?:\?|$)/.test(link.href)));
		this.#populateFilters(root);
		this.#bind(root);
		this.#applyContext(root);
		this._contents.scrollTop = scrollTop;
		this.#updateViewFreshness();
	}

	#decode(value) {
		return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(value), character => character.charCodeAt(0))));
	}

	#populateFilters(root) {
		const site = root.querySelector('.nu-site-filter');
		for (const value of this.#configuration.sites) site.append(this.#option(value.id, value.name));
		const role = root.querySelector('.nu-role-filter');
		for (const value of [...new Set(this.#configuration.links.map(link => link.role))].sort()) role.append(this.#option(value, value.replaceAll('_', ' ')));
	}

	#bind(root) {
		root.querySelector('.nu-search')?.addEventListener('input', event => { this.#search = event.target.value.trim().toLowerCase(); this.#applyFilters(root); });
		root.querySelector('.nu-site-filter')?.addEventListener('change', event => { this.#site = event.target.value; this.#applyFilters(root); });
		root.querySelector('.nu-role-filter')?.addEventListener('change', event => { this.#role = event.target.value; this.#applyFilters(root); });
		for (const tile of root.querySelectorAll('.nu-summary__item')) tile.addEventListener('click', () => {
			this.#filter = this.#filter === tile.dataset.filter ? '' : tile.dataset.filter; this.#applyFilters(root);
		});
		root.querySelector('.nu-filter-clear')?.addEventListener('click', () => { this.#filter = ''; this.#applyFilters(root); });
		for (const button of root.querySelectorAll('[data-sort]')) button.addEventListener('click', () => { this.#sort = button.dataset.sort; this.#sortRows(root); });
		for (const element of root.querySelectorAll('[data-link-id]')) element.addEventListener('click', event => {
			if (element.dataset.linkId !== '') { event.stopPropagation(); this.#openDetails(root, element.dataset.linkId); }
		});
		for (const site of root.querySelectorAll('.nu-site')) site.querySelector('.nu-site__header')?.addEventListener('click', () => site.classList.toggle('is-collapsed'));
		root.querySelector('.nu-panel-backdrop')?.addEventListener('click', () => { if (!this.#editing) this.#closePanels(root); });
		root.querySelector('.nu-edit-start')?.addEventListener('click', () => this.#beginEdit(root));
		if (this.isEditMode()) root.querySelector('.nu-edit-start')?.setAttribute('disabled', 'disabled');
	}

	#applyContext(root) {
		root.querySelector('.nu-search').value = this.#search;
		root.querySelector('.nu-site-filter').value = this.#site;
		root.querySelector('.nu-role-filter').value = this.#role;
		this.#applyFilters(root); this.#sortRows(root);
		if (this.#detailsLinkId !== '') this.#openDetails(root, this.#detailsLinkId);
	}

	#applyFilters(root) {
		for (const tile of root.querySelectorAll('.nu-summary__item')) tile.setAttribute('aria-pressed', tile.dataset.filter === this.#filter ? 'true' : 'false');
		const chip = root.querySelector('.nu-filter-chip'); chip?.classList.toggle('is-hidden', this.#filter === '');
		if (chip && this.#filter) chip.querySelector('.nu-filter-label').textContent = `Filtered: ${this.#filter.replaceAll('_', ' ')}`;
		for (const row of root.querySelectorAll('.nu-table tbody tr')) {
			const link = this.#findLink(row.dataset.linkId);
			const searchMatch = !this.#search || (row.dataset.search ?? '').includes(this.#search);
			const siteMatch = !this.#site || row.dataset.site === this.#site;
			const roleMatch = !this.#role || row.dataset.role === this.#role;
			let stateMatch = true;
			if (link && this.#filter) {
				if (this.#filter === 'HOT_NOW') stateMatch = link.worst_util_pct !== null && link.worst_util_pct >= link.warning_util_pct;
				else if (this.#filter === 'SUSTAINED') stateMatch = link.sustained;
				else if (this.#filter === 'ERRORS_DISCARDS') stateMatch = link.errors_total > 0 || link.discards_total > 0;
				else if (this.#filter === 'CAPACITY_RISK') stateMatch = link.p95_worst_pct !== null && link.p95_worst_pct >= this.#configuration.settings.capacity_risk_p95_pct;
				else if (this.#filter === 'UNKNOWN_STALE') stateMatch = link.data_state !== 'CURRENT' || link.capacity_bps === null || link.mapping_issue !== null;
			}
			row.classList.toggle('is-filtered-out', !(searchMatch && siteMatch && roleMatch && stateMatch));
		}
		for (const element of root.querySelectorAll('.nu-site-link')) {
			const link = this.#findLink(element.dataset.linkId); if (!link) continue;
			const search = `${link.display_name} ${link.host} ${link.interface.if_name} ${link.site}`.toLowerCase();
			const matches = (!this.#search || search.includes(this.#search)) && (!this.#site || link.site_id === this.#site)
				&& (!this.#role || link.role === this.#role);
			element.classList.toggle('is-filtered-out', !matches);
		}
		for (const site of root.querySelectorAll('.nu-site')) site.classList.toggle('is-filtered-out', ![...site.querySelectorAll('.nu-site-link')].some(link => !link.classList.contains('is-filtered-out')));
	}

	#sortRows(root) {
		for (const button of root.querySelectorAll('[data-sort]')) button.classList.toggle('is-active', button.dataset.sort === this.#sort);
		const body = root.querySelector('.nu-table tbody'); if (!body) return;
		const ascending = this.#sort === 'headroom';
		const rows = [...body.children];
		rows.sort((a, b) => {
			const av = Number(a.dataset[this.#sort] ?? -1); const bv = Number(b.dataset[this.#sort] ?? -1);
			if (av !== bv) return ascending ? av - bv : bv - av;
			return a.dataset.linkId.localeCompare(b.dataset.linkId);
		});
		for (const row of rows) body.append(row);
	}

	#findLink(id) { return this.#snapshot.links.find(link => link.id === id) ?? null; }

	#openDetails(root, linkId) {
		const link = this.#findLink(linkId); if (!link) return;
		this.#detailsLinkId = linkId;
		const panel = root.querySelector('.nu-panel'); panel.replaceChildren();
		panel.append(this.#button('×', 'nu-panel-close', () => this.#closePanels(root)), this.#element('h3', link.display_name));
		const fields = [
			['Site', link.site], ['Device', link.host_name], ['Interface', link.interface.if_name], ['Alias', link.current_alias || link.interface.if_alias || '—'],
			['Role', link.role.replaceAll('_', ' ')], ['Admin', link.admin_status], ['Operational', link.oper_status], ['Data freshness', link.data_age_s >= 2147483647 ? 'No data' : this.#formatAge(link.data_age_s)],
			['Capacity', `${this.#formatBps(link.capacity_bps)}${link.capacity_source === 'override' ? ' (override)' : ''}`],
			['CURRENT IN', this.#metric(link.current_in_bps, link.in_util_pct)], ['CURRENT OUT', this.#metric(link.current_out_bps, link.out_util_pct)],
			['P95 24H IN', this.#metric(link.p95_in_bps, link.p95_in_pct)], ['P95 24H OUT', this.#metric(link.p95_out_bps, link.p95_out_pct)],
			['PEAK 24H', this.#formatBps(link.peak_bps)], ['Headroom', this.#formatBps(link.headroom_bps)],
			['Sustained high', link.sustained ? this.#formatDuration(link.sustained_seconds) : 'No'],
			['Errors', String(link.errors_total)], ['Discards', String(link.discards_total)]
		];
		if (link.mapping_issue) fields.unshift(['Configuration', link.mapping_issue]);
		for (const [label, value] of fields) { const row = this.#element('div', '', 'nu-detail-row'); row.append(this.#element('span', label), this.#element('strong', value)); panel.append(row); }
		panel.append(this.#element('h4', 'Traffic trend'));
		panel.append(this.#trendPanel(link));
		const links = this.#element('div', '', 'nu-detail-links');
		if (link.hostid) {
			links.append(this.#link('Latest data', `zabbix.php?action=latest.view&filter_set=1&hostids%5B%5D=${encodeURIComponent(link.hostid)}`),
				this.#link('Problems', `zabbix.php?action=problem.view&filter_set=1&hostids%5B%5D=${encodeURIComponent(link.hostid)}`),
				this.#link('Host dashboard', `zabbix.php?action=host.dashboard.view&hostid=${encodeURIComponent(link.hostid)}`));
		}
		panel.append(links); panel.classList.remove('is-hidden'); root.querySelector('.nu-panel-backdrop').classList.remove('is-hidden');
	}

	#sparkline(inRows, outRows) {
		const box = this.#element('div', '', 'nu-sparkline');
		const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 300 70'); svg.setAttribute('role', 'img');
		const all = [...inRows, ...outRows]; const minClock = Math.min(...all.map(row => row.clock), Date.now() / 1000); const maxClock = Math.max(...all.map(row => row.clock), minClock + 1); const maxValue = Math.max(...all.map(row => Number(row.value)), 1);
		const make = (rows, className) => { const line = document.createElementNS(svg.namespaceURI, 'polyline'); line.setAttribute('class', className); line.setAttribute('points', rows.map(row => `${300 * (row.clock - minClock) / (maxClock - minClock)},${68 - 64 * Number(row.value) / maxValue}`).join(' ')); return line; };
		if (inRows.length) svg.append(make(inRows, 'is-in')); if (outRows.length) svg.append(make(outRows, 'is-out'));
		box.append(svg, this.#element('span', 'IN', 'nu-legend-in'), this.#element('span', 'OUT', 'nu-legend-out'));
		return box;
	}

	#trendPanel(link) {
		const panel = this.#element('div', '', 'nu-trend-panel'); const controls = this.#element('div', '', 'nu-trend-controls'); const chart = this.#element('div');
		const render = hours => {
			const cutoff = Date.now() / 1000 - hours * 3600;
			const source = hours === 168 ? 'trends_7d' : 'history';
			const incoming = (link.metrics.in?.[source] ?? []).filter(row => row.clock >= cutoff);
			const outgoing = (link.metrics.out?.[source] ?? []).filter(row => row.clock >= cutoff);
			chart.replaceChildren(this.#sparkline(incoming, outgoing));
			for (const button of controls.children) button.classList.toggle('is-active', Number(button.dataset.hours) === hours);
		};
		for (const [hours, label] of [[1, '1h'], [6, '6h'], [24, '24h'], [168, '7d']]) {
			const button = this.#button(label, 'btn-alt', () => render(hours)); button.dataset.hours = String(hours); controls.append(button);
		}
		panel.append(controls, chart); render(1); return panel;
	}

	#beginEdit(root) {
		if (this.isEditMode() || root.dataset.canEdit !== '1') return;
		this.#editing = true; this.#workingConfig = structuredClone(this.#configuration); this.#unsavedChanges = 0;
		this._pauseUpdating(); root.classList.add('is-editing'); this.#renderEditor(root);
	}

	#renderEditor(root) {
		const panel = root.querySelector('.nu-editor'); panel.replaceChildren();
		panel.append(this.#element('h3', `Edit links · ${this.#unsavedChanges} unsaved changes`));
		const actions = this.#element('div', '', 'nu-editor-actions'); actions.append(
			this.#button('Add site', 'btn-alt', () => this.#addSite(root)), this.#button('Add link', 'btn-alt', () => this.#addLink(root)),
			this.#button('Discard', 'btn-alt', () => this.#discardEdit(root)), this.#button('Save', 'btn', () => this.#saveWorking(root)));
		panel.append(actions, this.#element('h4', 'Sites'));
		this.#workingConfig.sites.forEach((site, index) => {
			const row = this.#element('div', '', 'nu-editor-row'); const name = this.#input(site.name, 'Site name');
			name.addEventListener('input', () => { site.name = name.value; this.#dirty(root); });
			row.append(name, this.#button('↑', 'btn-icon', () => this.#move(this.#workingConfig.sites, index, -1, root)), this.#button('↓', 'btn-icon', () => this.#move(this.#workingConfig.sites, index, 1, root)),
				this.#button('Delete', 'btn-link', () => { if (this.#workingConfig.links.some(link => link.site_id === site.id)) return this.#error(panel, 'Move or delete this Site’s Links first.'); this.#workingConfig.sites.splice(index, 1); this.#dirty(root, true); })); panel.append(row);
		});
		panel.append(this.#element('h4', 'Configured links'));
		this.#workingConfig.links.forEach((link, index) => panel.append(this.#linkEditor(root, link, index)));
		panel.append(this.#element('p', 'Hidden Links remain monitored and counted. Stable identity is Host + interface name; current ifIndex is resolved at runtime.', 'nu-editor-note'));
		panel.classList.remove('is-hidden'); root.querySelector('.nu-panel-backdrop').classList.remove('is-hidden');
	}

	#linkEditor(root, link, index) {
		const box = this.#element('details', '', 'nu-link-editor'); box.append(this.#element('summary', `${link.display_name} · ${link.host} / ${link.interface.if_name}`));
		const fields = this.#element('div', '', 'nu-editor-fields');
		const name = this.#input(link.display_name, 'Display name'); name.addEventListener('input', () => { link.display_name = name.value; this.#dirty(root); });
		const capacity = this.#input(link.capacity_override_bps ? String(link.capacity_override_bps) : '', 'Optional bits per second', 'number'); capacity.min = '1'; capacity.addEventListener('input', () => { link.capacity_override_bps = capacity.value === '' ? null : Number(capacity.value); this.#dirty(root); });
		const warning = this.#input(link.warning_util_pct ?? '', 'Use global default', 'number'); warning.min = '1'; warning.max = '100'; warning.addEventListener('input', () => { link.warning_util_pct = warning.value === '' ? null : Number(warning.value); this.#dirty(root); });
		const critical = this.#input(link.critical_util_pct ?? '', 'Use global default', 'number'); critical.min = '1'; critical.max = '100'; critical.addEventListener('input', () => { link.critical_util_pct = critical.value === '' ? null : Number(critical.value); this.#dirty(root); });
		const visible = document.createElement('input'); visible.type = 'checkbox'; visible.checked = Boolean(link.visible); visible.addEventListener('change', () => { link.visible = visible.checked; this.#dirty(root); });
		fields.append(this.#label('Display name', name), this.#label('Site', this.#select(this.#workingConfig.sites.map(site => [site.id, site.name]), link.site_id, value => { link.site_id = value; this.#dirty(root); })),
			this.#label('Role', this.#select(this.#roles().map(role => [role, role.replaceAll('_', ' ')]), link.role, value => { link.role = value; this.#dirty(root); })),
			this.#label('Capacity override (bps)', capacity), this.#label('Warning % override', warning), this.#label('Critical % override', critical), this.#label('Visible', visible));
		box.append(fields);
		const actions = this.#element('div', '', 'nu-editor-actions'); actions.append(this.#button('↑', 'btn-icon', () => this.#move(this.#workingConfig.links, index, -1, root)), this.#button('↓', 'btn-icon', () => this.#move(this.#workingConfig.links, index, 1, root)), this.#button('Delete link', 'btn-link', () => { this.#workingConfig.links.splice(index, 1); this.#dirty(root, true); })); box.append(actions); return box;
	}

	#addSite(root) { this.#workingConfig.sites.push({id: `site-${Date.now()}`, name: 'New Site', order: this.#workingConfig.sites.length * 10}); this.#dirty(root, true); }

	#addLink(root) {
		const panel = root.querySelector('.nu-editor'); if (this.#workingConfig.sites.length === 0) this.#addSite(root);
		panel.querySelector('.nu-add-link')?.remove();
		const box = this.#element('div', '', 'nu-add-link'); box.append(this.#element('h4', 'Quick add link'));
		const hostValues = [...new Map(this.#candidates.map(candidate => [candidate.host, candidate.host_name])).entries()];
		let host = hostValues[0]?.[0] ?? ''; let selected = null;
		const hostSelect = this.#select(hostValues, host, value => { host = value; rebuildInterfaces(); });
		const interfaceSelect = document.createElement('select'); const preview = this.#element('div', 'Select an interface', 'nu-candidate-preview');
		const display = this.#input('', 'Display name'); let siteId = this.#workingConfig.sites[0]?.id ?? ''; let role = 'UPLINK';
		const siteSelect = this.#select(this.#workingConfig.sites.map(site => [site.id, site.name]), siteId, value => { siteId = value; });
		const roleSelect = this.#select(this.#roles().map(value => [value, value.replaceAll('_', ' ')]), role, value => { role = value; });
		const capacity = this.#input('', 'Optional bits per second', 'number'); capacity.min = '1';
		const rebuildInterfaces = () => {
			interfaceSelect.replaceChildren(); const rows = this.#candidates.filter(candidate => candidate.host === host).sort((a, b) => a.if_name.localeCompare(b.if_name));
			for (const candidate of rows) interfaceSelect.append(this.#option(candidate.if_name, `${candidate.if_name}${candidate.if_alias ? ` · ${candidate.if_alias}` : ''}`));
			const update = () => { selected = rows.find(candidate => candidate.if_name === interfaceSelect.value) ?? null; if (selected) { if (!display.value) display.value = selected.if_name; preview.textContent = `${selected.if_alias || 'No alias'} · Capacity ${this.#formatBps(selected.capacity_bps)} · Status ${selected.oper_status ?? 'unknown'} · ${selected.metric_types.join(', ')}`; } };
			interfaceSelect.onchange = update; update();
		};
		box.append(this.#label('1. Host', hostSelect), this.#label('2. Interface', interfaceSelect), preview, this.#label('3. Display name', display), this.#label('Site', siteSelect), this.#label('Role', roleSelect), this.#label('Capacity override (bps, optional)', capacity));
		box.append(this.#button('Add to working copy', 'btn', () => {
			if (!selected || !display.value.trim()) return this.#error(panel, 'Host, interface and display name are required.');
			if (this.#workingConfig.links.some(link => link.host === selected.host && link.interface.if_name === selected.if_name)) return this.#error(panel, 'That Host/interface is already configured.');
			this.#workingConfig.links.push({id: `link-${this.#slug(selected.host)}-${this.#slug(selected.if_name)}-${Date.now()}`, display_name: display.value.trim(), site_id: siteId, host: selected.host,
				interface: {if_name: selected.if_name, if_alias: selected.if_alias || '', if_descr: ''}, role, order: this.#workingConfig.links.length * 10, visible: true, required: true,
				capacity_override_bps: capacity.value === '' ? null : Number(capacity.value)}); this.#dirty(root, true);
		})); rebuildInterfaces(); panel.insertBefore(box, panel.querySelector('h4:nth-of-type(2)'));
	}

	#move(items, index, delta, root) { const target = index + delta; if (target < 0 || target >= items.length) return; [items[index], items[target]] = [items[target], items[index]]; this.#dirty(root, true); }
	#dirty(root, rerender = false) { this.#unsavedChanges++; this.#workingConfig.sites.forEach((site, index) => site.order = index * 10); this.#workingConfig.links.forEach((link, index) => link.order = index * 10); if (rerender) this.#renderEditor(root); else root.querySelector('.nu-editor h3').textContent = `Edit links · ${this.#unsavedChanges} unsaved changes`; }
	#discardEdit(root) { this.#editing = false; this.#workingConfig = null; this.#unsavedChanges = 0; root.classList.remove('is-editing'); this.#closePanels(root); this._resumeUpdating(); this._startUpdating({delay_sec: 0}); }

	async #saveWorking(root) {
		const panel = root.querySelector('.nu-editor'); for (const item of panel.querySelectorAll('.nu-editor-error')) item.remove();
		try {
			const curl = new Curl('zabbix.php'); curl.setArgument('action', 'networkutilization.config.update');
			const response = await fetch(curl.getUrl(), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({payload: JSON.stringify(this.#workingConfig), expected_revision: this.#workingConfig.revision, [CSRF_TOKEN_NAME]: root.dataset.csrfToken})});
			const result = await response.json(); if (result.error) throw new Error(result.error.messages.join(' ')); this.#configuration = result.configuration; this.#discardEdit(root);
		}
		catch (error) { this.#error(panel, error.message || 'Configuration save failed.'); }
	}

	#closePanels(root) { this.#detailsLinkId = ''; root.querySelector('.nu-panel')?.classList.add('is-hidden'); root.querySelector('.nu-editor')?.classList.add('is-hidden'); root.querySelector('.nu-panel-backdrop')?.classList.add('is-hidden'); }
	#updateViewFreshness() { const root = this._contents?.querySelector('.netops-utilization'); if (!root || this.#lastSuccessfulUpdate === 0 || this.#editing) return; const age = Date.now() - this.#lastSuccessfulUpdate; const stale = age > Math.max(30000, Number(root.dataset.refreshSeconds ?? 60) * 2000); root.classList.toggle('is-view-stale', stale); root.querySelector('.nu-stale')?.classList.toggle('is-hidden', !stale); if (stale) root.querySelector('.nu-stale__age').textContent = this.#formatAge(Math.floor(age / 1000)); }
	#formatAge(seconds) { return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago` : seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s ago` : `${seconds}s ago`; }
	#formatDuration(seconds) { return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m` : `${Math.floor(seconds / 60)}m`; }
	#formatBps(value) { if (value === null || value === undefined) return 'Unknown'; for (const [scale, unit] of [[1e9, 'Gbps'], [1e6, 'Mbps'], [1e3, 'Kbps'], [1, 'bps']]) if (value >= scale) return `${Number(value / scale).toLocaleString(undefined, {maximumFractionDigits: value / scale >= 100 ? 0 : 2})} ${unit}`; return '0 bps'; }
	#metric(bps, pct) { return pct === null ? this.#formatBps(bps) : `${Number(pct).toFixed(1)}% · ${this.#formatBps(bps)}`; }
	#roles() { return ['WAN', 'ISP', 'DCI', 'CORE', 'UPLINK', 'FIREWALL', 'LOAD_BALANCER', 'SERVER', 'ACCESS', 'OTHER']; }
	#slug(value) { return value.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'link'; }
	#element(tag, text = '', className = '') { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
	#button(text, className, handler) { const button = this.#element('button', text, className); button.type = 'button'; button.addEventListener('click', handler); return button; }
	#link(text, href) { const link = this.#element('a', text); link.href = href; return link; }
	#input(value, placeholder, type = 'text') { const input = document.createElement('input'); input.type = type; input.value = value ?? ''; input.placeholder = placeholder; return input; }
	#label(text, control) { const label = this.#element('label', '', 'nu-editor-label'); label.append(this.#element('span', text), control); return label; }
	#option(value, label) { const option = document.createElement('option'); option.value = value; option.textContent = label; return option; }
	#select(options, selected, handler) { const select = document.createElement('select'); for (const [value, label] of options) { const option = this.#option(value, label); option.selected = value === selected; select.append(option); } select.addEventListener('change', () => handler(select.value)); return select; }
	#error(panel, message) { panel.prepend(this.#element('div', message, 'nu-editor-error')); }
}
