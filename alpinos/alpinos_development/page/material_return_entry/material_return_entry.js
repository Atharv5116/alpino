/**
 * Material Return — add / view screen (Material Management).
 *
 * A return always starts from a submitted Material Issue that still has a balance; its rows
 * load with Issued, Previously Returned and Balance filled in. Return Qty starts at 0 and a
 * row left at 0 is not returned. Every returned row needs a reason, and a reason of Other
 * needs a remark. The batch is the one that was issued. Enforced again on the server.
 */

frappe.pages['material_return_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Material Return'),
		single_column: true,
	});
	wrapper.material_return_entry = new MaterialReturnEntry(page);
};

frappe.pages['material_return_entry'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) {
		window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Material Returns'), '/app/material_return_list');
	}
	if (wrapper.material_return_entry) wrapper.material_return_entry.handle_route();
};

var MaterialReturnEntry = class {
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
					.mm-entry .mm-grid .frappe-control, .mm-entry .mm-grid .form-group { margin-bottom: 0; }
					.mm-entry .mm-note { color: var(--text-muted); font-size: 12px; margin-top: 6px; }
				</style>
				<div class="mm-banner"></div>
				<div class="mm-actionbar"></div>
				<div class="mm-card">
					<h5>${__('Return Details')}</h5>
					<div class="row">
						<div class="col-md-3 f-name"></div>
						<div class="col-md-3 f-mi"></div>
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
						<div class="col-md-3 f-reason-all"></div>
						<div class="col-md-6 f-remarks"></div>
					</div>
				</div>
				<div class="mm-card">
					<h5>${__('Materials')}</h5>
					<div class="mm-rows"></div>
					<div class="mm-note">${__('Return Qty cannot exceed the balance: what was issued minus what has already been returned.')}</div>
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
		this._ctl('.f-name', { fieldname: 'name', label: __('MRT ID'), read_only: 1, description: __('Assigned on save.') });
		this._ctl('.f-mi', {
			fieldname: 'material_issue', label: __('Linked MI'), fieldtype: 'Link', options: 'Stock Entry', reqd: 1,
			description: __('Submitted issues with something left to return.'),
			get_query() { return { query: 'alpinos.production.material_return.mi_query' }; },
			change() { me.on_mi(this.get_value()); },
		});
		this._ctl('.f-sub', { fieldname: 'sub_order', label: __('Sub PO'), read_only: 1 });
		this._ctl('.f-parent', { fieldname: 'parent', label: __('Parent PO'), read_only: 1 });
		this._ctl('.f-fg', { fieldname: 'fg_item', label: __('Target FG'), read_only: 1 });
		this._ctl('.f-type', { fieldname: 'production_type', label: __('Production Type'), read_only: 1 });
		this._ctl('.f-date', {
			fieldname: 'posting_date', label: __('Return Date'), fieldtype: 'Date', reqd: 1,
			description: __('Today or earlier.'),
		}, frappe.datetime.get_today());
		this._ctl('.f-by', { fieldname: 'returned_by', label: __('Returned By'), read_only: 1 });
		this._ctl('.f-status', { fieldname: 'status', label: __('Status'), read_only: 1 }, 'Draft');
		this._ctl('.f-reason-all', {
			fieldname: 'reason_all', label: __('Set Reason For All Rows'), fieldtype: 'Select',
			options: [''].concat(['Excess Material', 'Unused Material', 'Damaged Packaging', 'Quality Rejection',
				'Machine Spillage', 'Production Adjustment', 'Other']),
			change() {
				const v = this.get_value();
				if (!v || !me.editable()) return;
				me.rows.forEach((r) => { r.reason = v; });
				me.render_rows();
			},
		});
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
			method: 'alpinos.production.material_return.get_mrt_context',
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
		['name', 'material_issue', 'sub_order', 'parent', 'fg_item', 'production_type', 'remarks', 'reason_all'].forEach((f) => this._set(f, ''));
		this._set('posting_date', frappe.datetime.get_today());
		this._set('status', 'Draft');
		this._set('returned_by', this.ctx.returned_by || '');
		this.rows = [];
		this.page.set_title(__('New Material Return'));
		const opts = frappe.route_options || {};
		frappe.route_options = null;
		if (opts.material_issue) this._set('material_issue', opts.material_issue);
	}

	fill(doc) {
		this._set('name', doc.name);
		this._set('material_issue', doc.material_issue);
		this._set('sub_order', doc.sub_order);
		this._set('parent', doc.parent);
		this._set('fg_item', doc.fg_item_name && doc.fg_item_name !== doc.fg_item ? `${doc.fg_item} — ${doc.fg_item_name}` : doc.fg_item);
		this._set('production_type', doc.production_type);
		this._set('posting_date', doc.posting_date);
		this._set('returned_by', doc.returned_by);
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
		this._readonly('material_issue', !(ed && !this.ctx.doc));
		this._readonly('posting_date', !ed);
		this._readonly('remarks', !ed);
		this._readonly('reason_all', !ed);
		const $b = this.wrapper.find('.mm-banner').empty();
		if (!this.ctx.main_warehouse || !this.ctx.wip_warehouse) {
			$b.html(`<div class="alert alert-warning">${__('Set the Main and WIP warehouses in Production Settings before returning.')}</div>`);
		}
		this.render_rows();
		this.make_actions();
	}

	on_mi(mi) {
		const me = this;
		if (!this.editable() || this.ctx.doc) return;
		if (!mi) {
			['sub_order', 'parent', 'fg_item', 'production_type'].forEach((f) => this._set(f, ''));
			this.rows = [];
			this.render_rows();
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_return.issue_balance_rows',
			args: { material_issue: mi },
			callback(r) {
				const m = r.message;
				if (!m || me._val('material_issue') !== mi) return;
				me._set('sub_order', m.sub_order);
				me._set('parent', m.parent);
				me._set('fg_item', m.fg_item_name && m.fg_item_name !== m.fg_item ? `${m.fg_item} — ${m.fg_item_name}` : m.fg_item);
				me._set('production_type', m.production_type);
				const all = me._val('reason_all');
				me.rows = (m.rows || []).map((row) => Object.assign({}, row, all ? { reason: all } : {}));
				me.render_rows();
				if (!me.rows.length) {
					frappe.show_alert({ message: __('Everything issued on {0} has already been returned.', [mi]), indicator: 'orange' }, 6);
				}
			},
		});
	}

	render_rows() {
		const me = this;
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const num = (v) => esc(format_number(flt(v), null, 3));
		const ed = this.editable();
		const reasons = [''].concat(this.ctx.reasons || []);
		const $out = this.wrapper.find('.mm-rows').empty();
		let html = '<table class="table table-bordered table-condensed mm-grid"><thead><tr>';
		html += `<th style="width:30px;">#</th><th style="width:66px;">${__('Type')}</th>`;
		html += `<th style="width:120px;">${__('Item')}</th><th>${__('Item Name')}</th><th style="width:46px;">${__('UOM')}</th>`;
		html += `<th style="width:100px;">${__('Batch')}</th>`;
		html += `<th style="width:76px;" class="mm-num">${__('Issued')}</th>`;
		html += `<th style="width:86px;" class="mm-num">${__('Previously Returned')}</th>`;
		html += `<th style="width:76px;" class="mm-num">${__('Balance')}</th>`;
		html += `<th style="width:100px;" class="mm-num">${__('Return Qty')}</th>`;
		html += `<th style="width:150px;">${__('Reason')}</th>`;
		html += `<th style="width:120px;">${__('Source')}</th>`;
		html += `<th style="width:140px;">${__('Target')}</th>`;
		html += `<th style="width:130px;">${__('Remarks')}</th>`;
		html += '</tr></thead><tbody>';
		if (!this.rows.length) {
			html += `<tr><td colspan="14" class="text-muted" style="text-align:center;">${
				__('Choose the Material Issue, and the rows with a balance appear here.')}</td></tr>`;
		}
		this.rows.forEach((row, idx) => {
			html += `<tr data-idx="${idx}">`;
			html += `<td>${idx + 1}</td><td>${esc(row.material_type)}</td><td>${esc(row.item_code)}</td>`;
			html += `<td>${esc(row.item_name)}</td><td>${esc(row.uom)}</td><td>${esc(row.batch_no || '—')}</td>`;
			html += `<td class="mm-num">${num(row.issued_qty)}</td><td class="mm-num">${num(row.previously_returned)}</td>`;
			html += `<td class="mm-num">${num(row.balance)}</td>`;
			html += `<td class="mm-num c-qty">${ed ? '' : num(row.qty)}</td>`;
			html += `<td class="c-reason">${ed ? '' : esc(row.reason)}</td>`;
			html += `<td>${esc(row.s_warehouse)}</td>`;
			html += `<td class="c-tgt">${ed ? '' : esc(row.t_warehouse)}</td>`;
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
			me._cell($tr.find('.c-qty'), { fieldtype: 'Float', precision: 3 }, row.qty, (v) => { row.qty = flt(v); });
			me._cell($tr.find('.c-reason'), { fieldtype: 'Select', options: reasons }, row.reason, (v) => { row.reason = v; });
			me._cell($tr.find('.c-tgt'), {
				fieldtype: 'Link', options: 'Warehouse',
				get_query() { return { filters: { is_group: 0, disabled: 0 } }; },
			}, row.t_warehouse, (v) => { row.t_warehouse = v; });
			me._cell($tr.find('.c-rem'), { fieldtype: 'Data' }, row.line_remarks, (v) => { row.line_remarks = v; });
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
			btn(__('Print Return Slip'), 'btn-default', () => window.open(
				`/printview?doctype=${encodeURIComponent('Stock Entry')}&name=${encodeURIComponent(me.docname)}`
				+ `&format=${encodeURIComponent('Material Return Slip')}&no_letterhead=0`, '_blank'));
		}
		if (this.docname && cint(c.can_cancel)) btn(__('Cancel'), 'btn-danger', () => me.cancel());
		if (this.docname && cint(c.can_delete)) btn(__('Delete'), 'btn-danger', () => me.remove());
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('material_return_list'));
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			material_issue: this._val('material_issue'),
			posting_date: this._val('posting_date'),
			remarks: this._val('remarks'),
			reason_all: this._val('reason_all') || '',
			items: this.rows.map((r) => ({
				mi_detail: r.mi_detail, item_code: r.item_code, qty: flt(r.qty), reason: r.reason || '',
				s_warehouse: r.s_warehouse, t_warehouse: r.t_warehouse, line_remarks: r.line_remarks || '',
			})),
		};
	}

	validate_client() {
		// The server says all of this again; saying it here first saves a round trip.
		const rows = this.rows.filter((r) => flt(r.qty) > 0);
		if (!rows.length) return __('Enter a Return Qty on at least one row.');
		for (const r of rows) {
			if (flt(r.qty) > flt(r.balance)) {
				return __('{0}: you can return at most {1} {2}; {3} was issued and {4} already returned.',
					[r.item_code, flt(r.balance), r.uom || '', flt(r.issued_qty), flt(r.previously_returned)]);
			}
			if (!r.reason) return __('{0}: choose a Return Reason.', [r.item_code]);
			if (r.reason === 'Other' && !(r.line_remarks || '').trim()) {
				return __('{0}: the reason is Other, so please write a remark saying why.', [r.item_code]);
			}
		}
		if (this._val('posting_date') && this._val('posting_date') > frappe.datetime.get_today()) {
			return __('The Return Date cannot be in the future.');
		}
		return null;
	}

	save(then) {
		const me = this;
		const problem = this.validate_client();
		if (problem) {
			frappe.msgprint({ title: __('Please Check'), indicator: 'orange', message: problem });
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_return.save_mrt',
			args: { payload: this.collect() },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved'), indicator: 'green' }, 4);
				if (me.docname !== r.message.name) {
					frappe.set_route('material_return_entry', r.message.name);
				} else {
					me.load();
				}
				if (then) then(r.message.name);
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(__('Submit {0}? Stock moves back from the WIP warehouse now.', [this.docname]), () => {
			const go = () => frappe.call({
				method: 'alpinos.production.material_return.submit_mrt',
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
		frappe.confirm(__('Cancel {0}? The returned stock goes back to the WIP warehouse.', [this.docname]), () => {
			frappe.call({
				method: 'alpinos.production.material_return.cancel_mrt',
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
					frappe.set_route('material_return_list');
				},
			});
		});
	}
};
