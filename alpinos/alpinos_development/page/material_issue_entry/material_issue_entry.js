/**
 * Material Issue — add / view screen (Material Management).
 *
 * An issue always starts from a Material Request that is Pending Issue or Partially
 * Issued; its pending rows load into the grid with the Actual Issue Qty prefilled. A row
 * left at 0 is simply not issued. Batch-managed items need a batch: the earliest-expiring
 * batch with enough stock (FEFO) is suggested. Every rule is enforced again on the server.
 */

frappe.pages['material_issue_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Material Issue'),
		single_column: true,
	});
	wrapper.material_issue_entry = new MaterialIssueEntry(page);
};

frappe.pages['material_issue_entry'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) {
		alpinos_production_breadcrumb(__('Material Issues'), '/app/material_issue_list');
	}
	if (wrapper.material_issue_entry) wrapper.material_issue_entry.handle_route();
};

var MaterialIssueEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.ctx = {};
		this.rows = [];
		this.render_shell();
		this.make_fields();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="mm-entry">
				<style>
					.mm-entry .mm-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e2e2);
						border-radius: 8px; padding: 16px 18px; margin-bottom: 16px; }
					.mm-entry .mm-card > h5 { margin: 0 0 14px; font-size: 13px; text-transform: uppercase;
						letter-spacing: .4px; color: var(--text-muted); }
					.mm-entry .mm-actionbar { display: flex; justify-content: flex-end; align-items: center;
						margin-bottom: 14px; flex-wrap: wrap; gap: 6px; }
					.mm-entry table.mm-grid { width: 100%; }
					.mm-entry table.mm-grid th, .mm-entry table.mm-grid td { font-size: 12.5px; vertical-align: middle; }
					.mm-entry .mm-num { text-align: right; white-space: nowrap; }
					.mm-entry .mm-short { color: var(--red-600, #c0392b); font-weight: 600; }
					.mm-entry .mm-grid .frappe-control, .mm-entry .mm-grid .form-group { margin-bottom: 0; }
					.mm-entry .mm-note { color: var(--text-muted); font-size: 12px; margin-top: 6px; }
				</style>
				<div class="mm-banner"></div>
				<div class="mm-actionbar"></div>
				<div class="mm-card">
					<h5>${__('Issue Details')}</h5>
					<div class="row">
						<div class="col-md-3 f-name"></div>
						<div class="col-md-3 f-mr"></div>
						<div class="col-md-3 f-sub"></div>
						<div class="col-md-3 f-parent"></div>
					</div>
					<div class="row">
						<div class="col-md-3 f-fg"></div>
						<div class="col-md-3 f-type"></div>
						<div class="col-md-3 f-date"></div>
						<div class="col-md-3 f-by"></div>
					</div>
					<div class="row">
						<div class="col-md-3 f-status"></div>
						<div class="col-md-9 f-remarks"></div>
					</div>
				</div>
				<div class="mm-card">
					<h5>${__('Materials')}</h5>
					<div class="mm-rows"></div>
					<div class="mm-note">${__('Actual Issue Qty cannot exceed the pending quantity of the request or the stock in the source warehouse. Rows left at 0 are not issued.')}</div>
				</div>
				<div class="mm-card mm-returns-card" style="display:none;">
					<h5>${__('Return History')}</h5>
					<div class="mm-returns"></div>
				</div>
			</div>
		`);
	}

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		parent.empty();
		const control = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		control.refresh();
		control.set_value(value == null ? '' : value);
		this.fields[df.fieldname] = control;
		return control;
	}

	_set(f, v) { const c = this.fields[f]; if (c) c.set_value(v == null ? '' : v); }
	_val(f) { const c = this.fields[f]; return c ? c.get_value() : null; }
	_readonly(f, ro) { const c = this.fields[f]; if (c) { c.df.read_only = ro ? 1 : 0; c.refresh(); } }

	make_fields() {
		const me = this;
		this._ctl('.f-name', { fieldname: 'name', label: __('MI ID'), read_only: 1, description: __('Assigned on save.') });
		this._ctl('.f-mr', {
			fieldname: 'material_request', label: __('Linked MR'), fieldtype: 'Link', options: 'Material Request', reqd: 1,
			description: __('Only requests that are Pending Issue or Partially Issued.'),
			get_query() { return { query: 'alpinos.production.material_issue.mr_query' }; },
			change() { me.on_mr(this.get_value()); },
		});
		this._ctl('.f-sub', { fieldname: 'sub_order', label: __('Sub PO'), read_only: 1 });
		this._ctl('.f-parent', { fieldname: 'parent', label: __('Parent PO'), read_only: 1 });
		this._ctl('.f-fg', { fieldname: 'fg_item', label: __('Target FG'), read_only: 1 });
		this._ctl('.f-type', { fieldname: 'production_type', label: __('Production Type'), read_only: 1 });
		this._ctl('.f-date', {
			fieldname: 'posting_date', label: __('Issue Date'), fieldtype: 'Date', reqd: 1,
			description: __('Today or earlier.'),
		}, frappe.datetime.get_today());
		this._ctl('.f-by', { fieldname: 'issued_by', label: __('Issued By'), read_only: 1 });
		this._ctl('.f-status', { fieldname: 'status', label: __('Status'), read_only: 1 }, 'Draft');
		this._ctl('.f-remarks', { fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text' });
	}

	handle_route() {
		const route = frappe.get_route() || [];
		this.docname = route[1] && route[1] !== 'new' ? route[1] : null;
		this.load();
	}

	load() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.material_issue.get_mi_context',
			args: { stock_entry: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message || docname !== me.docname) return;
				me.ctx = r.message;
				if (me.ctx.doc) me.fill(me.ctx.doc); else me.reset();
				me.apply_state();
			},
		});
	}

	reset() {
		['name', 'material_request', 'sub_order', 'parent', 'fg_item', 'production_type', 'remarks'].forEach((f) => this._set(f, ''));
		this._set('posting_date', frappe.datetime.get_today());
		this._set('status', 'Draft');
		this._set('issued_by', this.ctx.issued_by || '');
		this.rows = [];
		this.page.set_title(__('New Material Issue'));
		const opts = frappe.route_options || {};
		frappe.route_options = null;
		if (opts.material_request) this._set('material_request', opts.material_request);
	}

	fill(doc) {
		this._set('name', doc.name);
		this._set('material_request', doc.material_request);
		this._set('sub_order', doc.sub_order);
		this._set('parent', doc.parent);
		this._set('fg_item', doc.fg_item_name && doc.fg_item_name !== doc.fg_item ? `${doc.fg_item} — ${doc.fg_item_name}` : doc.fg_item);
		this._set('production_type', doc.production_type);
		this._set('posting_date', doc.posting_date);
		this._set('issued_by', doc.issued_by);
		this._set('status', doc.status);
		this._set('remarks', doc.remarks);
		this.rows = (doc.items || []).map((r) => Object.assign({}, r));
		this.page.set_title(`${doc.name} — ${doc.status}`);
	}

	editable() {
		return !!cint(this.ctx.can_write) && (!this.ctx.doc || cint(this.ctx.doc.docstatus) === 0);
	}

	apply_state() {
		const ed = this.editable();
		this._readonly('material_request', !(ed && !this.ctx.doc));
		this._readonly('posting_date', !ed);
		this._readonly('remarks', !ed);
		const $b = this.wrapper.find('.mm-banner').empty();
		if (!this.ctx.main_warehouse || !this.ctx.wip_warehouse) {
			$b.html(`<div class="alert alert-warning">${__('Set the Main and WIP warehouses in Production Settings before issuing.')}</div>`);
		}
		this.render_rows();
		this.render_returns();
		this.make_actions();
	}

	on_mr(mr) {
		const me = this;
		if (!this.editable() || this.ctx.doc) return;
		if (!mr) {
			['sub_order', 'parent', 'fg_item', 'production_type'].forEach((f) => this._set(f, ''));
			this.rows = [];
			this.render_rows();
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_issue.mr_pending_rows',
			args: { material_request: mr },
			callback(r) {
				const m = r.message;
				if (!m || me._val('material_request') !== mr) return;
				me._set('sub_order', m.sub_order);
				me._set('parent', m.parent);
				me._set('fg_item', m.fg_item_name && m.fg_item_name !== m.fg_item ? `${m.fg_item} — ${m.fg_item_name}` : m.fg_item);
				me._set('production_type', m.production_type);
				me.rows = (m.rows || []).map((row) => Object.assign({}, row));
				me.render_rows();
			},
		});
	}

	// --------------------------------------------------------------- grid

	render_rows() {
		const me = this;
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const num = (v) => esc(format_number(flt(v), null, 3));
		const ed = this.editable();
		const $out = this.wrapper.find('.mm-rows').empty();
		let html = '<table class="table table-bordered table-condensed mm-grid"><thead><tr>';
		html += `<th style="width:30px;">#</th><th style="width:70px;">${__('Type')}</th>`;
		html += `<th style="width:130px;">${__('Item')}</th><th>${__('Item Name')}</th><th style="width:50px;">${__('UOM')}</th>`;
		html += `<th style="width:100px;" class="mm-num">${__('Total Required')}</th>`;
		html += `<th style="width:110px;" class="mm-num">${__('Actual Issue Qty')}</th>`;
		html += `<th style="width:90px;" class="mm-num">${__('Available')}</th>`;
		html += `<th style="width:150px;">${__('Batch No')}</th>`;
		html += `<th style="width:150px;">${__('Source Warehouse')}</th>`;
		html += `<th style="width:130px;">${__('Target Warehouse')}</th>`;
		html += `<th style="width:130px;">${__('Remarks')}</th>`;
		html += '</tr></thead><tbody>';
		if (!this.rows.length) {
			html += `<tr><td colspan="12" class="text-muted" style="text-align:center;">${
				__('Choose the Material Request, and its pending rows appear here.')}</td></tr>`;
		}
		this.rows.forEach((row, idx) => {
			html += `<tr data-idx="${idx}">`;
			html += `<td>${idx + 1}</td><td>${esc(row.material_type)}</td><td>${esc(row.item_code)}</td>`;
			html += `<td>${esc(row.item_name)}</td><td>${esc(row.uom)}</td>`;
			html += `<td class="mm-num">${num(row.required_qty)}</td>`;
			html += `<td class="mm-num c-qty">${ed ? '' : num(row.qty)}</td>`;
			html += `<td class="mm-num c-avail">${num(row.available_qty)}</td>`;
			html += `<td class="c-batch">${ed && cint(row.has_batch_no) ? '' : esc(row.batch_no || (cint(row.has_batch_no) ? '' : '—'))}</td>`;
			html += `<td class="c-src">${ed ? '' : esc(row.s_warehouse)}</td>`;
			html += `<td>${esc(row.t_warehouse)}</td>`;
			html += `<td class="c-rem">${ed ? '' : esc(row.line_remarks)}</td>`;
			html += '</tr>';
		});
		html += '</tbody></table>';
		$out.html(html);
		if (!ed) return;

		$out.find('tr[data-idx]').each(function () {
			const idx = cint($(this).attr('data-idx'));
			const row = me.rows[idx];
			const $tr = $(this);
			me._cell($tr.find('.c-qty'), { fieldtype: 'Float', precision: 3 }, row.qty, (v) => {
				row.qty = flt(v);
				me.mark_available($tr, row);
			});
			if (cint(row.has_batch_no)) {
				me._cell($tr.find('.c-batch'), {
					fieldtype: 'Link', options: 'Batch',
					get_query() { return { filters: { item: row.item_code, disabled: 0 } }; },
				}, row.batch_no, (v) => { row.batch_no = v; me.refresh_available(row, $tr); });
			}
			me._cell($tr.find('.c-src'), {
				fieldtype: 'Link', options: 'Warehouse',
				get_query() { return { filters: { is_group: 0, disabled: 0 } }; },
			}, row.s_warehouse, (v) => { row.s_warehouse = v; me.refresh_available(row, $tr); });
			me._cell($tr.find('.c-rem'), { fieldtype: 'Data' }, row.line_remarks, (v) => { row.line_remarks = v; });
			me.mark_available($tr, row);
		});
	}

	_cell($parent, df, value, onchange) {
		const control = frappe.ui.form.make_control({
			df: Object.assign({ fieldname: 'cell_' + Math.random().toString(36).slice(2) }, df, {
				change() { onchange(this.get_value()); },
			}),
			parent: $parent,
			render_input: true,
			only_input: true,
		});
		control.refresh();
		control.set_value(value == null ? '' : value);
		return control;
	}

	mark_available($tr, row) {
		$tr.find('.c-avail').text(format_number(flt(row.available_qty), null, 3))
			.toggleClass('mm-short', flt(row.qty) > flt(row.available_qty));
	}

	refresh_available(row, $tr) {
		const me = this;
		if (!row.s_warehouse) return;
		if (cint(row.has_batch_no)) {
			frappe.call({
				method: 'alpinos.production.material_issue.item_batches',
				args: { item_code: row.item_code, warehouse: row.s_warehouse },
				callback(r) {
					const list = r.message || [];
					const hit = list.find((b) => b.batch_no === row.batch_no);
					row.available_qty = hit ? flt(hit.qty) : 0;
					me.mark_available($tr, row);
				},
			});
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_request.item_row_info',
			args: { item_code: row.item_code, warehouse: row.s_warehouse },
			callback(r) {
				row.available_qty = flt((r.message || {}).available_qty);
				me.mark_available($tr, row);
			},
		});
	}

	render_returns() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const list = this.ctx.returns || [];
		this.wrapper.find('.mm-returns-card').toggle(!!(this.ctx.doc && list.length));
		if (!list.length) return;
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th>${__('Material Return')}</th><th>${__('Return Date')}</th><th>${__('Returned By')}</th>`;
		html += `<th class="mm-num">${__('Qty')}</th><th>${__('Status')}</th></tr></thead><tbody>`;
		list.forEach((r) => {
			html += `<tr class="mm-ret-row" data-name="${esc(r.name)}" style="cursor:pointer;"><td>${esc(r.name)}</td>`;
			html += `<td>${esc(frappe.datetime.str_to_user(r.posting_date))}</td><td>${esc(r.by)}</td>`;
			html += `<td class="mm-num">${esc(format_number(flt(r.qty), null, 3))}</td><td>${esc(r.status)}</td></tr>`;
		});
		html += '</tbody></table>';
		const $out = this.wrapper.find('.mm-returns').html(html);
		$out.find('.mm-ret-row').on('click', function () {
			frappe.set_route('material_return_entry', $(this).attr('data-name'));
		});
	}

	// ------------------------------------------------------------ actions

	make_actions() {
		const me = this;
		const c = this.ctx;
		const $bar = this.wrapper.find('.mm-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
		};
		if (this.editable()) btn(__('Save'), 'btn-primary', () => me.save());
		if (this.docname && cint(c.can_submit)) btn(__('Submit'), 'btn-primary', () => me.submit());
		if (this.docname) {
			btn(__('Print Issue Slip'), 'btn-default', () => window.open(
				`/printview?doctype=${encodeURIComponent('Stock Entry')}&name=${encodeURIComponent(me.docname)}`
				+ `&format=${encodeURIComponent('Material Issue Slip')}&no_letterhead=0`, '_blank'));
		}
		if (this.docname && cint(c.can_return)) {
			btn(__('Create Return'), 'btn-primary', () => {
				frappe.route_options = { material_issue: me.docname };
				frappe.set_route('material_return_entry', 'new');
			});
		}
		if (this.docname && cint(c.can_cancel)) btn(__('Cancel'), 'btn-danger', () => me.cancel());
		if (this.docname && cint(c.can_delete)) btn(__('Delete'), 'btn-danger', () => me.remove());
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('material_issue_list'));
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			material_request: this._val('material_request'),
			posting_date: this._val('posting_date'),
			remarks: this._val('remarks'),
			items: this.rows.map((r) => ({
				mr_item: r.mr_item, item_code: r.item_code, qty: flt(r.qty),
				batch_no: r.batch_no || '', s_warehouse: r.s_warehouse, t_warehouse: r.t_warehouse,
				line_remarks: r.line_remarks || '',
			})),
		};
	}

	save(then) {
		const me = this;
		if (this._val('posting_date') && this._val('posting_date') > frappe.datetime.get_today()) {
			frappe.msgprint({ title: __('Invalid Issue Date'), indicator: 'orange', message: __('The Issue Date cannot be in the future.') });
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_issue.save_mi',
			args: { payload: this.collect() },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved'), indicator: 'green' }, 4);
				if (me.docname !== r.message.name) {
					frappe.set_route('material_issue_entry', r.message.name);
				} else {
					me.load();
				}
				if (then) then(r.message.name);
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(__('Submit {0}? Stock moves to the WIP warehouse now.', [this.docname]), () => {
			const go = () => frappe.call({
				method: 'alpinos.production.material_issue.submit_mi',
				args: { stock_entry: me.docname },
				freeze: true,
				freeze_message: __('Submitting...'),
				callback(r) {
					if (!r.message) return;
					frappe.show_alert({ message: __('Submitted'), indicator: 'green' }, 4);
					me.load();
				},
			});
			if (me.editable()) me.save(go); else go();
		});
	}

	cancel() {
		const me = this;
		frappe.confirm(__('Cancel {0}? The stock goes back to the source warehouse and the request is reopened.', [this.docname]), () => {
			frappe.call({
				method: 'alpinos.production.material_issue.cancel_mi',
				args: { stock_entry: me.docname },
				freeze: true,
				freeze_message: __('Cancelling...'),
				callback(r) {
					if (!r.message) return;
					frappe.show_alert({ message: __('Cancelled'), indicator: 'orange' }, 4);
					me.load();
				},
			});
		});
	}

	remove() {
		const me = this;
		frappe.confirm(__('Delete draft {0}?', [this.docname]), () => {
			frappe.call({
				method: 'alpinos.production.material_issue.delete_entry',
				args: { stock_entry: me.docname },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					frappe.set_route('material_issue_list');
				},
			});
		});
	}
};
