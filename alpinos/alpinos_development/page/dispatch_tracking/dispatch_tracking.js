/**
 * Dispatch Tracking (FRD 11.3) -- read-only list of Delivery Notes (the existing dispatch
 * documents): Dispatch ID, Date, Customer, Vehicle No, Total Qty, Status. Click a row to
 * see the exact batch codes that went on that truck (recall traceability).
 */

frappe.pages['dispatch_tracking'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Dispatch Tracking'), single_column: true });
	wrapper.tracking = new DispatchTracking(page);
};

frappe.pages['dispatch_tracking'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	if (wrapper.tracking) wrapper.tracking.refresh();
};

class DispatchTracking {
	constructor(page) {
		this.page = page;
		this.f = { start: 0, page_length: 50, date_from: frappe.datetime.add_days(frappe.datetime.get_today(), -30) };
		this.$w = $(page.main);
		this.$w.html(`<div class="dtrk">
			<style>.dtrk .fl { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
				.dtrk .fl > div { min-width:160px; } .dtrk td.n, .dtrk th.n { text-align:right; }
				.dtrk tbody tr { cursor:pointer; } .dtrk tbody tr:hover { background: var(--bg-light-gray, #f4f5f6); }
				.dtrk .pager { display:flex; justify-content:space-between; }</style>
			<div class="fl"></div>
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('Dispatch ID')}</th><th>${__('Date')}</th><th>${__('Customer')}</th><th>${__('Vehicle No')}</th>
				<th class="n">${__('Total Qty')}</th><th>${__('Status')}</th></tr></thead><tbody></tbody></table>
			<div class="pager"><div class="cnt text-muted"></div><div>
				<button class="btn btn-sm btn-default prev">${__('Previous')}</button>
				<button class="btn btn-sm btn-default next">${__('Next')}</button></div></div></div>`);
		const me = this;
		const reload = frappe.utils.debounce(() => { me.f.start = 0; me.refresh(); }, 300);
		[
			{ fieldname: 'search', label: __('Search (ID / Customer / Vehicle)'), fieldtype: 'Data' },
			{ fieldname: 'customer', label: __('Customer'), fieldtype: 'Link', options: 'Customer' },
			{ fieldname: 'status', label: __('Status'), fieldtype: 'Select',
				options: ['', 'Draft', 'Submitted', 'Cancelled', 'To Bill', 'Completed', 'Return Issued', 'Closed'] },
			{ fieldname: 'batch', label: __('Batch Code'), fieldtype: 'Data' },
			{ fieldname: 'item', label: __('Item / SKU'), fieldtype: 'Link', options: 'Item' },
			{ fieldname: 'date_from', label: __('From'), fieldtype: 'Date' },
			{ fieldname: 'date_to', label: __('To'), fieldtype: 'Date' },
		].forEach((df) => {
			const c = frappe.ui.form.make_control({
				df: Object.assign({ change() { me.f[df.fieldname] = this.get_value(); reload(); } }, df),
				parent: $('<div>').appendTo(this.$w.find('.fl')), render_input: true,
			});
			c.refresh();
			if (this.f[df.fieldname]) c.set_value(this.f[df.fieldname]);
		});
		this.$w.find('.prev').on('click', () => { this.f.start = Math.max(this.f.start - this.f.page_length, 0); this.refresh(); });
		this.$w.find('.next').on('click', () => { this.f.start += this.f.page_length; this.refresh(); });
		this.$w.on('click', 'tbody tr[data-name]', (e) => this.detail($(e.currentTarget).attr('data-name')));
		this.page.add_inner_button(__('Delivery Notes'), () => frappe.set_route('delivery_note_entry_list'));
		this.page.add_inner_button(__('FG Inventory'), () => frappe.set_route('production_inventory'));
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	refresh() {
		frappe.call({ method: 'alpinos.production.dispatch_rules.get_dispatch_list', args: this.f }).then((r) => {
			const d = r.message || {};
			const rows = (d.rows || []).map((x) => `<tr data-name="${this.esc(x.name)}">
				<td><b>${this.esc(x.name)}</b></td><td>${x.posting_date ? frappe.datetime.str_to_user(x.posting_date) : ''}</td>
				<td>${this.esc(x.customer_name || x.customer)}</td><td>${this.esc(x.vehicle_no)}</td>
				<td class="n">${format_number(flt(x.total_qty), null, 0)}</td>
				<td>${this.esc(cint(x.docstatus) === 0 ? 'Draft' : (cint(x.docstatus) === 2 ? 'Cancelled' : (x.workflow_state || x.status)))}</td></tr>`).join('')
				|| `<tr><td colspan="6" class="text-muted text-center">${__('No dispatches match these filters.')}</td></tr>`;
			this.$w.find('tbody').html(rows);
			const n = (d.rows || []).length;
			this.$w.find('.cnt').text(n ? __('Showing {0} - {1}', [this.f.start + 1, this.f.start + n]) : '');
			this.$w.find('.prev').prop('disabled', !this.f.start);
			this.$w.find('.next').prop('disabled', !d.has_more);
		});
	}

	detail(name) {
		frappe.call({ method: 'alpinos.production.dispatch_rules.get_dispatch_detail', args: { name } }).then((r) => {
			const d = r.message || {};
			const rows = (d.items || []).map((it) => {
				const batches = (it.batch_info || []).length
					? it.batch_info.map((b) => `<div><b>${this.esc(b.batch_no)}</b>
						${b.fg_status ? `<span class="indicator-pill ${b.fg_status === 'FG-Cleared' ? 'green' : 'orange'}">${this.esc(b.fg_status)}</span>` : ''}
						${b.sub_order ? `<span class="small text-muted">${__('Sub PO')}: ${this.esc(b.sub_order)}</span>` : ''}
						${b.expiry_date ? `<span class="small text-muted">${__('Exp')}: ${frappe.datetime.str_to_user(b.expiry_date)}</span>` : ''}</div>`).join('')
					: this.esc(it.batch_code || '-');
				return `<tr><td>${it.idx}</td><td>${this.esc(it.item_code)}<div class="small text-muted">${this.esc(it.item_name)}</div></td>
					<td style="text-align:right;">${format_number(flt(it.qty), null, 0)} ${this.esc(it.uom)}</td>
					<td>${this.esc(it.warehouse)}</td><td>${batches}</td></tr>`;
			}).join('');
			const dlg = new frappe.ui.Dialog({ title: __('Dispatch {0}', [d.name]), size: 'extra-large', fields: [{ fieldtype: 'HTML', fieldname: 'body' }] });
			dlg.fields_dict.body.$wrapper.html(`
				<div class="small" style="margin-bottom:8px;">
					<b>${__('Customer')}:</b> ${this.esc(d.customer_name || d.customer)} &middot;
					<b>${__('Date')}:</b> ${d.posting_date ? frappe.datetime.str_to_user(d.posting_date) : ''} &middot;
					<b>${__('Vehicle')}:</b> ${this.esc(d.vehicle_no || '-')} &middot;
					<b>${__('Transporter')}:</b> ${this.esc(d.transporter || '-')} &middot; <b>${__('LR')}:</b> ${this.esc(d.lr_no || '-')}
				</div>
				<table class="table table-bordered table-condensed"><thead><tr><th>#</th><th>${__('Item')}</th>
					<th style="text-align:right;">${__('Qty')}</th><th>${__('Warehouse')}</th><th>${__('Batch Codes')}</th></tr></thead>
					<tbody>${rows}</tbody></table>`);
			dlg.set_primary_action(__('Open Delivery Note'), () => { dlg.hide(); frappe.set_route('delivery_note_entry', d.name); });
			dlg.show();
		});
	}
}
