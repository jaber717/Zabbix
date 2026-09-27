class CWidgetNetworkAvailability extends CWidget {
	#heroId = '';
	#heroSelectedAt = 0;
	#siteState = new Map();
	#siteLastAffected = new Map();
	#filter = '';
	#search = '';
	#detailsNodeId = '';
	#editing = false;
	#workingConfig = null;
	#unsavedChanges = 0;
	#lastSuccessfulUpdate = 0;
	#staleTimer = null;
	#snapshot = null;
	#configuration = null;
	#availableHosts = [];

	onStart() {
		this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000);
	}

	onActivate() {
		if (this.#staleTimer === null) {
			this.#staleTimer = setInterval(() => this.#updateViewFreshness(), 5000);
		}
	}

	onDeactivate() {
		if (this.#staleTimer !== null) {
			clearInterval(this.#staleTimer);
			this.#staleTimer = null;
		}
	}

	getUpdateRequestData() {
		return {
			...super.getUpdateRequestData(),
			availability_hero_id: this.#heroId || undefined,
			availability_hero_selected_at: this.#heroSelectedAt || undefined
		};
	}

	setContents(response) {
		if (this.#editing) {
			return;
		}
		const scrollTop = this._contents.scrollTop;
		super.setContents(response);
		const root = this._contents.querySelector('.netops-availability');
		if (root === null || !root.dataset.snapshot) {
			return;
		}
		this.#lastSuccessfulUpdate = Date.now();
		this.#heroId = root.dataset.heroId ?? '';
		this.#heroSelectedAt = Number(root.dataset.heroSelectedAt ?? 0);
		this.#snapshot = this.#decode(root.dataset.snapshot);
		this.#configuration = this.#decode(root.dataset.configuration);
		this.#availableHosts = this.#decode(root.dataset.availableHosts);
		root.querySelector('.na-updated').textContent = `Updated ${new Intl.DateTimeFormat(undefined,
			{hour: '2-digit', minute: '2-digit'}).format(new Date(this.#snapshot.generated_at * 1000))}`;
		root.classList.toggle('is-dark-theme', [...document.querySelectorAll('link[rel="stylesheet"]')]
			.some(link => /(?:dark-theme|hc-dark)\.css(?:\?|$)/.test(link.href)));
		this.#bind(root);
		this.#applyContext(root);
		this._contents.scrollTop = scrollTop;
		this.#updateViewFreshness();
	}

	#decode(value) {
		return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(value), character => character.charCodeAt(0))));
	}

	#bind(root) {
		root.querySelector('.na-search')?.addEventListener('input', event => {
			this.#search = event.target.value.trim().toLowerCase();
			this.#applyFilters(root);
		});
		for (const tile of root.querySelectorAll('.na-summary__tile:not([disabled])')) {
			tile.addEventListener('click', () => {
				this.#filter = this.#filter === tile.dataset.filter ? '' : tile.dataset.filter;
				this.#applyFilters(root);
			});
		}
		root.querySelector('.na-filter-clear')?.addEventListener('click', () => {
			this.#filter = '';
			this.#applyFilters(root);
		});
		root.querySelector('.na-attention-more')?.addEventListener('click', event => {
			for (const row of root.querySelectorAll('.na-attention__row.is-extra')) {
				row.classList.toggle('is-hidden');
			}
			event.currentTarget.textContent = event.currentTarget.textContent.includes('more') ? 'Show less'
				: `+${root.querySelectorAll('.na-attention__row.is-extra').length} more`;
		});

		const now = Date.now();
		for (const site of root.querySelectorAll('.na-site')) {
			const id = site.dataset.siteId;
			const signature = site.dataset.issueSignature;
			const affected = site.classList.contains('is-affected');
			const previous = this.#siteState.get(id);
			if (affected) {
				this.#siteLastAffected.set(id, now);
			}
			const recoveredAt = this.#siteLastAffected.get(id);
			const recovered = !affected && recoveredAt !== undefined && now - recoveredAt < 600000;
			if (recovered) {
				site.classList.add('is-recovered');
				site.querySelector('.na-site__recovered').textContent = 'Recovered';
			}
			const newIssue = affected && previous?.signature !== undefined && previous.signature !== signature;
			const open = newIssue || recovered || (previous?.signature === signature ? previous.open
				: site.dataset.defaultOpen === '1');
			this.#setSiteOpen(site, open);
			this.#siteState.set(id, {open, signature});
			site.querySelector('.na-site__header')?.addEventListener('click', () => {
				const next = site.classList.contains('is-collapsed');
				this.#setSiteOpen(site, next);
				this.#siteState.set(id, {open: next, signature});
			});
		}

		for (const chip of root.querySelectorAll('[data-site-open]')) {
			chip.addEventListener('click', () => {
				const site = root.querySelector(`.na-site[data-site-id="${CSS.escape(chip.dataset.siteOpen)}"]`);
				if (site !== null) {
					site.classList.add('is-expanded-from-chip');
					this.#setSiteOpen(site, true);
					this.#siteState.set(site.dataset.siteId, {open: true, signature: site.dataset.issueSignature});
					site.scrollIntoView({block: 'nearest'});
				}
			});
		}
		root.querySelector('.na-unassigned__header')?.addEventListener('click', () => {
			const rows = root.querySelector('.na-unassigned__rows');
			rows?.classList.toggle('is-hidden');
			const chevron = root.querySelector('.na-unassigned__chevron');
			if (chevron !== null) chevron.textContent = rows?.classList.contains('is-hidden') ? '▶' : '▼';
		});

		for (const element of root.querySelectorAll('[data-node-id]')) {
			if (!element.matches('.na-node, .na-attention__open, .na-unassigned__row')) continue;
			element.addEventListener('click', event => {
				if (event.target.closest('[data-quick-assign]')) return;
				this.#openDetails(root, element.dataset.nodeId);
			});
			if (element.matches('[role="button"]')) element.addEventListener('keydown', event => {
				if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); element.click(); }
			});
		}
		for (const action of root.querySelectorAll('[data-ack-node-id]')) action.addEventListener('click', event => {
			event.stopPropagation();
			const node = this.#findNode(action.dataset.ackNodeId);
			this.#openNativeAck(node?.problems ?? []);
		});
		for (const assign of root.querySelectorAll('[data-quick-assign]')) {
			assign.addEventListener('click', event => {
				event.stopPropagation();
				this.#openQuickAssign(root, assign.dataset.quickAssign);
			});
		}
		root.querySelector('.na-edit-start')?.addEventListener('click', () => this.#beginEdit(root));
		if (this.isEditMode()) {
			root.querySelector('.na-edit-start')?.setAttribute('disabled', 'disabled');
			root.querySelector('.na-edit-start')?.setAttribute('title', 'Exit dashboard edit mode before editing Sites');
		}
	}

	#applyContext(root) {
		const search = root.querySelector('.na-search');
		if (search !== null) search.value = this.#search;
		this.#applyFilters(root);
		if (this.#detailsNodeId !== '') this.#openDetails(root, this.#detailsNodeId);
	}

	#applyFilters(root) {
		for (const tile of root.querySelectorAll('.na-summary__tile')) {
			tile.setAttribute('aria-pressed', tile.dataset.filter === this.#filter ? 'true' : 'false');
		}
		const chip = root.querySelector('.na-filter-chip');
		chip?.classList.toggle('is-hidden', this.#filter === '');
		if (chip !== null && this.#filter !== '') {
			chip.querySelector('.na-filter-chip__label').textContent = `Filtered: ${this.#filter.replaceAll('_', ' ')}`;
		}
		for (const element of root.querySelectorAll('.na-node, .na-unassigned__row, .na-attention__row')) {
			const searchMatch = this.#search === '' || (element.dataset.search ?? '').includes(this.#search);
			let filterMatch = true;
			switch (this.#filter) {
				case 'DOWN': case 'DEGRADED': case 'UNKNOWN': case 'UP':
					filterMatch = element.dataset.state === this.#filter; break;
				case 'VISIBILITY_LOSS': filterMatch = element.dataset.visibility === 'LOST'; break;
				case 'MAINTENANCE': filterMatch = element.classList.contains('is-maintenance'); break;
				case 'IMPACTED_SITES': filterMatch = element.closest('.na-site')?.classList.contains('is-affected')
					|| element.dataset.impactedSite === '1'
					|| element.closest('.na-unassigned')?.dataset.impactedSite === '1'; break;
			}
			element.classList.toggle('is-filtered-out', !(searchMatch && filterMatch));
		}
		const active = this.#filter !== '' || this.#search !== '';
		for (const site of root.querySelectorAll('.na-site')) {
			const hasMatch = !!site.querySelector('.na-node:not(.is-config-hidden):not(.is-filtered-out)');
			site.classList.toggle('is-filtered-out', active && !hasMatch);
		}
		const unassigned = root.querySelector('.na-unassigned');
		if (unassigned) unassigned.classList.toggle('is-filtered-out', active
			&& !unassigned.querySelector('.na-unassigned__row:not(.is-filtered-out)'));
		for (const chip of root.querySelectorAll('.na-healthy-chip')) {
			const site = root.querySelector(`.na-site[data-site-id="${CSS.escape(chip.dataset.siteOpen)}"]`);
			chip.classList.toggle('is-filtered-out', active && !!site?.classList.contains('is-filtered-out'));
		}
	}

	#setSiteOpen(site, open) {
		site.classList.toggle('is-open', open);
		site.classList.toggle('is-collapsed', !open);
		const chevron = site.querySelector('.na-site__chevron');
		if (chevron !== null) chevron.textContent = open ? '▼' : '▶';
	}

	#openDetails(root, nodeId) {
		const node = this.#findNode(nodeId);
		this.#detailsNodeId = nodeId;
		const panel = root.querySelector('.na-details-panel');
		const backdrop = root.querySelector('.na-panel-backdrop');
		panel.replaceChildren();
		panel.append(this.#button('×', 'na-panel-close', () => this.#closePanels(root)));
		if (node === null) {
			const incident = this.#snapshot.needs_attention.find(candidate => candidate.id === nodeId);
			if (incident === undefined) return;
			panel.append(this.#element('h3', incident.name));
			for (const [label, value] of [['Site', incident.site], ['State', incident.state],
				['Tier', incident.criticality === null ? 'No tier' : `Tier-${incident.criticality.slice(-1)}`],
				['Affected Nodes', String(incident.affected_nodes ?? '—')], ['Source', incident.source_id ?? '—']]) {
				const row = this.#element('div', '', 'na-detail-row');
				row.append(this.#element('span', label), this.#element('strong', value)); panel.append(row);
			}
			panel.classList.remove('is-hidden'); backdrop.classList.remove('is-hidden'); return;
		}
		panel.append(this.#element('h3', node.name));
		const fields = [
			['Site', node.site], ['Type', node.kind ?? 'Unassigned'],
			['Tier', node.criticality === null ? 'No tier' : `Tier-${node.criticality.slice(-1)}`],
			['State', node.actual_state], ['Visibility', node.visibility],
			['Maintenance', node.maintenance ? 'Active' : 'No'], ['Flapping', node.flapping ? 'Yes' : 'No'],
			['Freshness', `${node.members.filter(member => member.fresh).length}/${node.members.length} fresh`],
			['Aggregation', node.policy], ['Required N', String(node.required_members)]
		];
		for (const [label, value] of fields) {
			const row = this.#element('div', '', 'na-detail-row');
			row.append(this.#element('span', label), this.#element('strong', value));
			panel.append(row);
		}
		panel.append(this.#element('h4', 'Members'));
		for (const member of node.members) {
			const row = this.#element('div', '', 'na-member-detail');
			row.append(this.#element('strong', member.name),
				this.#element('span', member.fresh ? member.raw_availability_state : 'STALE'),
				this.#element('span', member.availability_source),
				this.#element('span', member.data_age === null ? 'No successful data' : `${member.data_age}s old`));
			panel.append(row);
		}
		if (node.problems.length > 0) {
			panel.append(this.#element('h4', 'Active Zabbix Problems'));
			for (const problem of node.problems) {
				const link = document.createElement('a');
				link.href = `tr_events.php?triggerid=0&eventid=${encodeURIComponent(problem.eventid)}`;
				link.textContent = `${problem.name} · ${problem.acknowledged ? 'Acknowledged' : 'Unacknowledged'}`;
				panel.append(link);
			}
			panel.append(this.#button('Open native acknowledgement', 'btn-alt', () => this.#openNativeAck(node.problems)));
		}
		if (node.hostids.length > 0) {
			const links = this.#element('div', '', 'na-detail-links');
			const hostids = node.hostids.map(id => `hostids%5B%5D=${encodeURIComponent(id)}`).join('&');
			links.append(this.#link('Problems', `zabbix.php?action=problem.view&filter_set=1&${hostids}`),
				this.#link('Latest data', `zabbix.php?action=latest.view&filter_set=1&${hostids}`));
			panel.append(links);
		}
		panel.classList.remove('is-hidden');
		backdrop.classList.remove('is-hidden');
	}

	#openNativeAck(problems) {
		const eventids = problems.map(problem => problem.eventid).filter(Boolean);
		if (eventids.length === 0) return;
		if (typeof PopUp === 'function') {
			PopUp('acknowledge.edit', {eventids}, {dialogue_class: 'modal-popup-generic'});
		}
		else window.location.assign(`tr_events.php?triggerid=0&eventid=${encodeURIComponent(eventids[0])}`);
	}

	#findNode(nodeId) {
		for (const site of this.#snapshot.sites) {
			const node = site.nodes.find(candidate => candidate.id === nodeId);
			if (node !== undefined) return node;
		}
		return null;
	}

	#beginEdit(root) {
		if (this.isEditMode() || root.dataset.canEdit !== '1') return;
		this.#editing = true;
		this.#workingConfig = structuredClone(this.#configuration);
		this.#unsavedChanges = 0;
		this._pauseUpdating();
		root.classList.add('is-editing');
		this.#renderEditor(root);
	}

	#renderEditor(root) {
		const panel = root.querySelector('.na-editor-panel');
		const backdrop = root.querySelector('.na-panel-backdrop');
		panel.replaceChildren();
		const title = this.#element('div', '', 'na-editor-title');
		title.append(this.#element('h3', `Editing sites · ${this.#unsavedChanges} unsaved changes`));
		const saveActions = this.#element('div', '', 'na-editor-actions');
		saveActions.append(this.#button('Discard', 'btn-alt', () => this.#discardEdit(root)),
			this.#button('Save', 'btn', () => this.#saveWorking(root)));
		title.append(saveActions); panel.append(title);
		const actions = this.#element('div', '', 'na-editor-create');
		actions.append(this.#button('Add site', 'btn-alt', () => this.#addSite(root)),
			this.#button('Add Node', 'btn-alt', () => this.#addNode(root)),
			this.#button('Batch / multi-member', 'btn-alt', () => this.#openBatchCreator(root, panel)));
		panel.append(actions);

		panel.append(this.#element('h4', 'Sites'));
		this.#workingConfig.sites.forEach((site, index) => {
			const row = this.#element('div', '', 'na-editor-row');
			const input = this.#input(site.name, 'Site name');
			input.addEventListener('input', () => { site.name = input.value; this.#dirty(root); });
			row.append(input,
				this.#button('↑', 'btn-icon', () => this.#move(this.#workingConfig.sites, index, -1, root)),
				this.#button('↓', 'btn-icon', () => this.#move(this.#workingConfig.sites, index, 1, root)),
				this.#button('Delete', 'btn-link', () => {
					if (this.#workingConfig.nodes.some(node => node.site_id === site.id)) {
						this.#showEditorError(panel, 'Move or delete this Site’s Nodes first.'); return;
					}
					this.#workingConfig.sites.splice(index, 1); this.#dirty(root, true);
				}));
			panel.append(row);
		});

		panel.append(this.#element('h4', 'Nodes'));
		this.#workingConfig.nodes.forEach((node, index) => panel.append(this.#nodeEditor(root, node, index)));
		const note = this.#element('p', 'Hidden Nodes remain monitored, counted, and eligible for Needs Attention. Hide changes card layout only.', 'na-editor-note');
		panel.append(note);
		panel.classList.remove('is-hidden');
		backdrop.classList.remove('is-hidden');
	}

	#nodeEditor(root, node, index) {
		const box = this.#element('details', '', 'na-node-editor');
		box.open = index === this.#workingConfig.nodes.length - 1 && this.#unsavedChanges > 0;
		box.append(this.#element('summary', node.name || 'New Node'));
		const fields = this.#element('div', '', 'na-node-editor__fields');
		const name = this.#input(node.name, 'Display name');
		name.addEventListener('input', () => { node.name = name.value; box.querySelector('summary').textContent = name.value || 'New Node'; this.#dirty(root); });
		fields.append(this.#label('Display name', name));
		fields.append(this.#label('Site', this.#select(this.#workingConfig.sites.map(site => [site.id, site.name]), node.site_id,
			value => { node.site_id = value; this.#dirty(root); })));
		fields.append(this.#label('Kind', this.#select([
			['host', 'Host'], ['ha_pair', 'HA pair'], ['cluster', 'Cluster'], ['fabric', 'Fabric'],
			['logical_service', 'Logical service']
		], node.kind, value => { node.kind = value; this.#dirty(root); })));
		fields.append(this.#label('Tier', this.#select([
			['', 'Not set (Tier required to save)'], ['tier1', 'Tier-1'], ['tier2', 'Tier-2'], ['tier3', 'Tier-3']
		], node.criticality, value => { node.criticality = value; this.#dirty(root); })));
		fields.append(this.#label('Policy', this.#select([
			['ANY_REQUIRED', 'ANY_REQUIRED'], ['ALL_REQUIRED', 'ALL_REQUIRED'],
			['MAJORITY_REQUIRED', 'MAJORITY_REQUIRED'], ['MIN_N_REQUIRED', 'MIN_N_REQUIRED']
		], node.aggregation_policy, value => { node.aggregation_policy = value; this.#dirty(root); })));
		const min = this.#input(String(node.min_n ?? 1), 'MIN_N', 'number'); min.min = '1';
		min.addEventListener('input', () => { node.min_n = Number(min.value); this.#dirty(root); });
		fields.append(this.#label('Required N', min));
		const description = this.#input(node.description ?? '', 'Description');
		description.addEventListener('input', () => { node.description = description.value; this.#dirty(root); });
		fields.append(this.#label('Description', description));
		const hidden = document.createElement('input'); hidden.type = 'checkbox'; hidden.checked = Boolean(node.hidden);
		hidden.addEventListener('change', () => { node.hidden = hidden.checked; this.#dirty(root); });
		fields.append(this.#label('Hide normal card', hidden));
		const hostSearch = this.#input('', 'Search monitored Hosts');
		const members = document.createElement('select'); members.multiple = true; members.size = 7;
		const selected = new Set(node.members.map(member => member.host));
		for (const host of this.#availableHosts) {
			const option = document.createElement('option'); option.value = host.host;
			option.textContent = `${host.name} (${host.host})`; option.selected = selected.has(host.host);
			members.append(option);
		}
		hostSearch.addEventListener('input', () => {
			const query = hostSearch.value.toLowerCase();
			for (const option of members.options) option.hidden = !option.textContent.toLowerCase().includes(query);
		});
		members.addEventListener('change', () => {
			node.members = [...members.selectedOptions].map(option => ({id: this.#slug(option.value), name: option.textContent.replace(/ \([^)]*\)$/, ''), host: option.value}));
			this.#dirty(root);
		});
		fields.append(this.#label('Members', hostSearch), members);
		box.append(fields);
		const actions = this.#element('div', '', 'na-node-editor__actions');
		actions.append(this.#button('↑', 'btn-icon', () => this.#move(this.#workingConfig.nodes, index, -1, root)),
			this.#button('↓', 'btn-icon', () => this.#move(this.#workingConfig.nodes, index, 1, root)),
			this.#button('Delete Node', 'btn-link', () => { this.#workingConfig.nodes.splice(index, 1); this.#dirty(root, true); }));
		box.append(actions);
		return box;
	}

	#addSite(root) {
		this.#workingConfig.sites.push({id: `site-${Date.now()}`, name: 'New Site', order: this.#workingConfig.sites.length * 10});
		this.#dirty(root, true);
	}

	#addNode(root) {
		if (this.#workingConfig.sites.length === 0) { this.#addSite(root); }
		this.#workingConfig.nodes.push({id: `node-${Date.now()}`, name: 'New Node', site_id: this.#workingConfig.sites[0].id,
			kind: 'host', aggregation_policy: 'ANY_REQUIRED', criticality: '', order: this.#workingConfig.nodes.length * 10,
			hidden: false, description: '', members: []});
		this.#dirty(root, true);
	}

	#openBatchCreator(root, panel) {
		panel.querySelector('.na-batch-editor')?.remove();
		const box = this.#element('div', '', 'na-batch-editor');
		box.append(this.#element('h4', 'Create from monitored Hosts'));
		let mode = 'separate'; let siteId = this.#workingConfig.sites[0]?.id ?? ''; let tier = '';
		const modeSelect = this.#select([['separate', 'Separate host Nodes'], ['ha_pair', 'HA pair'], ['cluster', 'Cluster']],
			mode, value => { mode = value; });
		const siteSelect = this.#select(this.#workingConfig.sites.map(site => [site.id, site.name]), siteId,
			value => { siteId = value; });
		const tierSelect = this.#select([['', 'Not set (Tier required to save)'], ['tier1', 'Tier-1'], ['tier2', 'Tier-2'], ['tier3', 'Tier-3']],
			tier, value => { tier = value; });
		const required = this.#input('1', 'Required N', 'number'); required.min = '1';
		const search = this.#input('', 'Search monitored Hosts');
		const hosts = document.createElement('select'); hosts.multiple = true; hosts.size = 9;
		for (const host of this.#availableHosts) {
			const option = document.createElement('option'); option.value = host.host; option.textContent = `${host.name} (${host.host})`; hosts.append(option);
		}
		search.addEventListener('input', () => {
			const query = search.value.toLowerCase();
			for (const option of hosts.options) option.hidden = !option.textContent.toLowerCase().includes(query);
		});
		box.append(this.#label('Create as', modeSelect), this.#label('Site', siteSelect), this.#label('Tier', tierSelect),
			this.#label('Required N for HA/cluster', required), this.#label('Hosts', search), hosts);
		box.append(this.#button('Add to working copy', 'btn', () => {
			const selected = [...hosts.selectedOptions].map(option => this.#availableHosts.find(host => host.host === option.value));
			if (siteId === '' || tier === '') { this.#showEditorError(panel, 'Site and Tier are required.'); return; }
			if ((mode === 'ha_pair' && selected.length !== 2) || (mode === 'cluster' && selected.length < 2)
					|| (mode === 'separate' && selected.length < 1)) {
				this.#showEditorError(panel, mode === 'ha_pair' ? 'An HA pair requires exactly two Hosts.' : 'Select the required Hosts.'); return;
			}
			const makeMember = host => ({id: this.#slug(host.host), name: host.name, host: host.host});
			if (mode === 'separate') {
				for (const host of selected) {
					this.#workingConfig.nodes.push({id: `host-${this.#slug(host.host)}-${Date.now()}`, name: host.name,
						site_id: siteId, kind: 'host', aggregation_policy: 'ANY_REQUIRED', criticality: tier,
						order: this.#workingConfig.nodes.length * 10, hidden: false, description: '', members: [makeMember(host)]});
				}
			}
			else {
				const minN = Number(required.value);
				if (!Number.isInteger(minN) || minN < 1 || minN > selected.length) {
					this.#showEditorError(panel, `Required N must be within 1..${selected.length}.`); return;
				}
				this.#workingConfig.nodes.push({id: `${mode}-${Date.now()}`, name: mode === 'ha_pair' ? 'New HA pair' : 'New cluster',
					site_id: siteId, kind: mode, aggregation_policy: 'MIN_N_REQUIRED', min_n: minN, criticality: tier,
					order: this.#workingConfig.nodes.length * 10, hidden: false, description: '', members: selected.map(makeMember)});
			}
			this.#dirty(root, true);
		}));
		panel.insertBefore(box, panel.querySelector('h4:nth-of-type(2)'));
	}

	#move(items, index, delta, root) {
		const target = index + delta;
		if (target < 0 || target >= items.length) return;
		[items[index], items[target]] = [items[target], items[index]];
		this.#dirty(root, true);
	}

	#dirty(root, rerender = false) {
		this.#workingConfig.sites.forEach((site, index) => { site.order = index * 10; });
		this.#workingConfig.nodes.forEach((node, index) => { node.order = index * 10; });
		const changed = (current, saved) => {
			const baseline = new Map(saved.map(item => [item.id, item]));
			const ids = new Set(current.map(item => item.id));
			return current.filter(item => JSON.stringify(item) !== JSON.stringify(baseline.get(item.id))).length
				+ saved.filter(item => !ids.has(item.id)).length;
		};
		this.#unsavedChanges = changed(this.#workingConfig.sites, this.#configuration.sites)
			+ changed(this.#workingConfig.nodes, this.#configuration.nodes);
		if (rerender) this.#renderEditor(root);
		else root.querySelector('.na-editor-title h3').textContent = `Editing sites · ${this.#unsavedChanges} unsaved changes`;
	}

	#discardEdit(root) {
		this.#editing = false; this.#workingConfig = null; this.#unsavedChanges = 0;
		root.classList.remove('is-editing'); this.#closePanels(root); this._resumeUpdating(); this._startUpdating({delay_sec: 0});
	}

	async #saveWorking(root) {
		await this.#saveConfig(root, this.#workingConfig, () => this.#discardEdit(root));
	}

	#openQuickAssign(root, hostname) {
		if (root.dataset.canEdit !== '1' || this.isEditMode()) return;
		const host = this.#availableHosts.find(candidate => candidate.host === hostname);
		if (host === undefined) return;
		this.#editing = true;
		this._pauseUpdating();
		const panel = root.querySelector('.na-editor-panel'); panel.replaceChildren();
		panel.append(this.#button('×', 'na-panel-close', () => this.#cancelQuickAssign(root)), this.#element('h3', 'Assign to site'));
		panel.append(this.#element('p', `Host: ${host.name} (${host.host})`));
		const siteOptions = this.#configuration.sites.map(site => [site.id, site.name]); siteOptions.push(['__new__', 'New site…']);
		let siteId = siteOptions[0]?.[0] ?? '__new__'; let tier = '';
		const siteSelect = this.#select(siteOptions, siteId, value => { siteId = value; newSite.classList.toggle('is-hidden', value !== '__new__'); });
		const newSite = this.#input('', 'New site name'); newSite.classList.toggle('is-hidden', siteId !== '__new__');
		const display = this.#input(host.name, 'Display name');
		panel.append(this.#label('Site', siteSelect), this.#label('New site', newSite), this.#label('Display name', display));
		const tiers = this.#element('div', '', 'na-tier-choice');
		for (const value of ['tier1', 'tier2', 'tier3']) {
			const button = this.#button(`Tier-${value.slice(-1)}`, 'btn-alt', () => {
				tier = value; for (const item of tiers.children) item.classList.toggle('is-selected', item === button);
			}); tiers.append(button);
		}
		panel.append(this.#label('Tier (required)', tiers));
		panel.append(this.#button('Save', 'btn', async () => {
			if (tier === '') { this.#showEditorError(panel, 'Tier is required.'); return; }
			const config = structuredClone(this.#configuration);
			if (siteId === '__new__') {
				if (newSite.value.trim() === '') { this.#showEditorError(panel, 'New Site name is required.'); return; }
				siteId = `site-${this.#slug(newSite.value)}-${Date.now()}`;
				config.sites.push({id: siteId, name: newSite.value.trim(), order: config.sites.length * 10});
			}
			config.nodes.push({id: `host-${this.#slug(host.host)}-${Date.now()}`, name: display.value.trim() || host.name,
				site_id: siteId, kind: 'host', aggregation_policy: 'ANY_REQUIRED', criticality: tier,
				order: config.nodes.length * 10, hidden: false, description: '',
				members: [{id: this.#slug(host.host), name: host.name, host: host.host}]});
			await this.#saveConfig(root, config, () => {
				this.#editing = false; this.#closePanels(root); this._resumeUpdating(); this._startUpdating({delay_sec: 0});
			});
		}));
		panel.classList.remove('is-hidden'); root.querySelector('.na-panel-backdrop').classList.remove('is-hidden');
	}

	#cancelQuickAssign(root) {
		this.#editing = false;
		this.#closePanels(root);
		this._resumeUpdating();
	}

	async #saveConfig(root, config, onSuccess) {
		const panel = root.querySelector('.na-editor-panel');
		for (const error of panel.querySelectorAll('.na-editor-error')) error.remove();
		try {
			const curl = new Curl('zabbix.php'); curl.setArgument('action', 'networkavailability.config.update');
			const response = await fetch(curl.getUrl(), {method: 'POST', headers: {'Content-Type': 'application/json'},
				body: JSON.stringify({payload: JSON.stringify(config), expected_revision: config.revision,
					[CSRF_TOKEN_NAME]: root.dataset.csrfToken})});
			const result = await response.json();
			if (result.error) throw new Error(result.error.messages.join(' '));
			this.#configuration = result.configuration; onSuccess();
		}
		catch (error) { this.#showEditorError(panel, error.message || 'Configuration save failed.'); }
	}

	#showEditorError(panel, message) {
		panel.prepend(this.#element('div', message, 'na-editor-error'));
	}

	#closePanels(root) {
		this.#detailsNodeId = '';
		root.querySelector('.na-details-panel')?.classList.add('is-hidden');
		root.querySelector('.na-editor-panel')?.classList.add('is-hidden');
		root.querySelector('.na-panel-backdrop')?.classList.add('is-hidden');
	}

	#updateViewFreshness() {
		const root = this._contents?.querySelector('.netops-availability');
		if (root === null || root === undefined || this.#lastSuccessfulUpdate === 0 || this.#editing) return;
		const age = Date.now() - this.#lastSuccessfulUpdate;
		const stale = age > Math.max(20000, Number(root.dataset.refreshSeconds ?? 30) * 2000);
		root.classList.toggle('is-view-stale', stale);
		const banner = root.querySelector('.na-stale-view'); banner?.classList.toggle('is-hidden', !stale);
		if (stale && banner !== null) banner.querySelector('.na-stale-view__age').textContent = this.#formatAge(Math.floor(age / 1000));
	}

	#formatAge(seconds) {
		return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago`
			: seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s ago` : `${seconds}s ago`;
	}

	#slug(value) {
		return value.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'item';
	}

	#element(tag, text = '', className = '') {
		const element = document.createElement(tag); element.textContent = text;
		if (className !== '') element.className = className; return element;
	}

	#button(text, className, handler) {
		const button = this.#element('button', text, className); button.type = 'button'; button.addEventListener('click', handler); return button;
	}

	#link(text, href) {
		const link = this.#element('a', text); link.href = href; return link;
	}

	#input(value, placeholder, type = 'text') {
		const input = document.createElement('input'); input.type = type; input.value = value; input.placeholder = placeholder; return input;
	}

	#label(text, control) {
		const label = this.#element('label', '', 'na-editor-label'); label.append(this.#element('span', text), control); return label;
	}

	#select(options, selected, handler) {
		const select = document.createElement('select');
		for (const [value, label] of options) { const option = document.createElement('option'); option.value = value; option.textContent = label; option.selected = value === selected; select.append(option); }
		select.addEventListener('change', () => handler(select.value)); return select;
	}
}
