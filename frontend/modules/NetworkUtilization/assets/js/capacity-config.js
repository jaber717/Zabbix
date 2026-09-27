/* UI-only normalization. The PHP repository remains authoritative on save. */
class NetworkUtilizationCapacityRules {
	static shouldValidate(touched, isNew) { return Boolean(touched || isNew); }
	static initial(link) {
		const incoming = link.service_capacity_in_bps ?? link.capacity_override_bps ?? null;
		const outgoing = link.service_capacity_out_bps ?? link.capacity_override_bps ?? null;
		const display = value => {
			const unit = value && value % 1e9 === 0 ? 1e9 : value && value % 1e6 === 0 ? 1e6 : value && value % 1e3 === 0 ? 1e3 : 1;
			return {value: value ? String(value / unit) : '', unit: String(unit)};
		};
		const inDisplay = display(incoming), outDisplay = display(outgoing);
		return {capacity_source: link.capacity_source ?? (link.capacity_override_bps ? 'service_override' : 'interface_speed'),
			symmetric_service_bandwidth: link.symmetric_service_bandwidth ?? incoming === outgoing,
			in_value: inDisplay.value, in_unit: inDisplay.unit, out_value: outDisplay.value, out_unit: outDisplay.unit};
	}

	static normalize(form, portSpeed, strict = true) {
		const source = form.capacity_source;
		if (!['interface_speed', 'service_override'].includes(source)) throw new Error('Choose a capacity source.');
		const symmetric = Boolean(form.symmetric_service_bandwidth);
		if (source === 'interface_speed') {
			const accepted = Boolean(form.capacity_warning_accepted);
			if (strict && !(Number(portSpeed) > 0) && !accepted) {
				throw new Error('Port speed is unavailable. Set service bandwidth or explicitly accept the configuration warning.');
			}
			return {capacity_source: source, symmetric_service_bandwidth: symmetric,
				service_capacity_in_bps: null, service_capacity_out_bps: null, capacity_warning_accepted: accepted};
		}
		const amount = (value, unit) => {
			if (value === '' || value === null || value === undefined || ![1, 1e3, 1e6, 1e9].includes(Number(unit))) return null;
			const bps = Number(value) * Number(unit);
			return Number.isSafeInteger(bps) && bps > 0 && bps <= 1e15 ? bps : null;
		};
		const incoming = amount(form.in_value, form.in_unit);
		const outgoing = symmetric ? incoming : amount(form.out_value, form.out_unit);
		if (strict && (incoming === null || outgoing === null)) {
			throw new Error(symmetric ? 'Enter a positive service bandwidth.' : 'Enter positive IN and OUT service bandwidth.');
		}
		return {capacity_source: source, symmetric_service_bandwidth: symmetric,
			service_capacity_in_bps: incoming, service_capacity_out_bps: outgoing, capacity_warning_accepted: false};
	}
}

if (typeof module !== 'undefined') module.exports = NetworkUtilizationCapacityRules;
