/* global CWidget */
class CWidgetNocGraphWall extends CWidget {
    _init() {
        super._init();
        this._refresh_seconds = 30;
        this._in_flight = false;
        this._range_hours = 1;
    }

    _registerEvents() {
        super._registerEvents();
        const root = this._target;
        root.querySelectorAll('[data-hours]').forEach(btn => {
            btn.addEventListener('click', () => {
                root.querySelectorAll('[data-hours]').forEach(b => b.classList.remove('is-active'));
                btn.classList.add('is-active');
                this._range_hours = parseInt(btn.dataset.hours, 10);
                try { localStorage.setItem('ngw.range', String(this._range_hours)); } catch (_) {}
                this._reload();
            });
        });
        const fs = root.querySelector('.ngw-fullscreen');
        if (fs) fs.addEventListener('click', () => this._toggleFullscreen());
        try {
            const saved = localStorage.getItem('ngw.range');
            if (saved) {
                this._range_hours = parseInt(saved, 10);
                const btn = root.querySelector(`[data-hours="${this._range_hours}"]`);
                if (btn) {
                    root.querySelectorAll('[data-hours]').forEach(b => b.classList.remove('is-active'));
                    btn.classList.add('is-active');
                }
            }
        } catch (_) {}
        this._renderAllSlots();
    }

    _toggleFullscreen() {
        const el = this._target.querySelector('.netops-noc-wall');
        if (!el) return;
        el.classList.toggle('is-fullscreen');
    }

    _reload() {
        if (this._in_flight) return;
        this._in_flight = true;
        const now = Math.floor(Date.now() / 1000);
        const from = now - this._range_hours * 3600;
        const url = new URL(location.href);
        url.searchParams.set('action', 'widget.netops_noc_graph_wall.view');
        url.searchParams.set('from', String(from));
        url.searchParams.set('to', String(now));
        fetch(url.toString(), { credentials: 'same-origin' })
            .then(r => r.json())
            .then(j => this._applySnapshot(j))
            .catch(e => console.error('NOC wall refresh failed', e))
            .finally(() => { this._in_flight = false; });
    }

    _applySnapshot(data) {
        if (!data || !data.snapshot) return;
        const root = this._target.querySelector('.netops-noc-wall');
        if (!root) return;
        root.setAttribute('data-snapshot', btoa(unescape(encodeURIComponent(JSON.stringify(data.snapshot)))));
        const updatedAt = new Date(data.snapshot.generated_at * 1000);
        const label = root.querySelector('.ngw-updated');
        if (label) label.textContent = 'Updated ' + updatedAt.toLocaleTimeString();
        (data.snapshot.slots || []).forEach(slot => {
            const canvas = root.querySelector(`[data-slot="${slot.position}"]`);
            if (canvas) {
                canvas.setAttribute('data-series', btoa(unescape(encodeURIComponent(JSON.stringify(slot.series || [])))));
                drawTrafficChart(canvas, slot);
            }
        });
    }

    _renderAllSlots() {
        this._target.querySelectorAll('.ngw-slot__canvas').forEach(c => {
            try {
                const series = JSON.parse(decodeURIComponent(escape(atob(c.getAttribute('data-series') || ''))));
                drawTrafficChart(c, { position: c.dataset.slot, series });
            } catch (_) {}
        });
    }
}
