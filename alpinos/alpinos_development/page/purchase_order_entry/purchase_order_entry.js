/**
 * Purchase Order Entry — BRD "Purchase Inward Part -1", section 2 (Purchase Order
 * Screen Layout) and section 3 (Purchase Order Approval).
 *
 * The page is a DATA-ENTRY SURFACE, not a second pricing engine. It collects the
 * header and the item lines and saves a real Purchase Order through the ordinary
 * document API, so ERPNext computes net rate, tax, discount and every total exactly
 * as it does anywhere else; the Summary card then reads those numbers back off the
 * saved document. Re-implementing that arithmetic here would give the site two
 * answers for the same order.
 *
 * Approval (BRD 3) is drawn from alpinos.purchase.purchase_order_approval, which owns
 * the transition table, so a button can never be offered here and refused there.
 *
 * Design language matches the other alpinos entry pages: eso-card / eso-card-title /
 * eso-fld / alp-scroll / alp-actions, all from public/css/alpinos_pages.css.
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

// BRD 2.1.1 PO Type. Mirrors alpinos.purchase.constants.INWARD_TYPES.
var PO_INWARD_TYPES = ['RM', 'PM', 'FG', 'MM'];

/**
 * A Datetime typed as a date alone ("16-09-2026", then Tab) kept no time. Frappe's
 * frappe.datetime.user_to_str reads a time only when the text has a space in it, so the value
 * became a bare date -- midnight once stored -- while picking the same day from the calendar
 * keeps one. A date typed alone now takes the time already in the field or, when the field
 * had none, `default_time(user_time_format)`. get_value() parses through here too, so a save
 * made without leaving the field gets the time as well.
 */
var ALP_DATE_ONLY_KEEPS_TIME = function (control, default_time, default_hms) {
	// The last date and time the field held, kept here rather than read off the control.
	// Selecting the text and deleting it to type a new date empties control.value first
	// (air-datepicker fires a change for the empty input). And when the screen resets a field
	// to empty, Frappe can judge the set unchanged and skip it: control.value and, for a
	// moment, the input box still hold the previous document's time, which refresh() parses
	// again. So this follows every set_value (loading or resetting the document), and after
	// one takes in parsed entries only once the user has been in the field.
	let last = null;
	let touched = false;
	// A day picked from the calendar on a field that holds no time yet: the picker hands
	// over its own clock time (whatever it is right now), which is not "a date with no time".
	// Flag it so parse() gives it the default time instead.
	let picked_blank = false;
	// Typing into the box also makes the picker fire a select (it follows the text), so a
	// pick only counts when it is a click on a calendar day, not the person typing a time.
	let typing = false;
	if (control.$input) {
		control.$input.on('focus keydown input', () => { touched = true; });
		control.$input.on('keydown input', () => { typing = true; });
	}
	if (control.datepicker && control.datepicker.opts) {
		if (default_hms) {
			// The calendar's time sliders start at "now" (13:45:52 on screen). On a field with
			// no value yet, open them at the default time, so what is shown is what a click stores.
			const on_show = control.datepicker.opts.onShow;
			control.datepicker.opts.onShow = function () {
				const tp = control.datepicker.timepicker;
				if (!last && tp) {
					tp.hours = default_hms[0];
					tp.minutes = default_hms[1];
					tp.seconds = default_hms[2];
					tp.update();
				}
				return on_show && on_show.apply(this, arguments);
			};
		}
		// a click on the calendar itself is a pick, whatever was typed before it
		control.datepicker.$datepicker.on('mousedown', () => { typing = false; });
		const on_select = control.datepicker.opts.onSelect;
		control.datepicker.opts.onSelect = function () {
			picked_blank = !last && !typing;
			setTimeout(() => { picked_blank = false; }, 500);
			return on_select && on_select.apply(this, arguments);
		};
	}
	const set_value = control.set_value.bind(control);
	// Counts every set_value, so a redraw queued by parse() can tell the field was cleared or
	// reloaded in the meantime and must not put the old text back.
	let epoch = 0;
	control.set_value = function (value, ...rest) {
		last = value || null;
		touched = false;
		epoch += 1;
		return set_value(value, ...rest);
	};
	const parse = control.parse.bind(control);
	control.parse = function (value) {
		let typed = typeof value === 'string' ? value.trim() : '';
		const from_input = touched && !!control.$input && value === control.$input.val();
		if (picked_blank && typed.indexOf(' ') !== -1) {
			// keep only the date the user clicked; the time is the default, not the picker's
			typed = typed.split(' ')[0];
			value = typed;
			picked_blank = false;
		}
		const date_fmt = frappe.datetime.get_user_date_fmt().toUpperCase();
		// A date with no time, however it was typed: 29-09-2026, 29-9-2026, 29/09/2026,
		// 29.09.2026, 29092026, 29-09-26. It used to have to be dd-mm-yyyy exactly, so any other
		// way of typing it either kept no time at all or stored the time without showing it.
		const day = /^\d[\d./-]*\d$/.test(typed)
			? moment(typed, [date_fmt, date_fmt.replace(/[-/.]/g, '/'), date_fmt.replace(/[-/.]/g, '.'),
				date_fmt.replace(/[-/.]/g, ''), date_fmt.replace('YYYY', 'YY')])
			: null;
		if (!typed || !day || !day.isValid()) {
			const parsed = parse(value);
			if (parsed && from_input) last = parsed;
			return parsed;
		}
		typed = day.format(date_fmt);
		const time_fmt = frappe.datetime.get_user_time_fmt();
		const held = last ? frappe.datetime.convert_to_user_tz(last, false) : null;
		// Midnight is what a date-only entry used to leave behind, not a time anyone chose.
		let time =
			held && held.isValid() && held.format('HH:mm:ss') !== '00:00:00'
				? held.format(time_fmt)
				: default_time(time_fmt, day);
		if (default_hms && held && day.isSame(moment(), 'day')) {
			// Re-typing TODAY on a field that kept an earlier time (9:00, chosen for a future
			// day) would land in the past; today falls back to the default, which is "now" by then.
			const kept = moment(time, time_fmt);
			const at = day.clone().set({ hour: kept.hour(), minute: kept.minute(), second: kept.second() });
			if (at.isBefore(moment().subtract(1, 'minute'))) time = default_time(time_fmt, day);
		}
		const result = parse(`${typed} ${time}`);
		if (result && from_input) last = result;
		if (result && control.$input) {
			// Show the time that was just added. Frappe takes a value equal to its model as
			// nothing to do (retyping the same date), and a date typed in another shape
			// (29.09.2026) is stored with its time but left in the box as the bare date.
			// Redraw the box from the stored value, either way -- unless the field was cleared
			// or reloaded since (a refused past date is cleared right after this parse).
			const at = epoch;
			setTimeout(() => { if (at === epoch) control.set_input(result); }, 0);
		}
		return result;
	};
	return control;
};


frappe.pages['purchase_order_entry'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase Order Entry',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_order_entry'));
	wrapper.po_entry = new PurchaseOrderEntry(page);
};

frappe.pages['purchase_order_entry'].on_page_show = function (wrapper) {
	if (wrapper.po_entry) wrapper.po_entry.handle_route_entry();
};

// BRD 2.1.1: "If only the date is entered, the default time shall be set to 9:00 AM."
// Mirrors alpinos.purchase.purchase_order_fields.DEFAULT_ARRIVAL_HOUR, which applies it on save.
var PO_DEFAULT_ARRIVAL_HOUR = 9;

/**
 * No past dates or times (Purchase Order: PO Date, Expected Delivery Date, Estimated Arrival).
 * Today is fine, and so is the current time. `kind` is 'date' or 'datetime'.
 *
 * The calendar greys out earlier days (and, for a datetime, earlier times today); a value typed
 * or pasted past that is refused with a message and cleared -- or put back to `reset()` -- so it
 * never reaches the save. Only the person's own entry is checked: loading a saved PO that
 * already holds an old date must not fire it (`user` is set by focusing/typing, and cleared by
 * every programmatic set_value).
 */
var PO_NO_PAST = function (control, kind, label, reset) {
	const datetime = kind === 'datetime';
	const floor = () => (datetime ? moment().subtract(1, 'minute') : moment().startOf('day'));
	// The earliest selectable day/time is applied only while the calendar is OPEN, and lifted
	// when it closes. Left on, the picker refuses -- and locks up on -- a saved order's older
	// date being loaded into the field. It is set on the picker's own properties: its update()
	// also rewrites the text box from the picker's selection, which blanked a typed date.
	const NO_MIN = new Date(-8639999913600000);
	const set_min = (date) => {
		const dp = control.datepicker;
		if (!dp) return;
		try {
			dp.opts.minDate = date || '';
			dp.minDate = date || NO_MIN;
			if (dp.views && dp.views[dp.currentView]) dp.views[dp.currentView]._render();
			if (dp.nav && !dp.opts.onlyTimepicker) dp.nav._render();
			if (dp.opts.timepicker && dp.timepicker) {
				dp.timepicker._handleDate(dp.lastSelectedDate);
				dp.timepicker._updateRanges();
			}
		} catch (e) { /* cosmetic only: the check below is what enforces the rule */ }
	};
	if (control.datepicker && control.datepicker.opts) {
		const on_show = control.datepicker.opts.onShow;
		control.datepicker.opts.onShow = function () {
			set_min((datetime ? moment() : moment().startOf('day')).toDate());
			return on_show && on_show.apply(this, arguments);
		};
		const on_hide = control.datepicker.opts.onHide;
		control.datepicker.opts.onHide = function () {
			set_min(null);
			return on_hide && on_hide.apply(this, arguments);
		};
	}
	let user = false;
	if (control.$input) control.$input.on('focus keydown input', () => { user = true; });
	const set_value = control.set_value.bind(control);
	control.set_value = function (...args) {
		user = false;
		return set_value(...args);
	};
	// true when the value was refused (and put back), so the caller can stop there
	const check = () => {
		if (!user) return false;
		const v = control.get_value();
		if (!v || !moment(v).isBefore(floor())) return false;
		user = false;
		frappe.msgprint({
			title: __('Past Date'),
			indicator: 'red',
			message: datetime
				? __('{0} cannot be in the past. Choose the current or a future date and time.', [__(label)])
				: __('{0} cannot be in the past. Choose today or a later date.', [__(label)]),
		});
		// force: a Datetime compares against its previous value, finds '' equal to it, and skips
		// the clear -- the refused value would stay in the box.
		control.set_value(reset ? reset() : '', true);
		// Leaving the field fires a second change from the text still in the box, which would
		// put the refused value straight back (and, with `user` already spent, silently).
		const refused = v;
		setTimeout(() => {
			if (control.get_value() === refused) control.set_value(reset ? reset() : '', true);
		}, 400);
		return true;
	};
	const previous = control.df.change;
	control.df.change = function () {
		// Refuse first: a field with its own handler (the line cells) must not record the
		// past value before it is put back.
		if (check()) return;
		return previous && previous.apply(this, arguments);
	};
};

var PurchaseOrderEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.items = [];
		this.setup();
	}

	setup() {
		this.make_header_fields();
		this.make_supplier_fields();
		this.make_shipment_fields();
		this.make_summary_fields();
		this.make_approval_fields();
		this.bind_events();
		this.make_actions();
	}

	// ------------------------------------------------------------- helpers

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		if (c.df.fieldtype === 'Datetime') {
			// BRD 2.1.1: any date chosen without a time is 9:00 AM -- typed or picked from the
			// calendar, this month or a future one -- shown straight away rather than only after
			// saving. (Briefly the current time on 2026-09-18; back to 9:00 AM by request.)
			ALP_DATE_ONLY_KEEPS_TIME(
				c,
				(fmt, day) => {
					// 9:00 AM on that day -- but 9:00 AM today may already be behind us, and a
					// time in the past is not allowed, so today falls back to the current time.
					const nine = moment(day || undefined).startOf('day').hour(PO_DEFAULT_ARRIVAL_HOUR);
					const now = moment();
					return (nine.isSame(now, 'day') && nine.isBefore(now) ? now : nine).format(fmt);
				},
				[PO_DEFAULT_ARRIVAL_HOUR, 0, 0]
			);
		}
		if (df.no_past) {
			PO_NO_PAST(c, df.no_past, df.label, df.no_past_reset);
		}
		c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		c.refresh();
		this.fields[df.fieldname] = c;
		return c;
	}

	_val(f) { const c = this.fields[f]; return c ? c.get_value() : null; }

	_set(f, v) {
		const c = this.fields[f];
		if (c) { c.set_value(v === undefined || v === null ? '' : ALP_TRIM_MICROSECONDS(v)); c.refresh(); }
	}

	_toast(m, i) { frappe.show_alert({ message: m, indicator: i || 'blue' }, 5); }

	// ------------------------------------------------- BRD 2.1.1 header

	make_header_fields() {
		this._ctl('.field-name', {
			fieldname: 'name', label: 'Purchase Order ID', read_only: 1,
			description: 'Generated by the system on save.',
		});
		this._ctl('.field-inward-type', {
			fieldname: 'custom_inward_type', label: 'PO Type', fieldtype: 'Select',
			options: '\n' + PO_INWARD_TYPES.join('\n'), reqd: 1,
			description: 'Drives batch numbering and the QC checklist downstream.',
		});
		const me = this;
		const sup = this._ctl('.field-supplier', {
			fieldname: 'supplier', label: 'Vendor Name', fieldtype: 'Link',
			options: 'Supplier', reqd: 1,
		});
		if (sup && sup.$input) {
			sup.$input.on('change', () => me.fetch_supplier());
			// A pick from the dropdown fires no native 'change' (link.js sets the value through
			// parse_validate_and_set_in_model), so choosing a vendor never fetched its name or
			// address. Listening here rather than on df.change keeps the lookup to a real
			// pick: loading a saved PO must not overwrite its address with the vendor's primary.
			sup.$input.on('awesomplete-selectcomplete', () => setTimeout(() => me.fetch_supplier(), 0));
		}

		this._ctl('.field-transaction-date', {
			fieldname: 'transaction_date', label: 'PO Date', fieldtype: 'Date', reqd: 1,
			no_past: 'date', no_past_reset: () => frappe.datetime.get_today(),
		}, frappe.datetime.get_today());
		this._ctl('.field-schedule-date', {
			fieldname: 'schedule_date', label: 'Expected Delivery Date', fieldtype: 'Date', reqd: 1,
			no_past: 'date',
		});
		this._ctl('.field-set-warehouse', {
			fieldname: 'set_warehouse', label: 'Delivery Location', fieldtype: 'Link',
			options: 'Warehouse', reqd: 1,
		});
		this._ctl('.field-currency', {
			fieldname: 'currency', label: 'Currency', fieldtype: 'Link', options: 'Currency',
		});
		this._ctl('.field-payment-terms-template', {
			fieldname: 'payment_terms_template', label: 'Payment Terms',
			fieldtype: 'Link', options: 'Payment Terms Template',
		});
		this._ctl('.field-supplier-order-no', {
			fieldname: 'custom_supplier_order_no', label: 'Supplier Order No.',
			description: 'The reference the vendor quotes back on the invoice and challan.',
		});
		this._ctl('.field-buyer', {
			fieldname: 'owner', label: 'Buyer', fieldtype: 'Link', options: 'User', read_only: 1,
		}, frappe.session.user);
		this._ctl('.field-attachment', {
			fieldname: 'custom_inward_attachment', label: 'Attachment', fieldtype: 'Attach',
		});
		this._ctl('.field-direct-purchase-invoice', {
			fieldname: 'custom_direct_purchase_invoice', label: 'Direct Purchase Invoice',
			fieldtype: 'Check',
			description: 'Skips Purchase Inward, QC and GRN entirely (BR-PO-20 .. BR-PO-25).',
		});
		this._ctl('.field-remarks', {
			fieldname: 'custom_inward_remarks', label: 'Remarks', fieldtype: 'Small Text',
		});
	}

	// ------------------------------------------- BRD 2.2.2 supplier info

	make_supplier_fields() {
		const ro = (sel, fieldname, label, fieldtype, options) =>
			this._ctl(sel, {
				fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1,
			});
		ro('.field-supplier-name', 'supplier_name', 'Vendor Name');
		// Display fields, not links: Billing Address used to be bound to supplier_address,
		// the Address record's NAME ("Billing Address-Billing"), and Shipping / Delivery to
		// address_display, which is the VENDOR's address. A purchase order is delivered to
		// the company, so that block now shows the company's shipping address.
		ro('.field-contact-person', 'contact_display', 'Contact Person');
		ro('.field-contact-number', 'contact_mobile', 'Contact Number');
		ro('.field-billing-address', 'address_display', 'Billing Address', 'Small Text');
		ro('.field-shipping-address', 'shipping_address_display', 'Shipping / Delivery Address', 'Small Text');
	}

	/**
	 * Fill Supplier Information (BRD 2.2.2) from alpinos.purchase.purchase_order_fields.
	 * get_supplier_info, which runs ERPNext's party lookup and falls back to the supplier's
	 * own Primary Address / Primary Contact when they are not linked -- this used to read
	 * two Supplier columns and never fetched a contact at all.
	 *
	 * `supplier` is passed in by load(): reading the Link control straight after load()
	 * set it returns the previous value, because set_value lands asynchronously.
	 */
	fetch_supplier(supplier) {
		supplier = supplier || this._val('supplier');
		if (!supplier) return;
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.purchase_order_fields.get_supplier_info',
			args: { supplier: supplier, company: frappe.defaults.get_default('company') || null },
			callback(r) {
				const d = (r && r.message) || {};
				me._set('supplier_name', d.supplier_name);
				me._set('contact_display', d.contact_display);
				me._set('contact_mobile', d.contact_mobile);
				me._set('address_display', d.address_display);
				me._set('shipping_address_display', d.shipping_address_display);
			},
		});
	}

	// --------------------------------------------- planned shipment block

	make_shipment_fields() {
		this._ctl('.field-vehicle-no', {
			fieldname: 'custom_vehicle_no', label: 'Vehicle Number',
			description: 'Data, not a number: vehicle references carry leading zeros and spaces.',
		});
		const driver = this._ctl('.field-driver-contact-no', {
			fieldname: 'custom_driver_contact_no', label: 'Driver Contact Number',
			description: '10-digit number.',
		});
		if (driver && driver.$input) {
			// Only digits go in, and typing stops at 10. A pasted number keeps every digit it
			// had ("+91 98765 43210" -> 919876543210) so it is flagged instead of being cut
			// down to a different number; the server refuses anything but 10 digits
			// (purchase_order_fields.validate_driver_contact_no).
			driver.$input.attr({ inputmode: 'numeric', autocomplete: 'off' });
			const flag = () => {
				const v = driver.$input.val();
				// Through df.invalid: Frappe re-applies has-error from it after every change,
				// so toggling the class directly was wiped out the moment the field was left.
				driver.df.invalid = !!v && !/^\d{10}$/.test(v);
				driver.set_invalid();
			};
			driver.$input.on('input', (e) => {
				const el = e.target;
				let digits = el.value.replace(/\D/g, '');
				const pasted = e.originalEvent && /^insertFromPaste|^insertFromDrop/.test(e.originalEvent.inputType || '');
				if (!pasted && digits.length > 10) digits = digits.slice(0, 10);
				if (digits !== el.value) el.value = digits;
				flag();
			});
			driver.$input.on('change blur', flag);
		}
		this._ctl('.field-estimated-arrival', {
			fieldname: 'custom_estimated_arrival', label: 'Estimated Arrival Date & Time',
			fieldtype: 'Datetime',
			// Without this the control appends the site time zone as a description.
			hide_timezone: 1,
			description: 'A date with no time is treated as 9:00 AM (BRD 2.1.1).',
			no_past: 'datetime',
		});
	}

	// -------------------------------------------------- BRD 2.3.2 summary

	make_summary_fields() {
		const ro = (sel, fieldname, label, fieldtype) =>
			this._ctl(sel, { fieldname, label, fieldtype: fieldtype || 'Currency', read_only: 1 });
		ro('.field-total-qty', 'total_qty', 'Total Item Quantity', 'Float');
		ro('.field-total', 'total', 'Total Item Value');
		ro('.field-total-discount', 'discount_amount', 'Total Discount');
		ro('.field-total-taxes', 'total_taxes_and_charges', 'Total Tax');
		ro('.field-grand-total', 'grand_total', 'Grand Total');
	}

	// ---------------------------------------------------- BRD 3 approval

	make_approval_fields() {
		const ro = (sel, fieldname, label, fieldtype, options) =>
			this._ctl(sel, {
				fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1,
				hide_timezone: 1,
			});
		ro('.field-approval-status', 'custom_approval_status', 'Approval Status');
		ro('.field-approval-action-by', 'custom_approval_action_by', 'Approved / Rejected By',
			'Link', 'User');
		ro('.field-approval-datetime', 'custom_approval_datetime', 'Approval Date & Time', 'Datetime');
		ro('.field-approval-remarks', 'custom_approval_remarks', 'Approval Remarks', 'Small Text');
	}

	// ---------------------------------------------------- BRD 2.3.1 grid

	bind_events() {
		const me = this;
		this.wrapper.on('click', '.btn-add-row', () => me.add_row({}));
		this.wrapper.on('click', '.btn-remove-row', function () {
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.items.splice(idx, 1);
			me._summary_from_doc = false;
			me.redraw_items();
		});
	}

	add_row(row) {
		this.items.push(Object.assign({
			item_code: '', item_name: '', uom: '', qty: 0, price_list_rate: 0,
			discount_percentage: 0, rate: 0, amount: 0,
			schedule_date: this._val('schedule_date') || '',
			warehouse: this._val('set_warehouse') || '',
			custom_item_remarks: '',
		}, row || {}));
		this._summary_from_doc = false;
		this.redraw_items();
	}

	redraw_items() {
		const me = this;
		const $body = this.wrapper.find('.items-table tbody').empty();

		this.items.forEach((row, idx) => {
			const $tr = $(`
				<tr data-idx="${idx}">
					<td>${idx + 1}</td>
					<td class="cell-item-code"></td>
					<td class="cell-item-name"></td>
					<td class="cell-uom"></td>
					<td class="cell-qty"></td>
					<td class="cell-rate"></td>
					<td class="cell-discount"></td>
					<td class="cell-net-rate po-num"></td>
					<td class="cell-amount po-num"></td>
					<td class="cell-schedule"></td>
					<td class="cell-warehouse"></td>
					<td class="cell-remarks"></td>
					<td class="text-center">
						<button class="btn btn-xs btn-link btn-remove-row" title="Remove">
							<i class="fa fa-trash text-danger"></i>
						</button>
					</td>
				</tr>
			`);
			$body.append($tr);

			const mk = (sel, df, value, onchange) => {
				// The handler runs from Frappe's own df.change, which base_control calls for
				// every value it accepts, a pick from a Link dropdown included. This used to
				// listen for the input's native 'change' event, which a Link pick never fires
				// (link.js sets the value through parse_validate_and_set_in_model). So a
				// chosen SKU was never written to the row: Item Name and UOM were never
				// fetched, and the next Add Row / Remove, which redraws every row from
				// this.items, drew that row with a blank Item Code.
				//
				// `ready` skips the change Frappe fires for the programmatic set_value below.
				// Without it every redraw would re-fire the Item Code handler, fetch_item
				// would redraw again, and the grid would redraw forever.
				let ready = false;
				const c = frappe.ui.form.make_control({
					df: Object.assign({ fieldname: `${df.fieldname}_${idx}` }, df, {
						change: () => {
							if (!ready || !onchange) return;
							// the PARSED value: a Date control's raw text is the user format
							// (dd-mm-yyyy), an invalid DATE (MariaDB 1292)
							onchange(c.get_value());
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

			mk('.cell-item-code', {
				fieldtype: 'Link', fieldname: 'item_code', options: 'Item',
				// Combo/bundle SKUs are made of other items' stock (item_custom_fields.py
				// custom_is_bundle) and have no rate/warehouse of their own to receive
				// against, so a Purchase Order line can only be an individual SKU.
				get_query: () => ({ filters: { custom_is_bundle: 0 } }),
			},
				row.item_code, (val) => {
					me.items[idx].item_code = val;
					me.fetch_item(idx, val);
				});
			mk('.cell-item-name', { fieldtype: 'Data', fieldname: 'item_name', read_only: 1 },
				row.item_name);
			mk('.cell-uom', { fieldtype: 'Data', fieldname: 'uom', read_only: 1 }, row.uom);
			mk('.cell-qty', { fieldtype: 'Float', fieldname: 'qty' },
				row.qty, (val) => { me.items[idx].qty = flt(val); me.recalc_row(idx); });
			// BRD 2.3.1 calls this Rate and defines Net Rate as "rate after applicable
			// discount". In ERPNext that pair is price_list_rate -> discount_percentage
			// -> rate, so BRD Rate binds to price_list_rate and BRD Net Rate to rate.
			// Binding the discount against `rate` instead does nothing at all: ERPNext
			// applies it to price_list_rate, so the discount column would be inert.
			mk('.cell-rate', { fieldtype: 'Currency', fieldname: 'price_list_rate', precision: 2 },
				row.price_list_rate, (val) => {
					// At most 2 digits after the decimal.
					me.items[idx].price_list_rate = flt(flt(val).toFixed(2));
					me.recalc_row(idx);
				});
			mk('.cell-discount', { fieldtype: 'Percent', fieldname: 'discount_percentage' },
				row.discount_percentage, (val) => {
					let v = flt(val);
					if (v > 100) {
						v = 100;
						frappe.msgprint({
							title: __('Invalid Discount'),
							message: __('Discount cannot be more than 100%.'),
							indicator: 'red',
						});
						// The control still shows what was typed until told otherwise --
						// set_value redraws it to the capped value so the two never disagree.
						const c = me.fields[`discount_percentage_${idx}`];
						if (c) c.set_value(v);
					}
					me.items[idx].discount_percentage = v;
					me.recalc_row(idx);
				});
			mk('.cell-net-rate', { fieldtype: 'Currency', fieldname: 'rate', read_only: 1 },
				row.rate);
			mk('.cell-amount', { fieldtype: 'Currency', fieldname: 'amount', read_only: 1 },
				row.amount);
			const sched = mk('.cell-schedule', { fieldtype: 'Date', fieldname: 'schedule_date' },
				row.schedule_date, (val) => { me.items[idx].schedule_date = val; });
			PO_NO_PAST(sched, 'date', 'Required By', () => me.items[idx].schedule_date || '');
			mk('.cell-warehouse', { fieldtype: 'Link', fieldname: 'warehouse', options: 'Warehouse' },
				row.warehouse, (val) => { me.items[idx].warehouse = val; });
			mk('.cell-remarks', { fieldtype: 'Data', fieldname: 'custom_item_remarks' },
				row.custom_item_remarks, (val) => { me.items[idx].custom_item_remarks = val; });
		});
		// Every add, remove and load redraws the grid, so the summary follows it here.
		this.recalc_summary();
	}

	fetch_item(idx, item_code) {
		const me = this;
		// Hold the ROW, not its index: a row added or removed while the lookup is in flight
		// shifts every index, and writing to me.items[idx] then fills the wrong line.
		const row = this.items[idx];
		if (!row) return;
		if (!item_code) {
			// A cleared Item Code must not keep the previous item's name and unit.
			if (row.item_name || row.uom) {
				row.item_name = '';
				row.uom = '';
				me.redraw_items();
			}
			return;
		}
		// Same Item Code already on another row: caught here, at the moment it is picked,
		// rather than only at save (purchase_order_fields.validate_duplicate_items).
		if (me.items.some((r) => r !== row && r.item_code === item_code)) {
			frappe.msgprint({
				title: __('Duplicate Item'),
				message: __('{0} is already on another row. Combine the quantities into a single row instead.', [frappe.utils.escape_html(item_code)]),
				indicator: 'red',
			});
			row.item_code = '';
			row.item_name = '';
			row.uom = '';
			me.redraw_items();
			return;
		}
		frappe.call({
			method: 'alpinos.purchase.purchase_order_fields.get_item_defaults',
			args: { item_code },
		}).then((r) => {
			if (me.items.indexOf(row) === -1 || row.item_code !== item_code) return;
			const d = r.message || {};
			row.item_name = d.item_name || '';
			row.uom = d.stock_uom || '';
			// A row picking a fresh item always starts at Rate 0, so this can never clobber
			// a rate the buyer already typed.
			if (!flt(row.price_list_rate) && flt(d.rate)) row.price_list_rate = flt(d.rate);
			me.redraw_items();
			me.recalc_row(idx);
		});
	}

	/** Preview only. The ERP recomputes on save and the saved values win. */
	recalc_row(idx) {
		const row = this.items[idx];
		const net = flt(row.price_list_rate) * (1 - flt(row.discount_percentage) / 100);
		row.rate = net;
		row.amount = net * flt(row.qty);
		const nr = this.fields[`rate_${idx}`];
		const am = this.fields[`amount_${idx}`];
		if (nr) nr.set_value(ALP_TRIM_MICROSECONDS(row.rate));
		if (am) am.set_value(ALP_TRIM_MICROSECONDS(row.amount));
		this._summary_from_doc = false;
		this.recalc_summary();
	}

	/**
	 * BRD 2.3.2 PO Summary, kept live while the lines change.
	 *
	 * It used to be filled only from the saved document, so a new or edited order showed
	 * "—" in all five boxes. Quantity, value and discount now follow the lines the way the
	 * grid previews them (BRD Rate = price_list_rate, Net Rate = rate). Total Discount is
	 * the line discounts plus any document-level discount; it was bound to discount_amount
	 * alone, ERPNext's document-level discount, so a Discount % typed on a line never
	 * showed there. With that, Item Value - Discount + Tax = Grand Total.
	 *
	 * Tax is the ERP's figure from the last save, because only the server knows which tax
	 * applies. Straight after load, the net and grand totals are the ERP's own saved
	 * values too, so rounding never makes a reopened order disagree with its document.
	 */
	recalc_summary() {
		const keys = ['total_qty', 'total', 'discount_amount', 'total_taxes_and_charges', 'grand_total'];
		const lines = (this.items || []).filter((r) => r.item_code || flt(r.qty));
		if (!lines.length) {
			keys.forEach((k) => this._set(k, ''));
			return;
		}
		let qty = 0;
		let gross = 0;
		let net = 0;
		lines.forEach((r) => {
			const q = flt(r.qty);
			const list = flt(r.price_list_rate);
			const rate = list ? list * (1 - flt(r.discount_percentage) / 100) : flt(r.rate);
			qty += q;
			gross += q * (list || rate);
			net += q * rate;
		});
		const saved = !!(this._summary_from_doc && this.docname && this.doc);
		const doc = (this.docname && this.doc) || {};
		const doc_discount = flt(doc.discount_amount);
		const tax = flt(doc.total_taxes_and_charges);
		if (saved) net = flt(doc.total);
		this._set('total_qty', qty);
		this._set('total', flt(gross, 2));
		this._set('discount_amount', flt(gross - net + doc_discount, 2));
		this._set('total_taxes_and_charges', tax);
		this._set('grand_total', saved ? flt(doc.grand_total) : flt(net - doc_discount + tax, 2));
	}

	// ------------------------------------------------------ approval log

	render_approval_log() {
		const rows = (this.doc && this.doc.custom_approval_log) || [];
		const $body = this.wrapper.find('.approval-table tbody').empty();
		rows.forEach((r, i) => {
			$body.append($(`
				<tr>
					<td>${i + 1}</td>
					<td>${frappe.utils.escape_html(r.approval_status || '')}</td>
					<td>${frappe.utils.escape_html(r.action_by || '')}</td>
					<td>${frappe.utils.escape_html(String(r.action_on || '').split('.')[0])}</td>
					<td>${frappe.utils.escape_html(r.previous_status || '')}</td>
					<td>${frappe.utils.escape_html(r.new_status || '')}</td>
					<td>${frappe.utils.escape_html(r.remarks || '')}</td>
				</tr>
			`));
		});
	}

	// ----------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1] || (frappe.route_options && frappe.route_options.purchase_order);
		if (frappe.route_options) delete frappe.route_options.purchase_order;
		if (name && name !== this.docname) {
			this.load(name);
		} else if (!name && this.docname) {
			// Opened bare after viewing an order: the previous one must not linger.
			this.reset();
		}
	}

	reset() {
		this.docname = null;
		this.doc = null;
		this.items = [];
		this.wrapper.find('tbody').empty();
		[
			'custom_inward_type', 'supplier', 'schedule_date', 'set_warehouse', 'currency',
			'payment_terms_template', 'custom_supplier_order_no', 'custom_inward_attachment',
			'custom_direct_purchase_invoice', 'custom_inward_remarks', 'supplier_name',
			'contact_display', 'contact_mobile', 'address_display', 'shipping_address_display',
			'custom_vehicle_no', 'custom_driver_contact_no', 'custom_estimated_arrival',
			'total_qty', 'total', 'discount_amount', 'total_taxes_and_charges', 'grand_total',
			'custom_approval_status', 'custom_approval_action_by', 'custom_approval_datetime',
			'custom_approval_remarks', 'name',
		].forEach((f) => this._set(f, ''));
		this._set('transaction_date', frappe.datetime.get_today());
		this._set('owner', frappe.session.user);
		this.page.set_title(__('Purchase Order Entry'));
		this.apply_state();
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Order', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				me.docname = doc.name;
				me.doc = doc;
				[
					'name', 'custom_inward_type', 'supplier', 'transaction_date', 'schedule_date',
					'set_warehouse', 'currency', 'payment_terms_template',
					'custom_supplier_order_no', 'owner', 'custom_inward_attachment',
					'custom_direct_purchase_invoice', 'custom_inward_remarks',
					'supplier_name', 'contact_display', 'contact_mobile', 'address_display',
					'shipping_address_display', 'custom_vehicle_no', 'custom_driver_contact_no',
					'custom_estimated_arrival', 'total_qty', 'total', 'discount_amount',
					'total_taxes_and_charges', 'grand_total', 'custom_approval_status',
					'custom_approval_action_by', 'custom_approval_datetime',
					'custom_approval_remarks',
				].forEach((f) => me._set(f, doc[f]));

				// The page does not store the vendor's contact and addresses on the order, so a
				// reopened PO reads them from the Supplier again instead of showing blanks.
				if (doc.supplier && !doc.contact_display && !doc.address_display) {
					me.fetch_supplier(doc.supplier);
				}
				// Until a line is edited the summary shows the ERP's saved figures.
				me._summary_from_doc = true;
				me.items = (doc.items || []).map((row) => Object.assign({}, row));
				me.redraw_items();
				me.render_approval_log();
				me.apply_state();
				me.page.set_title(`${doc.name} — Purchase Order`);
			},
		});
	}

	apply_state() {
		const doc = this.doc || {};
		const status = doc.custom_approval_status || '';
		const $root = this.wrapper.find('.purchase-order-entry');
		$root.toggleClass('po-saved', !!this.docname);

		const $badge = this.wrapper.find('.field-stage-badge')
			.text(status)
			.removeClass('po-approved po-rejected po-waiting');
		if (status === 'Approved' || status === 'Sent to Supplier') $badge.addClass('po-approved');
		else if (status === 'Rejected' || status === 'Cancelled') $badge.addClass('po-rejected');
		else if (status === 'Pending Approval') $badge.addClass('po-waiting');

		// VAL-PO-08 / BR-PO-12: an order awaiting approval, or already submitted, is
		// not the Purchase Team to edit any more. The server refuses it either way;
		// this only stops the screen inviting an edit that cannot be saved.
		const locked = cint(doc.docstatus) !== 0 || status === 'Pending Approval';
		this.wrapper.find('.eso-card').not('.po-approval-card').toggleClass('po-locked', locked);

		this.make_actions();
	}

	// ------------------------------------------------- BRD 2.3.3 actions

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.po-actionbar').empty();
		// The approval buttons arrive asynchronously. When two renders run close together,
		// both empty the bar before either reply lands and both replies then append, giving
		// "Save | Submit for Approval | Print | Submit for Approval | Print". Each render takes
		// a token, and only the latest one may add its buttons.
		const token = (this._actions_token = (this._actions_token || 0) + 1);
		const doc = this.doc || {};
		const status = doc.custom_approval_status || '';
		const editable = cint(doc.docstatus) === 0 && status !== 'Pending Approval';

		const btn = (label, cls, handler) => {
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		};

		if (editable) btn(__('Save'), 'btn-primary', () => me.save());

		if (this.docname) {
			// The approval transitions come from the server so the two can never drift.
			frappe.call({
				method: 'alpinos.purchase.purchase_order_approval.get_available_actions',
				args: { purchase_order: this.docname },
				callback(r) {
					if (token !== me._actions_token) return;
					const info = r.message || {};
					const actions = info.actions || [];
					actions.forEach((a) => {
						btn(__(a.action), 'btn-primary', () => me.run_action(a.action));
					});
					me.make_next_step_actions(info, btn);
					// A Cancelled or Closed order has nothing left to cancel; Force Close (the
					// admin escape hatch) will not be on this screen -- that lives on the Inward.
					if (cint(doc.docstatus) === 1 && !['Cancelled', 'Closed'].includes(doc.status || '')) {
						btn(__('Cancel'), 'btn-danger', () => me.cancel_po());
					}
					btn(__('Print'), 'btn-light', () => {
						frappe.set_route('print', 'Purchase Order', me.docname);
					});
				},
			});
		} else {
			$bar.append(
				`<span class="text-muted">${__('Fill the header and at least one item line, then Save.')}</span>`
			);
		}
	}

	/**
	 * BRD 1.3 / 1.4: what comes after the order, the same as the Purchase Order desk form
	 * (purchase_order_approval._CLIENT_SCRIPT). Create Purchase Inward belongs to a Sent to
	 * Supplier order; a Direct Purchase Invoice order skips Inward, QC and GRN and goes to
	 * its invoice instead. The inward screen re-checks the order when it is saved.
	 */
	make_next_step_actions(info, btn) {
		const me = this;
		const status = info.status || '';

		if (cint(info.direct_purchase_invoice)) {
			if (info.direct_invoice) {
				btn(__('View Purchase Invoice'), 'btn-default', () =>
					frappe.set_route('purchase_invoice_entry', info.direct_invoice)
				);
			} else if (status === 'Approved' || status === 'Sent to Supplier') {
				btn(__('Create Purchase Invoice'), 'btn-primary', () => me.create_direct_invoice());
			}
			return;
		}

		if (status === 'Sent to Supplier') {
			btn(__('Create Purchase Inward'), 'btn-primary', () => {
				frappe.route_options = { purchase_order: me.docname };
				frappe.set_route('purchase_inward_entry');
			});
		} else if (status === 'Approved') {
			// Shown, and it says why: an absent button reads as a missing feature.
			btn(__('Create Purchase Inward'), 'btn-default', () =>
				frappe.msgprint({
					title: __('Create Purchase Inward Is Not Available Yet'),
					indicator: 'orange',
					message: __('Send this Purchase Order to the supplier first (BRD 1.4).'),
				})
			);
		}

		const inwards = info.inwards || [];
		if (inwards.length) {
			btn(__('View Purchase Inward ({0})', [inwards.length]), 'btn-default', () => {
				if (inwards.length === 1) {
					frappe.set_route('purchase_inward_entry', inwards[0]);
					return;
				}
				frappe.route_options = { purchase_order: me.docname };
				frappe.set_route('purchase_inward_list');
			});
		}
	}

	create_direct_invoice() {
		const me = this;
		frappe.confirm(
			__('Create the Purchase Invoice for {0}? Purchase Inward, QC and GRN are skipped for a Direct Purchase Invoice order.', [me.docname]),
			() =>
				frappe.call({
					method: 'alpinos.purchase.purchase_invoice.create_direct_from_po',
					args: { purchase_order: me.docname },
					freeze: true,
					freeze_message: __('Creating the Purchase Invoice...'),
					callback(r) {
						// also fires when the server refused (already invoiced)
						if (r.exc || !r.message) return;
						frappe.set_route('purchase_invoice_entry', r.message.name);
					},
				})
		);
	}

	/**
	 * Cancel a submitted Purchase Order. Refused, with the exact list of what is in the
	 * way, if any of its inwards still has a live Debit Note / Invoice / GRN / QC / the
	 * inward itself (BRD 5.3's reverse-chronological rule, one level up). An Admin is then
	 * offered a second button that cancels the whole chain and the order in one go.
	 */
	cancel_po() {
		const me = this;
		const attempt = (reason) => frappe.call({
			method: 'alpinos.purchase.purchase_order_approval.cancel_purchase_order',
			args: { purchase_order: me.docname, reason: reason || null },
			freeze: true,
			freeze_message: __('Cancelling...'),
			callback(r) {
				if (r.exc || !r.message) return;
				if (r.message.cancelled) {
					me._toast(__('Cancelled'), 'red');
					me.load(me.docname);
					return;
				}
				me.show_cancel_blockers(r.message.blockers);
			},
		});
		frappe.confirm(__('Cancel Purchase Order {0}?', [this.docname]), () => attempt(null));
	}

	show_cancel_blockers(blockers) {
		const me = this;
		// Cancelling the chain is Admin only (purchase_order_approval.PO_CANCEL_CHAIN_ROLES);
		// the server is the real guard, this only stops the button inviting a click that
		// cannot be saved -- same rule the rest of this module follows.
		const admin_roles = ['System Manager', 'Purchase Inward Admin'];
		const is_admin = (frappe.user_roles || []).some((r) => admin_roles.includes(r));
		const label = (b) => `${__(b.label || b.doctype)} ${frappe.utils.escape_html(b.name)}` +
			(cint(b.docstatus) === 0 ? ` (${__('Draft')})` : '');
		const rows = blockers.map((b) => `<li>${label(b)}</li>`).join('');
		const d = new frappe.ui.Dialog({
			title: __('Cannot Cancel Yet'),
			fields: [
				{
					fieldname: 'list', fieldtype: 'HTML',
					options:
						`<p>${__('These documents were raised from this order and must be cancelled first, in this order:')}</p>` +
						`<ol>${rows}</ol>` +
						(is_admin ? '' : `<p class="text-muted small">${__('Only {0} may cancel them from here.', [admin_roles.join(' / ')])}</p>`),
				},
				{
					fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', reqd: 1,
					description: __('Required to cancel these documents. Recorded on the Purchase Order.'),
					read_only: is_admin ? 0 : 1,
				},
			],
			primary_action_label: is_admin ? __('Cancel These Documents & the Purchase Order') : null,
			primary_action: is_admin
				? (values) => {
					d.hide();
					frappe.call({
						method: 'alpinos.purchase.purchase_order_approval.cancel_purchase_order_chain',
						args: { purchase_order: me.docname, reason: values.reason },
						freeze: true,
						freeze_message: __('Cancelling the linked documents...'),
						callback(r) {
							if (r.exc || !r.message) return;
							me._toast(__('{0} documents cancelled', [(r.message.cancelled_documents || []).length + 1]), 'red');
							me.load(me.docname);
						},
					});
				}
				: null,
		});
		d.show();
		if (!is_admin) d.get_primary_btn().hide();
	}

	run_action(action) {
		const me = this;
		const needs_remarks = action === 'Reject';
		const takes_remarks = needs_remarks || action === 'Return for Correction';

		const call = (remarks) => frappe.call({
			method: 'alpinos.purchase.purchase_order_approval.perform_action',
			args: { purchase_order: me.docname, action: action, remarks: remarks },
			freeze: true,
			freeze_message: __('Updating the Purchase Order...'),
			callback(r) { if (r.exc) return; me.load(me.docname); },
		});

		if (!takes_remarks) {
			frappe.confirm(__('{0} this Purchase Order?', [__(action)]), () => call(null));
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __(action),
			fields: [{
				fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text',
				reqd: needs_remarks ? 1 : 0,
			}],
			primary_action_label: __(action),
			primary_action(values) { d.hide(); call(values.remarks); },
		});
		d.show();
	}

	// ------------------------------------------------------------- save

	_payload() {
		return {
			// Sent explicitly. The payload goes to frappe.client.insert as a plain dict,
			// and the server does not resolve a field default of ":Company" for one -- so
			// with nothing here the insert failed outright with "Please specify Company"
			// for any user who had no Company default of their own. Reading it from
			// frappe.defaults picks up the session default, which falls back to
			// Global Defaults, so it no longer depends on per-user setup.
			company: frappe.defaults.get_default('company') || undefined,
			custom_inward_type: this._val('custom_inward_type'),
			supplier: this._val('supplier'),
			transaction_date: this._val('transaction_date'),
			schedule_date: this._val('schedule_date'),
			set_warehouse: this._val('set_warehouse'),
			currency: this._val('currency') || undefined,
			payment_terms_template: this._val('payment_terms_template') || undefined,
			custom_supplier_order_no: this._val('custom_supplier_order_no'),
			custom_inward_attachment: this._val('custom_inward_attachment'),
			custom_direct_purchase_invoice: cint(this._val('custom_direct_purchase_invoice')),
			custom_inward_remarks: this._val('custom_inward_remarks'),
			custom_vehicle_no: this._val('custom_vehicle_no'),
			custom_driver_contact_no: this._val('custom_driver_contact_no'),
			custom_estimated_arrival: this._val('custom_estimated_arrival'),
			items: this.items.map((row) => ({
				// The row's own name when it has one. save() does
				// Object.assign({}, server_doc, _payload()), a SHALLOW merge, so this array
				// replaces the server's: a nameless row is a NEW row to Frappe and the whole
				// set is deleted and re-inserted under fresh hashes. Purchase Order Item names
				// are stored by Purchase Inward Item.po_detail, which is the key the pending
				// quantity is summed over, and by Purchase Receipt Item.purchase_order_item.
				...(row.name ? { name: row.name } : {}),
				item_code: row.item_code,
				qty: flt(row.qty),
				price_list_rate: flt(row.price_list_rate),
				discount_percentage: flt(row.discount_percentage),
				schedule_date: row.schedule_date || this._val('schedule_date'),
				warehouse: row.warehouse || this._val('set_warehouse'),
				custom_item_remarks: row.custom_item_remarks,
			})),
		};
	}

	save() {
		const me = this;
		if (!this.items.length) {
			frappe.msgprint({
				title: __('No Items'),
				message: __('Please add at least one item to the Purchase Order.'),
				indicator: 'red',
			});
			return;
		}
		const payload = this._payload();

		if (this.docname) {
			frappe.call({
				method: 'frappe.client.get',
				args: { doctype: 'Purchase Order', name: this.docname },
				callback(r) {
					const doc = Object.assign({}, r.message, payload);
					frappe.call({
						method: 'frappe.client.save',
						args: { doc: doc },
						freeze: true,
						freeze_message: __('Saving...'),
						callback(res) {
							if (!res.message) return;
							me._toast(__('Saved'), 'green');
							me.load(res.message.name);
						},
					});
				},
			});
			return;
		}

		frappe.call({
			method: 'frappe.client.insert',
			args: { doc: Object.assign({ doctype: 'Purchase Order' }, payload) },
			freeze: true,
			freeze_message: __('Creating the Purchase Order...'),
			callback(r) {
				if (!r.message) return;
				me._toast(__('Purchase Order {0} created', [r.message.name]), 'green');
				// Claim the name BEFORE changing the route. set_route re-enters
				// handle_route_entry, which loads any name that is not already this.docname,
				// so a new order was loaded twice -- and the two renders of the action bar
				// each added "Submit for Approval | Print".
				me.docname = r.message.name;
				frappe.set_route('purchase_order_entry', r.message.name);
				me.load(r.message.name);
			},
		});
	}
};
