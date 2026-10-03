/* Slot editor — admin-only. Pops an overlay listing the 6 slots.
   Each slot can be: paired_interface | single_item | aggregate | empty.
   Admin picks items via the server-side search action; the browser never calls item.get directly.
*/
(function () {
    function openEditor(root) {
        const csrf = root.getAttribute('data-csrf-token') || '';
        const current = JSON.parse(decodeURIComponent(escape(atob(root.getAttribute('data-configuration') || ''))));
        const overlay = document.createElement('div');
        overlay.className = 'ngw-editor-overlay';
        overlay.innerHTML = `
            <div class="ngw-editor">
                <h3>Edit NOC wall</h3>
                <p class="ngw-editor__hint">Six fixed slots. Positions are stable. No automatic reordering.</p>
                <div class="ngw-editor__slots"></div>
                <div class="ngw-editor__footer">
                    <button type="button" class="btn-alt ngw-editor__cancel">Cancel</button>
                    <button type="button" class="btn ngw-editor__save">Save</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        const slotsEl = overlay.querySelector('.ngw-editor__slots');
        current.slots.forEach(slot => {
            const row = document.createElement('div');
            row.className = 'ngw-editor__slot';
            row.innerHTML = `
                <strong>Slot ${slot.position}</strong>
                <input type="text" data-field="label" value="${(slot.label || '').replace(/"/g, '&quot;')}" />
                <select data-field="kind">
                    <option value="empty"${slot.kind === 'empty' ? ' selected' : ''}>Empty</option>
                    <option value="paired_interface"${slot.kind === 'paired_interface' ? ' selected' : ''}>Interface IN/OUT</option>
                    <option value="single_item"${slot.kind === 'single_item' ? ' selected' : ''}>Single numeric item</option>
                    <option value="aggregate"${slot.kind === 'aggregate' ? ' selected' : ''}>Aggregate (sum of items)</option>
                </select>
                <input type="number" data-field="in_itemid" placeholder="in itemid" value="${slot.in_itemid || ''}" />
                <input type="number" data-field="out_itemid" placeholder="out itemid" value="${slot.out_itemid || ''}" />
                <input type="number" data-field="itemid" placeholder="itemid" value="${slot.itemid || ''}" />`;
            slotsEl.appendChild(row);
        });
        overlay.querySelector('.ngw-editor__cancel').addEventListener('click', () => overlay.remove());
        overlay.querySelector('.ngw-editor__save').addEventListener('click', async () => {
            const out = { $schema_version: 1, defaults: current.defaults, slots: [] };
            overlay.querySelectorAll('.ngw-editor__slot').forEach((row, idx) => {
                const kind = row.querySelector('[data-field=kind]').value;
                const entry = { position: idx + 1, kind, label: row.querySelector('[data-field=label]').value };
                if (kind === 'paired_interface') {
                    entry.in_itemid = parseInt(row.querySelector('[data-field=in_itemid]').value, 10) || null;
                    entry.out_itemid = parseInt(row.querySelector('[data-field=out_itemid]').value, 10) || null;
                } else if (kind === 'single_item') {
                    entry.itemid = parseInt(row.querySelector('[data-field=itemid]').value, 10) || null;
                }
                out.slots.push(entry);
            });
            const body = new FormData();
            body.append('configuration', JSON.stringify(out));
            body.append('_csrf_token', csrf);
            const res = await fetch(location.pathname + '?action=nocgraphwall.config.update', { method: 'POST', credentials: 'same-origin', body });
            if (res.ok) { overlay.remove(); location.reload(); }
            else { alert('Save failed'); }
        });
    }
    document.addEventListener('click', e => {
        const btn = e.target.closest('.ngw-edit-start');
        if (!btn) return;
        const root = btn.closest('.netops-noc-wall');
        if (root) openEditor(root);
    });
})();
