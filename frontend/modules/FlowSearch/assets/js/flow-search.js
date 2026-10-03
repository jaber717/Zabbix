/* Flow Search — browser is a thin query submitter. All SQL lives server-side. */
(function () {
    function readFilter(root) {
        const minutesBtn = root.querySelector('.fs-toolbar .is-active');
        const minutes = minutesBtn ? parseInt(minutesBtn.dataset.minutes, 10) : 60;
        const to = Math.floor(Date.now() / 1000);
        const from = to - minutes * 60;
        const filter = { from, to };
        root.querySelectorAll('.fs-filter input').forEach(i => {
            const v = (i.value || '').trim();
            if (v) filter[i.name] = v;
        });
        filter._csrf_token = root.getAttribute('data-csrf-token');
        return filter;
    }

    async function post(action, body) {
        const fd = new FormData();
        Object.entries(body).forEach(([k, v]) => fd.append(k, String(v)));
        const r = await fetch(location.pathname + '?action=' + action, { method: 'POST', credentials: 'same-origin', body: fd });
        return r.json();
    }

    function renderRows(tbody, rows) {
        tbody.innerHTML = '';
        rows.forEach(r => {
            const tr = document.createElement('tr');
            tr.innerHTML = ['time','SrcAddr','DstAddr','SrcPort','DstPort','Proto','Bytes','Packets','ExporterAddress','InIfName','OutIfName']
                .map(k => '<td>' + (r[k] ?? '—') + '</td>').join('');
            tbody.appendChild(tr);
        });
    }

    function fmtBytes(b) {
        const u = [[1e12,'TB'],[1e9,'GB'],[1e6,'MB'],[1e3,'KB']];
        for (const [s,l] of u) if (b >= s) return (b / s).toFixed(2) + ' ' + l;
        return b + ' B';
    }

    function renderSummary(root, s) {
        root.querySelector('.fs-summary').classList.remove('is-empty');
        root.querySelector('.fs-summary__traffic span').textContent = fmtBytes(Number(s.bytes || 0));
        root.querySelector('.fs-summary__packets span').textContent = Number(s.packets || 0).toLocaleString();
        root.querySelector('.fs-summary__flows span').textContent = Number(s.flows || 0).toLocaleString();
        root.querySelector('.fs-summary__peak span').textContent = fmtBytes(Number(s.peak_bytes || 0));
    }

    async function runSearch(root) {
        const filter = readFilter(root);
        const [q, ...topn] = await Promise.all([
            post('flowsearch.query', filter),
            ...['source','destination','conversation','port','protocol','exporter','ingress'].map(f => post('flowsearch.topn', { ...filter, facet: f, limit: 10 })),
        ]);
        if (!q.ok) { alert('Query failed: ' + (q.error || '')); return; }
        renderSummary(root, q.summary || {});
        renderRows(root.querySelector('.fs-results__tbody'), q.rows || []);
        topn.forEach((resp, idx) => {
            const facet = ['source','destination','conversation','port','protocol','exporter','ingress'][idx];
            const panel = root.querySelector(`.fs-topn__panel[data-facet="${facet}"] .fs-topn__list`);
            if (!panel) return;
            panel.innerHTML = (resp.rows || []).map(r => `<li>${r.key ?? '—'} — ${fmtBytes(Number(r.bytes || 0))}</li>`).join('');
        });
    }

    document.addEventListener('click', e => {
        const btn = e.target.closest('.netops-flow-search .fs-run');
        if (btn) {
            const root = btn.closest('.netops-flow-search');
            if (root) runSearch(root);
        }
        const rbtn = e.target.closest('.netops-flow-search .fs-toolbar [data-minutes]');
        if (rbtn) {
            const root = rbtn.closest('.netops-flow-search');
            if (!root) return;
            root.querySelectorAll('.fs-toolbar [data-minutes]').forEach(b => b.classList.remove('is-active'));
            rbtn.classList.add('is-active');
        }
    });
})();
