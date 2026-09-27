/* Traffic values are Zabbix-normalized bits per second. This component never polls devices. */
class NetworkUtilizationTrafficChart {
	static ranges = {1: 'Last hour', 6: 'Last 6 hours', 24: 'Last 24 hours', 168: 'Last 7 days'};

	static unit(maximum) {
		if (maximum >= 1e9) return {name: 'Gbps', factor: 1e9};
		if (maximum >= 1e6) return {name: 'Mbps', factor: 1e6};
		if (maximum >= 1e3) return {name: 'Kbps', factor: 1e3};
		return {name: 'bps', factor: 1};
	}

	static niceAxis(maximum) {
		if (maximum <= 0) return {top: 1, step: .2};
		const target = maximum * 1.04;
		const raw = target / 6;
		const magnitude = 10 ** Math.floor(Math.log10(raw));
		const step = [1, 2, 2.5, 5, 10].map(value => value * magnitude)
			.find(value => Math.ceil(target / value) <= 6);
		return {top: step * Math.ceil(target / step), step};
	}

	static model(link, hours, endClock) {
		const source = hours === 168 ? 'trends_7d' : 'history';
		const startClock = endClock - hours * 3600;
		const read = direction => (link.metrics?.[direction]?.[source] ?? [])
			.filter(row => Number.isFinite(Number(row.clock)) && Number.isFinite(Number(row.value))
				&& Number(row.value) >= 0 && Number(row.clock) >= startClock && Number(row.clock) <= endClock)
			.map(row => ({clock: Number(row.clock), value: Number(row.value)}))
			.sort((a, b) => a.clock - b.clock);
		const incoming = read('in'), outgoing = read('out');
		const maximum = Math.max(0, ...incoming.map(point => point.value), ...outgoing.map(point => point.value));
		return {hours, source, startClock, endClock, incoming, outgoing, maximum,
			unit: this.unit(maximum), axis: this.niceAxis(maximum), stale: link.data_state === 'STALE'};
	}

	static ticks(model, count) {
		return Array.from({length: count}, (_, index) => model.startClock
			+ (model.endClock - model.startClock) * index / (count - 1));
	}

	static nearest(rows, clock, tolerance) {
		if (!rows.length) return null;
		let nearest = rows[0];
		for (const row of rows) if (Math.abs(row.clock - clock) < Math.abs(nearest.clock - clock)) nearest = row;
		return Math.abs(nearest.clock - clock) <= tolerance ? nearest : null;
	}

	static formatTime(clock, hours, detailed = false) {
		const date = new Date(clock * 1000);
		if (detailed) return new Intl.DateTimeFormat(undefined, {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(date);
		return hours === 168
			? new Intl.DateTimeFormat(undefined, {weekday: 'short', day: 'numeric'}).format(date)
			: new Intl.DateTimeFormat(undefined, {hour: '2-digit', minute: '2-digit', hour12: false}).format(date);
	}

	static formatValue(value, unit) {
		if (value === null) return 'Unavailable';
		const scaled = value / unit.factor;
		return `${scaled.toLocaleString(undefined, {minimumFractionDigits: scaled < 10 ? 2 : scaled < 100 ? 1 : 0,
			maximumFractionDigits: scaled < 10 ? 2 : scaled < 100 ? 1 : 0})} ${unit.name}`;
	}

	constructor(link, endClock) {
		this.link = link;
		this.endClock = endClock;
		this.hours = 1;
		this.pinned = false;
		this.selectedClock = null;
		this.root = document.createElement('div');
		this.root.className = 'nu-chart';
		this.resizeObserver = typeof ResizeObserver === 'undefined' ? null
			: new ResizeObserver(() => this.render());
		this.resizeObserver?.observe(this.root);
		this.render();
	}

	setRange(hours) {
		this.hours = hours;
		this.pinned = false;
		this.selectedClock = null;
		this.render();
	}

	close() { this.resizeObserver?.disconnect(); }

	static svg(tag, attributes = {}, value = null) {
		const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
		for (const [key, item] of Object.entries(attributes)) element.setAttribute(key, String(item));
		if (value !== null) element.textContent = value;
		return element;
	}

	render() {
		const model = NetworkUtilizationTrafficChart.model(this.link, this.hours, this.endClock);
		const width = Math.max(280, this.root.clientWidth || 420);
		const height = 216, left = 58, right = 12, top = 14, bottom = 38;
		const plotWidth = width - left - right, plotHeight = height - top - bottom;
		const x = clock => left + plotWidth * (clock - model.startClock) / (model.endClock - model.startClock);
		const y = value => top + plotHeight * (1 - value / model.axis.top);
		this.root.replaceChildren();
		const header = document.createElement('div'); header.className = 'nu-chart__heading';
		const title = document.createElement('strong'); title.textContent = `Traffic — ${NetworkUtilizationTrafficChart.ranges[this.hours]}`;
		const unitLabel = document.createElement('span'); unitLabel.className = 'nu-chart__unit'; unitLabel.textContent = model.unit.name;
		const legend = document.createElement('div'); legend.className = 'nu-chart__legend';
		for (const [direction, available] of [['IN', model.incoming.length], ['OUT', model.outgoing.length]]) {
			const label = document.createElement('span'); label.className = `nu-chart__legend-${direction.toLowerCase()}`;
			label.textContent = `${direction}${available ? '' : ' unavailable'}`; legend.append(label);
		}
		header.append(title, unitLabel, legend); this.root.append(header);
		if (model.stale) { const warning = document.createElement('div'); warning.className = 'nu-chart__stale'; warning.textContent = 'Data stale — plotted history is not current'; this.root.append(warning); }
		if (!model.incoming.length && !model.outgoing.length) {
			const empty = document.createElement('div'); empty.className = 'nu-chart__empty'; empty.textContent = 'No traffic history available'; this.root.append(empty); return;
		}
		const frame = document.createElement('div'); frame.className = 'nu-chart__frame';
		const svg = NetworkUtilizationTrafficChart.svg('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `IN and OUT throughput in ${model.unit.name} over ${NetworkUtilizationTrafficChart.ranges[this.hours].toLowerCase()}`});
		for (let index = 0; index <= Math.round(model.axis.top / model.axis.step); index++) {
			const value = model.axis.step * index;
			const position = y(value);
			svg.append(NetworkUtilizationTrafficChart.svg('line', {x1: left, y1: position, x2: width - right, y2: position, class: 'nu-chart__grid'}));
			const text = NetworkUtilizationTrafficChart.svg('text', {x: left - 7, y: position + 4, 'text-anchor': 'end', class: 'nu-chart__tick'},
				Number((value / model.unit.factor).toPrecision(3)).toString());
			svg.append(text);
		}
		const count = width >= 570 ? 7 : width >= 400 ? 5 : 3;
		for (const clock of NetworkUtilizationTrafficChart.ticks(model, count)) {
			const position = x(clock);
			svg.append(NetworkUtilizationTrafficChart.svg('text', {x: position, y: height - 13,
				'text-anchor': position <= left + 2 ? 'start' : position >= width - right - 2 ? 'end' : 'middle', class: 'nu-chart__tick'},
				NetworkUtilizationTrafficChart.formatTime(clock, this.hours)));
		}
		for (const [rows, direction] of [[model.incoming, 'in'], [model.outgoing, 'out']]) {
			if (!rows.length) continue;
			const interval = this.hours === 168 ? 3600 : Math.max(60, Number(this.link.metrics?.[direction]?.expected_interval ?? 60));
			const segments = []; let segment = [];
			for (const row of rows) {
				if (segment.length && row.clock - segment[segment.length - 1].clock > interval * 2.5) { segments.push(segment); segment = []; }
				segment.push(row);
			}
			if (segment.length) segments.push(segment);
			for (const points of segments) svg.append(NetworkUtilizationTrafficChart.svg(points.length === 1 ? 'circle' : 'polyline', points.length === 1
				? {cx: x(points[0].clock), cy: y(points[0].value), r: 3, class: `nu-chart__series nu-chart__${direction}`}
				: {points: points.map(row => `${x(row.clock)},${y(row.value)}`).join(' '), class: `nu-chart__series nu-chart__${direction}`}));
		}
		const crosshair = NetworkUtilizationTrafficChart.svg('line', {y1: top, y2: top + plotHeight, class: 'nu-chart__crosshair'});
		crosshair.style.display = 'none'; svg.append(crosshair);
		const hit = NetworkUtilizationTrafficChart.svg('rect', {x: left, y: top, width: plotWidth, height: plotHeight, class: 'nu-chart__hit'});
		svg.append(hit);
		const tooltip = document.createElement('div'); tooltip.className = 'nu-chart__tooltip'; tooltip.hidden = true;
		const anchors = [...new Set([...model.incoming, ...model.outgoing].map(row => row.clock))].sort((a, b) => a - b);
		const inspect = clock => {
			const tolerance = this.hours === 168 ? 1800 : Math.max(30, Math.min(600,
				Math.max(Number(this.link.metrics?.in?.expected_interval ?? 0), Number(this.link.metrics?.out?.expected_interval ?? 0)) / 2));
			const incoming = NetworkUtilizationTrafficChart.nearest(model.incoming, clock, tolerance);
			const outgoing = NetworkUtilizationTrafficChart.nearest(model.outgoing, clock, tolerance);
			crosshair.setAttribute('x1', x(clock)); crosshair.setAttribute('x2', x(clock)); crosshair.style.display = '';
			tooltip.replaceChildren();
			const date = document.createElement('strong'); date.textContent = NetworkUtilizationTrafficChart.formatTime(clock, this.hours, true); tooltip.append(date);
			for (const [direction, point] of [['IN', incoming], ['OUT', outgoing]]) {
				const line = document.createElement('div'); line.className = `nu-chart__tooltip-${direction.toLowerCase()}`;
				line.textContent = `${direction}  ${NetworkUtilizationTrafficChart.formatValue(point?.value ?? null, model.unit)}`
					+ (point && point.clock !== clock ? ` · sample ${NetworkUtilizationTrafficChart.formatTime(point.clock, this.hours)}` : '');
				tooltip.append(line);
			}
			tooltip.hidden = false;
			tooltip.style.left = `${Math.max(82, Math.min(width - 82, x(clock)))}px`;
		};
		const nearestAnchor = event => {
			const bounds = svg.getBoundingClientRect();
			const position = (event.clientX - bounds.left) / bounds.width * width;
			const clock = model.startClock + (position - left) / plotWidth * (model.endClock - model.startClock);
			return NetworkUtilizationTrafficChart.nearest(anchors.map(value => ({clock: value})), clock, Infinity)?.clock;
		};
		hit.addEventListener('pointermove', event => { if (!this.pinned) inspect(nearestAnchor(event)); });
		hit.addEventListener('pointerleave', () => { if (!this.pinned) { tooltip.hidden = true; crosshair.style.display = 'none'; } });
		hit.addEventListener('click', event => {
			const clock = nearestAnchor(event);
			if (this.pinned && clock === this.selectedClock) { this.pinned = false; tooltip.hidden = true; crosshair.style.display = 'none'; }
			else { this.pinned = true; this.selectedClock = clock; inspect(clock); }
		});
		frame.append(svg, tooltip); this.root.append(frame);
		const footer = document.createElement('div'); footer.className = 'nu-chart__footer';
		footer.textContent = `${model.unit.name} · ${this.hours === 168 ? 'Hourly trend averages' : 'Zabbix history samples'} · ${NetworkUtilizationTrafficChart.formatTime(model.startClock, this.hours, true)} – ${NetworkUtilizationTrafficChart.formatTime(model.endClock, this.hours, true)}`;
		this.root.append(footer);
	}
}

if (typeof module !== 'undefined' && module.exports) module.exports = NetworkUtilizationTrafficChart;
