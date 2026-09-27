const assert = require('node:assert/strict');
const Rules = require('../../frontend/modules/NetworkUtilization/assets/js/capacity-config.js');

const symmetric = {capacity_source: 'service_override', symmetric_service_bandwidth: true,
	in_value: '50', in_unit: '1000000', out_value: '', out_unit: '1000000', capacity_warning_accepted: false};
const a = Rules.normalize(symmetric, null);
assert.equal(a.service_capacity_in_bps, 50_000_000);
assert.equal(a.service_capacity_out_bps, 50_000_000);
assert.equal(a.capacity_warning_accepted, false);
const reopened = Rules.initial(a);
assert.equal(reopened.capacity_source, 'service_override');
assert.equal(reopened.symmetric_service_bandwidth, true);
assert.equal(reopened.in_value, '50');
assert.equal(reopened.in_unit, '1000000');

const b = Rules.normalize({...symmetric, symmetric_service_bandwidth: false,
	in_value: '100', out_value: '50'}, null);
assert.equal(b.service_capacity_in_bps, 100_000_000);
assert.equal(b.service_capacity_out_bps, 50_000_000);

const auto = {...symmetric, capacity_source: 'interface_speed'};
assert.throws(() => Rules.normalize(auto, null), /Port speed is unavailable/);
assert.equal(Rules.normalize({...auto, capacity_warning_accepted: true}, null).capacity_source, 'interface_speed');
assert.equal(Rules.normalize(auto, 1_000_000_000).capacity_source, 'interface_speed');

assert.throws(() => Rules.normalize({...symmetric, in_value: ''}, null), /positive service bandwidth/);
assert.throws(() => Rules.normalize({...symmetric, in_value: '0'}, null), /positive service bandwidth/);
assert.throws(() => Rules.normalize({...b, capacity_source: 'service_override', symmetric_service_bandwidth: false,
	in_value: '100', in_unit: '1000000', out_value: '', out_unit: '1000000'}, null), /IN and OUT/);

assert.equal(Rules.shouldValidate(false, false), false, 'untouched legacy warning link must not block another save');
assert.equal(Rules.shouldValidate(true, false), true);
assert.equal(Rules.shouldValidate(false, true), true);
assert.doesNotThrow(() => Rules.normalize(symmetric, null), 'valid service bandwidth must not trigger port-speed error');
console.log('PASS: capacity source, symmetric/asymmetric bandwidth, warning scope and unavailable-port save rules');
