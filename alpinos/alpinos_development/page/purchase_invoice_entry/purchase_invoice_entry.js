/**
 * Purchase Invoice Entry — BRD "Purchase Invoice & Payment", section 6.2 (screen layout).
 *
 * One screen for both BRD 6.0 paths. A Normal invoice carries its GRN and Purchase Inward;
 * a Direct one carries its Purchase Order instead, and types its Payment Due Date by hand.
 *
 *   6.2.1 Supplier Bill, 6.2.2 Items, 6.2.3 Logistics  -> the Purchase Team, Draft only
 *   6.2.4 Payment & Logistics Reference                -> the Accounts Team, once submitted
 *
 * What may be edited, and which buttons show, come from the server
 * (purchase_invoice.get_invoice_context). The saves go through purchase_invoice.save_invoice
 * / submit_invoice, which write only the Purchase Team's fields, and payments through
 * add_payment -- so the rules (VAL-UNF-01..07, BR-UNF-03..06) are enforced there, not here.
 *
 * Design language matches the Purchase Inward and Purchase QC entry pages.
 */

// A Datetime straight out of the database carries microseconds, which the Frappe Datetime
// control rejects and then blanks. var, not const: desk pages are re-evaluated on navigation.
var ALP_TRIM_MICROSECONDS = function (v) {
	if (typeof v !== 'string') return v;
	var m = v.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.\d+$/);
	return m ? m[1] : v;
};

var PINV_DIRECT_TYPE = 'Direct Purchase Invoice';

frappe.pages['purchase_invoice_entry'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase Invoice Entry',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_invoice_entry'));
	wrapper.pinv_entry = new PurchaseInvoiceEntry(page);
};

frappe.pages['purchase_invoice_entry'].on_page_show = function (wrapper) {
	if (wrapper.pinv_entry) wrapper.pinv_entry.handle_route_entry();
};

var PurchaseInvoiceEntry = class {
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
		// refresh() BEFORE set_value(): set_value is asynchronous and refresh is not, so the
		// other order let a Date control redraw empty and clear itself after the value landed
		// (the same bug the Purchase Inward screen documents in its _ctl).
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

	_is_direct() {
		return (this.ctx.invoice_type || '') === PINV_DIRECT_TYPE;
	}

	_money(v) {
		return format_currency(flt(v), (this.doc && this.doc.currency) || undefined);
	}

	// ---------------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1];
		const opts = frappe.route_options || {};
		// Add Payment on the list opens this screen and asks for the dialog.
		if (cint(opts.add_payment)) this._open_payment = true;
		if (frappe.route_options) delete frappe.route_options.add_payment;

		if (name && name !== this.docname) {
			this.wrapper.find('.purchase-invoice-entry').removeClass('pinv-blank');
			this.load(name);
		} else if (name) {
			this.maybe_open_payment();
		} else if (this.docname) {
			// Opened bare after viewing an invoice: the previous one must not linger on
			// screen looking like the current one.
			this.docname = null;
			this.doc = null;
			this.ctx = {};
			this.items = [];
			this.wrapper.find('tbody').empty();
			this.page.set_title(__('Purchase Invoice Entry'));
			this.apply_state();
		}
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Invoice', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				frappe.call({
					method: 'alpinos.purchase.purchase_invoice.get_invoice_context',
					args: { purchase_invoice: doc.name },
					callback(c) {
						if (!c.message) return;
						me.doc = doc;
						me.ctx = c.message;
						me.docname = doc.name;
						me.render();
						me.apply_state();
						me.page.set_title(`${doc.name} — Purchase Invoice`);
						me.maybe_open_payment();
					},
				});
			},
		});
	}

	// ---------------------------------------------------------------- render

	render() {
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const editable = !!cint(ctx.can_edit);
		const direct = this._is_direct();
		const ro = (sel, fieldname, label, fieldtype, options, value) =>
			this._ctl(sel, { fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1 },
				value === undefined ? doc[fieldname] : value);
		const ed = (sel, df, value) =>
			this._ctl(sel, Object.assign({}, df, { read_only: editable ? 0 : 1 }),
				value === undefined ? doc[df.fieldname] : value);

		// ---- 6.2.1 supplier bill
		ro('.field-name', 'name', 'Purchase Invoice ID');
		ro('.field-grn', 'custom_grn', 'GRN ID', 'Link', 'Purchase Receipt');
		ro('.field-purchase-inward', 'custom_purchase_inward', 'Purchase Inward ID', 'Link', 'Purchase Inward');
		ro('.field-purchase-order', 'purchase_order', 'PO ID', 'Data', null,
			(ctx.purchase_orders || []).join(', '));
		ro('.field-supplier', 'supplier_name', 'Supplier Name', 'Data', null,
			doc.supplier_name || doc.supplier);
		ed('.field-bill-no', { fieldname: 'bill_no', label: 'Supplier Invoice Number', fieldtype: 'Data', reqd: 1 });
		ed('.field-bill-date', { fieldname: 'bill_date', label: 'Supplier Invoice Date', fieldtype: 'Date', reqd: 1 });

		let due_note;
		if (direct) due_note = __('Enter the date the payment is due.');
		else if (cint(ctx.due_date_auto)) due_note = __("Invoice Date + the supplier's Payment Terms, calculated on save.");
		else due_note = __('The supplier has no Payment Terms, so enter the date by hand.');
		this._ctl('.field-due-date', {
			fieldname: 'custom_payment_due_date',
			label: 'Payment Due Date',
			fieldtype: 'Date',
			reqd: 1,
			read_only: editable && !cint(ctx.due_date_auto) ? 0 : 1,
			description: editable ? due_note : '',
		}, doc.custom_payment_due_date);

		ro('.field-grand-total', 'grand_total', 'Total Invoice Amount', 'Currency', null,
			flt(doc.rounded_total || doc.grand_total));
		ed('.field-invoice-attachment', {
			fieldname: 'custom_invoice_attachment', label: 'Invoice Attachment', fieldtype: 'Attach', reqd: 1,
		});
		ed('.field-invoice-remarks', {
			fieldname: 'custom_invoice_remarks', label: 'Invoice Remarks', fieldtype: 'Small Text',
		});

		// ---- 6.2.2 items
		this.items = (doc.items || []).map((row) => Object.assign({}, row));
		// Buying Settings "Maintain Same Rate" (Stop) makes ERPNext refuse any price that
		// differs from the PO / GRN, so the price is only offered for editing when it may change.
		this.render_items(editable && !!cint(ctx.rate_editable));
		this.wrapper.find('.field-rate-note').text(
			editable && !cint(ctx.rate_editable)
				? __('Unit Price follows the Purchase Order: Buying Settings has "Maintain Same Rate" switched on.')
				: ''
		);

		// ---- 6.2.3 logistics
		const me = this;
		ed('.field-include-logistics', {
			fieldname: 'custom_include_logistics',
			label: 'Include Logistics?',
			fieldtype: 'Check',
			change: () => {
				me.toggle_logistics();
				me.recalc_payment_summary();
			},
		});
		ed('.field-logistics-vendor', {
			fieldname: 'custom_logistics_vendor', label: 'Logistics Vendor', fieldtype: 'Link',
			options: 'Supplier', reqd: 1,
		});
		ed('.field-transport-invoice-no', {
			fieldname: 'custom_transport_invoice_no', label: 'Transport Invoice No.', fieldtype: 'Data', reqd: 1,
		});
		const freight = ed('.field-freight-amount', {
			fieldname: 'custom_freight_amount', label: 'Freight Amount', fieldtype: 'Currency', reqd: 1,
			change: () => me.recalc_payment_summary(),
		});
		// df.change only fires when the box loses focus; follow the typing as well.
		if (freight && freight.$input) {
			freight.$input.on('input', frappe.utils.debounce(() => me.recalc_payment_summary(), 150));
		}
		ed('.field-transport-attachment', {
			fieldname: 'custom_transport_attachment', label: 'Transport Attachment', fieldtype: 'Attach', reqd: 1,
		});
		this.toggle_logistics();

		// ---- 6.2.4 payments
		this.recalc_payment_summary();
		this.render_payments();
	}

	/**
	 * Supplier / Logistics Payable and Pending (BR-UNF-04).
	 *
	 * A submitted invoice shows what the server derived from the recorded payments. A Draft
	 * holds no payments, so its payable IS what is on screen: the invoice total and, when
	 * Include Logistics is ticked, the Freight Amount. These used to show the last SAVED
	 * figures, so ticking Include Logistics and typing a freight amount left Logistics
	 * Payable at 0.00 until the draft was saved and reopened, which read as freight being
	 * ignored.
	 */
	recalc_payment_summary() {
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		let supplier_payable = flt(ctx.supplier_payable);
		let supplier_pending = flt(ctx.supplier_pending);
		let logistics_payable = flt(ctx.logistics_payable);
		let logistics_pending = flt(ctx.logistics_pending);
		let total_paid = flt(ctx.total_paid);

		if (this.docname && cint(doc.docstatus) === 0) {
			supplier_payable = flt(this._live_total);
			logistics_payable = cint(this._val('custom_include_logistics'))
				? flt(this._val('custom_freight_amount'))
				: 0;
			supplier_pending = supplier_payable;
			logistics_pending = logistics_payable;
			total_paid = 0;
		}

		const ro = (sel, fieldname, label, value) =>
			this._ctl(sel, { fieldname, label, fieldtype: 'Currency', read_only: 1 }, value);
		ro('.field-supplier-payable', 'supplier_payable', 'Supplier Payable', supplier_payable);
		ro('.field-supplier-pending', 'supplier_pending', 'Supplier Pending', supplier_pending);
		ro('.field-logistics-payable', 'logistics_payable', 'Logistics Payable', logistics_payable);
		ro('.field-logistics-pending', 'logistics_pending', 'Logistics Pending', logistics_pending);
		ro('.field-total-paid', 'total_paid', 'Total Paid', total_paid);
	}

	render_items(editable) {
		const me = this;
		const $body = this.wrapper.find('.items-table tbody').empty();
		this.items.forEach((row, idx) => {
			const $tr = $(`<tr data-idx="${idx}">
				<td class="text-muted">${cint(row.idx) || idx + 1}</td>
				<td>${frappe.utils.escape_html(row.item_code || '')}
					<div class="text-muted" style="font-size:11px;">${frappe.utils.escape_html(row.item_name || '')}</div></td>
				<td>${frappe.utils.escape_html(row.uom || '')}</td>
				<td class="pinv-num">${format_number(row.qty, null, 3)}</td>
				<td class="pinv-num c-rate"></td>
				<td class="pinv-num c-amount"></td>
				<td>${frappe.utils.escape_html(row.purchase_order || '')}</td>
			</tr>`);
			$body.append($tr);

			if (editable) {
				// BRD 6.2.2: Unit Price is the one item value typed here. `ready` ignores the
				// df.change the initial set_value fires, so loading does not mark a row edited.
				let ready = false;
				const c = frappe.ui.form.make_control({
					df: {
						fieldname: `rate_${idx}`,
						fieldtype: 'Currency',
						change: () => {
							if (!ready) return;
							row.rate = flt(c.get_value());
							me.paint_amount($tr, row);
							me.recalc_totals();
						},
					},
					parent: $tr.find('.c-rate'),
					render_input: true,
				});
				Promise.resolve(c.set_value(flt(row.rate))).then(() => {
					ready = true;
				});
			} else {
				$tr.find('.c-rate').text(me._money(row.rate));
			}
			me.paint_amount($tr, row);
		});
		this.recalc_totals();
	}

	paint_amount($tr, row) {
		$tr.find('.c-amount').text(this._money(flt(row.qty) * flt(row.rate)));
	}

	/**
	 * Net total live from the lines; taxes as last saved. On a Draft the total moves with the
	 * net so the figure reacts to a price change -- the exact taxes are recomputed on save.
	 */
	recalc_totals() {
		const doc = this.doc || {};
		const net = this.items.reduce((s, r) => s + flt(r.qty) * flt(r.rate), 0);
		const saved_total = flt(doc.rounded_total || doc.grand_total);
		const total = cint(doc.docstatus) === 0 ? saved_total + (net - flt(doc.net_total)) : saved_total;
		this._live_total = total;
		this._ctl('.field-net-total', { fieldname: 'net_total', label: 'Net Total', fieldtype: 'Currency', read_only: 1 }, net);
		this._ctl('.field-taxes', {
			fieldname: 'total_taxes_and_charges', label: 'Taxes & Charges', fieldtype: 'Currency', read_only: 1,
		}, flt(doc.total_taxes_and_charges));
		this._ctl('.field-total-amount', {
			fieldname: 'total_amount', label: 'Total Invoice Amount', fieldtype: 'Currency', read_only: 1,
		}, total);
		// A price change moves the supplier payable on a Draft too.
		if (this.fields.custom_include_logistics) this.recalc_payment_summary();
	}

	toggle_logistics() {
		const on = !!cint(this._val('custom_include_logistics'));
		this.wrapper.find('.pinv-logistics-fields').toggle(on);
	}

	render_payments() {
		const rows = (this.doc && this.doc.custom_payment_references) || [];
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const $body = this.wrapper.find('.payments-table tbody').empty();
		rows.forEach((row, i) => {
			const file = row.payment_attachment
				? `<a href="${esc(row.payment_attachment)}" target="_blank" rel="noopener">${esc(
						String(row.payment_attachment).split('/').pop()
				  )}</a>`
				: '';
			$body.append(`<tr>
				<td class="text-muted">${i + 1}</td>
				<td>${esc(row.payment_type)}</td>
				<td class="pinv-num">${esc(this._money(row.payment_amount))}</td>
				<td>${esc(row.payment_date ? frappe.datetime.str_to_user(row.payment_date) : '')}</td>
				<td>${esc(row.payment_mode)}</td>
				<td>${esc(row.reference_number)}</td>
				<td>${file}</td>
				<td>${esc(row.payment_status)}</td>
				<td>${esc(row.remarks)}</td>
				<td>${esc(row.recorded_by)}</td>
				<td>${esc(row.recorded_on ? frappe.datetime.str_to_user(ALP_TRIM_MICROSECONDS(row.recorded_on)) : '')}</td>
			</tr>`);
		});
	}

	// ----------------------------------------------------------------- state

	apply_state() {
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const $root = this.wrapper.find('.purchase-invoice-entry');
		$root.toggleClass('pinv-blank', !this.docname);
		$root.toggleClass('pinv-direct', this._is_direct());

		const status = ctx.status || '';
		this.wrapper.find('.field-stage-badge')
			.text(status ? __(status) : '')
			.removeClass('pinv-done pinv-open pinv-cancelled')
			.addClass(status === 'Completed' ? 'pinv-done' : status === 'Cancelled' ? 'pinv-cancelled' : 'pinv-open');
		this.wrapper.find('.field-type-badge').text(
			this.docname ? (this._is_direct() ? __('Direct Invoice') : __('Normal Invoice')) : ''
		);

		const docstatus = cint(doc.docstatus);
		let lock_note = '';
		if (docstatus === 1) lock_note = __('Submitted — the supplier bill, items and logistics bill are read-only (BR-UNF-03).');
		else if (docstatus === 2) lock_note = __('This invoice is cancelled.');
		else if (this.docname && !cint(ctx.can_edit)) lock_note = __('Only the Purchase Team edits the supplier bill.');
		this.wrapper.find('.field-lock-note').text(lock_note);

		let pay_note = '';
		if (docstatus === 0) pay_note = __('Payments are recorded by the Accounts Team once the invoice is submitted.');
		else if (status === 'Completed') pay_note = __('The supplier and logistics amounts are fully paid.');
		else if (docstatus === 1 && !cint(ctx.can_add_payment)) pay_note = __('Payments are recorded by the Accounts Team.');
		this.wrapper.find('.field-payment-note').text(pay_note);

		const $pay = this.wrapper.find('.pinv-payment-actions').empty();
		if (cint(ctx.can_add_payment)) {
			$(`<button class="btn btn-sm btn-primary"><i class="fa fa-plus"></i> ${__('Add Payment')}</button>`)
				.on('click', () => this.open_payment_dialog())
				.appendTo($pay);
		}

		this.make_actions();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.pinv-actionbar').empty();
		if (!this.docname) return;
		const doc = this.doc || {};
		const ctx = this.ctx || {};
		const btn = (label, cls, handler) => {
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		};

		if (cint(ctx.can_edit)) btn(__('Save Draft'), 'btn-default', () => me.save());
		if (cint(ctx.can_submit)) btn(__('Submit Invoice'), 'btn-primary', () => me.submit());
		btn(__('Print'), 'btn-default', () => me.print_invoice());
		if (doc.custom_grn) btn(__('Open GRN'), 'btn-default', () => frappe.set_route('purchase_grn_view', doc.custom_grn));
		if (doc.custom_purchase_inward) {
			btn(__('Open Inward'), 'btn-default', () => frappe.set_route('purchase_inward_entry', doc.custom_purchase_inward));
		}
		if ((ctx.purchase_orders || []).length) {
			btn(__('Open PO'), 'btn-default', () => frappe.set_route('Form', 'Purchase Order', ctx.purchase_orders[0]));
		}
		btn(__('Open Full Record'), 'btn-light', () => frappe.set_route('Form', 'Purchase Invoice', me.docname));
	}

	/**
	 * The module's own "Purchase Invoice" format (alpinos.purchase.print_formats), opened by
	 * name. It is not the doctype default -- Purchase Invoice also carries debit notes and
	 * invoices keyed in outside this module -- and set_route('print', ...) can only open the
	 * default, so the printview endpoint is used, as the QC list does for its report.
	 */
	print_invoice() {
		const url =
			'/printview?doctype=' + encodeURIComponent('Purchase Invoice') +
			'&name=' + encodeURIComponent(this.docname) +
			'&format=' + encodeURIComponent('Purchase Invoice') +
			'&trigger_print=1&_lang=' + encodeURIComponent(frappe.boot.lang || 'en');
		const w = window.open(url, '_blank');
		if (!w) frappe.msgprint(__('Please allow pop-ups to print the invoice.'));
	}

	// ------------------------------------------------------------ save / submit

	collect() {
		const data = {};
		[
			'bill_no', 'bill_date', 'custom_invoice_attachment', 'custom_invoice_remarks',
			'custom_include_logistics', 'custom_logistics_vendor', 'custom_transport_invoice_no',
			'custom_freight_amount', 'custom_transport_attachment',
		].forEach((f) => {
			data[f] = this._val(f);
		});
		// A computed due date is the server's to set; sending the stale screen value back
		// would only be overwritten.
		if (!cint(this.ctx.due_date_auto)) data.custom_payment_due_date = this._val('custom_payment_due_date');
		data.custom_include_logistics = cint(data.custom_include_logistics);
		data.items = this.items.map((r) => ({ name: r.name, rate: flt(r.rate) }));
		return data;
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.purchase_invoice.save_invoice',
			args: { purchase_invoice: me.docname, data: JSON.stringify(me.collect()) },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				// A refused save keeps what is on screen, so nothing typed is lost.
				if (r.exc) return;
				me._toast(__('Saved'), 'green');
				me.load(me.docname);
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(
			__('Submit this invoice? The supplier bill, items and logistics bill lock, and it moves to the Accounts Team for payment.'),
			() =>
				frappe.call({
					method: 'alpinos.purchase.purchase_invoice.submit_invoice',
					args: { purchase_invoice: me.docname, data: JSON.stringify(me.collect()) },
					freeze: true,
					freeze_message: __('Submitting...'),
					callback(r) {
						// save and submit run in one request, so a refusal (VAL-UNF-01..03)
						// stores nothing and the screen keeps what was typed
						if (r.exc) return;
						me._toast(__('Invoice submitted'), 'green');
						me.load(me.docname);
					},
				})
		);
	}

	// --------------------------------------------------------------- payments

	maybe_open_payment() {
		if (!this._open_payment || !this.docname) return;
		this._open_payment = false;
		if (cint(this.ctx.can_add_payment)) this.open_payment_dialog();
	}

	/** BRD 6.2.4 "Add Payment & Submit" — one payment, checked by the server (VAL-UNF-04..07). */
	open_payment_dialog() {
		const me = this;
		const ctx = this.ctx || {};
		const types = ctx.payment_types || ['Supplier Payment'];
		const pending = (type) =>
			type === 'Logistics Payment' ? flt(ctx.logistics_pending) : flt(ctx.supplier_pending);
		const summary = () =>
			`<div class="text-muted" style="font-size:12px; margin-bottom:6px;">${__(
				'Supplier pending: {0} · Logistics pending: {1}',
				[me._money(ctx.supplier_pending), me._money(ctx.logistics_pending)]
			)}</div>`;

		const d = new frappe.ui.Dialog({
			title: __('Add Payment — {0}', [this.docname]),
			fields: [
				{ fieldname: 'summary', fieldtype: 'HTML', options: summary() },
				{
					fieldname: 'payment_type', fieldtype: 'Select', label: __('Payment Type'),
					options: types.join('\n'), default: types[0], reqd: 1,
					onchange: () => d.set_value('payment_amount', pending(d.get_value('payment_type'))),
				},
				{ fieldname: 'payment_amount', fieldtype: 'Currency', label: __('Payment Amount'), reqd: 1 },
				{
					fieldname: 'payment_date', fieldtype: 'Date', label: __('Payment Date'),
					default: frappe.datetime.get_today(), reqd: 1,
				},
				{ fieldname: 'col_1', fieldtype: 'Column Break' },
				{
					fieldname: 'payment_mode', fieldtype: 'Select', label: __('Payment Mode'),
					options: [''].concat(ctx.payment_modes || []).join('\n'), reqd: 1,
				},
				{
					fieldname: 'reference_number', fieldtype: 'Data', label: __('Reference Number'),
					description: __('Tally ID / UTR / Cheque No.'),
				},
				{ fieldname: 'payment_attachment', fieldtype: 'Attach', label: __('Payment Attachment') },
				{ fieldname: 'sec_1', fieldtype: 'Section Break' },
				{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('Remarks') },
			],
			primary_action_label: __('Save Payment'),
			primary_action(values) {
				frappe.call({
					method: 'alpinos.purchase.purchase_invoice.add_payment',
					args: {
						purchase_invoice: me.docname,
						payment_type: values.payment_type,
						payment_amount: values.payment_amount,
						payment_date: values.payment_date,
						payment_mode: values.payment_mode,
						reference_number: values.reference_number || null,
						payment_attachment: values.payment_attachment || null,
						remarks: values.remarks || null,
					},
					freeze: true,
					freeze_message: __('Recording payment...'),
					callback(r) {
						// VAL-UNF-04..07 refusals keep the dialog open with what was typed
						if (r.exc || !r.message) return;
						d.hide();
						me._toast(__('Payment recorded — invoice is now {0}', [__(r.message.status)]), 'green');
						me.load(me.docname);
					},
				});
			},
		});
		d.show();
		d.set_value('payment_amount', pending(types[0]));
	}
};
