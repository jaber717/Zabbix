const assert = require('node:assert/strict');
const fs = require('node:fs');
const Chart = require('../../frontend/modules/NetworkUtilization/assets/js/traffic-chart.js');

const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const {link, generated_at: end} = fixture;
for (const hours of [1, 6, 24, 168]) {
	const model = Chart.model(link, hours, end);
	const nativeSource = hours === 168 ? 'trends_7d' : 'history';
	for (const [direction, rows] of [['in', model.incoming], ['out', model.outgoing]]) {
		const expected = (link.metrics[direction][nativeSource] ?? []).filter(row => row.clock >= end - hours * 3600 && row.clock <= end);
		assert.deepEqual(rows, expected.map(row => ({clock: Number(row.clock), value: Number(row.value)})));
	}
	assert.equal(Chart.ticks(model, 5)[0], end - hours * 3600);
	assert.equal(Chart.ticks(model, 5).at(-1), end);
	assert.ok(model.axis.top >= model.maximum);
	assert.ok(model.axis.top <= Math.max(model.maximum * 2, 1), 'traffic scale should not track 1 Gbps capacity');
	console.log(`${hours}h: IN=${model.incoming.length} OUT=${model.outgoing.length} unit=${model.unit.name} top=${model.axis.top} max=${model.maximum}`);
}
console.log('PASS: four live LAB chart ranges, timestamps, normalized values and traffic-based scale');
