class CWidgetNetworkAvailability extends CWidget {
	#heroId = '';
	#heroSelectedAt = 0;
	#expandedSites = new Set();

	getUpdateRequestData() {
		return {
			...super.getUpdateRequestData(),
			availability_hero_id: this.#heroId || undefined,
			availability_hero_selected_at: this.#heroSelectedAt || undefined
		};
	}

	setContents(response) {
		super.setContents(response);
		const root = this._contents.querySelector('.netops-availability');
		if (root === null) {
			return;
		}
		this.#heroId = root.dataset.heroId ?? '';
		this.#heroSelectedAt = Number(root.dataset.heroSelectedAt ?? 0);
		for (const site of root.querySelectorAll('.na-site')) {
			const siteId = site.dataset.siteId;
			const open = this.#expandedSites.has(siteId) ||
				(!this.#expandedSites.has(`closed:${siteId}`) && site.dataset.defaultOpen === '1');
			this.#setSiteOpen(site, open);
			site.querySelector('.na-site__header')?.addEventListener('click', () => {
				const nextOpen = site.classList.contains('is-collapsed');
				this.#expandedSites.delete(nextOpen ? `closed:${siteId}` : siteId);
				this.#expandedSites.add(nextOpen ? siteId : `closed:${siteId}`);
				this.#setSiteOpen(site, nextOpen);
			});
		}
	}

	#setSiteOpen(site, open) {
		site.classList.toggle('is-open', open);
		site.classList.toggle('is-collapsed', !open);
		const chevron = site.querySelector('.na-site__chevron');
		if (chevron !== null) {
			chevron.textContent = open ? '▼' : '▶';
		}
	}
}
