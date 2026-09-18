/**
 * Purchase Inward Entry — BRD "Purchase Inward Part -1", section 2 (Screen Layout).
 *
 * One screen shared by two teams (BR-PI-01): Purchase fills the header and the item
 * lines against an approved Purchase Order, Store records the physical receipt and
 * hands it to QC. Which half is editable is decided by the SERVER
 * (inward_api.get_form_context -> roles.get_section_access), never by this file — the
 * dimming here is only so each team can see whose turn it is.
 *
 * Design language matches the other alpinos entry pages (sales_order_entry): eso-card /
 * eso-card-title / eso-subtitle / eso-fld / alp-scroll / alp-actions, all defined in
 * public/css/alpinos_pages.css, which scopes on data-page-route.
 */

// A Datetime straight out of the database carries microseconds
// (2026-09-06 07:20:44.774097). frappe.datetime.validate parses strictly against
// YYYY-MM-DD HH:mm:ss, so the control rejects the value, raises a msgprint and
// blanks the field. Trim the fraction before any value reaches a control.
// var, not const: desk pages are re-evaluated on navigation.
var ALP_TRIM_MICROSECONDS = function (v) {
	if (typeof v !== 'string') return v;
	var m = v.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.\d+$/);
	return m ? m[1] : v;
};

/**
 * A Datetime typed as a date alone ("16-09-2026", then Tab) kept no time. Frappe's
 * frappe.datetime.user_to_str reads a time only when the text has a space in it, so the value
 * became a bare date -- midnight once stored -- while picking the same day from the calendar
 * keeps one. A date typed alone now takes the time already in the field or, when the field
 * had none, `default_time(user_time_format)`. get_value() parses through here too, so a save
 * made without leaving the field gets the time as well.
 */
var ALP_DATE_ONLY_KEEPS_TIME = function (control, default_time) {
	// The last date and time the field held, kept here rather than read off the control.
	// Selecting the text and deleting it to type a new date empties control.value first
	// (air-datepicker fires a change for the empty input). And when the screen resets a field
	// to empty, Frappe can judge the set unchanged and skip it: control.value and, for a
	// moment, the input box still hold the previous document's time, which refresh() parses
	// again. So this follows every set_value (loading or resetting the document), and after
	// one takes in parsed entries only once the user has been in the field.
	let last = null;
	let touched = false;
	if (control.$input) control.$input.on('focus keydown input', () => { touched = true; });
	const set_value = control.set_value.bind(control);
	control.set_value = function (value, ...rest) {
		last = value || null;
		touched = false;
		return set_value(value, ...rest);
	};
	const parse = control.parse.bind(control);
	control.parse = function (value) {
		const typed = typeof value === 'string' ? value.trim() : '';
		const from_input = touched && !!control.$input && value === control.$input.val();
		const date_fmt = frappe.datetime.get_user_date_fmt().toUpperCase();
		if (!typed || !moment(typed, [date_fmt, date_fmt.replace('YYYY', 'YY')], true).isValid()) {
			const parsed = parse(value);
			if (parsed && from_input) last = parsed;
			return parsed;
		}
		const time_fmt = frappe.datetime.get_user_time_fmt();
		const held = last ? frappe.datetime.convert_to_user_tz(last, false) : null;
		// Midnight is what a date-only entry used to leave behind, not a time anyone chose.
		const time =
			held && held.isValid() && held.format('HH:mm:ss') !== '00:00:00'
				? held.format(time_fmt)
				: default_time(time_fmt);
		const result = parse(`${typed} ${time}`);
		if (result && from_input) last = result;
		if (result && control.$input && (result === control.value || result === control.get_model_value())) {
			// Frappe takes a value equal to its model as nothing to do. Without a doc that model
			// falls back to the value from before the text was cleared, so retyping the same date
			// neither stored the value nor redrew its time. Do both here.
			setTimeout(() => control.set_input(result), 0);
		}
		return result;
	};
	return control;
};

frappe.pages['purchase_inward_entry'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase Inward Entry',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_inward_entry'));
	wrapper.piw_entry = new PurchaseInwardEntry(page);
};

// Fires on every visit; the route decides whether we open blank or load a document.
frappe.pages['purchase_inward_entry'].on_page_show = function (wrapper) {
	if (wrapper.piw_entry) wrapper.piw_entry.handle_route_entry();
};

var PIW_INWARD_TYPES = ['RM', 'PM', 'FG', 'MM'];

// The Store hand-over reads the stored receipt, so the page saves before running it.
var PIW_SAVE_FIRST_ACTIONS = ['submit_for_qc'];

// Performed on the QC screen (workflow.QC_SCREEN_ACTIONS); the inward offers Go to QC instead.
var PIW_QC_SCREEN_ACTIONS = ['start_qc', 'complete_qc'];

var PurchaseInwardEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.items = [];
		this.attachments = [];
		this.docname = null;
		this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
		this.setup();
	}

	setup() {
		this.make_header_fields();
		this.make_receiving_fields();
		this.make_totals();
		this.bind_events();
		this.apply_context();
		this.stamp_inward_datetime();
	}

	/**
	 * BRD 2.1.1: Inward Date & Time is auto-captured when the inward is created.
	 *
	 * The field is already handed now() when it is built and again in reset(), yet a new
	 * inward could still open with the box empty. A Frappe Datetime control writes its value
	 * asynchronously and interacts with its air-datepicker, whose clear()/selectDate()
	 * callbacks fire "change" events of their own, so the value can be lost in the timing
	 * between them. Rather than depend on that exact sequence, this runs once everything the
	 * page queued has settled and fills the box if it is still empty.
	 *
	 * Only on an unsaved inward, and only when empty: a loaded document keeps its stored time
	 * and a time the user typed is never replaced.
	 */
	stamp_inward_datetime() {
		setTimeout(() => {
			const c = this.fields.inward_datetime;
			if (!c || this.docname) return;
			if (!c.get_value()) c.set_value(frappe.datetime.now_datetime());
		}, 0);
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
		if (control.df.fieldtype === 'Datetime') {
			// A date typed without a time takes the current time, as a calendar pick does.
			ALP_DATE_ONLY_KEEPS_TIME(control, (fmt) => moment(frappe.datetime.now_time(), 'HH:mm:ss').format(fmt));
		}
		// refresh() BEFORE set_value(). set_value is asynchronous (frappe.run_serially) and
		// refresh is not, so refreshing afterwards redrew the still-empty field first. For a
		// Date / Datetime that calls datepicker.clear(); air-datepicker's clear() fires
		// onSelect, Frappe's onSelect triggers "change", and that change wrote '' AFTER the
		// value -- which is why Inward Date & Time came up blank although it was given
		// now(). set_input (controls/data.js) repaints the read-only display as well, so no
		// field needs the refresh to come last.
		control.refresh();
		control.set_value(value === undefined ? '' : ALP_TRIM_MICROSECONDS(value));
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
			// Refresh first, then set: the other order let a Date / Datetime clear itself after
			// the value landed (see _ctl).
			c.refresh();
			c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		}
	}

	_toast(message, indicator) {
		frappe.show_alert({ message: message, indicator: indicator || 'blue' }, 5);
	}

	// ------------------------------------------------------- BRD 2.1.1 header

	make_header_fields() {
		const me = this;

		this._ctl('.field-purchase-order', {
			fieldname: 'purchase_order',
			label: 'Purchase Order',
			fieldtype: 'Link',
			options: 'Purchase Order',
			reqd: 1,
			// VAL-PO-15 / VAL-PO-13: only an approved, non-direct-invoice PO can be inwarded.
			get_query: () => ({
				filters: {
					docstatus: 1,
					custom_direct_purchase_invoice: 0,
					status: ['not in', ['Closed', 'On Hold']],
				},
			}),
			change: () => me.on_purchase_order_change(),
		});

		this._ctl('.field-inward-type', {
			fieldname: 'inward_type',
			label: 'Inward Type',
			fieldtype: 'Select',
			options: [''].concat(PIW_INWARD_TYPES).join('\n'),
			// BRD 2.1.1 "Auto Fetch" — the server forces it to the PO's type anyway.
			read_only: 1,
		});
		this._ctl('.field-supplier', {
			fieldname: 'supplier',
			label: 'Vendor',
			fieldtype: 'Link',
			options: 'Supplier',
			read_only: 1,
		});
		this._ctl('.field-supplier-order-no', {
			fieldname: 'supplier_order_no',
			label: 'Supplier Order No.',
			fieldtype: 'Data',
			read_only: 1,
		});
		this._ctl('.field-invoice-number', {
			fieldname: 'invoice_number',
			label: 'Invoice Number',
			fieldtype: 'Data',
			reqd: 1,
			description: 'Unique per vendor (BR-PI-15).',
		});
		this._ctl('.field-invoice-date', {
			fieldname: 'invoice_date',
			label: 'Invoice Date',
			fieldtype: 'Date',
			// Greys out future days in the picker. A typed date bypasses the picker, so the
			// server refuses a future Invoice Date on save as well.
			max_date: frappe.datetime.str_to_obj(frappe.datetime.get_today()),
		});
		this._ctl('.field-challan-no', {
			fieldname: 'challan_no',
			label: 'Challan / DC No.',
			fieldtype: 'Data',
		});
		this._ctl('.field-gross-weight', {
			fieldname: 'gross_weight',
			label: 'Gross Weight',
			fieldtype: 'Float',
		});
		this._ctl('.field-inward-datetime', {
			fieldname: 'inward_datetime',
			label: 'Inward Date & Time',
			fieldtype: 'Datetime',
			// Without this the control appends the site time zone as a description, which
			// renders as a loose "Asia/Kolkata" under the field.
			hide_timezone: 1,
		}, frappe.datetime.now_datetime());
		this._ctl('.field-attachment', {
			fieldname: 'attachment',
			label: 'Attachment',
			fieldtype: 'Attach',
		});
		this._ctl('.field-remarks', {
			fieldname: 'remarks',
			label: 'Remarks',
			fieldtype: 'Small Text',
		});
	}

	on_purchase_order_change() {
		const po = this._val('purchase_order');
		if (!po) return;
		// load() fills this field from the saved document, and a Frappe control fires its
		// `change` for a programmatic set_value too -- a moment AFTER load() has drawn the
		// saved rows. Rebuilding then replaced every saved line with a blank one straight
		// from the Purchase Order: Received 0, no batch, no manufacturing date. The pending
		// figures looked wrong as well, because this inward's own receipt was being counted
		// as "previously received". A save from that screen would have written the zeros
		// back. Only a Purchase Order the user actually changed to may rebuild the grid.
		if (po === this.loaded_po) return;
		this.loaded_po = po;
		// A different order starts from its own type's lines again.
		this._set_include_other(false);
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_purchase_order_items',
			// Exclude this inward from "previously received", so a saved document is never
			// measured against its own quantities.
			args: { purchase_order: po, purchase_inward: me.docname || null, include_unmatched: 0 },
			callback(r) {
				if (!r.message) return;
				const d = r.message;
				me._set('inward_type', d.inward_type);
				me._set('supplier', d.supplier);
				me.company = d.company;
				frappe.db.get_value('Purchase Order', po, [
					'custom_supplier_order_no',
					'custom_vehicle_no',
					'custom_driver_contact_no',
					'set_warehouse',
				]).then((res) => {
					const v = (res && res.message) || {};
					me._set('supplier_order_no', v.custom_supplier_order_no);
					me._set('po_vehicle_no', v.custom_vehicle_no);
					me._set('po_driver_contact_no', v.custom_driver_contact_no);
					// Section 2: Default Target Location as per the selected PO -- its own, or
					// its lines' warehouse when the header has none.
					const line = (d.items || []).find((row) => row.target_warehouse);
					const wh = v.set_warehouse || (line && line.target_warehouse);
					if (wh) me._set('target_warehouse', wh);
				});
				// Always reload against the PO that is now selected. This used to be guarded by
				// `if (!me.items.length)`, which meant that once any row was on screen, picking a
				// different Purchase Order left the previous order's lines in the grid.
				me.load_items(d.items || [], d.skipped || {}, d.unmatched_available || 0);
			},
		});
	}

	load_items(rows, skipped, unmatched_available) {
		this.items = [];
		this.wrapper.find('.items-table tbody').empty();
		(rows || []).forEach((row) => this.add_item_row(row));
		this.render_receiving_rows();
		this.load_item_info();
		this.recalc_totals();
		this.explain_skipped(rows, skipped, unmatched_available);
	}

	/**
	 * get_purchase_order_items reports WHY it dropped a line, as a dict keyed by reason:
	 * {fully_received: n, type_mismatch: n}. This read it as an array and tested
	 * `skipped.length`, which is undefined on an object -- so the message never appeared
	 * and a Purchase Order whose every line was dropped drew an empty grid with no
	 * explanation, which is indistinguishable from the fetch being broken.
	 *
	 * Reported in the grid itself, never through frappe.msgprint. `frappe.msg_dialog` is a
	 * SINGLETON: when a message is already open, msgprint appends to it behind whatever
	 * title got set last. Frappe uses it for its own "Version Updated" notice, so this
	 * explanation appeared glued under that title with a Refresh button attached to it.
	 * The empty-state text is painted from data-empty on the scroll wrapper, which is
	 * where the user is already looking, needs no dismissing, and cannot collide.
	 */
	explain_skipped(rows, skipped, unmatched_available) {
		skipped = skipped || {};
		const fully = cint(skipped.fully_received);
		const mismatch = cint(skipped.type_mismatch);
		const dropped = fully + mismatch;
		const $scroll = this.wrapper.find('.items-table').closest('.alp-scroll');

		if (this._items_empty_default === undefined) {
			this._items_empty_default = $scroll.attr('data-empty') || '';
		}
		$scroll.attr('data-empty', this._items_empty_default);

		// The tick the hint below refers to: offered whenever the order has lines of another
		// type, and kept while ticked so it can be unticked again.
		this._set_include_other(this.include_other, cint(unmatched_available) > 0);
		const other = (rows || []).filter((r) => r.matches_inward_type === false).length;
		if (other) {
			this._toast(
				__('{0} line(s) of another inward type included. They are received as {1}.', [
					other,
					this._val('inward_type') || __('this inward'),
				]),
				'orange'
			);
		}

		if (!dropped) return;

		const parts = [];
		if (fully) parts.push(__('{0} fully received', [fully]));
		if (mismatch) {
			parts.push(
				__('{0} of a different inward type than {1}', [
					mismatch,
					this._val('inward_type') || __('this inward'),
				])
			);
		}
		const detail = __('{0} Purchase Order line(s) were not offered: {1}.', [
			dropped,
			parts.join(__(' and ')),
		]);

		if ((rows || []).length) {
			this._toast(detail, 'orange');
			return;
		}
		// Nothing at all came back, so the grid is the right place to say why: it stays on
		// screen for as long as the grid is empty.
		const hint = cint(unmatched_available)
			// The inward's type is copied from the order, so "raise it under the matching type"
			// means correcting the order's PO Type.
			? __('Tick Include Other Inward Types below to receive them on this inward, or correct the PO Type on the Purchase Order.')
			: __('Every line on this Purchase Order has already been received in full.');
		$scroll.attr('data-empty', `${detail} ${hint}`);
		this._toast(detail, 'orange');
	}

	// -------------------------------------------------------- BRD 2.2.2 grid

	add_item_row(data) {
		data = data || {};
		const idx = this.items.length;
		const row = Object.assign(
			{
				item_code: '',
				item_name: '',
				stock_uom: '',
				order_qty: 0,
				previously_received_qty: 0,
				pending_qty: 0,
				received_qty: 0,
				excess_qty: 0,
				po_detail: '',
				target_warehouse: '',
				batch_no: '',
				manufacturing_date: '',
				expiry_date: '',
				mrp: 0,
				usp: '',
				item_remarks: '',
			},
			data
		);
		this.items.push(row);

		const $tr = $(`
			<tr data-idx="${idx}">
				<td class="text-muted">${idx + 1}</td>
				<td class="cell-item-code"></td>
				<td class="cell-item-name"></td>
				<td class="cell-uom"></td>
				<td class="piw-num cell-order-qty"></td>
				<td class="piw-num cell-prev-qty"></td>
				<td class="piw-num cell-pending-qty"></td>
				<td class="cell-remarks"></td>
				<td class="text-center">
					<button class="btn btn-xs btn-link btn-remove-row" title="Remove">
						<i class="fa fa-trash text-danger"></i>
					</button>
				</td>
			</tr>
		`);
		this.wrapper.find('.items-table tbody').append($tr);

		$tr.find('.cell-item-code').text(row.item_code || '');
		$tr.find('.cell-item-name').text(row.item_name || '');
		$tr.find('.cell-uom').text(row.stock_uom || '');
		$tr.find('.cell-order-qty').text(format_number(row.order_qty, null, 2));
		$tr.find('.cell-prev-qty').text(format_number(row.previously_received_qty, null, 2));
		$tr.find('.cell-pending-qty').text(format_number(row.pending_qty, null, 2));

		const me = this;
		const remarks = frappe.ui.form.make_control({
			df: { fieldname: `item_remarks_${idx}`, fieldtype: 'Data', placeholder: 'Remarks' },
			parent: $tr.find('.cell-remarks'),
			render_input: true,
		});
		remarks.set_value(ALP_TRIM_MICROSECONDS(row.item_remarks || ''));
		// Same rule as the grid cells below: the handler is handed the control's parsed
		// value, never the raw input text.
		remarks.$input && remarks.$input.on('change', () => {
			me.items[idx].item_remarks = remarks.get_value();
		});
	}

	// ------------------------------------------------- BRD 2.2.1 store fields

	make_receiving_fields() {
		const me = this;
		this._ctl('.field-po-vehicle-no', {
			fieldname: 'po_vehicle_no', label: 'Planned Vehicle (PO)',
			fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-po-driver-contact', {
			fieldname: 'po_driver_contact_no', label: 'Planned Driver (PO)',
			fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-actual-vehicle-no', {
			fieldname: 'actual_vehicle_no', label: 'Actual Vehicle No.', fieldtype: 'Data',
		});
		this._ctl('.field-actual-driver-contact', {
			fieldname: 'actual_driver_contact_no', label: 'Actual Driver Contact',
			fieldtype: 'Data',
		});
		this._ctl('.field-actual-arrival', {
			fieldname: 'actual_arrival_datetime', label: 'Actual Arrival Date & Time',
			fieldtype: 'Datetime',
			hide_timezone: 1,
		});
		this._ctl('.field-vehicle-verified', {
			fieldname: 'vehicle_details_verified', label: 'Vehicle Details Verified',
			fieldtype: 'Check',
			// VAL-PI-05: ticking it means the fetched details were WRONG, so the corrected
			// ones become mandatory. Left unticked, the PO's details are accepted as-is.
			description: 'Tick only if the actual vehicle/driver differ from the PO.',
		});
		this._ctl('.field-allow-excess', {
			fieldname: 'allow_excess_qty', label: 'Allow Excess Quantity',
			fieldtype: 'Check',
			description: 'BR-PI-14 — receive more than the pending quantity.',
			change: () => me.recalc_totals(),
		});
		this._ctl('.field-target-warehouse', {
			fieldname: 'target_warehouse', label: 'Default Target Location',
			fieldtype: 'Link', options: 'Warehouse',
			change: () => me.apply_default_warehouse(),
		});
		this._ctl('.field-receiving-remarks', {
			fieldname: 'receiving_remarks', label: 'Receiving Remarks', fieldtype: 'Small Text',
		});

		// dispute evidence (task 301)
		this._ctl('.field-dispute-file', {
			fieldname: 'dispute_file', label: 'File', fieldtype: 'Attach',
		});
		this._ctl('.field-dispute-kind', {
			fieldname: 'dispute_kind', label: 'Kind', fieldtype: 'Select',
			options: ['Photo', 'Video', 'Document'].join('\n'),
		}, 'Photo');
		this._ctl('.field-dispute-description', {
			fieldname: 'dispute_description', label: 'Description', fieldtype: 'Data',
		});
	}

	apply_default_warehouse() {
		const wh = this._val('target_warehouse');
		if (!wh) return;
		this.items.forEach((row, idx) => {
			if (!row.target_warehouse) {
				row.target_warehouse = wh;
				const c = this.fields[`target_warehouse_${idx}`];
				if (c) c.set_value(ALP_TRIM_MICROSECONDS(wh));
			}
		});
	}

	render_receiving_rows() {
		const me = this;
		const $body = this.wrapper.find('.receiving-table tbody').empty();

		this.items.forEach((row, idx) => {
			const $tr = $(`
				<tr data-idx="${idx}">
					<td class="text-muted">${idx + 1}</td>
					<td>${frappe.utils.escape_html(row.item_code || '')}<br>
						<span class="text-muted" style="font-size:11px;">
							${frappe.utils.escape_html(row.item_name || '')}</span></td>
					<td class="piw-num cell-pending">${format_number(row.pending_qty, null, 2)}</td>
					<td class="cell-received"></td>
					<td class="piw-num cell-excess">0</td>
					<td class="cell-warehouse"></td>
					<td class="cell-batch"></td>
					<td class="cell-mfg"></td>
					<td class="cell-expiry"></td>
					<td class="cell-mrp"></td>
					<td class="cell-usp"></td>
				</tr>
			`);
			$body.append($tr);

			const mk = (sel, df, value, onchange) => {
				// Same rule as purchase_qc_entry._mk_cell: run the handler from Frappe's own
				// df.change, which fires for a Link pick. The input's native 'change' event
				// this used to listen for does not, so a Target Location chosen from the
				// dropdown was never written to the row. `ready` skips the change Frappe
				// fires for the programmatic set_value that draws the saved value.
				let ready = false;
				const c = frappe.ui.form.make_control({
					df: Object.assign({ fieldname: `${df.fieldname}_${idx}` }, df, {
						change: () => {
							if (!ready || !onchange) return;
							// the PARSED value -- for a Date control the raw input text is the
							// user format (dd-mm-yyyy), an invalid DATE (MariaDB 1292)
							onchange.call(c.$input ? c.$input.get(0) : null, c.get_value());
						},
					}),
					parent: $tr.find(sel),
					render_input: true,
				});
				Promise.resolve(
					c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value))
				).then(() => {
					ready = true;
				});
				me.fields[`${df.fieldname}_${idx}`] = c;
				return c;
			};

			mk('.cell-received', { fieldtype: 'Float', fieldname: 'received_qty' },
				row.received_qty, function (val) {
					me.items[idx].received_qty = flt(val);
					me.recalc_row(idx);
					me.recalc_totals();
				});
			mk('.cell-warehouse', { fieldtype: 'Link', fieldname: 'target_warehouse', options: 'Warehouse' },
				row.target_warehouse, function (val) {
					me.items[idx].target_warehouse = val;
				});
			mk('.cell-batch', { fieldtype: 'Data', fieldname: 'batch_no' },
				row.batch_no, function (val) { me.items[idx].batch_no = val; });
			mk('.cell-mfg', { fieldtype: 'Date', fieldname: 'manufacturing_date' },
				row.manufacturing_date, function (val) {
					me.items[idx].manufacturing_date = val;
					me.update_expiry(idx);
				});
			// Expiry = Manufacturing Date + the Item's shelf life. Shown as soon as the date is
			// picked (update_expiry); the server derives the same on save.
			mk('.cell-expiry', { fieldtype: 'Date', fieldname: 'expiry_date', read_only: 1 },
				row.expiry_date);
			mk('.cell-mrp', { fieldtype: 'Currency', fieldname: 'mrp' },
				row.mrp, function (val) {
					me.items[idx].mrp = flt(val);
					me.update_usp(idx);
				});
			mk('.cell-usp', { fieldtype: 'Data', fieldname: 'usp' },
				row.usp, function (val) { me.items[idx].usp = val; });
		});
	}

	/**
	 * Section 2 values the grid can show before saving: Expiry from the Item's shelf life, MRP
	 * from the PO line's Rate and USP = MRP ÷ product weight. Fetched once per set of rows;
	 * the server computes the same on save (inward_api.receiving_item_info / format_usp /
	 * po_line_mrp).
	 */
	load_item_info() {
		const me = this;
		const codes = Array.from(new Set(this.items.map((r) => r.item_code).filter(Boolean)));
		if (!codes.length) return;
		const token = (this._info_token = (this._info_token || 0) + 1);
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_item_receiving_info',
			args: {
				item_codes: codes,
				company: me.company || null,
				po_details: me.items.map((r) => r.po_detail).filter(Boolean),
			},
			callback(r) {
				if (token !== me._info_token || !r.message) return;
				me.item_info = r.message.items || {};
				me.currency_symbol = r.message.currency_symbol || '';
				const po_mrp = r.message.po_mrp || {};
				me.items.forEach((row, idx) => {
					// A line saved without an MRP shows its PO line's Rate.
					if (!flt(row.mrp) && flt(po_mrp[row.po_detail])) {
						row.mrp = flt(po_mrp[row.po_detail]);
						const c = me.fields[`mrp_${idx}`];
						if (c) c.set_value(row.mrp);
					}
					me.update_expiry(idx);
					me.update_usp(idx);
				});
			},
		});
	}

	update_expiry(idx) {
		const row = this.items[idx];
		const info = (this.item_info || {})[row && row.item_code];
		if (!row || !info) return;
		const shelf = cint(info.shelf_life_in_days);
		const expiry = row.manufacturing_date && shelf ? frappe.datetime.add_days(row.manufacturing_date, shelf) : '';
		if ((row.expiry_date || '') === expiry) return;
		row.expiry_date = expiry;
		const c = this.fields[`expiry_date_${idx}`];
		if (c) c.set_value(expiry);
	}

	update_usp(idx) {
		const row = this.items[idx];
		const info = (this.item_info || {})[row && row.item_code];
		if (!row || !info || !flt(info.usp_weight)) return;
		const c = this.fields[`usp_${idx}`];
		if (c && !cint(c.df.read_only)) {
			// Worked out from MRP and weight, so it is not typed.
			c.df.read_only = 1;
			c.refresh();
		}
		const usp = flt(row.mrp) > 0
			? `${this.currency_symbol || ''}${(flt(row.mrp) / flt(info.usp_weight)).toFixed(3)}/${info.usp_unit}`
			: '';
		if ((row.usp || '') === usp) return;
		row.usp = usp;
		if (c) c.set_value(usp);
	}

	recalc_row(idx) {
		const row = this.items[idx];
		const over = flt(row.received_qty) - flt(row.pending_qty);
		row.excess_qty = over > 0 ? over : 0;
		const $tr = this.wrapper.find(`.receiving-table tbody tr[data-idx="${idx}"]`);
		$tr.find('.cell-excess').text(format_number(row.excess_qty, null, 2));
		$tr.toggleClass('text-danger', row.excess_qty > 0 && !cint(this._val('allow_excess_qty')));
	}

	// ------------------------------------------------------------- totals

	make_totals() {
		[
			['total-order-qty', 'total_order_qty', 'Total Order Qty'],
			['total-received-qty', 'total_received_qty', 'Total Received Qty'],
			['total-pending-qty', 'total_pending_qty', 'Total Pending Qty'],
			['total-excess-qty', 'total_excess_qty', 'Total Excess Qty'],
			// Not a stored field. BRD 2.2.1 fixes Pending Quantity as the balance BEFORE
			// this receipt, because Excess = Received - Pending depends on it, so it
			// cannot also drop as the Store types. Nothing then showed what was left
			// after the receipt being entered, which read as "pending is not updating".
			['total-balance-qty', 'total_balance_qty', 'Balance After This Receipt'],
		].forEach(([sel, fieldname, label]) => {
			this._ctl(`.field-${sel}`, {
				fieldname: fieldname, label: label, fieldtype: 'Float', read_only: 1,
			}, 0);
		});
	}

	recalc_totals() {
		let order = 0, received = 0, pending = 0, excess = 0, balance = 0;
		this.items.forEach((row, idx) => {
			this.recalc_row(idx);
			order += flt(row.order_qty);
			received += flt(row.received_qty);
			pending += flt(row.pending_qty);
			excess += flt(row.excess_qty);
			// Ordered less everything received against the line, this inward included.
			// Floored at zero: an excess receipt leaves nothing pending, it does not owe
			// the supplier quantity back.
			const left = flt(row.order_qty) - flt(row.previously_received_qty) - flt(row.received_qty);
			balance += left > 0 ? left : 0;
		});
		this._set('total_order_qty', order);
		this._set('total_received_qty', received);
		this._set('total_pending_qty', pending);
		this._set('total_excess_qty', excess);
		this._set('total_balance_qty', balance);
	}

	// ----------------------------------------------------------- attachments

	add_attachment_row(data) {
		const idx = this.attachments.length;
		this.attachments.push(data);
		const $tr = $(`
			<tr data-idx="${idx}">
				<td class="text-muted">${idx + 1}</td>
				<td><a href="${frappe.utils.escape_html(data.file)}" target="_blank">
					${frappe.utils.escape_html(data.file)}</a></td>
				<td>${frappe.utils.escape_html(data.kind || '')}</td>
				<td>${frappe.utils.escape_html(data.description || '')}</td>
				<td class="text-muted">${frappe.utils.escape_html(data.uploaded_by || frappe.session.user)}</td>
				<td class="text-center">
					<button class="btn btn-xs btn-link btn-remove-attachment" title="Remove">
						<i class="fa fa-trash text-danger"></i>
					</button>
				</td>
			</tr>
		`);
		this.wrapper.find('.attachments-table tbody').append($tr);
	}

	// --------------------------------------------------------------- events

	bind_events() {
		const me = this;

		this.wrapper.on('click', '.btn-get-items', () => {
			const po = me._val('purchase_order');
			if (!po) {
				frappe.msgprint(__('Please select a Purchase Order first.'));
				return;
			}
			frappe.call({
				method: 'alpinos.purchase.inward_api.get_purchase_order_items',
				args: {
					purchase_order: po,
					purchase_inward: me.docname || undefined,
					include_unmatched: me.include_other ? 1 : 0,
				},
				freeze: true,
				freeze_message: __('Fetching Purchase Order lines...'),
				callback(r) {
					if (r.exc || !r.message) return;
					me.load_items(
						r.message.items || [],
						r.message.skipped || {},
						r.message.unmatched_available || 0
					);
				},
			});
		});

		// Lines of another inward type are held back unless asked for; ticking refetches the
		// order with them, unticking without them.
		this.wrapper.on('change', '.piw-include-other-check', function () {
			me.include_other = $(this).prop('checked');
			me.wrapper.find('.btn-get-items').trigger('click');
		});

		this.wrapper.on('click', '.btn-add-row', () => {
			me.add_item_row({});
			me.render_receiving_rows();
		});

		this.wrapper.on('click', '.btn-remove-row', function () {
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.items.splice(idx, 1);
			me.redraw_items();
		});

		this.wrapper.on('click', '.btn-add-attachment', () => {
			const file = me._val('dispute_file');
			if (!file) {
				frappe.msgprint(__('Please attach a file first.'));
				return;
			}
			me.add_attachment_row({
				file: file,
				kind: me._val('dispute_kind'),
				description: me._val('dispute_description'),
			});
			me._set('dispute_file', '');
			me._set('dispute_description', '');
		});

		this.wrapper.on('click', '.btn-remove-attachment', function () {
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.attachments.splice(idx, 1);
			me.redraw_attachments();
		});
	}

	redraw_items() {
		const rows = this.items.slice();
		this.items = [];
		this.wrapper.find('.items-table tbody').empty();
		rows.forEach((r) => this.add_item_row(r));
		this.render_receiving_rows();
		this.load_item_info();
		this.recalc_totals();
	}

	redraw_attachments() {
		const rows = this.attachments.slice();
		this.attachments = [];
		this.wrapper.find('.attachments-table tbody').empty();
		rows.forEach((r) => this.add_attachment_row(r));
	}

	// ----------------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const opts = frappe.route_options || {};
		const name = route[1] || opts.purchase_inward;
		// BRD 1.3 "Create Purchase Inward" arrives here from the Purchase Order form with
		// the order already decided, rather than making the user retype it.
		const po = opts.purchase_order;
		if (frappe.route_options) {
			delete frappe.route_options.purchase_inward;
			delete frappe.route_options.purchase_order;
		}
		if (name && name !== this.docname) {
			this.load(name);
			return;
		}
		if (po) {
			this.reset();
			this._set('purchase_order', po);
			// The normal change handler is what stamps supplier / inward type and pulls
			// the pending lines, so the two entry points cannot drift apart.
			this.on_purchase_order_change();
			return;
		}
		if (!name && this.docname) this.reset();
	}

	//: Header + receiving controls that live in the template and are never destroyed.
	//  Per-ROW controls are keyed "<field>_<idx>" and their DOM is emptied when the grids
	//  are cleared, so calling set_value on them afterwards operates on detached inputs.
	//  reset() therefore clears the standing fields only and drops the row controls.
	static get STANDING_FIELDS() {
		return [
			'purchase_order', 'inward_type', 'supplier', 'supplier_order_no',
			'invoice_number', 'invoice_date', 'challan_no', 'gross_weight',
			'inward_datetime', 'attachment', 'remarks',
			'po_vehicle_no', 'po_driver_contact_no', 'actual_vehicle_no',
			'actual_driver_contact_no', 'actual_arrival_datetime',
			'vehicle_details_verified', 'allow_excess_qty', 'target_warehouse',
			'receiving_remarks', 'dispute_file', 'dispute_kind', 'dispute_description',
			'total_order_qty', 'total_received_qty', 'total_pending_qty', 'total_excess_qty',
			'total_balance_qty',
		];
	}

	/** The Include Other Inward Types tick: `show` keeps it on screen, else only while ticked. */
	_set_include_other(checked, show) {
		this.include_other = !!checked;
		this.wrapper.find('.piw-include-other-check').prop('checked', this.include_other);
		this.wrapper.find('.piw-include-other').toggle(!!show || this.include_other);
	}

	reset() {
		this._set_include_other(false);
		this.docname = null;
		this.company = null;
		this.quarantine_doc = null;
		this.purchase_qc = null;
		this.items = [];
		this.attachments = [];
		this.wrapper.find('.items-table tbody, .receiving-table tbody, .attachments-table tbody').empty();

		const standing = PurchaseInwardEntry.STANDING_FIELDS;
		Object.keys(this.fields).forEach((k) => {
			if (standing.indexOf(k) === -1) delete this.fields[k];
		});
		standing.forEach((k) => this._set(k, ''));

		this._set('inward_datetime', frappe.datetime.now_datetime());
		this._set('dispute_kind', 'Photo');
		this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
		// A fresh inward has no PO yet, so picking the same PO the previous document used
		// must still load its lines.
		this.loaded_po = null;
		this.page.set_title(__('Purchase Inward Entry'));
		this.apply_context();
		this.stamp_inward_datetime();
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Inward', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				me.docname = doc.name;
				me.company = doc.company;
				// A stored inward shows its saved lines; the tick only matters for a fetch.
				me._set_include_other(false);
				// Before the fields are filled: the purchase_order change that filling it
				// fires must see this as the document's own PO and leave the rows alone.
				me.loaded_po = doc.purchase_order;

				[
					'purchase_order', 'inward_type', 'supplier', 'supplier_order_no',
					'invoice_number', 'invoice_date', 'challan_no', 'gross_weight',
					'inward_datetime', 'attachment', 'remarks', 'po_vehicle_no',
					'po_driver_contact_no', 'actual_vehicle_no', 'actual_driver_contact_no',
					'actual_arrival_datetime', 'vehicle_details_verified', 'allow_excess_qty',
					'target_warehouse', 'receiving_remarks',
				].forEach((f) => me._set(f, doc[f]));
				me.quarantine_doc = doc.purchase_quarantine || null;
				me.purchase_qc = doc.purchase_qc || null;

				me.items = [];
				me.wrapper.find('.items-table tbody').empty();
				(doc.items || []).forEach((row) => me.add_item_row(row));
				me.render_receiving_rows();
				me.load_item_info();

				me.attachments = [];
				me.wrapper.find('.attachments-table tbody').empty();
				(doc.dispute_attachments || []).forEach((row) => me.add_attachment_row(row));

				me.recalc_totals();
				me.refresh_context();
				me.page.set_title(`${doc.name} — Purchase Inward`);
			},
		});
	}

	refresh_context() {
		if (!this.docname) {
			this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
			this.apply_context();
			return;
		}
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_form_context',
			args: { purchase_inward: this.docname },
			callback(r) {
				if (r.message) me.ctx = r.message;
				me.apply_context();
			},
		});
	}

	// ------------------------------------------------- server-driven gating

	apply_context() {
		const ctx = this.ctx || {};
		const status = ctx.status || 'Draft';

		this.wrapper.find('.field-stage-badge').text(status);
		this.wrapper.find('.field-receiving-badge').text(
			ctx.docstatus === 1 ? 'Store' : 'awaiting submit'
		);

		// The server owns the decision; this only reflects it.
		const header_open = ctx.header_editable !== false && cint(ctx.docstatus) === 0;
		this._lock_section(this.wrapper.find('.piw-header'), !header_open);
		this._lock_section(this.wrapper.find('.items-table').closest('.eso-card'), !header_open);

		const receiving = (ctx.sections || {}).receiving;
		// roles.get_section_access returns `edit`, not `editable`. Reading the wrong key
		// gave undefined, and `undefined !== false` is true, so the Store Receiving grid
		// stayed editable in EVERY status -- including after the handover to QC, where the
		// server reports edit=false with "closed while the document is QC In Progress".
		const receiving_open = receiving ? receiving.edit !== false : cint(ctx.docstatus) === 1;
		this._lock_section(this.wrapper.find('.piw-receiving'), !receiving_open);
		// make_actions reads this, so the Save Receipt button and the lock share one decision.
		this.receiving_open = receiving_open;

		this.make_actions();
	}

	/**
	 * Close a card for editing, for real.
	 *
	 * This used to only add .piw-locked. The page's own <style> gives that class
	 * `opacity:.55; pointer-events:none`, which stops the mouse but not the keyboard: Tab
	 * still reached every input in a closed section and typing still changed it, and the
	 * save was then refused by assert_can_edit_section with a permission error, which reads
	 * as a bug rather than as a closed section. So the controls are disabled as well.
	 *
	 * The disabled state of each control is remembered before locking, so unlocking can
	 * never enable a field that was already read-only for another reason (an Expiry cell
	 * derived server-side, say). The page's action bar sits outside these cards, so the
	 * workflow buttons are unaffected.
	 */
	_lock_section($card, locked) {
		if (!$card || !$card.length) return;
		$card.toggleClass('piw-locked', !!locked);
		$card.find('input, select, textarea, button').each(function () {
			const $i = $(this);
			if (locked) {
				if ($i.attr('data-piw-prev') === undefined) {
					$i.attr('data-piw-prev', $i.prop('disabled') ? '1' : '0');
				}
				$i.prop('disabled', true);
			} else if ($i.attr('data-piw-prev') !== undefined) {
				$i.prop('disabled', $i.attr('data-piw-prev') === '1');
				$i.removeAttr('data-piw-prev');
			}
		});
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.piw-actionbar').empty();
		const btn = (label, cls, handler, blocked, reason) => {
			const $b = $(
				`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`
			);
			if (blocked) {
				// Greyed out with the reason in a title attribute only, this looked like a
				// button that did nothing: the workflow guard for Submit for QC is
				// "Please enter the Actual Arrival Date & Time...", and a Store user who
				// had not recorded the arrival yet clicked it and got silence. The button
				// stays clickable and says why, which is the rule the rest of the module
				// already follows -- refuse by name rather than hide.
				$b.addClass('btn-default').css('opacity', 0.65).attr('title', reason || '');
				$b.on('click', () => {
					frappe.msgprint({
						title: __('{0} Is Not Available Yet', [label]),
						indicator: 'orange',
						message: reason || __('This action is not available on this Purchase Inward yet.'),
					});
				});
			} else {
				$b.on('click', handler);
			}
			$bar.append($b);
			return $b;
		};

		if (cint(this.ctx.docstatus) === 0) {
			btn(__('Save'), 'btn-primary', () => me.save(false));
			if (this.docname) btn(__('Submit'), 'btn-primary', () => me.save(true));
			if (this.docname) {
				btn(__('Cancel'), 'btn-default', () => {
					frappe.confirm(__('Discard this draft Purchase Inward?'), () => {
						frappe.call({
							method: 'alpinos.purchase.inward_api.cancel_draft',
							args: { purchase_inward: me.docname },
							callback(r) {
								// A refused cancel must not claim the draft is gone and
								// then navigate away from it.
								if (r.exc) return;
								me._toast(__('Draft discarded'), 'orange');
								frappe.set_route('purchase_inward_list');
							},
						});
					});
				});
			}
		} else if (this.receiving_open) {
			// Only while the server keeps Store Receiving open. This used to show on every
			// submitted inward, so after the handover to QC a locked form still offered a
			// Save Receipt that could only be refused; BRD 1.4 gives Pending QC and QC In
			// Progress just View / View QC.
			btn(__('Save Receipt'), 'btn-primary', () => me.save(false));
		}

		// Workflow transitions, exactly as the engine reports them (task 295 / BRD 1.4).
		(this.ctx.actions || []).forEach((action) => {
			if (action.kind !== 'transition' || action.action === 'submit') return;
			if (PIW_QC_SCREEN_ACTIONS.includes(action.action)) return;
			btn(
				action.label,
				'btn-default',
				() => me.run_action(action.action, action.label),
				!action.enabled,
				action.reason
			);
		});

		// The inspection itself is done on the QC screen, from Start QC to Complete QC.
		if (this.purchase_qc && cint(this.ctx.docstatus) === 1) {
			btn(__('Go to QC'), 'btn-primary', () => {
				frappe.set_route('purchase_qc_entry', me.purchase_qc);
			});
		}
		if (this.quarantine_doc) {
			btn(__('Open Quarantine'), 'btn-default', () => {
				frappe.set_route('purchase_quarantine_view', me.quarantine_doc);
			});
		}
		if (this.docname) {
			btn(__('Print'), 'btn-default', () => {
				frappe.set_route('print', 'Purchase Inward', me.docname);
			});
		}
	}

	run_action(action, label) {
		const me = this;
		frappe.confirm(__('Run "{0}" on {1}?', [label, this.docname]), () => {
			// The hand-over reads the STORED inward, so what is still only on screen -- the
			// reminder days, the quarantine picks, a received quantity -- was never seen: the
			// Store user had to click Save Receipt first. Save it, then hand over.
			if (me.receiving_open && PIW_SAVE_FIRST_ACTIONS.includes(action)) {
				me.save(false, () => me._run_after_save(action));
			} else {
				me._call_action(action, label);
			}
		});
	}

	/**
	 * After the save, run the hand-over the server now offers. Saving can change which one
	 * that is: ticking Quarantine Entire Inward turns Submit for QC into Create Quarantine
	 * (workflow hides the other), and back.
	 */
	_run_after_save(action) {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_form_context',
			args: { purchase_inward: me.docname },
			callback(r) {
				if (r.exc || !r.message) return;
				const offered = (r.message.actions || []).filter(
					(a) => a.kind === 'transition' && PIW_SAVE_FIRST_ACTIONS.includes(a.action)
				);
				const pick = offered.find((a) => a.action === action) || offered[0];
				if (!pick || !pick.enabled) {
					me.load(me.docname);
					frappe.msgprint({
						title: __('Saved, Not Handed Over'),
						indicator: 'orange',
						message: (pick && pick.reason) || __('The receipt was saved, but it cannot be handed over yet.'),
					});
					return;
				}
				me._call_action(pick.action, pick.label);
			},
		});
	}

	_call_action(action, label) {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.run_action',
			args: { purchase_inward: me.docname, action: action },
			freeze: true,
			freeze_message: __('Working...'),
			callback(r) {
				// A guard the workflow refused -- quarantine still open, arrival not
				// recorded -- comes back through this same callback.
				if (r.exc) {
					// the save before a hand-over did land, so show what is now stored
					me.load(me.docname);
					return;
				}
				me._toast(__('{0} done', [label]), 'green');
				// The new invoice is where the Purchase Team works next (BRD 6.2.1).
				if (action === 'create_purchase_invoice' && r.message && r.message.purchase_invoice) {
					frappe.set_route('purchase_invoice_entry', r.message.purchase_invoice);
					return;
				}
				me.load(me.docname);
				if (r.message && r.message.inward_status) {
					me.ctx.status = r.message.inward_status;
				}
			},
		});
	}

	// ----------------------------------------------------------------- save

	collect_doc() {
		// Store Receiving belongs to the Store team and opens only once Purchase has
		// submitted the inward (BRD 2.2.1 / 2.3), so a DRAFT never sends those fields. The
		// page used to send its pre-filled values with every draft save -- the PO's vehicle
		// and driver, each line's target location, zero quantities -- and the section guard
		// counts that as editing Store Receiving. It refused the save for the Purchase team,
		// and it is why the section could not be closed on a draft without also refusing
		// the admin's. What a draft already stores is kept by the save path's row merge.
		const receiving = cint((this.ctx || {}).docstatus) === 1;
		const doc = {
			doctype: 'Purchase Inward',
			purchase_order: this._val('purchase_order'),
			invoice_number: this._val('invoice_number'),
			invoice_date: this._val('invoice_date'),
			challan_no: this._val('challan_no'),
			gross_weight: flt(this._val('gross_weight')),
			inward_datetime: this._val('inward_datetime'),
			attachment: this._val('attachment'),
			remarks: this._val('remarks'),
			...(receiving ? {
				actual_vehicle_no: this._val('actual_vehicle_no'),
				actual_driver_contact_no: this._val('actual_driver_contact_no'),
				actual_arrival_datetime: this._val('actual_arrival_datetime'),
				vehicle_details_verified: cint(this._val('vehicle_details_verified')),
				allow_excess_qty: cint(this._val('allow_excess_qty')),
				target_warehouse: this._val('target_warehouse'),
				receiving_remarks: this._val('receiving_remarks'),
			} : {}),
			items: this.items.map((row) => ({
				// The row's OWN name, whenever it already has one.
				//
				// save() does Object.assign({}, server_doc, collect_doc()), and that is a
				// SHALLOW merge: this `items` array replaces the server's wholesale. A child
				// row arriving without a name is a NEW row to Frappe, so every save deleted
				// all the rows and re-inserted them under fresh hashes. Purchase Inward Item
				// autonames by hash, and two things store those hashes -- Purchase Receipt
				// Item.custom_purchase_inward_item, which is a LINK, and the row map Purchase
				// QC builds against the inward. One save orphaned both, which surfaced as
				// "Purchase Inward Item <hash> not found" and as a line vanishing from the
				// receipt it had been mapped into.
				...(row.name ? { name: row.name } : {}),
				item_code: row.item_code,
				po_detail: row.po_detail,
				item_remarks: row.item_remarks,
				...(receiving ? {
					received_qty: flt(row.received_qty),
					target_warehouse: row.target_warehouse,
					batch_no: row.batch_no,
					manufacturing_date: row.manufacturing_date || null,
					mrp: flt(row.mrp),
					usp: row.usp,
				} : {}),
			})),
			...(receiving ? {
				dispute_attachments: this.attachments.map((a) => ({
					// Same rule as the item rows above: keep the row identity across a save.
					...(a.name ? { name: a.name } : {}),
					file: a.file, kind: a.kind, description: a.description,
				})),
			} : {}),
		};
		if (this.docname) doc.name = this.docname;
		if (this.company) doc.company = this.company;
		return doc;
	}

	/** Save the inward; `after(name)` replaces the reload once the server has stored it. */
	save(then_submit, after) {
		const me = this;
		if (!this._val('purchase_order')) {
			frappe.msgprint(__('Please select a Purchase Order.'));
			return;
		}
		if (!this.items.length) {
			frappe.msgprint(__('Please add at least one item to the Purchase Inward.'));
			return;
		}

		const finish = (name) => {
			me.docname = name;
			if (after) {
				after(name);
				return;
			}
			me._toast(then_submit ? __('Submitted') : __('Saved'), 'green');
			me.load(name);
		};

		if (!this.docname) {
			frappe.call({
				method: 'frappe.client.insert',
				args: { doc: this.collect_doc() },
				freeze: true,
				freeze_message: __('Saving...'),
				callback(r) {
					if (!r.message) return;
					if (then_submit) me.submit_doc(r.message.name, finish);
					else finish(r.message.name);
				},
			});
			return;
		}

		// Update in place: frappe.client.get -> apply -> save keeps the doc's own
		// validate()/before_update_after_submit() gates in charge.
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Inward', name: this.docname },
			callback(g) {
				if (!g.message) return;
				const payload = me.collect_doc();
				// Row identity comes from the SERVER copy, matched on po_detail -- never
				// from whatever name this page happens to be holding. A save replaces the
				// child rows, so a name picked up before an earlier save no longer exists,
				// and on a SUBMITTED document frappe loads every non-new child row through
				// BaseDocument._validate_update_after_submit -> frappe.get_doc(child, name),
				// which then throws "Purchase Inward Item <hash> not found" and blocks the
				// save entirely. po_detail is the stable key: _validate_unique_po_detail
				// already guarantees one row per Purchase Order line.
				//
				// Each row is also laid OVER the server's copy instead of replacing it. This
				// page only sends the fields it manages, so a wholesale replace wrote every
				// other column of the row back as empty -- quarantine flags set by
				// quarantine.mark, for one -- and, on a draft, the Store Receiving values it
				// deliberately no longer sends. idx is dropped so Frappe renumbers the rows in
				// the order they are sent, which is the order on screen.
				const server_rows = {};
				(g.message.items || []).forEach((row) => {
					if (row.po_detail) server_rows[row.po_detail] = row;
				});
				payload.items = (payload.items || []).map((row) => {
					const server = server_rows[row.po_detail];
					if (!server) {
						const fresh = Object.assign({}, row);
						delete fresh.name;
						return fresh;
					}
					const merged = Object.assign({}, server, row, { name: server.name });
					delete merged.idx;
					return merged;
				});
				// Same problem, same fix, for dispute attachments: this page never sends
				// uploaded_by / uploaded_on (server-stamped, read-only -- _stamp_dispute_
				// attachments), so an existing row sent as-is lost both on the round trip.
				// _stamp_dispute_attachments then saw no uploaded_on and stamped a NEW one,
				// which _validate_update_after_submit then refused as a change to a row that,
				// from the user's side, was never touched: "Row #1: Not allowed to change
				// Uploaded On after submission from <original> to <just-now>".
				if (payload.dispute_attachments) {
					const server_attachments = {};
					(g.message.dispute_attachments || []).forEach((row) => {
						if (row.name) server_attachments[row.name] = row;
					});
					payload.dispute_attachments = payload.dispute_attachments.map((row) => {
						const server = row.name && server_attachments[row.name];
						if (!server) return row;
						const merged = Object.assign({}, server, row, { name: server.name });
						delete merged.idx;
						return merged;
					});
				}
				const doc = Object.assign({}, g.message, payload);
				frappe.call({
					method: 'frappe.client.save',
					args: { doc: doc },
					freeze: true,
					freeze_message: __('Saving...'),
					callback(r) {
						if (!r.message) return;
						if (then_submit) me.submit_doc(r.message.name, finish);
						else finish(r.message.name);
					},
				});
			},
		});
	}

	submit_doc(name, done) {
		frappe.call({
			method: 'alpinos.purchase.inward_api.run_action',
			args: { purchase_inward: name, action: 'submit' },
			freeze: true,
			freeze_message: __('Submitting...'),
			callback() { done(name); },
		});
	}
};
