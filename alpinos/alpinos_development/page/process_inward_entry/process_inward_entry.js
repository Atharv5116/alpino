/**
 * Mixing & Baking Inward Entry (/app/process_inward_entry/<PRUN-... | PINW-...>) -- FRD 4.8 / 4.9.
 *
 * Opened from "Create Inward Entry" on the Shop Floor with the Production Run, or with an
 * existing Process Inward. One scrollable sheet: header (auto), Mass Mixing, Baking with the
 * oven grid, Output / Manpower, and the read-only Mass Balance footer. The server computes
 * the footer again on save and enforces every rule.
 */

frappe.pages['process_inward_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Inward Entry'), single_column: true });
	wrapper.process_inward_entry = new ProcessInwardEntry(page);
};

frappe.pages['process_inward_entry'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Shop Floor'), '/app/production_floor');
	if (wrapper.process_inward_entry) wrapper.process_inward_entry.load();
};

var ProcessInwardEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	load() {
		const key = (frappe.get_route() || [])[1] || '';
		if (!key) {
			this.wrapper.html(`<div class="text-muted" style="padding:40px;text-align:center">
				${__('Open this screen from Create Inward Entry on the Shop Floor.')}</div>`);
			return;
		}
		const args = key.startsWith('PINW-') ? { name: key } : { production_run: key };
		frappe.call({
			method: 'alpinos.production.execution_inward.get_inward_context', args, freeze: true,
			callback: (r) => { this.ctx = r.message; this.render(); },
		});
	}

	fields(d, ro) {
		const RO = 1;
		const ovens = (this.ctx.ovens || []);
		return [
			{ fieldtype: 'Section Break', label: __('Header') },
			{ fieldname: 'posting_date', label: __('Date / Day'), fieldtype: 'Date', default: d.posting_date, read_only: ro, reqd: 1 },
			{ fieldname: 'shift', label: __('Shift'), fieldtype: 'Data', default: d.shift, read_only: ro },
			{ fieldname: 'shift_start', label: __('Shift Start Time'), fieldtype: 'Time', default: d.shift_start, read_only: ro },
			{ fieldname: 'shift_end', label: __('Shift End Time'), fieldtype: 'Time', default: d.shift_end, read_only: ro },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'batch_number', label: __('UID / Batch Code'), fieldtype: 'Data', default: d.batch_number, read_only: RO },
			{ fieldname: 'production_item', label: __('Product / SKU'), fieldtype: 'Data',
				default: d.production_item + (d.item_name && d.item_name !== d.production_item ? ' - ' + d.item_name : ''), read_only: RO },
			{ fieldname: 'process_label', label: __('Process'), fieldtype: 'Data', default: this.ctx.process_label || d.process_master, read_only: RO },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'run_start', label: __('Start Time'), fieldtype: 'Datetime', default: d.run_start, read_only: RO },
			{ fieldname: 'run_end', label: __('End Time'), fieldtype: 'Datetime', default: d.run_end, read_only: RO },
			{ fieldname: 'production_run', label: __('Production Run'), fieldtype: 'Data', default: d.production_run, read_only: RO },

			{ fieldtype: 'Section Break', label: __('Mass Mixing') },
			{ fieldname: 'mixing_start', label: __('Mixing Start Time'), fieldtype: 'Time', default: d.mixing_start, read_only: ro },
			{ fieldname: 'mixing_end', label: __('Mixing End Time'), fieldtype: 'Time', default: d.mixing_end, read_only: ro },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'total_batch', label: __('Total Batch'), fieldtype: 'Int', default: d.total_batch, read_only: ro },
			{ fieldname: 'mixing_wastage_kg', label: __('Wastage (KG)'), fieldtype: 'Float', precision: 3,
				default: d.mixing_wastage_kg, read_only: ro, change: () => this.recalc() },

			{ fieldtype: 'Section Break', label: __('Baking') },
			{ fieldname: 'total_output_kg', label: __('Total Output (KG)'), fieldtype: 'Float', precision: 3, default: d.total_output_kg, read_only: ro },
			{ fieldname: 'first_batch_in', label: __('First Batch IN'), fieldtype: 'Time', default: d.first_batch_in, read_only: ro },
			{ fieldname: 'last_batch_out', label: __('Last Batch OUT'), fieldtype: 'Time', default: d.last_batch_out, read_only: ro },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'baking_wastage_kg', label: __('Total Baking Wastage (KG)'), fieldtype: 'Float', precision: 3,
				default: d.baking_wastage_kg, read_only: ro, change: () => this.recalc() },
			{ fieldtype: 'Section Break', label: __('Oven Grid') },
			{ fieldname: 'ovens', fieldtype: 'Table', label: __('Ovens'), read_only: ro, cannot_add_rows: ro, cannot_delete_rows: ro,
				in_place_edit: true, data: (d.ovens || []).map((o) => Object.assign({}, o)),
				get_data: () => this.oven_rows || [],
				fields: [
					{ fieldname: 'oven', label: __('Oven No.'), fieldtype: 'Select', in_list_view: 1, reqd: 1, read_only: ro,
						options: [''].concat(ovens.map((o) => o.name)),
						description: ovens.map((o) => `${o.name}: ${o.machine_name}`).join(', ') },
					{ fieldname: 'no_of_batches', label: __('No of Batch'), fieldtype: 'Int', in_list_view: 1, read_only: ro },
					{ fieldname: 'time_mins', label: __('Time (Mins)'), fieldtype: 'Int', in_list_view: 1, read_only: ro },
					{ fieldname: 'temp_c', label: __('Temp (°C)'), fieldtype: 'Int', in_list_view: 1, read_only: ro },
				] },

			{ fieldtype: 'Section Break', label: __('Output, Manpower & Remarks') },
			{ fieldname: 'actual_output_kg', label: __('Actual Output (KG)'), fieldtype: 'Float', precision: 3,
				default: d.actual_output_kg, read_only: ro, reqd: this.ctx.posts_stock ? 1 : 0, change: () => this.recalc() },
			{ fieldname: 'total_wastage_kg', label: __('Total Wastage (KG)'), fieldtype: 'Float', precision: 3,
				default: d.total_wastage_kg, read_only: ro, description: __('Blank = Mixing + Baking wastage') },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'supervisor_count', label: __('Supervisor'), fieldtype: 'Int', default: d.supervisor_count, read_only: ro },
			{ fieldname: 'operator_count', label: __('Operator'), fieldtype: 'Int', default: d.operator_count, read_only: ro },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'hh_labour_count', label: __('HH Labour'), fieldtype: 'Int', default: d.hh_labour_count, read_only: ro },
			{ fieldname: 'ahf_labour_count', label: __('AHF Labour'), fieldtype: 'Int', default: d.ahf_labour_count, read_only: ro },
			{ fieldtype: 'Section Break' },
			{ fieldname: 'remark', label: __('Remark'), fieldtype: 'Small Text', default: d.remark, read_only: ro },

			{ fieldtype: 'Section Break', label: __('Mass Balance (auto)') },
			{ fieldname: 'total_issued_rm', label: __('Total Issued RM (KG)'), fieldtype: 'Float', precision: 3, default: d.total_issued_rm, read_only: RO },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'process_loss_kg', label: __('Process Loss (KG)'), fieldtype: 'Float', precision: 3, default: d.process_loss_kg, read_only: RO },
			{ fieldtype: 'Column Break' },
			{ fieldname: 'yield_pct', label: __('Actual Yield %'), fieldtype: 'Percent', default: d.yield_pct, read_only: RO },
			{ fieldtype: 'Section Break', label: __('Distribution To Sub POs') },
			{ fieldname: 'alloc_html', fieldtype: 'HTML' },
		];
	}

	render() {
		const c = this.ctx;
		const d = c.doc;
		const ro = c.can_write ? 0 : 1;
		this.page.set_title(d.name ? __('Inward Entry {0}', [d.name]) : __('New Inward Entry'));
		this.page.clear_actions();
		this.page.clear_inner_toolbar();
		this.page.set_indicator(__(d.status || 'Draft'), { 'Draft': 'orange', 'Inward Logged': 'blue',
			'Pending QC': 'orange', 'Ready for Next Stage': 'green', 'QC Done': 'green', 'Reversed': 'red' }[d.status] || 'grey');

		this.render_frame();
		this.oven_rows = (d.ovens || []).map((o) => Object.assign({}, o));
		this.form = new frappe.ui.FieldGroup({ fields: this.fields(d, ro), body: this.wrapper.find('.pie-form') });
		this.form.make();
		this.form.fields_dict.ovens.df.data = this.oven_rows;
		this.form.fields_dict.ovens.grid.refresh();
		this.render_alloc();
		this.recalc();

		if (c.can_write) {
			this.page.set_primary_action(__('Submit & Send for QC'), () => this.submit(1));
			this.page.add_inner_button(__('Submit'), () => this.submit(0));
			this.page.add_inner_button(__('Save Draft'), () => this.save());
		}
		if (c.can_send_qc) this.page.set_primary_action(__('Send for QC'), () => this.send_qc());
		if (d.production_qc) this.page.add_inner_button(__('Open Production QC'), () => frappe.set_route('production_qc_entry', d.production_qc));
		if (c.can_reverse) this.page.add_inner_button(__('Reverse Inward'), () => this.reverse());
		this.page.add_inner_button(__('Shop Floor'), () => frappe.set_route('production_floor'));
	}

	render_frame() {
		const d = this.ctx.doc;
		const sig = d.submitted_by
			? `<div class="text-muted small" style="margin:8px 0">${__('Submitted by')} <b>${this.esc(this.ctx.submitted_by_name || d.submitted_by)}</b>
				${d.submitted_on ? __('at') + ' ' + frappe.datetime.str_to_user(d.submitted_on) : ''}</div>` : '';
		const rev = d.reversal_reason ? `<div class="alert alert-danger">${__('Reversed')}: ${this.esc(d.reversal_reason)}</div>` : '';
		const note = this.ctx.posts_stock ? '' : `<div class="alert alert-info small">${__('This process does not post stock: the WIP is generated by the final pre-filling process.')}</div>`;
		this.wrapper.html(`<div class="pie" style="max-width:1100px">${rev}${note}<div class="pie-form"></div>${sig}</div>`);
	}

	render_alloc() {
		const rows = (this.ctx.doc.allocations || []).map((a) => `<tr>
			<td><a href="/app/sub_order_view/${encodeURIComponent(a.sub_order)}">${this.esc(a.sub_order)}</a></td>
			<td class="text-right">${format_number(a.planned_qty, null, 3)}</td>
			<td class="text-right">${format_number(a.share_pct, null, 2)}%</td>
			<td class="text-right">${format_number(a.issued_rm_kg, null, 3)}</td>
			<td class="text-right">${format_number(a.output_kg, null, 3)}</td>
			<td class="text-right">${format_number(a.loss_kg, null, 3)}</td>
			<td>${this.esc(a.batch_no || '')}</td>
			<td>${a.stock_entry ? `<a href="/app/stock-entry/${encodeURIComponent(a.stock_entry)}">${this.esc(a.stock_entry)}</a>` : ''}</td></tr>`).join('');
		this.form.fields_dict.alloc_html.$wrapper.html(`<table class="table table-bordered table-sm">
			<thead><tr><th>${__('Sub PO')}</th><th class="text-right">${__('Planned (KG)')}</th><th class="text-right">${__('Share')}</th>
			<th class="text-right">${__('Issued RM')}</th><th class="text-right">${__('Output')}</th><th class="text-right">${__('Loss')}</th>
			<th>${__('Batch')}</th><th>${__('Stock Entry')}</th></tr></thead><tbody>${rows}</tbody></table>
			<div class="text-muted small">${__('Output and loss are split by planned quantity (BR-MRG-04) when the run is saved.')}</div>`);
	}

	recalc() {
		if (!this.form) return;
		const v = (k) => flt(this.form.get_value(k));
		const issued = flt(this.ctx.doc.total_issued_rm);
		const out = v('actual_output_kg');
		const loss = issued - (out + v('mixing_wastage_kg') + v('baking_wastage_kg'));
		this.form.set_value('process_loss_kg', flt(loss, 3));
		this.form.set_value('yield_pct', issued ? flt(out / issued * 100, 2) : 0);
	}

	payload() {
		const v = this.form.get_values(true) || {};
		const p = { name: this.ctx.doc.name || null, production_run: this.ctx.doc.production_run };
		['posting_date', 'shift', 'shift_start', 'shift_end', 'mixing_start', 'mixing_end', 'total_batch',
			'mixing_wastage_kg', 'total_output_kg', 'first_batch_in', 'last_batch_out', 'baking_wastage_kg',
			'actual_output_kg', 'total_wastage_kg', 'supervisor_count', 'operator_count', 'hh_labour_count',
			'ahf_labour_count', 'remark'].forEach((k) => { p[k] = v[k] == null ? '' : v[k]; });
		p.ovens = (this.form.fields_dict.ovens.grid.get_data() || []).map((r) => ({
			oven: r.oven, no_of_batches: r.no_of_batches, time_mins: r.time_mins, temp_c: r.temp_c }));
		return p;
	}

	save(after) {
		frappe.call({
			method: 'alpinos.production.execution_inward.save_inward', args: { payload: this.payload() }, freeze: true,
			callback: (r) => {
				const name = r.message.name;
				if (after) return after(name);
				frappe.show_alert({ message: __('Saved'), indicator: 'green' });
				if ((frappe.get_route() || [])[1] !== name) frappe.set_route('process_inward_entry', name);
				else this.load();
			},
		});
	}

	submit(send_for_qc) {
		const msg = send_for_qc
			? __('Submit this Inward Entry and send it for QC? The sheet is locked after submission.')
			: __('Submit this Inward Entry? The sheet is locked after submission.');
		frappe.confirm(msg, () => this.save((name) => {
			frappe.call({
				method: 'alpinos.production.execution_inward.submit_inward', args: { name, send_for_qc }, freeze: true,
				callback: (r) => {
					const m = r.message || {};
					frappe.show_alert({ message: __('Inward submitted: {0}', [__(m.status)]), indicator: 'green' });
					if (send_for_qc && m.production_qc) frappe.set_route('production_qc_entry', m.production_qc);
					else frappe.set_route('process_inward_entry', name);
					if (!send_for_qc) this.load();
				},
			});
		}));
	}

	send_qc() {
		frappe.call({
			method: 'alpinos.production.execution_inward.send_inward_for_qc', args: { name: this.ctx.doc.name }, freeze: true,
			callback: (r) => frappe.set_route('production_qc_entry', r.message.production_qc),
		});
	}

	reverse() {
		frappe.prompt([{ fieldname: 'reason', label: __('Reason for reversal'), fieldtype: 'Small Text', reqd: 1 }],
			(v) => frappe.call({
				method: 'alpinos.production.execution_inward.reverse_inward', args: { name: this.ctx.doc.name, reason: v.reason },
				freeze: true, callback: () => { frappe.show_alert({ message: __('Inward reversed'), indicator: 'orange' }); this.load(); },
			}), __('Reverse Inward Entry'), __('Reverse'));
	}
};
