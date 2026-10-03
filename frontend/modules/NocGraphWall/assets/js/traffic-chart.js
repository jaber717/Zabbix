/* Minimal canvas line chart — IN/OUT paired or single. No fake interpolation.
   Gaps are drawn as broken lines; unknown data stays empty rather than zeroed.
   Intentionally compact; a later release can swap in the Network Utilization chart renderer.
*/
function drawTrafficChart(canvas, slot) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const series = (slot.series || []).filter(s => s && s.points && s.points.length);
    if (!series.length) {
        ctx.fillStyle = 'rgba(128,128,128,0.5)';
        ctx.font = '12px sans-serif';
        ctx.fillText('No data', 8, 20);
        return;
    }
    let tmin = Infinity, tmax = -Infinity, vmax = -Infinity;
    series.forEach(s => s.points.forEach(([t, v]) => {
        if (t < tmin) tmin = t;
        if (t > tmax) tmax = t;
        if (v > vmax) vmax = v;
    }));
    if (!isFinite(tmin) || !isFinite(tmax) || tmax === tmin) {
        ctx.fillText('No data', 8, 20);
        return;
    }
    if (vmax <= 0) vmax = 1;
    const colors = { in: '#2b8a3e', out: '#1864ab', value: '#862e9c', aggregate: '#5f3dc4' };
    const padL = 46, padR = 10, padT = 8, padB = 20;
    const chartW = W - padL - padR, chartH = H - padT - padB;
    // axes
    ctx.strokeStyle = 'rgba(128,128,128,0.3)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, padT + chartH); ctx.lineTo(padL + chartW, padT + chartH); ctx.stroke();
    // y labels (3)
    ctx.fillStyle = 'rgba(128,128,128,0.8)'; ctx.font = '11px sans-serif';
    for (let i = 0; i <= 3; i++) {
        const y = padT + chartH * (1 - i / 3);
        const v = vmax * i / 3;
        ctx.fillText(formatBps(v), 2, y + 4);
    }
    // series
    series.forEach(s => {
        ctx.strokeStyle = colors[s.role] || '#495057';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        let first = true;
        s.points.forEach(([t, v]) => {
            const x = padL + chartW * (t - tmin) / (tmax - tmin);
            const y = padT + chartH * (1 - v / vmax);
            if (first) { ctx.moveTo(x, y); first = false; } else { ctx.lineTo(x, y); }
        });
        ctx.stroke();
    });
    // current value in slot header
    const slotEl = canvas.closest('.ngw-slot');
    if (slotEl) {
        const last = series[series.length - 1].points.slice(-1)[0];
        const vel = slotEl.querySelector('.ngw-slot__value');
        if (vel && last) vel.textContent = formatBps(last[1]);
    }
}
function formatBps(v) {
    const u = [[1e9, 'Gbps'], [1e6, 'Mbps'], [1e3, 'Kbps']];
    for (const [s, l] of u) if (Math.abs(v) >= s) return (v / s).toFixed(v / s >= 10 ? 1 : 2) + ' ' + l;
    return Math.round(v) + ' bps';
}
