const assert = require('node:assert/strict');
const Chart = require('../../frontend/modules/NetworkUtilization/assets/js/traffic-chart.js');

const end = 1_800_000_000;
const link = {
	port_speed_bps: 1_000_000_000,
	capacity_in_bps: 50_000_000,
	capacity_out_bps: 50_000_000,
	data_state: 'CURRENT',
	metrics: {
		in: {expected_interval: 180, history: [
			{clock: end - 1800, value: 2_680_000},
			{clock: end - 1200, value: 5_110_000},
			{clock: end - 600, value: 1_400_000}
		], trends_7d: [{clock: end - 3 * 86400, value: 2_200_000}]},
		out: {expected_interval: 180, history: [
			{clock: end - 1795, value: 1_770_000},
			{clock: end - 1195, value: 3_000_000},
			{clock: end - 595, value: 900_000}
		], trends_7d: [{clock: end - 3 * 86400, value: 1_100_000}]}
	}
};

for (const hours of [1, 6, 24, 168]) {
	const model = Chart.model(link, hours, end);
	assert.equal(model.startClock, end - hours * 3600);
	assert.equal(model.endClock, end);
	assert.equal(model.incoming[0].clock, hours === 168 ? end - 3 * 86400 : end - 1800);
	assert.equal(model.outgoing[0].clock, hours === 168 ? end - 3 * 86400 : end - 1795);
	assert.equal(Chart.ticks(model, 5)[0], model.startClock);
	assert.equal(Chart.ticks(model, 5)[4], model.endClock);
}

const hour = Chart.model(link, 1, end);
assert.equal(hour.unit.name, 'Mbps');
assert.equal(hour.maximum, 5_110_000);
assert.equal(hour.axis.top, 6_000_000);
assert.equal(hour.axis.step, 1_000_000);
assert.ok(hour.axis.top < link.capacity_in_bps, 'axis must reflect traffic, not service capacity');
assert.equal(Chart.model({...link, capacity_in_bps: 1_000_000_000, capacity_out_bps: 100_000_000}, 1, end).axis.top, hour.axis.top);
assert.equal(Chart.formatValue(2_680_000, hour.unit), '2.68 Mbps');
assert.equal(Chart.nearest(hour.outgoing, end - 1800, 90).value, 1_770_000);
assert.equal(Chart.nearest(hour.outgoing, end - 1800, 2), null);
assert.equal(Chart.model({metrics: {}, data_state: 'STALE'}, 1, end).maximum, 0);
assert.equal(Chart.model({metrics: {in: link.metrics.in}, data_state: 'STALE'}, 1, end).outgoing.length, 0);
assert.equal(Chart.model({...link, data_state: 'STALE'}, 1, end).stale, true);
assert.equal(Chart.unit(850_000_000).name, 'Mbps');
assert.equal(Chart.unit(1_840_000_000).name, 'Gbps');
assert.equal(Chart.unit(800_000).name, 'Kbps');
assert.equal(Chart.unit(500).name, 'bps');
assert.equal(Chart.model(link, 168, end).source, 'trends_7d');
assert.match(Chart.formatTime(end, 168), /\d/);
console.log('PASS: chart ranges, real timestamps, units, traffic scale, nearest samples and missing/stale data');
