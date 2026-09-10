/**
 * GRN Detail — BRD 5.2, "GRN Detail Screen Layout (Read-Only)".
 *
 * Read-only is the point, not a shortcut. Everything on this screen was decided
 * upstream: the quantities come from the Purchase QC decision, the stock split from
 * the module warehouses, and only an Admin may finally submit the receipt
 * (BR-GRN-06). Offering edits here would give the site a second place to change
 * numbers that the QC already reconciled.
 *
 * The one action it does carry is Submit, and only for the role that may do it —
 * drawn from the server rather than decided here.
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
		this.make_fields();
		this.apply_state();
	}

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data', read_only: 1, hide_timezone: 1 }, df),
			parent: parent,
			render_input: true,
		});
		c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		c.refresh();
		this.fields[df.fieldname] = c;
		return c;
	}

	_set(f, v) {
		const c = this.fields[f];
		if (c) { c.set_value(v === undefined || v === null ? '' : ALP_TRIM_MICROSECONDS(v)); c.refresh(); }
	}

	make_fields() {
		const ro = (sel, fieldname, label, fieldtype, options) =>
			this._ctl(sel, { fieldname, label, fieldtype: fieldtype || 'Data', options });

		ro('.field-name', 'name', 'GRN No.');
		ro('.field-posting-date', 'posting_date', 'Posting Date', 'Date');
		ro('.field-supplier', 'supplier', 'Vendor', 'Link', 'Supplier');
		ro('.field-bill-no', 'bill_no', 'Supplier Invoice No.');
		ro('.field-purchase-inward', 'custom_purchase_inward', 'Purchase Inward',
			'Link', 'Purchase Inward');
		ro('.field-purchase-qc', 'custom_purchase_qc', 'Purchase QC', 'Link', 'Purchase QC');
		ro('.field-grn-status', 'custom_grn_status', 'GRN Status');
		ro('.field-debit-note', 'custom_debit_note', 'Debit Note', 'Link', 'Purchase Invoice');

		ro('.field-total-received', 'total_received', 'Total Received', 'Float');
		ro('.field-total-accepted', 'total_accepted', 'Total Accepted', 'Float');
		ro('.field-total-rejected', 'total_rejected', 'Total Rejected', 'Float');

		ro('.field-submitted-by', 'custom_final_submitted_by', 'Final Submitted By',
			'Link', 'User');
		ro('.field-submitted-on', 'custom_final_submission_datetime', 'Final Submitted On',
			'Datetime');
		ro('.field-receiving-remarks', 'custom_receiving_remarks', 'Receiving Remarks',
			'Small Text');
	}

	// ---------------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1] || (frappe.route_options && frappe.route_options.purchase_receipt);
		if (frappe.route_options) delete frappe.route_options.purchase_receipt;
		if (name && name !== this.docname) {
			// Drop the resting card before the fetch so the body is not swapped in
			// behind the freeze overlay.
			this.wrapper.find('.purchase-grn-view').removeClass('grn-blank');
			this.load(name);
		} else if (!name && this.docname) {
			this.docname = null;
			this.doc = null;
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
				me.docname = doc.name;
				me.doc = doc;
				[
					'name', 'posting_date', 'supplier', 'bill_no', 'custom_purchase_inward',
					'custom_purchase_qc', 'custom_grn_status', 'custom_debit_note',
					'custom_final_submitted_by', 'custom_final_submission_datetime',
					'custom_receiving_remarks',
				].forEach((f) => me._set(f, doc[f]));

				me.render_items();
				me.render_changelog();
				me.apply_state();
				me.page.set_title(`${doc.name} — GRN`);
			},
		});
	}

	render_items() {
		const rows = (this.doc && this.doc.items) || [];
		const $body = this.wrapper.find('.items-table tbody').empty();
		let received = 0;
		let accepted = 0;
		let rejected = 0;

		rows.forEach((row) => {
			const acc = flt(row.qty);
			const rej = flt(row.rejected_qty);
			accepted += acc;
			rejected += rej;
			received += acc + rej;
			$body.append($(`
				<tr>
					<td>${row.idx}</td>
					<td>${frappe.utils.escape_html(row.item_code || '')}
						<div class="text-muted" style="font-size:11px;">${frappe.utils.escape_html(row.item_name || '')}</div></td>
					<td>${frappe.utils.escape_html(row.uom || '')}</td>
					<td class="grn-num">${format_number(acc + rej, null, 3)}</td>
					<td class="grn-num">${format_number(acc, null, 3)}</td>
					<td class="grn-num ${rej ? 'grn-rejected' : ''}">${format_number(rej, null, 3)}</td>
					<td>${frappe.utils.escape_html(row.warehouse || '')}</td>
					<td>${frappe.utils.escape_html(row.rejected_warehouse || '')}</td>
					<td>${frappe.utils.escape_html(row.batch_no || '')}</td>
					<td>${frappe.utils.escape_html(row.custom_rejection_reason || '')}</td>
				</tr>
			`));
		});

		this._set('total_received', received);
		this._set('total_accepted', accepted);
		this._set('total_rejected', rejected);
	}

	render_changelog() {
		const rows = (this.doc && this.doc.custom_grn_change_log) || [];
		const $body = this.wrapper.find('.changelog-table tbody').empty();
		rows.forEach((row, i) => {
			$body.append($(`
				<tr>
					<td>${i + 1}</td>
					<td>${frappe.utils.escape_html(row.field_label || '')}</td>
					<td>${frappe.utils.escape_html(row.old_value || '')}</td>
					<td>${frappe.utils.escape_html(row.new_value || '')}</td>
					<td>${frappe.utils.escape_html(row.changed_by || '')}</td>
					<td>${frappe.utils.escape_html(String(row.changed_on || '').split('.')[0])}</td>
				</tr>
			`));
		});
	}

	apply_state() {
		const doc = this.doc || {};
		this.wrapper.find('.purchase-grn-view').toggleClass('grn-blank', !this.docname);

		const status = doc.custom_grn_status || '';
		const $badge = this.wrapper.find('.field-stage-badge')
			.text(status)
			.removeClass('grn-done grn-draft');
		if (cint(doc.docstatus) === 1) $badge.addClass('grn-done');
		else if (cint(doc.docstatus) === 0) $badge.addClass('grn-draft');

		this.make_actions();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.grn-actionbar').empty();
		if (!this.docname) return;
		const doc = this.doc || {};

		const btn = (label, cls, handler) => {
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		};

		if (cint(doc.docstatus) === 0) {
			// BR-GRN-06 / VAL-GRN-04: the server decides who may do this. The button is
			// shown to everyone and refused by name, rather than hidden, so a Purchase
			// user is told WHY instead of wondering where the action went.
			btn(__('Submit GRN'), 'btn-primary', () => {
				frappe.confirm(
					__('Submit this GRN? Stock moves and it can no longer be edited.'),
					() => frappe.call({
						method: 'frappe.client.submit',
						args: { doc: me.doc },
						freeze: true,
						freeze_message: __('Submitting the GRN...'),
						callback() {
							frappe.show_alert({ message: __('GRN submitted'), indicator: 'green' }, 5);
							me.load(me.docname);
						},
					})
				);
			});
		}

		btn(__('Print'), 'btn-light', () => {
			frappe.set_route('print', 'Purchase Receipt', me.docname);
		});
		btn(__('Open Full Record'), 'btn-light', () => {
			frappe.set_route('Form', 'Purchase Receipt', me.docname);
		});
	}
};
