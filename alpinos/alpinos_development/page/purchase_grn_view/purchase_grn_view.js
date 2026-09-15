/**
 * GRN Detail — BRD 5.2.
 *
 * A Draft GRN is the Purchase Team's review copy: every value on it can be changed here,
 * and each change is written to the Draft Edit Log (purchase_receipt_fields.
 * log_draft_grn_edits, which logs desk-form edits the same way). Once submitted the GRN is
 * read-only. A Draft can be cancelled, a cancelled GRN amended into a new Draft, and that
 * Draft submitted.
 *
 * What may be done is decided on the server (grn_edit.get_grn_context), and every write
 * goes through grn_edit, which re-checks the role.
 */

// A Datetime straight out of the database carries microseconds, which the Frappe
// Datetime control rejects outright and then blanks. var, not const: desk pages are
// re-evaluated on navigation.
var ALP_TRIM_MICROSECONDS = function (v) {
	if (typeof v !== 'string') return v;
	var m = v.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.\d+$/);
	return m ? m[1] : v;
};

frappe.pages['purchase_grn_view'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'GRN Detail',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_grn_view'));
	wrapper.grn_view = new GRNView(page);
};

frappe.pages['purchase_grn_view'].on_page_show = function (wrapper) {
	if (wrapper.grn_view) wrapper.grn_view.handle_route_entry();
};

var GRNView = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.ctx = {};
		this.items = [];
		this.apply_state();
	}

	// ------------------------------------------------------------- helpers

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data', hide_timezone: 1 }, df),
			parent: parent,
			render_input: true,
		});
		// refresh() BEFORE set_value(): set_value is asynchronous, and the other order let a
		// Date control redraw empty and clear itself after the value landed.
		c.refresh();
		c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		this.fields[df.fieldname] = c;
		return c;
	}

	_val(f) {
		const c = this.fields[f];
		return c ? c.get_value() : null;
	}

	_toast(m, i) {
		frappe.show_alert({ message: m, indicator: i || 'blue' }, 5);
	}

	/**
	 * A Link cell's suggestion list, taken out of the scrolling grid so it is not clipped
	 * to the table's height (the same fix the Purchase QC screen uses).
	 */
	_float_dropdown(c) {
		if (!c || !c.$input || !c.awesomplete || !c.awesomplete.ul) return;
		const input = c.$input.get(0);
		const ul = c.awesomplete.ul;
		const place = () => {
			const r = input.getBoundingClientRect();
			ul.style.position = 'fixed';
			ul.style.left = `${r.left}px`;
			ul.style.width = `${Math.max(r.width, 260)}px`;
			ul.style.minWidth = '0';
			ul.style.zIndex = '1060';
			const below = window.innerHeight - r.bottom;
			const needed = ul.offsetHeight || 0;
			ul.style.top = needed > below && r.top > below
				? `${Math.max(r.top - needed - 2, 4)}px`
				: `${r.bottom + 2}px`;
		};
		c.$input.on('awesomplete-open', () => {
			place();
			requestAnimationFrame(place);
			window.addEventListener('scroll', place, true);
			window.addEventListener('resize', place);
		});
		c.$input.on('awesomplete-close', () => {
			window.removeEventListener('scroll', place, true);
			window.removeEventListener('resize', place);
		});
	}

	// ---------------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1] || (frappe.route_options && frappe.route_options.purchase_receipt);
		if (frappe.route_options) delete frappe.route_options.purchase_receipt;
		if (name && name !== this.docname) {
			this.wrapper.find('.purchase-grn-view').removeClass('grn-blank');
			this.load(name);
		} else if (!name && this.docname) {
			this.docname = null;
			this.doc = null;
			this.ctx = {};
			this.items = [];
			this.wrapper.find('tbody').empty();
			this.page.set_title(__('GRN Detail'));
			this.apply_state();
		}
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Receipt', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				frappe.call({
					method: 'alpinos.purchase.grn_edit.get_grn_context',
					args: { purchase_receipt: doc.name },
					callback(c) {
						if (!c.message) return;
						me.doc = doc;
						me.ctx = c.message;
						me.docname = doc.name;
						me.render();
						me.apply_state();
						me.page.set_title(`${doc.name} — GRN`);
					},
				});
			},
		});
	}

	// ---------------------------------------------------------------- render

	render() {
		const doc = this.doc || {};
		const editable = !!cint(this.ctx.can_edit);
		const ro = (sel, fieldname, label, fieldtype, options, value) =>
			this._ctl(sel, { fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1 },
				value === undefined ? doc[fieldname] : value);
		const ed = (sel, df) =>
			this._ctl(sel, Object.assign({}, df, { read_only: editable ? 0 : 1 }), doc[df.fieldname]);

		ro('.field-name', 'name', 'GRN No.');
		ed('.field-posting-date', { fieldname: 'posting_date', label: 'Posting Date', fieldtype: 'Date' });
		ro('.field-supplier', 'supplier_name', 'Vendor', 'Data', null, doc.supplier_name || doc.supplier);
		ro('.field-grn-status', 'custom_grn_status', 'GRN Status');
		ro('.field-purchase-inward', 'custom_purchase_inward', 'Purchase Inward', 'Link', 'Purchase Inward');
		ro('.field-purchase-qc', 'custom_purchase_qc', 'Purchase QC', 'Link', 'Purchase QC');
		const note_state = { 0: 'Draft', 1: 'Submitted', 2: 'Cancelled' }[this.ctx.debit_note_docstatus];
		ro('.field-debit-note', 'custom_debit_note',
			note_state ? __('Debit Note ({0})', [__(note_state)]) : __('Debit Note'), 'Link', 'Purchase Invoice');
		ro('.field-amended-from', 'amended_from', 'Amended From', 'Link', 'Purchase Receipt');
		ed('.field-supplier-delivery-note', {
			fieldname: 'supplier_delivery_note', label: 'Supplier Delivery Note', fieldtype: 'Data',
		});
		ed('.field-lr-no', { fieldname: 'lr_no', label: 'Vehicle Number', fieldtype: 'Data' });
		ed('.field-lr-date', { fieldname: 'lr_date', label: 'Vehicle Date', fieldtype: 'Date' });
		ed('.field-set-warehouse', {
			fieldname: 'set_warehouse', label: 'Accepted Warehouse', fieldtype: 'Link', options: 'Warehouse',
			get_query: () => ({ filters: { company: doc.company, is_group: 0 } }),
		});
		ed('.field-rejected-warehouse', {
			fieldname: 'rejected_warehouse', label: 'Rejected Warehouse', fieldtype: 'Link', options: 'Warehouse',
			get_query: () => ({ filters: { company: doc.company, is_group: 0 } }),
		});
		ed('.field-receiving-remarks', {
			fieldname: 'custom_receiving_remarks', label: 'Receiving Remarks', fieldtype: 'Small Text',
		});
		this._ctl('.field-edit-reason', {
			fieldname: 'edit_reason', label: 'Reason for these changes', fieldtype: 'Small Text',
			description: 'Optional. Saved in the Draft Edit Log against every change in this save.',
		});

		ro('.field-submitted-by', 'custom_final_submitted_by', 'Final Submitted By', 'Link', 'User');
		ro('.field-submitted-on', 'custom_final_submission_datetime', 'Final Submitted On', 'Datetime');

		this.items = (doc.items || []).map((row) => Object.assign({}, row));
		this.render_items(editable);
		this.wrapper.find('.field-rate-note').text(
			editable && !cint(this.ctx.rate_editable)
				? __('Rate follows the Purchase Order: Buying Settings has "Maintain Same Rate" switched on.')
				: ''
		);
		this.render_changelog();
	}

	render_items(editable) {
		const me = this;
		const doc = this.doc || {};
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const $body = this.wrapper.find('.items-table tbody').empty();

		this.items.forEach((row, idx) => {
			const $tr = $(`<tr data-idx="${idx}">
				<td class="text-muted">${cint(row.idx) || idx + 1}</td>
				<td>${esc(row.item_code)}<div class="text-muted" style="font-size:11px;">${esc(row.item_name)}</div></td>
				<td>${esc(row.uom)}</td>
				<td class="grn-num c-received"></td>
				<td class="c-qty"></td><td class="c-rej"></td>
				<td class="c-wh"></td><td class="c-rwh"></td>
				<td class="c-batch"></td><td class="c-rate"></td>
				<td class="c-mrp"></td><td class="c-usp"></td>
				<td class="c-reason"></td>
			</tr>`);
			$body.append($tr);

			const cell = (sel, df, fieldname, onchange, can_edit) => {
				const value = row[fieldname];
				if (!editable || can_edit === false) {
					let shown = value;
					if (df.fieldtype === 'Float') shown = format_number(flt(value), null, 3);
					else if (df.fieldtype === 'Currency') shown = format_currency(flt(value), doc.currency);
					$tr.find(sel).text(shown == null ? '' : shown)
						.toggleClass('grn-num', ['Float', 'Currency'].includes(df.fieldtype))
						.toggleClass('grn-rejected', fieldname === 'rejected_qty' && flt(value) > 0);
					return;
				}
				// `ready` ignores the df.change Frappe fires for the value drawn on load.
				let ready = false;
				const c = frappe.ui.form.make_control({
					df: Object.assign({ fieldname: `${fieldname}_${idx}` }, df, {
						change: () => {
							if (!ready) return;
							row[fieldname] = ['Float', 'Currency'].includes(df.fieldtype)
								? flt(c.get_value())
								: c.get_value();
							if (onchange) onchange();
						},
					}),
					parent: $tr.find(sel),
					render_input: true,
				});
				Promise.resolve(c.set_value(value == null ? '' : value)).then(() => {
					ready = true;
				});
				if (df.fieldtype === 'Link') me._float_dropdown(c);
			};
			const wh_query = () => ({ filters: { company: doc.company, is_group: 0 } });
			const qty_changed = () => {
				me.paint_received($tr, row);
				me.recalc_totals();
			};

			cell('.c-qty', { fieldtype: 'Float' }, 'qty', qty_changed);
			cell('.c-rej', { fieldtype: 'Float' }, 'rejected_qty', qty_changed);
			cell('.c-wh', { fieldtype: 'Link', options: 'Warehouse', get_query: wh_query }, 'warehouse');
			cell('.c-rwh', { fieldtype: 'Link', options: 'Warehouse', get_query: wh_query }, 'rejected_warehouse');
			cell('.c-batch', { fieldtype: 'Data' }, 'batch_no');
			cell('.c-rate', { fieldtype: 'Currency' }, 'rate', null, !!cint(me.ctx.rate_editable));
			cell('.c-mrp', { fieldtype: 'Currency' }, 'custom_mrp');
			cell('.c-usp', { fieldtype: 'Data' }, 'custom_usp');
			cell('.c-reason', { fieldtype: 'Data' }, 'custom_rejection_reason');
			me.paint_received($tr, row);
		});
		this.recalc_totals();
	}

	paint_received($tr, row) {
		$tr.find('.c-received').text(format_number(flt(row.qty) + flt(row.rejected_qty), null, 3));
	}

	recalc_totals() {
		let accepted = 0;
		let rejected = 0;
		this.items.forEach((row) => {
			accepted += flt(row.qty);
			rejected += flt(row.rejected_qty);
		});
		const ro = (sel, fieldname, label, value) =>
			this._ctl(sel, { fieldname, label, fieldtype: 'Float', read_only: 1 }, value);
		ro('.field-total-received', 'total_received', 'Total Received', accepted + rejected);
		ro('.field-total-accepted', 'total_accepted', 'Total Accepted', accepted);
		ro('.field-total-rejected', 'total_rejected', 'Total Rejected', rejected);
	}

	render_changelog() {
		const rows = (this.doc && this.doc.custom_grn_change_log) || [];
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const $body = this.wrapper.find('.changelog-table tbody').empty();
		rows.forEach((row, i) => {
			$body.append(`<tr>
				<td>${i + 1}</td>
				<td>${esc(row.field_label)}</td>
				<td>${esc(row.old_value)}</td>
				<td>${esc(row.new_value)}</td>
				<td>${esc(row.reason)}</td>
				<td>${esc(row.changed_by)}</td>
				<td>${esc(String(row.changed_on || '').split('.')[0])}</td>
			</tr>`);
		});
	}

	// ----------------------------------------------------------------- state

	apply_state() {
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const docstatus = cint(doc.docstatus);
		const $root = this.wrapper.find('.purchase-grn-view');
		$root.toggleClass('grn-blank', !this.docname);
		$root.toggleClass('grn-editable', !!cint(ctx.can_edit));

		const status = this.docname
			? (docstatus === 2 ? 'Cancelled' : (doc.custom_grn_status || (docstatus === 1 ? 'Completed' : 'Draft')))
			: '';
		this.wrapper.find('.field-stage-badge')
			.text(status ? __(status) : '')
			.removeClass('grn-done grn-draft grn-cancelled')
			.addClass(docstatus === 1 ? 'grn-done' : docstatus === 2 ? 'grn-cancelled' : 'grn-draft');

		let note = '';
		if (this.docname) {
			if (docstatus === 0 && cint(ctx.can_edit)) {
				note = __('Draft — review and change any value, then Save. Every change is recorded in the Draft Edit Log. Only an Admin can submit.');
			} else if (docstatus === 0) {
				note = __('Draft — awaiting review by the Purchase Team and final submission by the Admin.');
			} else if (docstatus === 1) {
				note = __('Submitted — this GRN is read-only.');
			} else if (ctx.amended_to) {
				note = __('Cancelled — amended as {0}.', [ctx.amended_to]);
			} else {
				note = __('Cancelled. Amend it to raise a new Draft that can be edited and submitted.');
			}
		}
		this.wrapper.find('.field-state-note').text(note);
		this.make_actions();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.grn-actionbar').empty();
		if (!this.docname) return;
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const docstatus = cint(doc.docstatus);
		const btn = (label, cls, handler) =>
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);

		if (docstatus === 0) {
			if (cint(ctx.can_edit)) btn(__('Save'), 'btn-default', () => me.save());
			if (cint(ctx.can_submit)) btn(__('Submit GRN'), 'btn-primary', () => me.submit());
		}
		if (cint(ctx.can_cancel)) btn(__('Cancel GRN'), 'btn-default', () => me.cancel());
		if (docstatus === 2) {
			if (cint(ctx.can_amend)) btn(__('Amend'), 'btn-primary', () => me.amend());
			if (ctx.amended_to) {
				btn(__('Open {0}', [ctx.amended_to]), 'btn-default', () =>
					frappe.set_route('purchase_grn_view', ctx.amended_to)
				);
			}
		}

		// The Debit Note for the rejected quantity, raised as a draft when the GRN is submitted.
		if (ctx.debit_note) {
			btn(__('View Debit Note'), 'btn-default', () =>
				frappe.set_route('Form', 'Purchase Invoice', ctx.debit_note)
			);
		}
		if (cint(ctx.can_cancel_debit_note)) btn(__('Cancel Debit Note'), 'btn-default', () => me.cancel_debit_note());
		if (cint(ctx.can_generate_debit_note)) btn(__('Generate Debit Note'), 'btn-default', () => me.generate_debit_note());

		// BRD 6.0 path A: the invoice becomes available once the Admin has finally submitted
		// the GRN (BR-UNF-01), one per GRN (BR-UNF-02). create_from_grn re-checks both.
		if (docstatus === 1) {
			frappe.db
				.get_value('Purchase Invoice', { custom_grn: me.docname, docstatus: ['<', 2] }, 'name')
				.then((r) => {
					const invoice = r && r.message && r.message.name;
					if (me.doc !== doc) return; // another GRN loaded meanwhile
					if (invoice) {
						btn(__('View Invoice'), 'btn-default', () =>
							frappe.set_route('purchase_invoice_entry', invoice)
						);
					} else if (frappe.model.can_create('Purchase Invoice')) {
						btn(__('Create Invoice'), 'btn-primary', () => me.create_invoice());
					}
				});
		}

		btn(__('Print'), 'btn-light', () => frappe.set_route('print', 'Purchase Receipt', me.docname));
		btn(__('Open Full Record'), 'btn-light', () => frappe.set_route('Form', 'Purchase Receipt', me.docname));
	}

	// --------------------------------------------------------------- actions

	collect() {
		const header = {};
		[
			'posting_date', 'supplier_delivery_note', 'lr_no', 'lr_date',
			'set_warehouse', 'rejected_warehouse', 'custom_receiving_remarks',
		].forEach((f) => {
			header[f] = this._val(f);
		});
		return {
			header: header,
			items: this.items.map((r) => ({
				name: r.name,
				qty: flt(r.qty),
				rejected_qty: flt(r.rejected_qty),
				warehouse: r.warehouse,
				rejected_warehouse: r.rejected_warehouse,
				batch_no: r.batch_no,
				rate: flt(r.rate),
				custom_mrp: flt(r.custom_mrp),
				custom_usp: r.custom_usp,
				custom_rejection_reason: r.custom_rejection_reason,
			})),
			reason: this._val('edit_reason'),
		};
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.grn_edit.save_grn',
			args: { purchase_receipt: me.docname, data: JSON.stringify(me.collect()) },
			freeze: true,
			freeze_message: __('Saving the GRN...'),
			callback(r) {
				// a refused save keeps what is on screen
				if (r.exc) return;
				me._toast(__('GRN saved'), 'green');
				me.load(me.docname);
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(__('Submit this GRN? Stock moves and it can no longer be edited.'), () =>
			frappe.call({
				method: 'alpinos.purchase.grn_edit.submit_grn',
				args: {
					purchase_receipt: me.docname,
					data: cint(me.ctx.can_edit) ? JSON.stringify(me.collect()) : null,
				},
				freeze: true,
				freeze_message: __('Submitting the GRN...'),
				callback(r) {
					if (r.exc) return;
					me._toast(__('GRN submitted'), 'green');
					me.load(me.docname);
				},
			})
		);
	}

	cancel() {
		const me = this;
		const submitted = cint((this.doc || {}).docstatus) === 1;
		frappe.prompt(
			[{
				fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason for cancelling'),
				reqd: submitted ? 1 : 0,
			}],
			(values) =>
				frappe.call({
					method: 'alpinos.purchase.grn_edit.cancel_grn',
					args: { purchase_receipt: me.docname, reason: values.reason || null },
					freeze: true,
					freeze_message: __('Cancelling the GRN...'),
					callback(r) {
						if (r.exc) return;
						me._toast(__('GRN cancelled'), 'orange');
						me.load(me.docname);
					},
				}),
			submitted ? __('Cancel submitted GRN {0}? Its stock is reversed.', [me.docname]) : __('Cancel Draft GRN {0}?', [me.docname]),
			__('Cancel GRN')
		);
	}

	cancel_debit_note() {
		const me = this;
		const note = this.ctx.debit_note;
		const submitted = cint(this.ctx.debit_note_docstatus) === 1;
		frappe.prompt(
			[{
				fieldname: 'reason', fieldtype: 'Small Text', label: __('Reason for cancelling'),
				reqd: submitted ? 1 : 0,
			}],
			(values) =>
				frappe.call({
					method: 'alpinos.purchase.grn_edit.cancel_debit_note',
					args: { purchase_receipt: me.docname, debit_note: note, reason: values.reason || null },
					freeze: true,
					freeze_message: __('Cancelling the Debit Note...'),
					callback(r) {
						if (r.exc) return;
						me._toast(__('Debit Note {0} cancelled', [note]), 'orange');
						me.load(me.docname);
					},
				}),
			submitted
				? __('Cancel submitted Debit Note {0}? Its accounting entries are reversed.', [note])
				: __('Cancel Draft Debit Note {0}?', [note]),
			__('Cancel Debit Note')
		);
	}

	generate_debit_note() {
		const me = this;
		frappe.confirm(__('Raise a new Draft Debit Note for the rejected quantity on {0}?', [me.docname]), () =>
			frappe.call({
				method: 'alpinos.purchase.grn.generate_debit_note',
				args: { purchase_receipt: me.docname },
				freeze: true,
				freeze_message: __('Raising the Debit Note...'),
				callback(r) {
					if (r.exc) return;
					const note = r.message && r.message.debit_note;
					me._toast(note ? __('Debit Note {0} raised', [note]) : __('Nothing rejected, so no Debit Note'), note ? 'green' : 'orange');
					me.load(me.docname);
				},
			})
		);
	}

	amend() {
		const me = this;
		frappe.confirm(__('Raise a new Draft GRN from {0}?', [me.docname]), () =>
			frappe.call({
				method: 'alpinos.purchase.grn_edit.amend_grn',
				args: { purchase_receipt: me.docname },
				freeze: true,
				freeze_message: __('Amending...'),
				callback(r) {
					if (r.exc || !r.message) return;
					me._toast(__('Amended as {0}', [r.message.name]), 'green');
					frappe.set_route('purchase_grn_view', r.message.name);
				},
			})
		);
	}

	create_invoice() {
		const me = this;
		frappe.confirm(__('Create the Purchase Invoice for {0}?', [me.docname]), () =>
			frappe.call({
				method: 'alpinos.purchase.invoice_list_api.create_invoice',
				args: { source_type: 'grn', source: me.docname },
				freeze: true,
				freeze_message: __('Creating the Purchase Invoice...'),
				callback(r) {
					if (r.exc || !r.message) return;
					frappe.set_route('purchase_invoice_entry', r.message.name);
				},
			})
		);
	}
};
