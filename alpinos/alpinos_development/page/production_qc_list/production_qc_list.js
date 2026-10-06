/**
 * Production QC list (/app/production_qc_list) -- FRD Phase 5.
 * Draft inspections first (the QC Inspector's queue), then the sent ones.
 */

frappe.pages['production_qc_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Production QC'), single_column: true });
	wrapper.production_qc_list = new ProductionQCList(page);
};

frappe.pages['production_qc_list'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb();
	if (wrapper.production_qc_list) wrapper.production_qc_list.refresh();
};

var ProductionQCList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.start = 0;
		this.page_length = 50;
		const go = () => { this.start = 0; this.refresh(); };
		this.f = {
			search: page.add_field({ fieldname: 'search', label: __('QC / Sub PO / Batch / Item'), fieldtype: 'Data', change: go }),
			status: page.add_field({ fieldname: 'status', label: __('Status'), fieldtype: 'Select',
				options: ['', 'Draft', 'Sent For Filling', 'QC Rejected'], change: go }),
			date_from: page.add_field({ fieldname: 'date_from', label: __('From'), fieldtype: 'Date', change: go }),
			date_to: page.add_field({ fieldname: 'date_to', label: __('To'), fieldtype: 'Date', change: go }),
		};
		page.set_primary_action(__('Refresh'), () => this.refresh(), 'refresh');
		page.add_inner_button(__('Shop Floor'), () => frappe.set_route('production_floor'));
		this.wrapper.html(`<div class="pql"><div class="pql-body"></div>
			<div class="pql-more" style="margin-top:10px;text-align:center"></div></div>`);
		this.wrapper.on('click', '.pql-row', function () { frappe.set_route('production_qc_entry', $(this).attr('data-name')); });
		this.wrapper.on('click', '.pql-next', () => { this.start += this.page_length; this.refresh(); });
		this.wrapper.on('click', '.pql-prev', () => { this.start = Math.max(this.start - this.page_length, 0); this.refresh(); });
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	refresh() {
		const v = (k) => this.f[k].get_value() || null;
		frappe.call({
			method: 'alpinos.production.production_qc.get_qc_list',
			args: { search: v('search'), status: v('status'), date_from: v('date_from'), date_to: v('date_to'),
				start: this.start, page_length: this.page_length },
			callback: (r) => this.render(r.message || {}),
		});
	}

	render(m) {
		const ind = { 'Draft': 'orange', 'Sent For Filling': 'green', 'QC Rejected': 'red' };
		const rows = (m.data || []).map((r) => `
			<tr class="pql-row" data-name="${this.esc(r.name)}" style="cursor:pointer">
				<td><b>${this.esc(r.name)}</b></td>
				<td>${this.esc(r.batch_number || '')}</td>
				<td>${this.esc(r.sub_order || r.member_sub_orders || '')}</td>
				<td>${this.esc(r.production_item)}${r.item_name && r.item_name !== r.production_item ? '<div class="text-muted small">' + this.esc(r.item_name) + '</div>' : ''}</td>
				<td class="text-right">${format_number(r.total_baked_output_kg, null, 3)}</td>
				<td class="text-right">${r.docstatus ? format_number(r.approved_kg, null, 3) : ''}</td>
				<td class="text-right">${r.docstatus ? format_number(r.rejected_kg, null, 3) : ''}</td>
				<td><span class="indicator-pill ${ind[r.status] || 'grey'}">${this.esc(__(r.status))}</span></td>
				<td>${this.esc(r.inspector_name || '')}</td>
				<td>${r.creation ? frappe.datetime.str_to_user(r.creation) : ''}</td>
			</tr>`).join('');
		this.wrapper.find('.pql-body').html(rows ? `<div style="overflow-x:auto"><table class="table table-bordered table-hover">
			<thead><tr><th>${__('QC')}</th><th>${__('Batch')}</th><th>${__('Sub PO')}</th><th>${__('Product')}</th>
			<th class="text-right">${__('Baked Output (KG)')}</th><th class="text-right">${__('Approved')}</th>
			<th class="text-right">${__('Rejected')}</th><th>${__('Status')}</th><th>${__('Inspector')}</th><th>${__('Created')}</th></tr></thead>
			<tbody>${rows}</tbody></table></div>`
			: `<div class="text-muted" style="padding:40px;text-align:center">${__('No Production QC records.')}</div>`);
		this.wrapper.find('.pql-more').html(
			(this.start ? `<button class="btn btn-sm btn-default pql-prev">${__('Previous')}</button> ` : '')
			+ (m.has_more ? `<button class="btn btn-sm btn-default pql-next">${__('Next')}</button>` : ''));
	}
};
