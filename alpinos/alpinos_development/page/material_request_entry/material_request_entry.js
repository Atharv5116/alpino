/**
 * Material Request — add / view screen (Material Management, BR-MR-01..06).
 *
 * /app/material_request_entry/new           a manual MR (pick the Sub PO, rows load from it)
 * /app/material_request_entry/MR-2026-00001 an existing one
 *
 * Only a manual draft is editable. An auto MR is generated and submitted by the Store
 * Planning board, so it opens read-only. Every rule is enforced again on the server.
 */

frappe.pages['material_request_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Material Request'),
		single_column: true,
	});
	wrapper.material_request_entry = new MaterialRequestEntry(page);
};

frappe.pages['material_request_entry'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) {
		window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Material Requests'), '/app/material_request_list');
	}
	if (wrapper.material_request_entry) wrapper.material_request_entry.handle_route();
};

var MaterialRequestEntry = class {
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
					.mm-entry .mm-grid .frappe-control { margin-bottom: 0; }
					.mm-entry .mm-grid .form-group { margin-bottom: 0; }
					.mm-entry .mm-note { color: var(--text-muted); font-size: 12px; margin-top: 6px; }
				</style>
				<div class="mm-banner"></div>
				<div class="mm-actionbar"></div>
				<div class="mm-card">
					<h5>${__('Request Details')}</h5>
					<div class="row">
						<div class="col-md-3 f-name"></div>
						<div class="col-md-3 f-sub"></div>
						<div class="col-md-3 f-parent"></div>
						<div class="col-md-3 f-status"></div>
					</div>
					<div class="row">
						<div class="col-md-3 f-fg"></div>
						<div class="col-md-3 f-type"></div>
						<div class="col-md-3 f-by"></div>
						<div class="col-md-3 f-source"></div>
					</div>
					<div class="row">
						<div class="col-md-3 f-date"></div>
						<div class="col-md-3 f-required"></div>
						<div class="col-md-6 f-remarks"></div>
					</div>
				</div>
				<div class="mm-card">
					<h5>${__('Materials')}</h5>
					<div class="mm-rows"></div>
					<div class="mm-add-row" style="margin-top:8px;"></div>
					<div class="mm-note">${__('Available Stock is what the source warehouse holds now. A shortage is a warning; it does not block the request.')}</div>
				</div>
				<div class="mm-card mm-issues-card" style="display:none;">
					<h5>${__('Material Issues')}</h5>
					<div class="mm-issues"></div>
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

	_set(fieldname, value) {
		const c = this.fields[fieldname];
		if (c) c.set_value(value == null ? '' : value);
	}

	_val(fieldname) {
		const c = this.fields[fieldname];
		return c ? c.get_value() : null;
	}

	_readonly(fieldname, ro) {
		const c = this.fields[fieldname];
		if (!c) return;
		c.df.read_only = ro ? 1 : 0;
		c.refresh();
	}

	make_fields() {
		const me = this;
		this._ctl('.f-name', { fieldname: 'name', label: __('MR ID'), read_only: 1, description: __('Assigned on save.') });
		this._ctl('.f-sub', {
			fieldname: 'sub_order', label: __('Sub PO'), fieldtype: 'Link', options: 'Work Order', reqd: 1,
			get_query() { return { query: 'alpinos.production.material_request.sub_order_query' }; },
			change() { me.on_sub_order(this.get_value()); },
		});
		this._ctl('.f-parent', { fieldname: 'parent', label: __('Parent PO'), read_only: 1 });
		this._ctl('.f-status', { fieldname: 'status', label: __('Status'), read_only: 1 }, 'Draft');
		this._ctl('.f-fg', { fieldname: 'fg_item', label: __('Target FG'), read_only: 1 });
		this._ctl('.f-type', { fieldname: 'production_type', label: __('Production Type'), read_only: 1 });
		this._ctl('.f-by', { fieldname: 'requested_by', label: __('Requested By'), read_only: 1 });
		this._ctl('.f-source', { fieldname: 'source', label: __('Source'), read_only: 1 }, 'Manual');
		this._ctl('.f-date', { fieldname: 'transaction_date', label: __('Requested Date'), fieldtype: 'Date', read_only: 1 },
			frappe.datetime.get_today());
		this._ctl('.f-required', { fieldname: 'schedule_date', label: __('Required Date'), fieldtype: 'Date', reqd: 1 });
		this._ctl('.f-remarks', { fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text' });
	}

	// ------------------------------------------------------------ route

	handle_route() {
		const route = frappe.get_route() || [];
		const name = route[1] && route[1] !== 'new' ? route[1] : null;
		this.docname = name;
		this.load();
	}

	load() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.material_request.get_mr_context',
			args: { material_request: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message || docname !== me.docname) return;
				me.ctx = r.message;
				if (me.ctx.doc) {
					me.fill(me.ctx.doc);
				} else {
					me.reset();
				}
				me.apply_state();
			},
		});
	}

	reset() {
		this.loading = true;
		['name', 'sub_order', 'parent', 'fg_item', 'production_type', 'remarks', 'schedule_date'].forEach((f) => this._set(f, ''));
		this._set('status', 'Draft');
		this._set('source', 'Manual');
		this._set('requested_by', this.ctx.requested_by || '');
		this._set('transaction_date', frappe.datetime.get_today());
		this.rows = [];
		this.page.set_title(__('New Material Request'));
		this.loading = false;
		const opts = frappe.route_options || {};
		frappe.route_options = null;
		if (opts.sub_order) this._set('sub_order', opts.sub_order);
	}

	fill(doc) {
		this.loading = true;
		this._set('name', doc.name);
		this._set('sub_order', doc.sub_order);
		this._set('parent', doc.parent);
		this._set('status', doc.status);
		this._set('fg_item', doc.fg_item_name && doc.fg_item_name !== doc.fg_item
			? `${doc.fg_item} — ${doc.fg_item_name}` : doc.fg_item);
		this._set('production_type', doc.production_type);
		this._set('requested_by', doc.requested_by);
		this._set('source', doc.source);
		this._set('transaction_date', doc.transaction_date);
		this._set('schedule_date', doc.schedule_date);
		this._set('remarks', doc.remarks);
		this.rows = (doc.items || []).map((r) => Object.assign({}, r));
		this.page.set_title(`${doc.name} — ${doc.status}`);
		this.loading = false;
	}

	editable() {
		return !!cint(this.ctx.can_write) && (!this.ctx.doc || cint(this.ctx.doc.docstatus) === 0);
	}

	apply_state() {
		const ed = this.editable();
		const manual = !this.ctx.doc || this.ctx.doc.source !== 'Auto';
		this._readonly('sub_order', !(ed && manual));
		this._readonly('schedule_date', !ed);
		this._readonly('remarks', !ed);
		const $b = this.wrapper.find('.mm-banner').empty();
		if (!this.ctx.main_warehouse || !this.ctx.wip_warehouse) {
			$b.html(`<div class="alert alert-warning">${__('Set the Main and WIP warehouses in Production Settings before raising requests.')}</div>`);
		} else if (this.ctx.doc && this.ctx.doc.source === 'Auto' && cint(this.ctx.doc.docstatus) === 1) {
			$b.html(`<div class="alert alert-info">${__('Generated from the Store Planning board. The sub order plan is locked while this request is open.')}</div>`);
		}
		this.render_rows();
		this.render_issues();
		this.make_actions();
	}

	on_sub_order(sub) {
		const me = this;
		if (this.loading || !this.editable()) return;
		// Filling a saved draft sets the Sub PO too, and the control reports that as a change
		// a moment later. The saved rows belong to the document; they must not be replaced.
		if (this.ctx.doc && this.ctx.doc.sub_order === sub) return;
		if (!sub) {
			['parent', 'fg_item', 'production_type'].forEach((f) => this._set(f, ''));
			this.rows = [];
			this.render_rows();
			return;
		}
		frappe.call({
			method: 'alpinos.production.material_request.sub_order_materials',
			args: { sub_order: sub },
			callback(r) {
				const m = r.message;
				if (!m || me._val('sub_order') !== sub) return;
				me._set('parent', m.parent);
				me._set('fg_item', m.fg_item_name && m.fg_item_name !== m.fg_item ? `${m.fg_item} — ${m.fg_item_name}` : m.fg_item);
				me._set('production_type', m.production_type);
				if (!me._val('schedule_date')) {
					const today = frappe.datetime.get_today();
					me._set('schedule_date', m.planned_date && m.planned_date >= today ? m.planned_date : today);
				}
				me.rows = (m.rows || []).map((row) => Object.assign({}, row));
				me.render_rows();
				if (!me.rows.length) {
					frappe.show_alert({ message: __('{0} has nothing pending; add rows by hand.', [sub]), indicator: 'orange' }, 6);
				}
			},
		});
	}

	// ------------------------------------------------------------- grid

	render_rows() {
		const me = this;
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const num = (v) => esc(format_number(flt(v), null, 3));
		const ed = this.editable();
		const $out = this.wrapper.find('.mm-rows').empty();
		const $add = this.wrapper.find('.mm-add-row').empty();

		let html = '<table class="table table-bordered table-condensed mm-grid"><thead><tr>';
		html += `<th style="width:30px;">#</th><th style="width:70px;">${__('Type')}</th>`;
		html += `<th style="width:170px;">${__('Item')}</th><th>${__('Item Name')}</th>`;
		html += `<th style="width:50px;">${__('UOM')}</th>`;
		html += `<th style="width:80px;" class="mm-num">${__('Standard Qty')}</th>`;
		html += `<th style="width:110px;" class="mm-num">${__('Total Required Qty')}</th>`;
		html += `<th style="width:90px;" class="mm-num">${__('Available Stock')}</th>`;
		html += `<th style="width:80px;" class="mm-num">${__('Shortage')}</th>`;
		html += `<th style="width:160px;">${__('Warehouse')}</th>`;
		html += `<th style="width:70px;" class="mm-num">${__('Issued')}</th>`;
		html += `<th style="width:70px;" class="mm-num">${__('Pending')}</th>`;
		html += `<th style="width:140px;">${__('Remarks')}</th>`;
		if (ed) html += '<th style="width:34px;"></th>';
		html += '</tr></thead><tbody>';
		if (!this.rows.length) {
			html += `<tr><td colspan="${ed ? 14 : 13}" class="text-muted" style="text-align:center;">${
				__('Choose the Sub PO, and its pending materials appear here.')}</td></tr>`;
		}
		this.rows.forEach((row, idx) => {
			html += `<tr data-idx="${idx}">`;
			html += `<td>${idx + 1}</td><td class="c-type">${esc(row.material_type)}</td>`;
			html += `<td class="c-item">${ed ? '' : esc(row.item_code)}</td>`;
			html += `<td class="c-name">${esc(row.item_name)}</td><td class="c-uom">${esc(row.uom)}</td>`;
			html += `<td class="mm-num">${num(row.standard_qty)}</td>`;
			html += `<td class="mm-num c-qty">${ed ? '' : num(row.qty)}</td>`;
			html += `<td class="mm-num c-avail">${num(row.available_qty)}</td>`;
			html += `<td class="mm-num c-short ${flt(row.shortage_qty) > 0 ? 'mm-short' : ''}">${flt(row.shortage_qty) > 0 ? num(row.shortage_qty) : '—'}</td>`;
			html += `<td class="c-wh">${ed ? '' : esc(row.from_warehouse)}</td>`;
			html += `<td class="mm-num">${num(row.issued_qty)}</td>`;
			html += `<td class="mm-num">${num(ed ? row.qty : row.pending_qty)}</td>`;
			html += `<td class="c-rem">${ed ? '' : esc(row.line_remarks)}</td>`;
			if (ed) html += `<td><button class="btn btn-xs btn-default mm-del" data-idx="${idx}" title="${__('Remove')}">&times;</button></td>`;
			html += '</tr>';
		});
		html += '</tbody></table>';
		$out.html(html);

		if (!ed) return;
		const types = this.ctx.material_types || ['RM', 'PM', 'Additive'];
		$out.find('tr[data-idx]').each(function () {
			const idx = cint($(this).attr('data-idx'));
			const row = me.rows[idx];
			const $tr = $(this);
			me._cell($tr.find('.c-item'), {
				fieldtype: 'Link', options: 'Item',
				get_query() { return { filters: { custom_material_type: ['in', types], disabled: 0 } }; },
			}, row.item_code, (v) => { row.item_code = v; me.refresh_row(idx, $tr); });
			me._cell($tr.find('.c-qty'), { fieldtype: 'Float', precision: 3 }, row.qty, (v) => {
				row.qty = flt(v);
				me.update_row_display(idx, $tr);
			});
			me._cell($tr.find('.c-wh'), {
				fieldtype: 'Link', options: 'Warehouse',
				get_query() { return { filters: { is_group: 0, disabled: 0 } }; },
			}, row.from_warehouse, (v) => { row.from_warehouse = v; me.refresh_row(idx, $tr); });
			me._cell($tr.find('.c-rem'), { fieldtype: 'Data' }, row.line_remarks, (v) => { row.line_remarks = v; });
		});
		$out.find('.mm-del').on('click', function () {
			me.rows.splice(cint($(this).attr('data-idx')), 1);
			me.render_rows();
		});
		const $btn = $(`<button class="btn btn-xs btn-default">${__('Add Row')}</button>`);
		$btn.on('click', () => {
			me.rows.push({
				item_code: '', item_name: '', uom: '', material_type: '', standard_qty: 0, qty: 0,
				available_qty: 0, shortage_qty: 0, from_warehouse: me.ctx.main_warehouse || '',
				issued_qty: 0, pending_qty: 0, line_remarks: '',
			});
			me.render_rows();
		});
		$add.append($btn);
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

	refresh_row(idx, $tr) {
		const me = this;
		const row = this.rows[idx];
		if (!row || !row.item_code) return;
		frappe.call({
			method: 'alpinos.production.material_request.item_row_info',
			args: { item_code: row.item_code, warehouse: row.from_warehouse || '' },
			callback(r) {
				const m = r.message;
				if (!m || me.rows[idx] !== row) return;
				row.item_name = m.item_name;
				row.uom = m.uom;
				row.material_type = m.material_type || row.material_type;
				row.available_qty = flt(m.available_qty);
				me.update_row_display(idx, $tr);
			},
		});
	}

	update_row_display(idx, $tr) {
		const row = this.rows[idx];
		const num = (v) => format_number(flt(v), null, 3);
		row.shortage_qty = Math.max(flt(row.qty) - flt(row.available_qty), 0);
		$tr.find('.c-name').text(row.item_name || '');
		$tr.find('.c-uom').text(row.uom || '');
		$tr.find('.c-type').text(row.material_type || '');
		$tr.find('.c-avail').text(num(row.available_qty));
		$tr.find('.c-short').toggleClass('mm-short', row.shortage_qty > 0)
			.text(row.shortage_qty > 0 ? num(row.shortage_qty) : '—');
	}

	render_issues() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const issues = this.ctx.issues || [];
		const $card = this.wrapper.find('.mm-issues-card');
		$card.toggle(!!(this.ctx.doc && issues.length));
		if (!issues.length) return;
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th>${__('Material Issue')}</th><th>${__('Issue Date')}</th><th>${__('Issued By')}</th><th>${__('Status')}</th></tr></thead><tbody>`;
		issues.forEach((i) => {
			html += `<tr class="mm-issue-row" data-name="${esc(i.name)}" style="cursor:pointer;"><td>${esc(i.name)}</td>`;
			html += `<td>${esc(frappe.datetime.str_to_user(i.posting_date))}</td><td>${esc(i.issued_by)}</td><td>${esc(i.status)}</td></tr>`;
		});
		html += '</tbody></table>';
		const $out = this.wrapper.find('.mm-issues').html(html);
		$out.find('.mm-issue-row').on('click', function () {
			frappe.set_route('material_issue_entry', $(this).attr('data-name'));
		});
	}

	// ---------------------------------------------------------- actions

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
		if (this.docname && cint(c.can_issue)) {
			btn(__('Create Material Issue'), 'btn-primary', () => {
				frappe.route_options = { material_request: me.docname };
				frappe.set_route('material_issue_entry', 'new');
			});
		}
		if (this.docname) {
			btn(__('Print'), 'btn-default', () => window.open(
				`/printview?doctype=${encodeURIComponent('Material Request')}&name=${encodeURIComponent(me.docname)}`
				+ `&format=${encodeURIComponent('Material Request Slip')}&no_letterhead=0`, '_blank'));
		}
		if (this.docname && cint(c.can_cancel)) btn(__('Cancel'), 'btn-danger', () => me.cancel());
		if (this.docname && cint(c.can_delete)) btn(__('Delete'), 'btn-danger', () => me.remove());
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('material_request_list'));
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			sub_order: this._val('sub_order'),
			schedule_date: this._val('schedule_date'),
			remarks: this._val('remarks'),
			items: this.rows.filter((r) => r.item_code).map((r) => ({
				item_code: r.item_code, qty: flt(r.qty), from_warehouse: r.from_warehouse,
				material_type: r.material_type, standard_qty: flt(r.standard_qty),
				line_remarks: r.line_remarks || '',
			})),
		};
	}

	save(then) {
		const me = this;
		frappe.call({
			method: 'alpinos.production.material_request.save_mr',
			args: { payload: this.collect() },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved'), indicator: 'green' }, 4);
				if (me.docname !== r.message.name) {
					frappe.set_route('material_request_entry', r.message.name);
				} else {
					me.load();
				}
				if (then) then(r.message.name);
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(__('Submit {0}? The store can then issue against it, and it can no longer be edited.', [this.docname]), () => {
			const go = () => frappe.call({
				method: 'alpinos.production.material_request.submit_mr',
				args: { material_request: me.docname },
				freeze: true,
				freeze_message: __('Submitting...'),
				callback(r) {
					if (!r.message) return;
					frappe.show_alert({ message: __('Submitted'), indicator: 'green' }, 4);
					me.load();
				},
			});
			// Unsaved edits on the draft are saved first, so what is submitted is what is shown.
			if (me.editable()) me.save(go); else go();
		});
	}

	cancel() {
		const me = this;
		frappe.confirm(__('Cancel {0}? Nothing has been issued against it. If it was generated from the plan, the sub order goes back to Assigned and can be re-planned.', [this.docname]), () => {
			frappe.call({
				method: 'alpinos.production.material_request.cancel_mr',
				args: { material_request: me.docname },
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
				method: 'alpinos.production.material_request.delete_mr',
				args: { material_request: me.docname },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					frappe.set_route('material_request_list');
				},
			});
		});
	}
};
