/**
 * Inventory (FRD 10.1) -- two read-only dashboards:
 *   1. Production (WIP): RM / PM / Additive and baked bulk on the floor (WIP + Baked WIP
 *      warehouses), plus the approved baked WIP per Sub PO with its aging.
 *   2. FG: finished goods by SKU / batch with the FG status; only FG-Cleared stock in the
 *      FG warehouse counts as Available for Dispatch.
 */

frappe.pages['production_inventory'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Inventory'), single_column: true });
	wrapper.inventory = new ProductionInventory(page);
};

frappe.pages['production_inventory'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	if (wrapper.inventory) wrapper.inventory.refresh();
};

class ProductionInventory {
	constructor(page) {
		this.page = page;
		this.tab = 'wip';
		this.f = { item: '', category: '', warehouse: '', status: '', batch: '' };
		this.$w = $(page.main);
		this.$w.html(`
			<div class="pinv">
				<style>
					.pinv .pinv-tabs { display:flex; gap:8px; margin-bottom:12px; }
					.pinv .pinv-filters { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:10px; }
					.pinv .pinv-filters > div { min-width:170px; }
					.pinv .pinv-cards { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
					.pinv .pinv-card { border:1px solid var(--border-color); border-radius:8px; padding:8px 14px; min-width:150px; }
					.pinv .pinv-card .v { font-size:18px; font-weight:600; }
					.pinv table { width:100%; }
					.pinv td.n, .pinv th.n { text-align:right; white-space:nowrap; }
					.pinv h5 { margin:14px 0 6px; }
					.pinv .lnk { cursor:pointer; color:var(--text-color); text-decoration:underline; }
				</style>
				<div class="pinv-tabs">
					<button class="btn btn-sm btn-primary" data-tab="wip">${__('Production (WIP) Inventory')}</button>
					<button class="btn btn-sm btn-default" data-tab="fg">${__('FG Inventory')}</button>
				</div>
				<div class="pinv-filters"></div>
				<div class="pinv-msg text-muted"></div>
				<div class="pinv-cards"></div>
				<div class="pinv-body"></div>
			</div>`);
		this.$w.find('[data-tab]').on('click', (e) => {
			this.tab = $(e.currentTarget).attr('data-tab');
			this.$w.find('[data-tab]').removeClass('btn-primary').addClass('btn-default');
			$(e.currentTarget).removeClass('btn-default').addClass('btn-primary');
			this.make_filters();
			this.refresh();
		});
		this.page.add_inner_button(__('Stock Transfers'), () => frappe.set_route('production_transfer_list'));
		this.page.add_inner_button(__('Inventory Adjustments'), () => frappe.set_route('inventory_adjustment_list'));
		this.page.set_secondary_action(__('Refresh'), () => this.refresh());
		this.make_filters();
	}

	ctl(df, value) {
		const me = this;
		const $p = $('<div>').appendTo(this.$w.find('.pinv-filters'));
		const c = frappe.ui.form.make_control({
			df: Object.assign({ change() { me.f[df.fieldname] = this.get_value(); me.refresh(); } }, df),
			parent: $p, render_input: true,
		});
		c.refresh();
		if (value) c.set_value(value);
		return c;
	}

	make_filters() {
		this.$w.find('.pinv-filters').empty();
		this.ctl({ fieldname: 'item', label: __('Item / SKU'), fieldtype: 'Link', options: 'Item' }, this.f.item);
		this.ctl({ fieldname: 'warehouse', label: __('Warehouse'), fieldtype: 'Link', options: 'Warehouse' }, this.f.warehouse);
		if (this.tab === 'wip') {
			this.ctl({ fieldname: 'category', label: __('Category'), fieldtype: 'Select',
				options: ['', 'RM', 'PM', 'Additive', 'Baked / Semi-finished', 'Other'] }, this.f.category);
		} else {
			this.ctl({ fieldname: 'status', label: __('Status'), fieldtype: 'Select',
				options: ['', 'FG-Cleared', 'FG-Hold', 'QC-Rejected'] }, this.f.status);
			this.ctl({ fieldname: 'batch', label: __('Batch'), fieldtype: 'Link', options: 'Batch' }, this.f.batch);
		}
	}

	refresh() {
		const fn = this.tab === 'wip' ? 'get_wip_dashboard' : 'get_fg_dashboard';
		const args = this.tab === 'wip'
			? { item: this.f.item, category: this.f.category, warehouse: this.f.warehouse }
			: { item: this.f.item, status: this.f.status, warehouse: this.f.warehouse, batch: this.f.batch };
		frappe.call({ method: 'alpinos.production.inventory_api.' + fn, args, freeze: true })
			.then((r) => (this.tab === 'wip' ? this.render_wip(r.message || {}) : this.render_fg(r.message || {})));
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }
	num(v, p) { return format_number(flt(v), null, p == null ? 3 : p); }
	date(v) { return v ? frappe.datetime.str_to_user(v) : ''; }

	cards(items) {
		this.$w.find('.pinv-cards').html(items.map(([l, v]) =>
			`<div class="pinv-card"><div class="text-muted small">${this.esc(l)}</div><div class="v">${this.esc(v)}</div></div>`).join(''));
	}

	render_wip(d) {
		this.$w.find('.pinv-msg').text(d.message || __('Floor warehouses: {0}', [(d.warehouses || []).join(', ')]));
		const stock = d.stock || [], baked = d.baked || [];
		const by = {};
		stock.forEach((r) => { by[r.category] = (by[r.category] || 0) + 1; });
		this.cards(Object.keys(by).map((k) => [k, __('{0} items', [by[k]])]));
		const rows = stock.map((r) => `<tr>
			<td>${this.esc(r.item_code)}</td><td>${this.esc(r.item_name)}</td><td>${this.esc(r.category)}</td>
			<td>${this.esc(r.warehouse)}</td><td class="n">${this.num(r.qty)}</td><td>${this.esc(r.uom)}</td>
			<td class="n">${format_currency(r.value)}</td></tr>`).join('')
			|| `<tr><td colspan="7" class="text-muted text-center">${__('No stock on the floor.')}</td></tr>`;
		const brows = baked.map((r) => `<tr>
			<td><span class="lnk" data-sub="${this.esc(r.name)}">${this.esc(r.name)}</span></td>
			<td>${this.esc(r.batch)}</td><td>${this.esc(r.parent)}</td><td>${this.esc(r.production_item)}</td>
			<td class="n">${this.num(r.wip_qty)}</td><td>${this.date(r.last_baked_on)}</td>
			<td class="n">${r.aging_days == null ? '' : r.aging_days}</td><td>${this.esc(r.status)}</td></tr>`).join('')
			|| `<tr><td colspan="8" class="text-muted text-center">${__('No approved baked WIP waiting for filling.')}</td></tr>`;
		this.$w.find('.pinv-body').html(`
			<h5>${__('Floor Stock')}</h5>
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('Item')}</th><th>${__('Item Name')}</th><th>${__('Category')}</th><th>${__('Warehouse')}</th>
				<th class="n">${__('Qty')}</th><th>${__('UOM')}</th><th class="n">${__('Value')}</th></tr></thead>
				<tbody>${rows}</tbody></table>
			<h5>${__('Baked WIP by Sub PO (QC-approved, awaiting filling)')}</h5>
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('Sub PO')}</th><th>${__('Batch No')}</th><th>${__('Parent PO')}</th><th>${__('Item')}</th>
				<th class="n">${__('WIP (KG)')}</th><th>${__('Baked On')}</th><th class="n">${__('Aging (Days)')}</th>
				<th>${__('Status')}</th></tr></thead><tbody>${brows}</tbody></table>`);
		this.$w.find('[data-sub]').on('click', (e) => frappe.set_route('sub_order_view', $(e.currentTarget).attr('data-sub')));
	}

	render_fg(d) {
		this.$w.find('.pinv-msg').text(d.message || (d.tracked ? '' : __('FG status is not tracked yet (Filling module not installed).')));
		const t = d.totals || {};
		this.cards(Object.keys(t).map((k) => [k, this.num(t[k], 0)]));
		const badge = (s) => {
			const c = { 'FG-Cleared': 'green', 'FG-Hold': 'orange', 'QC-Rejected': 'red' }[s] || 'gray';
			return s ? `<span class="indicator-pill ${c}">${this.esc(s)}</span>` : '<span class="text-muted">-</span>';
		};
		const rows = (d.rows || []).map((r) => `<tr>
			<td>${this.esc(r.item_code)}</td><td>${this.esc(r.item_name)}</td><td>${this.esc(r.batch_no)}</td>
			<td>${badge(r.fg_status)}</td><td>${this.esc(r.warehouse)}</td><td class="n">${this.num(r.qty, 0)}</td>
			<td>${this.esc(r.uom)}</td><td class="n"><b>${this.num(r.available_for_dispatch, 0)}</b></td>
			<td>${this.date(r.mfg_date)}</td><td>${this.date(r.expiry_date)}</td>
			<td>${this.esc(r.sub_order)}</td></tr>`).join('')
			|| `<tr><td colspan="11" class="text-muted text-center">${__('No FG stock matches these filters.')}</td></tr>`;
		this.$w.find('.pinv-body').html(`
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('SKU')}</th><th>${__('SKU Name')}</th><th>${__('Batch')}</th><th>${__('Status')}</th>
				<th>${__('Warehouse')}</th><th class="n">${__('Qty')}</th><th>${__('UOM')}</th>
				<th class="n">${__('Available for Dispatch')}</th><th>${__('MFG')}</th><th>${__('Expiry')}</th>
				<th>${__('Sub PO')}</th></tr></thead><tbody>${rows}</tbody></table>`);
	}
}
