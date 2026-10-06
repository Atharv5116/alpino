/**
 * Production QC entry (/app/production_qc_entry/<PQCP-...>) -- FRD 5.1 - 5.4.
 *
 * Header from the submitted Inward Entry (read-only), observations, Approved / Rejected KG.
 * "Send For Filling" submits and locks the QC: only the Approved KG is released to Filling,
 * the Rejected KG moves to the Rejected warehouse. The server checks Approved + Rejected =
 * Total Baked Output and the rejection reason again.
 */

frappe.pages['production_qc_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Production QC'), single_column: true });
	wrapper.production_qc_entry = new ProductionQCEntry(page);
};

frappe.pages['production_qc_entry'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Production QC'), '/app/production_qc_list');
	if (wrapper.production_qc_entry) wrapper.production_qc_entry.load();
};

var ProductionQCEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	load() {
		const name = (frappe.get_route() || [])[1];
		if (!name) { frappe.set_route('production_qc_list'); return; }
		frappe.call({
			method: 'alpinos.production.production_qc.get_qc_context', args: { name }, freeze: true,
			callback: (r) => { this.ctx = r.message; this.render(); },
		});
	}

	render() {
		const c = this.ctx;
		const d = c.doc;
		const ro = c.can_write ? 0 : 1;
		this.page.set_title(__('Production QC {0}', [d.name]));
		this.page.set_indicator(__(d.status), { 'Draft': 'orange', 'Sent For Filling': 'green', 'QC Rejected': 'red' }[d.status] || 'grey');
		this.page.clear_actions();
		this.page.clear_inner_toolbar();
		this.wrapper.html(`<div style="max-width:1000px"><div class="pqe-form"></div><div class="pqe-alloc"></div></div>`);
		this.form = new frappe.ui.FieldGroup({
			body: this.wrapper.find('.pqe-form'),
			fields: [
				{ fieldtype: 'Section Break', label: __('Inspection Details') },
				{ fieldname: 'batch_number', label: __('Batch Code / UID'), fieldtype: 'Data', default: d.batch_number, read_only: 1 },
				{ fieldname: 'product', label: __('Product Name / SKU'), fieldtype: 'Data', read_only: 1,
					default: d.production_item + (d.item_name && d.item_name !== d.production_item ? ' - ' + d.item_name : '') },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'total_baked_output_kg', label: __('Total Baked Output (KG)'), fieldtype: 'Float', precision: 3,
					default: d.total_baked_output_kg, read_only: 1 },
				{ fieldname: 'inspector', label: __('QC Inspector Name'), fieldtype: 'Data', default: c.inspector_name, read_only: 1 },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'process_inward', label: __('Inward Entry'), fieldtype: 'Data', default: d.process_inward, read_only: 1 },
				{ fieldname: 'inspection_date', label: __('Inspection Date'), fieldtype: 'Date', default: d.inspection_date, read_only: ro },
				{ fieldtype: 'Section Break', label: __('Observations') },
				{ fieldname: 'observations', label: __('Observations / Test Results / Remarks'), fieldtype: 'Small Text',
					default: d.observations, read_only: ro },
				{ fieldtype: 'Section Break', label: __('QC Approval') },
				{ fieldname: 'approved_kg', label: __('Approved Qty (KG)'), fieldtype: 'Float', precision: 3, default: d.approved_kg,
					read_only: ro, change: () => this.balance('approved_kg') },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'approval_remarks', label: __('Approval Remarks'), fieldtype: 'Small Text', default: d.approval_remarks, read_only: ro },
				{ fieldtype: 'Section Break', label: __('QC Rejection') },
				{ fieldname: 'rejected_kg', label: __('Rejected Qty (KG)'), fieldtype: 'Float', precision: 3, default: d.rejected_kg,
					read_only: ro, change: () => this.balance('rejected_kg') },
				{ fieldname: 'rejection_reason', label: __('Rejection Reason'), fieldtype: 'Select', default: d.rejection_reason,
					options: [''].concat(c.rejection_reasons || []), read_only: ro,
					description: __('Mandatory if any quantity is rejected.') },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'rejection_remarks', label: __('Rejection Remarks'), fieldtype: 'Small Text', default: d.rejection_remarks, read_only: ro },
			],
		});
		this.form.make();
		this.render_alloc();
		if (c.can_write) {
			this.page.set_primary_action(__('Send For Filling'), () => this.send());
			this.page.add_inner_button(__('Save'), () => this.save());
		}
		if (d.process_inward) this.page.add_inner_button(__('Open Inward Entry'), () => frappe.set_route('process_inward_entry', d.process_inward));
		this.page.add_inner_button(__('QC List'), () => frappe.set_route('production_qc_list'));
	}

	balance(changed) {
		if (this._balancing) return;
		const total = flt(this.ctx.doc.total_baked_output_kg);
		const other = changed === 'approved_kg' ? 'rejected_kg' : 'approved_kg';
		const val = flt(this.form.get_value(changed));
		if (val > total) return;
		this._balancing = true;
		this.form.set_value(other, flt(total - val, 3)).then(() => { this._balancing = false; });
	}

	render_alloc() {
		const inward = this.ctx.inward;
		if (!inward) return;
		const rows = (inward.allocations || []).map((a) => `<tr><td>${this.esc(a.sub_order)}</td>
			<td class="text-right">${format_number(a.output_kg, null, 3)}</td><td>${this.esc(a.batch_no || '')}</td>
			<td class="text-right">${this.ctx.doc.docstatus ? format_number(a.approved_kg, null, 3) : ''}</td>
			<td class="text-right">${this.ctx.doc.docstatus ? format_number(a.rejected_kg, null, 3) : ''}</td></tr>`).join('');
		this.wrapper.find('.pqe-alloc').html(`<h6 style="margin-top:16px">${__('Sub POs')}</h6>
			<table class="table table-bordered table-sm"><thead><tr><th>${__('Sub PO')}</th><th class="text-right">${__('Output (KG)')}</th>
			<th>${__('Batch')}</th><th class="text-right">${__('Approved')}</th><th class="text-right">${__('Rejected')}</th></tr></thead>
			<tbody>${rows}</tbody></table>
			<div class="text-muted small">${__('Issued RM')}: ${format_number(inward.total_issued_rm, null, 3)} KG &middot;
			${__('Process Loss')}: ${format_number(inward.process_loss_kg, null, 3)} KG &middot; ${__('Yield')}: ${format_number(inward.yield_pct, null, 2)}%
			${this.ctx.doc.stock_entries ? '<br>' + __('Rejection transfers') + ': ' + this.esc(this.ctx.doc.stock_entries) : ''}</div>`);
	}

	payload() {
		const v = this.form.get_values(true) || {};
		const p = { name: this.ctx.doc.name };
		['inspection_date', 'observations', 'approved_kg', 'approval_remarks', 'rejected_kg', 'rejection_reason',
			'rejection_remarks'].forEach((k) => { p[k] = v[k] == null ? '' : v[k]; });
		return p;
	}

	save() {
		frappe.call({
			method: 'alpinos.production.production_qc.save_qc', args: { payload: this.payload() }, freeze: true,
			callback: () => { frappe.show_alert({ message: __('Saved'), indicator: 'green' }); this.load(); },
		});
	}

	send() {
		const p = this.payload();
		const total = flt(this.ctx.doc.total_baked_output_kg);
		if (Math.abs(flt(p.approved_kg) + flt(p.rejected_kg) - total) > 0.001) {
			frappe.msgprint(__('Approved + Rejected must equal the Total Baked Output ({0} KG).', [format_number(total, null, 3)]));
			return;
		}
		if (flt(p.rejected_kg) > 0 && !p.rejection_reason) {
			frappe.msgprint(__('Rejection Reason is mandatory when any quantity is rejected.'));
			return;
		}
		frappe.confirm(__('Send for Filling? The QC record is locked and {0} KG is released to Filling.', [format_number(p.approved_kg, null, 3)]),
			() => frappe.call({
				method: 'alpinos.production.production_qc.send_for_filling', args: { payload: p }, freeze: true,
				callback: (r) => { frappe.show_alert({ message: __('QC {0}', [__(r.message.status)]), indicator: 'green' }); this.load(); },
			}));
	}
};
