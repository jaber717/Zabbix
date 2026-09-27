class CWidgetNetworkUtilization extends CWidget {
	#filter = '';
	#search = '';
	#site = '';
	#role = '';
	#sort = 'configured';
	#sortDirection = 'asc';
	#detailsLinkId = '';
	#editing = false;
	#workingConfig = null;
	#unsavedChanges = 0;
	#lastSuccessfulUpdate = 0;
	#staleTimer = null;
	#snapshot = null;
	#configuration = null;
	#candidates = [];
	#detailChart = null;
	#pinnedCharts = new Map();
	#chartRange = 1;
	#capacityValidators = [];

	onStart() { this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000); }
	onActivate() { if (this.#staleTimer === null) this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000); }
	onDeactivate() { if (this.#staleTimer !== null) clearInterval(this.#staleTimer); this.#staleTimer = null; }

	setContents(response) {
		if (this.#editing) return;
		this.#closeCharts();
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
		this.#renderPinnedGraphs(root);
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
		root.querySelector('.nu-more')?.addEventListener('click', event => {
			const rows = root.querySelectorAll('.nu-attention__row.is-extra');
			const show = rows[0]?.classList.contains('is-hidden');
			for (const row of rows) row.classList.toggle('is-hidden', !show);
			event.currentTarget.textContent = show ? 'Show less' : `+${rows.length} more`;
		});
		for (const button of root.querySelectorAll('[data-sort]')) button.addEventListener('click', () => {
			if (this.#sort === button.dataset.sort) this.#sortDirection = this.#sortDirection === 'desc' ? 'asc' : 'desc';
			else { this.#sort = button.dataset.sort; this.#sortDirection = 'desc'; }
			this.#sortRows(root);
		});
		for (const button of root.querySelectorAll('[data-global-hours]')) button.addEventListener('click', () => this.#setGlobalRange(root, Number(button.dataset.globalHours)));
		for (const element of root.querySelectorAll('[data-details-link-id]')) element.addEventListener('click', event => {
			event.stopPropagation(); this.#openDetails(root, element.dataset.detailsLinkId);
		});
		for (const button of root.querySelectorAll('[data-graph-toggle]')) button.addEventListener('click', event => {
			event.stopPropagation(); this.#changeGraph(root, button.dataset.linkId, button.dataset.graphToggle);
		});
		for (const button of root.querySelectorAll('[data-graph-remove]')) button.addEventListener('click', () => this.#changeGraph(root, button.dataset.graphRemove, 'remove'));
		for (const button of root.querySelectorAll('[data-graph-move]')) button.addEventListener('click', () => {
			const card = button.closest('[data-graph-link-id]'); this.#changeGraph(root, card.dataset.graphLinkId, button.dataset.graphMove);
		});
		root.querySelector('.nu-panel-backdrop')?.addEventListener('click', () => { if (!this.#editing) this.#closePanels(root); });
		root.querySelector('.nu-edit-start')?.addEventListener('click', () => this.#beginEdit(root));
		if (this.isEditMode()) root.querySelector('.nu-edit-start')?.setAttribute('disabled', 'disabled');
	}

	#applyContext(root) {
		root.querySelector('.nu-updated').textContent = `Updated ${new Intl.DateTimeFormat(undefined, {hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(new Date(this.#snapshot.generated_at * 1000))}`;
		root.querySelector('.nu-search').value = this.#search;
		root.querySelector('.nu-site-filter').value = this.#site;
		root.querySelector('.nu-role-filter').value = this.#role;
		this.#applyFilters(root); this.#sortRows(root);
		this.#setGlobalRange(root, this.#chartRange);
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
				else if (this.#filter === 'UNKNOWN_STALE') stateMatch = link.data_state !== 'CURRENT' || link.capacity_in_bps === null || link.capacity_out_bps === null || link.mapping_issue !== null;
			}
			row.classList.toggle('is-filtered-out', !(searchMatch && siteMatch && roleMatch && stateMatch));
		}
	}

	#sortRows(root) {
		for (const button of root.querySelectorAll('[data-sort]')) {
			const active = button.dataset.sort === this.#sort;
			button.classList.toggle('is-active', active);
			button.setAttribute('aria-pressed', active ? 'true' : 'false');
			button.querySelector('.nu-sort-direction').textContent = active ? (this.#sortDirection === 'desc' ? '↓' : '↑') : '';
		}
		const body = root.querySelector('.nu-table tbody'); if (!body) return;
		const rows = [...body.children];
		rows.sort((a, b) => {
			const av = Number(a.dataset[this.#sort]); const bv = Number(b.dataset[this.#sort]);
			const aMissing = !Number.isFinite(av) || a.dataset[this.#sort] === '';
			const bMissing = !Number.isFinite(bv) || b.dataset[this.#sort] === '';
			if (aMissing !== bMissing) return aMissing ? 1 : -1;
			if (!aMissing && av !== bv) return this.#sortDirection === 'desc' ? bv - av : av - bv;
			return a.dataset.linkId.localeCompare(b.dataset.linkId);
		});
		for (const row of rows) body.append(row);
	}

	#findLink(id) { return this.#snapshot.links.find(link => link.id === id) ?? null; }

	#openDetails(root, linkId) {
		const link = this.#findLink(linkId); if (!link) return;
		this.#detailsLinkId = linkId;
		this.#detailChart?.close(); this.#detailChart = null;
		const panel = root.querySelector('.nu-panel'); panel.replaceChildren();
		panel.append(this.#button('×', 'nu-panel-close', () => this.#closePanels(root)));
		const heading = this.#element('div', '', 'nu-panel-heading');
		heading.append(this.#element('span', `${link.site} / ${link.host_name}`, 'nu-eyebrow'), this.#element('h3', link.display_name),
			this.#element('span', `${link.interface.if_name} · ${link.role.replaceAll('_', ' ')}`, 'nu-panel-subtitle'));
		panel.append(heading);
		const section = (title, fields) => {
			const box = this.#element('section', '', 'nu-detail-section');
			if (title === 'CURRENT TRAFFIC' || title === 'REMAINING CAPACITY') box.classList.add('is-emphasized');
			box.append(this.#element('h4', title));
			for (const [label, value] of fields) {
				const row = this.#element('div', '', 'nu-detail-row');
				const valueElement = this.#element('strong', value); valueElement.title = value;
				row.append(this.#element('span', label), valueElement); box.append(row);
			}
			panel.append(box);
		};
		section('IDENTITY', [['Site', link.site], ['Device', link.host_name], ['Interface', link.interface.if_name],
			['Alias', link.current_alias || link.interface.if_alias || '—'], ['Role', link.role.replaceAll('_', ' ')]]);
		section('STATUS', [['Admin', link.admin_status], ['Operational', link.oper_status],
			['Freshness', link.data_age_s >= 2147483647 ? 'No successful data' : this.#formatAge(link.data_age_s)],
			['Data', link.data_state === 'CURRENT' ? 'Current' : link.data_state]]);
		if (link.mapping_issue) section('CONFIGURATION', [['Issue', link.mapping_issue]]);
		section('CAPACITY', [['Physical port speed', this.#capacityText(link.port_speed_bps)],
			['Monitored capacity IN', this.#capacityText(link.capacity_in_bps)], ['Monitored capacity OUT', this.#capacityText(link.capacity_out_bps)],
			['Source', link.capacity_source === 'service_override' ? 'Service / circuit override' : 'Auto — interface speed']]);
		if ((link.capacity_in_bps === null || link.capacity_out_bps === null) && root.dataset.canEdit === '1') {
			panel.lastElementChild.append(this.#button('Edit / Set capacity', 'btn-alt', () => this.#beginEdit(root)));
		}
		section('CURRENT TRAFFIC', [['IN', this.#metric(link.current_in_bps, link.in_util_pct)],
			['OUT', this.#metric(link.current_out_bps, link.out_util_pct)]]);
		section('REMAINING CAPACITY', [['IN', this.#remaining(link.remaining_in_bps, link.capacity_in_bps)], ['OUT', this.#remaining(link.remaining_out_bps, link.capacity_out_bps)]]);
		section('24H STATISTICS', [['P95 IN', this.#metric(link.p95_in_bps, link.p95_in_pct)],
			['P95 OUT', this.#metric(link.p95_out_bps, link.p95_out_pct)], ['Peak', this.#formatBps(link.peak_bps)],
			['Sustained high', link.sustained ? this.#formatDuration(link.sustained_seconds) : 'No']]);
		section('QUALITY', [['Errors', String(link.errors_total)], ['Discards', String(link.discards_total)]]);
		const traffic = this.#element('section', '', 'nu-detail-section'); traffic.append(this.#element('h4', 'TRAFFIC TREND'), this.#trendPanel(link)); panel.append(traffic);
		const links = this.#element('div', '', 'nu-detail-links');
		if (link.hostid) {
			links.append(this.#link('Latest data', `zabbix.php?action=latest.view&filter_set=1&hostids%5B%5D=${encodeURIComponent(link.hostid)}`),
				this.#link('Problems', `zabbix.php?action=problem.view&filter_set=1&hostids%5B%5D=${encodeURIComponent(link.hostid)}`),
				this.#link('Host dashboard', `zabbix.php?action=host.dashboard.view&hostid=${encodeURIComponent(link.hostid)}`));
		}
		const native = this.#element('section', '', 'nu-detail-section'); native.append(this.#element('h4', 'NATIVE LINKS'), links); panel.append(native);
		panel.classList.remove('is-hidden'); root.querySelector('.nu-panel-backdrop').classList.remove('is-hidden');
	}

	#trendPanel(link) {
		const panel = this.#element('div', '', 'nu-trend-panel'); const controls = this.#element('div', '', 'nu-trend-controls');
		this.#detailChart = new NetworkUtilizationTrafficChart(link, this.#snapshot.generated_at);
		this.#detailChart.setRange(this.#chartRange);
		for (const [hours, label] of [[1, '1h'], [6, '6h'], [24, '24h'], [168, '7d']]) {
			const button = this.#button(label, 'btn-alt', () => this.#setGlobalRange(this._contents.querySelector('.netops-utilization'), hours));
			button.dataset.hours = String(hours); if (hours === this.#chartRange) button.classList.add('is-active'); controls.append(button);
		}
		panel.append(controls, this.#detailChart.root); return panel;
	}

	#setGlobalRange(root, hours) {
		this.#chartRange = hours;
		for (const button of root.querySelectorAll('[data-global-hours]')) button.classList.toggle('is-active', Number(button.dataset.globalHours) === hours);
		for (const button of root.querySelectorAll('.nu-trend-controls [data-hours]')) button.classList.toggle('is-active', Number(button.dataset.hours) === hours);
		for (const chart of this.#pinnedCharts.values()) chart.setRange(hours);
		this.#detailChart?.setRange(hours);
	}

	#renderPinnedGraphs(root) {
		for (const chart of this.#pinnedCharts.values()) chart.close();
		this.#pinnedCharts.clear();
		const definitions = [...this.#configuration.links].filter(link => link.show_graph)
			.sort((a, b) => (a.graph_order - b.graph_order) || (a.order - b.order) || a.id.localeCompare(b.id));
		const list = root.querySelector('.nu-graph-list');
		for (const definition of definitions) {
			const card = list.querySelector(`[data-graph-link-id="${CSS.escape(definition.id)}"]`);
			const link = this.#findLink(definition.id); if (!card || !link) continue;
			card.classList.remove('is-hidden'); list.append(card);
			const chart = new NetworkUtilizationTrafficChart(link, this.#snapshot.generated_at);
			chart.setRange(this.#chartRange); card.querySelector('.nu-pinned-chart').replaceChildren(chart.root);
			this.#pinnedCharts.set(definition.id, chart);
		}
		for (const card of list.querySelectorAll('[data-graph-link-id]')) {
			if (!this.#pinnedCharts.has(card.dataset.graphLinkId)) card.classList.add('is-hidden');
		}
		root.querySelector('.nu-graph-empty').classList.toggle('is-hidden', definitions.length !== 0);
		root.querySelector('.nu-graph-count').textContent = `${definitions.length} Link${definitions.length === 1 ? '' : 's'}`;
		for (const button of root.querySelectorAll('[data-graph-toggle]')) {
			const selected = definitions.some(link => link.id === button.dataset.linkId);
			button.dataset.graphToggle = selected ? 'remove' : 'add'; button.textContent = selected ? 'In graphs ✓ · Remove' : '+ Add to graphs';
		}
	}

	async #changeGraph(root, linkId, operation) {
		if (root.dataset.canEdit !== '1' || root.classList.contains('is-saving-graphs')) return;
		const document = structuredClone(this.#configuration); const target = document.links.find(link => link.id === linkId); if (!target) return;
		const pinned = document.links.filter(link => link.show_graph).sort((a, b) => (a.graph_order - b.graph_order) || a.id.localeCompare(b.id));
		if (operation === 'add') {
			target.show_graph = true; target.graph_order = pinned.length === 0 ? 0 : Math.max(...pinned.map(link => link.graph_order)) + 10;
		}
		else if (operation === 'remove') target.show_graph = false;
		else {
			const index = pinned.findIndex(link => link.id === linkId); const swap = operation === 'up' ? index - 1 : index + 1;
			if (index < 0 || swap < 0 || swap >= pinned.length) return;
			[pinned[index], pinned[swap]] = [pinned[swap], pinned[index]];
			pinned.forEach((link, order) => link.graph_order = order * 10);
		}
		root.classList.add('is-saving-graphs');
		try {
			this.#configuration = await this.#persistConfiguration(root, document);
			this.#renderPinnedGraphs(root); this._startUpdating({delay_sec: 0});
		}
		catch (error) { this.#showGraphError(root, error.message || 'Graph selection could not be saved.'); }
		finally { root.classList.remove('is-saving-graphs'); }
	}

	async #persistConfiguration(root, document) {
		const curl = new Curl('zabbix.php'); curl.setArgument('action', 'networkutilization.config.update');
		const response = await fetch(curl.getUrl(), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
			payload: JSON.stringify(document), expected_revision: document.revision, [CSRF_TOKEN_NAME]: root.dataset.csrfToken})});
		const result = await response.json(); if (result.error) throw new Error(result.error.messages.join(' ')); return result.configuration;
	}

	#showGraphError(root, message) {
		root.querySelector('.nu-graph-error')?.remove();
		const error = this.#element('div', message, 'nu-graph-error'); root.querySelector('.nu-graphs .nu-section-heading').after(error);
	}

	#closeCharts() {
		this.#detailChart?.close(); this.#detailChart = null;
		for (const chart of this.#pinnedCharts.values()) chart.close(); this.#pinnedCharts.clear();
	}

	#beginEdit(root) {
		if (this.isEditMode() || root.dataset.canEdit !== '1') return;
		this.#editing = true; this.#workingConfig = structuredClone(this.#configuration); this.#unsavedChanges = 0;
		this._pauseUpdating(); root.classList.add('is-editing'); this.#renderEditor(root);
	}

	#renderEditor(root) {
		const panel = root.querySelector('.nu-editor'); panel.replaceChildren();
		this.#capacityValidators = [];
		const heading = this.#element('div', '', 'nu-editor-heading');
		heading.append(this.#element('h3', `Editing Links · ${this.#unsavedChanges} unsaved changes`));
		const actions = this.#element('div', '', 'nu-editor-actions');
		actions.append(this.#button('Discard', 'btn-alt', () => this.#discardEdit(root)), this.#button('Save', 'btn', () => this.#saveWorking(root)));
		heading.append(actions); panel.append(heading);
		const creation = this.#element('div', '', 'nu-editor-create');
		creation.append(this.#button('Add site', 'btn-alt', () => this.#addSite(root)), this.#button('Add link', 'btn-alt', () => this.#addLink(root)));
		panel.append(creation, this.#element('h4', 'Sites'));
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
		const current = this.#findLink(link.id);
		const capacity = this.#capacityForm(link, () => current?.port_speed_bps ?? null, () => this.#dirty(root));
		this.#capacityValidators.push(capacity.validate);
		const warning = this.#input(link.warning_util_pct ?? '', 'Use global default', 'number'); warning.min = '1'; warning.max = '100'; warning.addEventListener('input', () => { link.warning_util_pct = warning.value === '' ? null : Number(warning.value); this.#dirty(root); });
		const critical = this.#input(link.critical_util_pct ?? '', 'Use global default', 'number'); critical.min = '1'; critical.max = '100'; critical.addEventListener('input', () => { link.critical_util_pct = critical.value === '' ? null : Number(critical.value); this.#dirty(root); });
		const visible = document.createElement('input'); visible.type = 'checkbox'; visible.checked = Boolean(link.visible); visible.addEventListener('change', () => { link.visible = visible.checked; this.#dirty(root); });
		const showGraph = document.createElement('input'); showGraph.type = 'checkbox'; showGraph.checked = Boolean(link.show_graph); showGraph.addEventListener('change', () => { link.show_graph = showGraph.checked; this.#dirty(root); });
		const group = (title, controls) => { const section = this.#element('section', '', 'nu-editor-group'); section.append(this.#element('h5', title)); const body = this.#element('div', '', 'nu-editor-group__fields'); body.append(...controls); section.append(body); return section; };
		fields.append(group('IDENTITY', [this.#label('Display name', name),
			this.#label('Site', this.#select(this.#workingConfig.sites.map(site => [site.id, site.name]), link.site_id, value => { link.site_id = value; this.#dirty(root); })),
			this.#label('Role', this.#select(this.#roles().map(role => [role, role.replaceAll('_', ' ')]), link.role, value => { link.role = value; this.#dirty(root); }))]),
			group('INTERFACE', [this.#element('div', `${link.host} · ${link.interface.if_name} · ${link.interface.if_alias || 'No alias'}`, 'nu-editor-reference')]),
			group('CAPACITY', [capacity.element]),
			group('THRESHOLDS', [this.#label('Custom warning % (default '+this.#workingConfig.settings.warning_util_pct+'%)', warning),
				this.#label('Custom critical % (default '+this.#workingConfig.settings.critical_util_pct+'%)', critical)]),
			group('DASHBOARD', [this.#label('Visible in Link list', visible), this.#label('Show persistent traffic graph', showGraph)]));
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
		const draft = {capacity_source: 'interface_speed', capacity_warning_accepted: false};
		const capacity = this.#capacityForm(draft, () => selected?.capacity_bps ?? null, () => {}, true);
		const rebuildInterfaces = () => {
			interfaceSelect.replaceChildren(); const rows = this.#candidates.filter(candidate => candidate.host === host).sort((a, b) => a.if_name.localeCompare(b.if_name));
			for (const candidate of rows) interfaceSelect.append(this.#option(candidate.if_name, `${candidate.if_name}${candidate.if_alias ? ` · ${candidate.if_alias}` : ''}`));
			const update = () => { selected = rows.find(candidate => candidate.if_name === interfaceSelect.value) ?? null; if (selected) { if (!display.value) display.value = selected.if_name; preview.textContent = `${selected.if_alias || 'No alias'} · Port speed ${this.#capacityText(selected.capacity_bps)} · Status ${selected.oper_status ?? 'unknown'} · ${selected.metric_types.join(', ')}`; } capacity.update(); };
			interfaceSelect.onchange = update; update();
		};
		box.append(this.#label('1. Host', hostSelect), this.#label('2. Interface', interfaceSelect), preview, this.#label('3. Display name', display), this.#label('Site', siteSelect), this.#label('Role', roleSelect), capacity.element);
		box.append(this.#button('Add to working copy', 'btn', () => {
			if (!selected || !display.value.trim()) return this.#error(panel, 'Host, interface and display name are required.');
			if (this.#workingConfig.links.some(link => link.host === selected.host && link.interface.if_name === selected.if_name)) return this.#error(panel, 'That Host/interface is already configured.');
			try { capacity.validate(); } catch (error) { return this.#error(panel, error.message); }
			this.#workingConfig.links.push({id: `link-${this.#slug(selected.host)}-${this.#slug(selected.if_name)}-${Date.now()}`, display_name: display.value.trim(), site_id: siteId, host: selected.host,
				interface: {if_name: selected.if_name, if_alias: selected.if_alias || '', if_descr: ''}, role, order: this.#workingConfig.links.length * 10, visible: true,
				show_graph: false, graph_order: this.#workingConfig.links.length * 10, required: true,
				...draft}); this.#dirty(root, true);
		})); rebuildInterfaces(); panel.insertBefore(box, panel.querySelector('h4:nth-of-type(2)'));
	}

	#capacityForm(link, portSpeed, onChange, preferServiceWhenMissing = false) {
		const box = this.#element('div', '', 'nu-capacity-form');
		let sourceTouched = false, touched = false;
		const initial = NetworkUtilizationCapacityRules.initial(link);
		const source = this.#select([['interface_speed', 'Auto — interface speed'], ['service_override', 'Service / circuit bandwidth']],
			initial.capacity_source, () => { sourceTouched = true; sync(); });
		const symmetric = document.createElement('input'); symmetric.type = 'checkbox';
		symmetric.checked = initial.symmetric_service_bandwidth;
		const makeAmount = (value, factor) => {
			const input = this.#input(value, 'Bandwidth', 'number'); input.min = '0.001'; input.step = 'any';
			const unit = this.#select([[1, 'bps'], [1e3, 'Kbps'], [1e6, 'Mbps'], [1e9, 'Gbps']], Number(factor), () => sync());
			return {input, unit, row: this.#element('div', '', 'nu-bandwidth-row')};
		};
		const incoming = makeAmount(initial.in_value, initial.in_unit), outgoing = makeAmount(initial.out_value, initial.out_unit);
		for (const part of [incoming, outgoing]) { part.row.append(part.input, part.unit); part.input.addEventListener('input', sync); }
		const warning = document.createElement('input'); warning.type = 'checkbox'; warning.checked = Boolean(link.capacity_warning_accepted);
		const warningLabel = this.#label('Accept configuration warning: capacity not configured', warning);
		const speed = this.#element('div', '', 'nu-candidate-preview');
		box.append(this.#label('Capacity source', source), speed, this.#label('Symmetric service bandwidth', symmetric),
			this.#label('IN bandwidth', incoming.row), this.#label('OUT bandwidth', outgoing.row), warningLabel);
		const form = () => ({capacity_source: source.value, symmetric_service_bandwidth: symmetric.checked,
			in_value: incoming.input.value, in_unit: incoming.unit.value, out_value: outgoing.input.value,
			out_unit: outgoing.unit.value, capacity_warning_accepted: warning.checked});
		function sync(notify = true) {
			if (symmetric.checked) { outgoing.input.value = incoming.input.value; outgoing.unit.value = incoming.unit.value; }
			Object.assign(link, NetworkUtilizationCapacityRules.normalize(form(), portSpeed(), false));
			incoming.row.parentElement.classList.toggle('is-hidden', source.value !== 'service_override');
			outgoing.row.parentElement.classList.toggle('is-hidden', source.value !== 'service_override' || symmetric.checked);
			warningLabel.classList.toggle('is-hidden', source.value !== 'interface_speed' || Boolean(portSpeed()));
			speed.textContent = `Physical port speed: ${portSpeed() === null ? 'Not available' : formatSpeed(portSpeed())}`;
			if (notify !== false) { touched = true; onChange(); }
		}
		const formatSpeed = value => this.#formatBps(value);
		for (const control of [symmetric, warning]) control.addEventListener('change', sync);
		const validate = () => {
			if (!NetworkUtilizationCapacityRules.shouldValidate(touched, preferServiceWhenMissing)) return;
			Object.assign(link, NetworkUtilizationCapacityRules.normalize(form(), portSpeed(), true));
		};
		const update = () => { if (preferServiceWhenMissing && !sourceTouched) source.value = portSpeed() ? 'interface_speed' : 'service_override'; sync(false); };
		update();
		return {element: box, validate, update};
	}

	#move(items, index, delta, root) { const target = index + delta; if (target < 0 || target >= items.length) return; [items[index], items[target]] = [items[target], items[index]]; this.#dirty(root, true); }
	#dirty(root, rerender = false) { this.#unsavedChanges++; this.#workingConfig.sites.forEach((site, index) => site.order = index * 10); this.#workingConfig.links.forEach((link, index) => link.order = index * 10); if (rerender) this.#renderEditor(root); else root.querySelector('.nu-editor h3').textContent = `Editing Links · ${this.#unsavedChanges} unsaved changes`; }
	#discardEdit(root) { this.#editing = false; this.#workingConfig = null; this.#unsavedChanges = 0; root.classList.remove('is-editing'); this.#closePanels(root); this._resumeUpdating(); this._startUpdating({delay_sec: 0}); }

	async #saveWorking(root) {
		const panel = root.querySelector('.nu-editor'); for (const item of panel.querySelectorAll('.nu-editor-error')) item.remove();
		try {
			for (const validate of this.#capacityValidators) validate();
			this.#configuration = await this.#persistConfiguration(root, this.#workingConfig); this.#discardEdit(root);
		}
		catch (error) { this.#error(panel, error.message || 'Configuration save failed.'); }
	}

	#closePanels(root) { this.#detailChart?.close(); this.#detailChart = null; this.#detailsLinkId = ''; root.querySelector('.nu-panel')?.classList.add('is-hidden'); root.querySelector('.nu-editor')?.classList.add('is-hidden'); root.querySelector('.nu-panel-backdrop')?.classList.add('is-hidden'); }
	#updateViewFreshness() { const root = this._contents?.querySelector('.netops-utilization'); if (!root || this.#lastSuccessfulUpdate === 0 || this.#editing) return; const age = Date.now() - this.#lastSuccessfulUpdate; const stale = age > Math.max(30000, Number(root.dataset.refreshSeconds ?? 60) * 2000); root.classList.toggle('is-view-stale', stale); root.querySelector('.nu-stale')?.classList.toggle('is-hidden', !stale); if (stale) root.querySelector('.nu-stale__age').textContent = this.#formatAge(Math.floor(age / 1000)); }
	#formatAge(seconds) { return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago` : seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s ago` : `${seconds}s ago`; }
	#formatDuration(seconds) { return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m` : `${Math.floor(seconds / 60)}m`; }
	#formatBps(value) { if (value === null || value === undefined) return '—'; for (const [scale, unit] of [[1e9, 'Gbps'], [1e6, 'Mbps'], [1e3, 'Kbps'], [1, 'bps']]) if (Math.abs(value) >= scale) return `${Number(value / scale).toLocaleString(undefined, {maximumFractionDigits: Math.abs(value / scale) >= 100 ? 0 : 2})} ${unit}`; return `${Number(value).toFixed(value ? 2 : 0)} bps`; }
	#capacityText(value) { return value === null ? 'Not configured' : this.#formatBps(value); }
	#remaining(value, capacity) { return value === null ? (capacity === null ? '— · Capacity required' : '— · Current traffic unavailable') : value < 0 ? `Over capacity by ${this.#formatBps(-value)}` : this.#formatBps(value); }
	#metric(bps, pct) { return bps === null ? '— · Data unavailable' : `${this.#formatBps(bps)} · ${pct === null ? '— · Capacity required' : `${Number(pct).toFixed(1)}%`}`; }
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
