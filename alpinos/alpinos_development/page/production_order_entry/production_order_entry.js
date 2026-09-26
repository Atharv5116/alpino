/**
 * Parent Production Order — add / edit screen (Tasks 21 to 24, plus Task E).
 *
 * What this screen deliberately does NOT have: Submit, Approve, Reject and Send to Store.
 * Who may do each of those, whether a Manager skips Pending Approval, and where a rejection
 * lands are all still open questions, so instead of buttons that would have to guess, the
 * screen says what it is waiting on. Everything a draft order needs is here and works.
 *
 * Total Required Qty is the one editable cell in the grid, for the same reason: the batch
 * formula is undecided, so the number is entered rather than invented.
 */

frappe.pages['production_order_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Production Order'),
		single_column: true,
	});
	page.main.html(frappe.render_template('production_order_entry'));
	wrapper.production_order_entry = new ProductionOrderEntry(page);
};

frappe.pages['production_order_entry'].on_page_show = function (wrapper) {
	// The list this record belongs to, matching the Back to List button.
	alpinos_production_breadcrumb(__("Production Orders"), "/app/production_order_list");
	if (wrapper.production_order_entry) wrapper.production_order_entry.handle_route();
};

var ProductionOrderEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.ctx = {};
		this.rows = [];
		this.make_fields();
		this.handle_route();
	}

	// ------------------------------------------------------------- helpers

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const control = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		control.refresh();
		control.set_value(value === undefined || value === null ? '' : value);
		this.fields[df.fieldname] = control;
		return control;
	}

	_val(fieldname) {
		const c = this.fields[fieldname];
		return c ? c.get_value() : null;
	}

	_set(fieldname, value) {
		const c = this.fields[fieldname];
		if (c) {
			c.refresh();
			c.set_value(value === undefined || value === null ? '' : value);
		}
	}

	_toast(message, indicator) {
		frappe.show_alert({ message: message, indicator: indicator || 'blue' }, 5);
	}

	// -------------------------------------------------------------- fields

	make_fields() {
		const me = this;

		this._ctl('.field-po-id', {
			fieldname: 'po_id', label: __('Production Order No'), fieldtype: 'Data', read_only: 1,
			description: __('Assigned on save.'),
		});
		this._ctl('.field-creation-date', {
			fieldname: 'creation_date', label: __('Creation Date'), fieldtype: 'Date', read_only: 1,
		}, frappe.datetime.get_today());
		this._ctl('.field-production-type', {
			fieldname: 'production_type', label: __('Production Type'), fieldtype: 'Select',
			options: ['Own Production', 'Export', 'White Label'], reqd: 1,
			change() { me.toggle_client(this.get_value()); },
		}, 'Own Production');
		this._ctl('.field-client-name', {
			fieldname: 'client_name', label: __('Client Name'), fieldtype: 'Link', options: 'Customer',
			description: __('Required for Export and White Label.'),
		});
		this._ctl('.field-batch-number', {
			fieldname: 'batch_number', label: __('Batch Number'), fieldtype: 'Data',
		});
		this._ctl('.field-delivery-date', {
			fieldname: 'delivery_date', label: __('Delivery Date'), fieldtype: 'Date',
			description: __('On or after the start date.'),
		});
		this._ctl('.field-status', {
			fieldname: 'status', label: __('Status'), fieldtype: 'Data', read_only: 1,
		}, 'Draft');

		this._ctl('.field-fg-item', {
			fieldname: 'fg_item', label: __('FG Item Code'), fieldtype: 'Link', options: 'Item', reqd: 1,
			// Same server query the BOM screen uses, so the two screens agree about what
			// counts as a finished good.
			get_query() { return { query: 'alpinos.production.bom_api.fg_item_query' }; },
			change() { me.fetch_bom(this.get_value()); },
		});
		this._ctl('.field-fg-item-name', {
			fieldname: 'fg_item_name', label: __('FG Item Name'), fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-bom-no', {
			fieldname: 'bom_no', label: __('BOM No'), fieldtype: 'Data', read_only: 1,
			description: __('The Active default recipe for this item.'),
		});

		this._ctl('.field-qty-kg', {
			fieldname: 'production_qty_kg', label: __('Production Quantity (KG)'),
			fieldtype: 'Float', precision: 3, reqd: 1,
		});
		this._ctl('.field-qty-pcs', {
			fieldname: 'production_qty_pcs', label: __('Production Quantity (PCS)'), fieldtype: 'Int',
			description: __('Informational. Nothing is recalculated from it.'),
		});
		this._ctl('.field-uom', {
			fieldname: 'uom', label: __('UOM'), fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-start-date', {
			fieldname: 'production_start_date', label: __('Production Start Date'),
			fieldtype: 'Date', reqd: 1,
		}, frappe.datetime.get_today());

		this._ctl('.field-total-batches', {
			fieldname: 'total_batches', label: __('Total Batches'), fieldtype: 'Float', precision: 3,
		});
		this._ctl('.field-total-rm', {
			fieldname: 'total_rm_requirement', label: __('Total RM Requirement'),
			fieldtype: 'Float', precision: 3,
		});
		this._ctl('.field-total-additive', {
			fieldname: 'total_additive_requirement', label: __('Total Additive Requirement'),
			fieldtype: 'Float', precision: 3,
		});
		this._ctl('.field-total-material', {
			fieldname: 'total_material_requirement', label: __('Total Material Requirement'),
			fieldtype: 'Float', precision: 3,
		});
		this._ctl('.field-remarks', {
			fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text',
		});

		this.toggle_client('Own Production');
	}

	toggle_client(production_type, value) {
		// The value is passed in explicitly on load rather than read back off the control: a
		// change handler firing while the document was still being filled in used to wipe the
		// client off a saved Export order.
		const needs = (this.ctx.types_needing_client || ['Export', 'White Label'])
			.includes(production_type);
		const c = this.fields.client_name;
		if (!c) return;
		this.wrapper.find('.field-client-name').toggle(needs);
		c.df.reqd = needs ? 1 : 0;
		c.refresh();
		if (needs) {
			if (value !== undefined) c.set_value(value || '');
		} else {
			c.set_value('');
		}
		// c.refresh() above clears the disabled prop -- that is what refresh does to an
		// input. This runs from the production_type change handler, which fires after the
		// load has already locked the card, so on an order past Draft the Client Name came
		// back editable. Invisible on an Own Production order, but a real hole on an Export
		// or White Label one, and reachable by keyboard even when the card was still faded.
		if (this.ctx && this.ctx.can_write === false && c.$input) {
			c.$input.prop('disabled', true);
		}
	}

	// --------------------------------------------------------- route / load

	handle_route() {
		const route = frappe.get_route() || [];
		const name = route[1];
		if (name && name !== this.docname) {
			this.load(name);
			return;
		}
		if (!name && this.docname) this.reset();
		if (!name && !this.docname) this.refresh_context();
	}

	reset() {
		this.docname = null;
		this.doc = null;
		this.rows = [];
		['po_id', 'client_name', 'batch_number', 'delivery_date', 'fg_item', 'fg_item_name',
			'bom_no', 'uom', 'remarks'].forEach((f) => this._set(f, ''));
		['production_qty_kg', 'production_qty_pcs', 'total_batches', 'total_rm_requirement',
			'total_additive_requirement', 'total_material_requirement'].forEach((f) => this._set(f, 0));
		this._set('production_type', 'Own Production');
		this._set('status', 'Draft');
		this._set('creation_date', frappe.datetime.get_today());
		this._set('production_start_date', frappe.datetime.get_today());
		this.toggle_client('Own Production', '');
		this.page.set_title(__('New Production Order'));
		this.refresh_context();
	}

	load(name) {
		this.docname = name;
		this.refresh_context();
	}

	refresh_context() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.production_order_api.get_form_context',
			args: { production_order: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				// A route change while this was in flight must not stamp the old order onto
				// the new screen.
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				me.apply_permissions();
				me.make_actions();
				me.render_materials();
				me.render_sub_orders();
				me.render_shortage(null);
			},
		});
	}

	fill(doc) {
		this._set('po_id', doc.name);
		['creation_date', 'production_type', 'batch_number', 'delivery_date', 'status',
			'fg_item', 'fg_item_name', 'bom_no', 'production_qty_kg', 'production_qty_pcs',
			'uom', 'production_start_date', 'total_batches', 'total_rm_requirement',
			'total_additive_requirement', 'total_material_requirement', 'remarks',
		].forEach((f) => this._set(f, doc[f]));
		// Passed the stored value outright, because toggle_client fires on a change of
		// Production Type and would otherwise read a control that has not been filled yet.
		this.toggle_client(doc.production_type, doc.client_name);
		this.rows = (doc.items || []).map((row) => ({
			item_code: row.item_code, item_name: row.item_name, uom: row.uom,
			material_type: row.material_type, process_stage: row.process_stage,
			standard_qty: flt(row.standard_qty), total_required_qty: flt(row.total_required_qty),
		}));
		this.page.set_title(`${doc.name} — ${doc.fg_item || ''}`);
	}

	/**
	 * Lock the cards that may not be edited -- no permission, or past Draft.
	 *
	 * Read-only, not faded. The cards used to drop to 55% opacity with pointer-events off,
	 * and an order spends nearly its whole life past Draft: reading it is the main thing it
	 * is for by then, and it was the hardest thing on the screen to read. alpinos_set_readonly
	 * is the treatment the Purchase and BOM screens use for the same state.
	 *
	 * Turning off pointer-events also silently killed the Sub PO rows, whose whole job is to
	 * be clicked through to on an APPROVED order -- that is, only ever while locked. They
	 * work now.
	 */
	apply_permissions() {
		const locked = !this.ctx.can_write;
		// The Stock Check card is a report, not an input, so it is never locked -- a locked
		// order is exactly when someone wants to run it.
		alpinos_set_readonly(this.wrapper.find('.po-card').not(':has(.field-shortage)'), locked);

		const $banner = this.wrapper.find('.po-banner').empty();
		const notes = [];
		if (locked && this.docname) {
			notes.push(__('This order is {0}, so it can no longer be changed here.',
				[this.doc ? this.doc.status : __('not a draft')]));
		} else if (locked) {
			notes.push(__('You do not have permission to create a Production Order.'));
		}
		// Says what this order is waiting for, in its own words -- not a generic notice.
		const status = this.doc ? this.doc.status : null;
		if (status === 'Pending Approval' && !this.ctx.can_approve_order) {
			notes.push(__('Waiting for a {0} or {1} to approve it.',
				['Production Manager', 'Production Admin']));
		} else if (status === 'Approved') {
			notes.push(__('Approved. Its sub orders stay locked until it is sent to store.'));
		}
		const pending = this.ctx.pending_decisions || [];
		if (pending.length) {
			notes.push(__('{0} are not built yet: who does each of them has not been decided.',
				[pending.join(' and ')]));
		}
		if (notes.length) {
			$banner.html(`<div class="alert alert-info" style="margin-bottom:0;">${
				notes.map((n) => frappe.utils.escape_html(n)).join('<br>')
			}</div>`);
		}
	}

	// ------------------------------------------------------ the BOM and grid

	fetch_bom(fg_item) {
		const me = this;
		if (!fg_item) {
			this._set('bom_no', '');
			this._set('fg_item_name', '');
			this.rows = [];
			this.render_materials();
			return;
		}
		frappe.call({
			method: 'alpinos.production.production_order_api.default_bom',
			args: { fg_item: fg_item },
			callback(r) {
				const m = r.message || {};
				// A late reply for a finished good the user has already moved off must not
				// redraw the grid underneath the current one.
				if (me._val('fg_item') !== fg_item) return;
				if (m.error) {
					// Said once, plainly, and the grid is cleared: a stale grid beside a
					// message about a missing BOM is worse than an empty one.
					me._set('bom_no', '');
					me.rows = [];
					me.render_materials();
					frappe.msgprint({ message: m.error, title: __('No Default BOM'), indicator: 'orange' });
					return;
				}
				me._set('bom_no', m.bom_no || '');
				me._set('fg_item_name', m.fg_item_name || '');
				me._set('uom', m.uom || '');
				// The saved order OWNS its rows. Copying a blank set off the BOM is only
				// right when the finished good is not the one this order was saved with --
				// a different recipe, so any quantity typed against the old one is
				// meaningless. Same FG, saved rows, including the Total Required Qty.
				//
				// fill() sets fg_item, which fires this same handler, so this reply always
				// lands AFTER the document has been filled in. Without the check it wrote 0
				// over every stored quantity on load, and again on the redraw after each
				// save -- which is exactly why a typed Total Required Qty came back 0 while
				// the server had it stored correctly all along.
				const saved = (me.doc && me.doc.fg_item === fg_item) ? (me.doc.items || []) : null;
				me.rows = (saved || m.items || []).map((row) => ({
					item_code: row.item_code, item_name: row.item_name, uom: row.uom,
					material_type: row.material_type, process_stage: row.process_stage,
					standard_qty: flt(row.standard_qty),
					total_required_qty: saved ? flt(row.total_required_qty) : 0,
				}));
				me.render_materials();
			},
		});
	}

	render_materials() {
		const me = this;
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $out = this.wrapper.find('.field-materials').empty();

		if (!this.rows.length) {
			$out.html(`<div class="text-muted">${__('Choose a finished good, and its recipe rows appear here.')}</div>`);
			return;
		}

		// Grouped by stage, which is the order the shop floor works in and the order the Job
		// Card prints. A row with no stage is shown under its own heading rather than dropped.
		const stages = [];
		const byStage = {};
		this.rows.forEach((row, idx) => {
			const key = row.process_stage || '__none__';
			if (!byStage[key]) { byStage[key] = []; stages.push(key); }
			byStage[key].push({ row: row, idx: idx });
		});

		let html = '<table class="table table-bordered table-condensed po-grid"><thead><tr>';
		html += `<th style="width:34px;">#</th><th style="width:84px;">${__('Type')}</th>`;
		html += `<th>${__('Item')}</th><th style="width:64px;">${__('UOM')}</th>`;
		html += `<th style="width:100px;" class="po-num">${__('Standard Qty')}</th>`;
		html += `<th style="width:140px;" class="po-num">${__('Total Required Qty')}</th>`;
		html += '</tr></thead><tbody>';

		let n = 0;
		stages.forEach((stage) => {
			html += `<tr class="po-stage-head"><td colspan="6">${
				stage === '__none__' ? __('No stage') : esc(stage)}</td></tr>`;
			byStage[stage].forEach(({ row, idx }) => {
				n += 1;
				const label = row.item_name && row.item_name !== row.item_code
					? `${esc(row.item_code)} <span class="text-muted">${esc(row.item_name)}</span>`
					: esc(row.item_code);
				html += `<tr data-idx="${idx}">`;
				html += `<td>${n}</td><td>${esc(row.material_type || '')}</td>`;
				html += `<td>${label}</td><td>${esc(row.uom || '')}</td>`;
				html += `<td class="po-num">${esc(format_number(flt(row.standard_qty), null, 3))}</td>`;
				html += '<td class="cell-required"></td>';
				html += '</tr>';
			});
		});
		html += '</tbody></table>';
		$out.html(html);

		const locked = !this.ctx.can_write;
		$out.find('tr[data-idx]').each(function () {
			const idx = cint($(this).attr('data-idx'));
			const parent = $(this).find('.cell-required');
			const control = frappe.ui.form.make_control({
				df: {
					fieldname: `required_${idx}`, fieldtype: 'Float', precision: 3,
					read_only: locked ? 1 : 0,
					change() { me.rows[idx].total_required_qty = flt(this.get_value()); },
				},
				parent: parent,
				render_input: true,
			});
			control.refresh();
			control.set_value(flt(me.rows[idx].total_required_qty));
			me.fields[`required_${idx}`] = control;
		});
	}

	render_sub_orders() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $out = this.wrapper.find('.field-sub-orders');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Sub orders appear once the order is approved.')}</div>`);
			return;
		}
		const rows = this.ctx.sub_orders || [];
		if (!rows.length) {
			$out.html(`<div class="text-muted">${__('No sub order yet. When one is created has not been decided.')}</div>`);
			return;
		}
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th style="width:140px;">${__('Sub PO')}</th>`;
		html += `<th style="width:120px;" class="po-num">${__('Qty')}</th>`;
		html += `<th>${__('Status')}</th></tr></thead><tbody>`;
		rows.forEach((s) => {
			html += `<tr class="po-sub-row" data-sub="${esc(s.name)}" style="cursor:pointer;">`;
			html += `<td>${esc(s.name)}</td>`;
			html += `<td class="po-num">${esc(format_number(flt(s.qty), null, 3))}</td>`;
			html += `<td>${esc(s.status || '')}</td></tr>`;
		});
		html += '</tbody></table>';
		$out.html(html);
		$out.find('.po-sub-row').on('click', function () {
			frappe.set_route('Form', 'Work Order', $(this).attr('data-sub'));
		});
	}

	// --------------------------------------------------------- Task E report

	render_shortage(result) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $out = this.wrapper.find('.field-shortage');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Save the order, then check stock against it.')}</div>`);
			return;
		}
		if (!result) {
			$out.html(`<button class="btn btn-sm btn-default po-check-stock">${__('Check Stock')}</button>`);
			const me = this;
			$out.find('.po-check-stock').on('click', () => me.check_stock());
			return;
		}
		if (!result.rows.length) {
			$out.html(`<div class="text-muted">${__('This order has no material rows to check.')}</div>`);
			return;
		}
		let html = '';
		if (result.unset_count) {
			html += `<div class="text-muted" style="margin-bottom:8px;">${
				__('{0} row(s) have no Total Required Qty recorded, so nothing can be compared for them.',
					[result.unset_count])}</div>`;
		}
		html += '<table class="table table-bordered table-condensed po-grid"><thead><tr>';
		html += `<th>${__('Item')}</th><th style="width:84px;">${__('Type')}</th>`;
		html += `<th style="width:64px;">${__('UOM')}</th>`;
		html += `<th style="width:110px;" class="po-num">${__('Required')}</th>`;
		html += `<th style="width:110px;" class="po-num">${__('Available')}</th>`;
		html += `<th style="width:110px;" class="po-num">${__('Shortage')}</th>`;
		html += `<th style="width:90px;">${__('Status')}</th></tr></thead><tbody>`;
		result.rows.forEach((row) => {
			const cls = row.status === 'Short' ? 'short' : (row.status === 'Not Set' ? 'unset' : '');
			html += `<tr class="${cls}">`;
			html += `<td>${esc(row.item_code)}</td><td>${esc(row.material_type || '')}</td>`;
			html += `<td>${esc(row.uom || '')}</td>`;
			html += `<td class="po-num">${esc(format_number(flt(row.required_qty), null, 3))}</td>`;
			html += `<td class="po-num">${esc(format_number(flt(row.available_qty), null, 3))}</td>`;
			html += `<td class="po-num">${row.shortage_qty
				? esc(format_number(flt(row.shortage_qty), null, 3)) : '—'}</td>`;
			html += `<td>${esc(row.status)}</td></tr>`;
		});
		html += '</tbody></table>';
		html += `<button class="btn btn-sm btn-default po-check-stock" style="margin-top:8px;">${__('Check Again')}</button>`;
		$out.html(html);
		const me = this;
		$out.find('.po-check-stock').on('click', () => me.check_stock());
	}

	check_stock() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.production_order_api.material_shortage',
			args: { production_order: this.docname },
			freeze: true,
			freeze_message: __('Checking stock...'),
			callback(r) {
				if (!r.message) return;
				me.render_shortage(r.message);
				if (r.message.short_count) {
					me._toast(__('{0} item(s) short', [r.message.short_count]), 'orange');
				}
			},
		});
	}

	_reason_dialog(opts) {
		// Reject and Cancel both need a reason and both are refusals, so they ask the same
		// way. A plain frappe.prompt would accept whitespace and send it.
		const d = new frappe.ui.Dialog({
			title: opts.title,
			fields: [
				{ fieldtype: 'HTML', options: `<p>${frappe.utils.escape_html(opts.message)}</p>` },
				{
					fieldtype: 'Small Text', fieldname: 'reason', label: opts.label, reqd: 1,
					description: opts.description || '',
				},
			],
			primary_action_label: opts.action_label,
			primary_action(values) {
				const reason = (values.reason || '').trim();
				if (!reason) {
					frappe.msgprint({ title: __('Reason Required'), indicator: 'orange',
						message: opts.empty_message });
					return;
				}
				d.hide();
				opts.on_confirm(reason);
			},
		});
		d.show();
	}

	reject_order() {
		const me = this;
		this._reason_dialog({
			title: __('Reject {0}', [this.docname]),
			message: __('It goes back to the planner, who can correct it and send it again.'),
			label: __('Rejection Reason'),
			description: __('This is all the planner has to work from.'),
			action_label: __('Reject'),
			empty_message: __('Please say why this order is being rejected.'),
			on_confirm(reason) {
				frappe.call({
					method: 'alpinos.production.production_order_api.reject_production_order',
					args: { production_order: me.docname, reason: reason },
					freeze: true,
					freeze_message: __('Rejecting...'),
					callback(r) {
						if (!r.message) return;
						me._toast(__('Rejected'), 'orange');
						me.refresh_context();
					},
				});
			},
		});
	}

	cancel_order() {
		const me = this;
		const subs = (this.ctx.sub_orders || []).length;
		this._reason_dialog({
			title: __('Cancel {0}', [this.docname]),
			message: subs
				? __('Its {0} sub order(s) are cancelled with it. This cannot be undone.', [subs])
				: __('This cannot be undone.'),
			label: __('Cancellation Reason'),
			action_label: __('Cancel Order'),
			empty_message: __('Please say why this order is being cancelled.'),
			on_confirm(reason) {
				frappe.call({
					method: 'alpinos.production.production_order_api.cancel_production_order',
					args: { production_order: me.docname, reason: reason },
					freeze: true,
					freeze_message: __('Cancelling...'),
					callback(r) {
						if (!r.message) return;
						const removed = r.message.removed_sub_orders || [];
						me._toast(removed.length
							? __('Cancelled. {0} removed.', [removed.join(', ')])
							: __('Cancelled'), 'orange');
						me.refresh_context();
					},
				});
			},
		});
	}

	send_to_store() {
		const me = this;
		const subs = (this.ctx.sub_orders || []).map((s) => s.name);
		frappe.confirm(
			__('Send {0} to store? Its sub orders ({1}) are unlocked and the store team is told.',
				[this.docname, subs.join(', ') || __('none')]),
			() => {
				frappe.call({
					method: 'alpinos.production.production_order_api.send_to_store',
					args: { production_order: me.docname },
					freeze: true,
					freeze_message: __('Sending...'),
					callback(r) {
						if (!r.message) return;
						me._toast(__('Sent to store. {0} unlocked.',
							[(r.message.unlocked || []).join(', ')]), 'green');
						me.refresh_context();
					},
				});
			}
		);
	}

	// -------------------------------------------------------------- actions

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.po-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
			return $b;
		};

		if (this.ctx.can_write) {
			btn(__('Save'), 'btn-primary', () => me.save());
		}
		// Task 26, the two transitions that exist. Submit hands the order to its approver;
		// approving is what creates the first sub order (SPO-01). Reject and Send to Store
		// are not drawn, because who does what in those is still open.
		if (this.ctx.can_submit_order) {
			btn(__('Submit for Approval'), 'btn-primary', () => me.submit_order());
		}
		if (this.ctx.can_approve_order) {
			btn(__('Approve'), 'btn-primary', () => me.approve_order());
		}
		if (this.ctx.can_reject_order) {
			btn(__('Reject'), 'btn-danger', () => me.reject_order());
		}
		if (this.ctx.can_send_to_store) {
			btn(__('Send to Store'), 'btn-primary', () => me.send_to_store());
		}
		if (this.ctx.can_cancel_order) {
			btn(__('Cancel Order'), 'btn-danger', () => me.cancel_order());
		}
		if (this.docname && this.ctx.can_delete) {
			btn(__('Delete'), 'btn-danger', () => me.remove());
		}
		// Straight through to this order's sub orders, on the Sub PO screen and filtered
		// to it. Drawn only when there are any: they are created by approving the order, so
		// before that the button would always land on an empty list -- the same reason the
		// Sub PO screen has no New button.
		//
		// The count is in the label because it is the one thing worth knowing before
		// clicking, and on a split order it is not the number anybody assumes.
		const sub_count = (this.ctx.sub_orders || []).length;
		if (this.docname && sub_count) {
			btn(__('Sub POs ({0})', [sub_count]), 'btn-default',
				() => frappe.set_route('sub_order_list', me.docname));
		}
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('production_order_list'));
	}

	submit_order() {
		const me = this;
		frappe.confirm(
			__('Submit {0} for approval? It cannot be edited afterwards.', [this.docname]),
			() => {
				frappe.call({
					method: 'alpinos.production.production_order_api.submit_production_order',
					args: { production_order: me.docname },
					freeze: true,
					freeze_message: __('Submitting...'),
					callback(r) {
						if (!r.message) return;
						me._toast(__('Sent for approval'), 'blue');
						me.refresh_context();
					},
				});
			}
		);
	}

	approve_order() {
		const me = this;
		frappe.confirm(
			__('Approve {0}? This creates its first sub order.', [this.docname]),
			() => {
				frappe.call({
					method: 'alpinos.production.production_order_api.approve_production_order',
					args: { production_order: me.docname },
					freeze: true,
					freeze_message: __('Approving...'),
					callback(r) {
						if (!r.message) return;
						const subs = r.message.sub_orders || [];
						me._toast(subs.length
							? __('Approved. Sub order {0} created.', [subs.join(', ')])
							: __('Approved'), 'green');
						me.refresh_context();
					},
				});
			}
		);
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			production_type: this._val('production_type'),
			client_name: this._val('client_name') || null,
			batch_number: this._val('batch_number'),
			delivery_date: this._val('delivery_date') || null,
			fg_item: this._val('fg_item'),
			production_qty_kg: flt(this._val('production_qty_kg')),
			production_qty_pcs: cint(this._val('production_qty_pcs')),
			production_start_date: this._val('production_start_date') || null,
			total_batches: flt(this._val('total_batches')),
			total_rm_requirement: flt(this._val('total_rm_requirement')),
			total_additive_requirement: flt(this._val('total_additive_requirement')),
			total_material_requirement: flt(this._val('total_material_requirement')),
			remarks: this._val('remarks'),
			items: this.rows.map((row) => ({
				item_code: row.item_code,
				process_stage: row.process_stage,
				total_required_qty: flt(row.total_required_qty),
			})),
		};
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.production_order_api.save_production_order',
			args: { payload: this.collect() },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				const created = !me.docname;
				me._toast(created ? __('Created') : __('Saved'), 'green');
				if (created) {
					frappe.set_route('production_order_entry', r.message.name);
				} else {
					me.refresh_context();
				}
			},
		});
	}

	remove() {
		const me = this;
		frappe.confirm(__('Delete production order {0}?', [this.docname]), () => {
			frappe.call({
				method: 'frappe.client.delete',
				args: { doctype: 'Production Order', name: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Deleted'), 'orange');
					frappe.set_route('production_order_list');
				},
			});
		});
	}
};
