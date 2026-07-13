frappe.pages['ecom-sales-order-entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('E-Com Sales Order Entry'),
		single_column: true,
	});
	page.main.html(frappe.render_template('ecom_sales_order_entry'));
	wrapper.eso_instance = new EcomSalesOrderEntry(page);
};

// Re-run per visit so navigating away and back starts blank unless edit is asked.
frappe.pages['ecom-sales-order-entry'].on_page_show = function (wrapper) {
	if (wrapper.eso_instance) wrapper.eso_instance.handle_route_entry();
};

class EcomSalesOrderEntry {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.items = [];
		this.freebies = [];
		this.editing = null; // SO name when editing a draft
		this._site_manual = false;
		this.make_fields();
		this.bind_events();
	}

	// ---- field construction ------------------------------------------------
	make_fields() {
		const w = this.wrapper;
		const mk = (sel, df) =>
			frappe.ui.form.make_control({ df, parent: w.find(sel), render_input: true });

		this.f_channel = mk('.fld-channel', {
			fieldtype: 'Data', fieldname: 'channel', label: __('Channel'), read_only: 1,
		});
		this.f_channel.set_value('E-com');

		this.f_customer = mk('.fld-customer', {
			fieldtype: 'Link', options: 'Customer', fieldname: 'customer', reqd: 1,
			label: __('Customer Name'),
			get_query: () => ({ query: 'alpinos.sales_order_offline_buyer.ecom_sales_order_customer_query' }),
			onchange: () => this.on_customer_change(),
		});
		this.f_customer_type = mk('.fld-customer-type', {
			fieldtype: 'Link', options: 'Alpino Customer Type', fieldname: 'customer_type',
			label: __('Customer Type'), reqd: 1,
		});

		this.f_appointment = mk('.fld-appointment-required', {
			fieldtype: 'Check', fieldname: 'appointment_required', label: __('Appointment Required'),
		});
		this.f_grn = mk('.fld-grn-available', {
			fieldtype: 'Check', fieldname: 'grn_available', label: __('GRN Available'),
		});
		this.f_partial = mk('.fld-partial-order-allowed', {
			fieldtype: 'Check', fieldname: 'partial_order_allowed', label: __('Partial Order Allowed'),
		});
		this.f_gst_excl = mk('.fld-gst-exclusive-buyer', {
			fieldtype: 'Check', fieldname: 'gst_exclusive_buyer', label: __('GST-Exclusive Buyer'),
		});

		// Address
		this.f_site = mk('.fld-site-name', {
			fieldtype: 'Data', fieldname: 'site_name', label: __('Site Name'),
			onchange: () => { this._site_manual = true; },
		});
		this.f_bill_gstin = mk('.fld-billing-gstin', {
			fieldtype: 'Data', fieldname: 'billing_gstin', label: __('Billing GSTIN'), length: 15,
		});
		this.f_ship_gstin = mk('.fld-shipping-gstin', {
			fieldtype: 'Data', fieldname: 'shipping_gstin', label: __('Shipping GSTIN'), length: 15,
		});
		this.f_bill_addr = mk('.fld-billing-address', {
			fieldtype: 'Small Text', fieldname: 'billing_address', label: __('Billing Address'), reqd: 1,
		});
		this.f_ship_addr = mk('.fld-shipping-address', {
			fieldtype: 'Small Text', fieldname: 'shipping_address', label: __('Shipping Address'), reqd: 1,
		});

		// PO details
		this.f_po_no = mk('.fld-po-number', {
			fieldtype: 'Data', fieldname: 'po_number', label: __('PO Number'), reqd: 1,
		});
		this.f_po_date = mk('.fld-po-date', {
			fieldtype: 'Date', fieldname: 'po_date', label: __('PO Date'), reqd: 1,
		});
		this.f_po_expiry = mk('.fld-po-expiry-date', {
			fieldtype: 'Date', fieldname: 'po_expiry_date', label: __('PO Expiry Date'),
		});
		this.f_delivery_by = mk('.fld-delivery-by-date', {
			fieldtype: 'Date', fieldname: 'delivery_by_date', label: __('Delivery By Date'),
		});
		this.f_dispatch = mk('.fld-dispatch-date', {
			fieldtype: 'Date', fieldname: 'dispatch_date', label: __('Dispatch Date'), reqd: 1,
		});
		this.f_dispatch.set_value(frappe.datetime.get_today());

		// Freebies flag
		this.f_freebie_po = mk('.fld-is-freebie-po', {
			fieldtype: 'Check', fieldname: 'is_freebie_po', label: __('Freebies (Entire PO Free)'),
			onchange: () => this.toggle_freebie_po(),
		});

		// Add-item controls
		this.f_add_sku = mk('.fld-add-sku', {
			fieldtype: 'Link', options: 'Item', fieldname: 'add_sku', label: __('SKU'),
			get_query: () => ({ filters: { disabled: 0 } }),
		});
		this.f_add_qty = mk('.fld-add-qty', {
			fieldtype: 'Float', fieldname: 'add_qty', label: __('Qty'),
		});
		this.f_add_freebie_sku = mk('.fld-add-freebie-sku', {
			fieldtype: 'Link', options: 'Item', fieldname: 'add_freebie_sku', label: __('SKU'),
			get_query: () => ({ filters: { disabled: 0 } }),
		});
		this.f_add_freebie_qty = mk('.fld-add-freebie-qty', {
			fieldtype: 'Float', fieldname: 'add_freebie_qty', label: __('Qty'),
		});
	}

	// ---- events ------------------------------------------------------------
	bind_events() {
		const w = this.wrapper;
		w.find('.btn-add-item').on('click', () => this.add_item());
		w.find('.btn-add-freebie').on('click', () => this.add_freebie());
		w.find('.btn-eso-save').on('click', () => this.save());
		w.find('.btn-eso-clear').on('click', () => this.clear_form());

		w.on('input change', '.eso-items-table .item-input', (e) => {
			const $el = $(e.currentTarget);
			const idx = cint($el.closest('tr').data('idx'));
			const field = $el.data('field');
			if (!this.items[idx]) return;
			this.items[idx][field] = flt($el.val());
			if (field === 'mrp' || field === 'margin_percent') this.recalc_row(idx);
		});
		w.on('click', '.eso-items-table .btn-del-row', (e) => {
			const idx = cint($(e.currentTarget).closest('tr').data('idx'));
			this.items.splice(idx, 1);
			this.render_items();
		});
		w.on('input change', '.eso-freebies-table .free-input', (e) => {
			const $el = $(e.currentTarget);
			const idx = cint($el.closest('tr').data('idx'));
			if (!this.freebies[idx]) return;
			this.freebies[idx].qty = flt($el.val());
		});
		w.on('click', '.eso-freebies-table .btn-del-row', (e) => {
			const idx = cint($(e.currentTarget).closest('tr').data('idx'));
			this.freebies.splice(idx, 1);
			this.render_freebies();
		});
	}

	handle_route_entry() {
		const ro = frappe.route_options || {};
		if (ro.edit_eso) {
			const name = ro.edit_eso;
			delete ro.edit_eso;
			this.clear_form();
			this.load_prefill(name);
		}
	}

	// ---- customer / buyer autofill ----------------------------------------
	on_customer_change() {
		const customer = this.f_customer.get_value();
		if (!customer) return;
		frappe.call({
			method: 'alpinos.ecom_sales_order_api.get_ecom_buyer_for_customer',
			args: { customer },
			callback: (r) => {
				const d = r.message || {};
				this.f_customer_type.set_value(d.customer_type || '');
				this.f_appointment.set_value(cint(d.appointment_required));
				this.f_grn.set_value(cint(d.grn_available));
				this.f_partial.set_value(cint(d.partial_order_allowed));
				this.f_gst_excl.set_value(cint(d.gst_exclusive_buyer));
				if (!this._site_manual && d.site_name) this.f_site.set_value(d.site_name);
				const b = d.billing || {}, s = d.shipping || {};
				this.f_bill_addr.set_value(b.address || '');
				this.f_bill_gstin.set_value(b.gstin || '');
				this.f_ship_addr.set_value(s.address || '');
				this.f_ship_gstin.set_value(s.gstin || '');
			},
		});
	}

	// ---- items -------------------------------------------------------------
	add_item() {
		const item_code = this.f_add_sku.get_value();
		if (!item_code) { frappe.show_alert({ message: __('Select a SKU'), indicator: 'orange' }); return; }
		const qty = flt(this.f_add_qty.get_value());
		frappe.call({
			method: 'alpinos.ecom_sales_order_api.get_ecom_item_defaults',
			args: { customer: this.f_customer.get_value() || '', item_code },
			callback: (r) => {
				const d = r.message || {};
				const box_factor = flt(d.box_factor);
				const row = {
					item_code,
					item_name: d.item_name || '',
					qty: qty || 0,
					box: box_factor && qty ? Math.ceil(qty / box_factor) : 0,
					box_factor,
					mrp: flt(d.mrp),
					margin_percent: flt(d.margin_percent),
					gst_percent: flt(d.gst_percent),
					selling_price: flt(d.selling_price),
				};
				this.items.push(row);
				this.render_items();
				this.f_add_sku.set_value('');
				this.f_add_qty.set_value('');
			},
		});
	}

	recalc_row(idx) {
		const r = this.items[idx];
		if (!r) return;
		r.selling_price = flt(r.mrp * (1 - flt(r.margin_percent) / 100), 2);
		if (r.box_factor && r.qty) r.box = Math.ceil(r.qty / r.box_factor);
		this.render_items();
	}

	render_items() {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const tb = this.wrapper.find('.eso-items-table tbody').empty();
		if (!this.items.length) {
			tb.append('<tr><td colspan="8" class="text-muted text-center">' + __('No SKUs added') + '</td></tr>');
			this.render_total();
			return;
		}
		this.items.forEach((r, i) => {
			tb.append(`<tr data-idx="${i}">
				<td>${esc(r.item_code)}</td>
				<td>${esc(r.item_name)}</td>
				<td><input class="item-input" data-field="qty" type="number" min="0" value="${flt(r.qty)}"></td>
				<td><input class="item-input" data-field="box" type="number" min="0" value="${flt(r.box)}"></td>
				<td><input class="item-input" data-field="mrp" type="number" min="0" value="${flt(r.mrp)}"></td>
				<td><input class="item-input" data-field="margin_percent" type="number" min="0" max="90" value="${flt(r.margin_percent)}"></td>
				<td class="readonly-cell">${format_number(flt(r.selling_price), null, 2)}</td>
				<td class="text-center"><button type="button" class="btn btn-xs btn-danger btn-del-row">&times;</button></td>
			</tr>`);
		});
		this.render_total();
	}

	render_total() {
		let total = 0;
		this.items.forEach((r) => { total += flt(r.qty) * flt(r.selling_price); });
		this.wrapper.find('.eso-total').text(__('Order Value (incl. GST): {0}', [format_number(total, null, 2)]));
	}

	// ---- freebies ----------------------------------------------------------
	add_freebie() {
		const item_code = this.f_add_freebie_sku.get_value();
		if (!item_code) { frappe.show_alert({ message: __('Select a SKU'), indicator: 'orange' }); return; }
		const qty = flt(this.f_add_freebie_qty.get_value());
		frappe.db.get_value('Item', item_code, 'item_name').then((r) => {
			this.freebies.push({ item_code, item_name: (r.message || {}).item_name || '', qty });
			this.render_freebies();
			this.f_add_freebie_sku.set_value('');
			this.f_add_freebie_qty.set_value('');
		});
	}

	render_freebies() {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const tb = this.wrapper.find('.eso-freebies-table tbody').empty();
		if (!this.freebies.length) {
			tb.append('<tr><td colspan="4" class="text-muted text-center">' + __('No freebies added') + '</td></tr>');
			return;
		}
		this.freebies.forEach((r, i) => {
			tb.append(`<tr data-idx="${i}">
				<td>${esc(r.item_code)}</td>
				<td>${esc(r.item_name)}</td>
				<td><input class="free-input" type="number" min="0" value="${flt(r.qty)}"></td>
				<td class="text-center"><button type="button" class="btn btn-xs btn-danger btn-del-row">&times;</button></td>
			</tr>`);
		});
	}

	toggle_freebie_po() {
		const on = cint(this.f_freebie_po.get_value());
		this.wrapper.find('.eso-ordered-products').toggle(!on);
		this.wrapper.find('.eso-freebies-title').text(on ? __('Freebie Items (Entire PO)') : __('Freebies'));
	}

	// ---- save --------------------------------------------------------------
	build_payload() {
		const freebie_po = cint(this.f_freebie_po.get_value());
		let items, freebies;
		if (freebie_po) {
			items = this.freebies.map((f) => ({
				item_code: f.item_code, qty: flt(f.qty),
				custom_box: 0, custom_customer_mrp: 0, custom_selling_price: 0,
				margin_percent: 0, custom_gst_percent: 0,
			}));
			freebies = [];
		} else {
			items = this.items.map((r) => ({
				item_code: r.item_code, qty: flt(r.qty), custom_box: flt(r.box),
				custom_customer_mrp: flt(r.mrp), custom_selling_price: flt(r.selling_price),
				margin_percent: flt(r.margin_percent), custom_gst_percent: flt(r.gst_percent),
			}));
			freebies = this.freebies.map((f) => ({ item_code: f.item_code, item_name: f.item_name, qty: flt(f.qty) }));
		}
		return {
			customer: this.f_customer.get_value(),
			order_type: this.f_customer_type.get_value(),
			company: '',
			items: JSON.stringify(items),
			freebies: JSON.stringify(freebies),
			flags: JSON.stringify({
				appointment_required: cint(this.f_appointment.get_value()),
				grn_available: cint(this.f_grn.get_value()),
				partial_order_allowed: cint(this.f_partial.get_value()),
				gst_exclusive_buyer: cint(this.f_gst_excl.get_value()),
			}),
			po_number: this.f_po_no.get_value(),
			po_date: this.f_po_date.get_value(),
			po_expiry_date: this.f_po_expiry.get_value(),
			delivery_by_date: this.f_delivery_by.get_value(),
			dispatch_date: this.f_dispatch.get_value(),
			billing_gstin: this.f_bill_gstin.get_value(),
			shipping_gstin: this.f_ship_gstin.get_value(),
			billing_address: this.f_bill_addr.get_value(),
			shipping_address: this.f_ship_addr.get_value(),
			site_name: this.f_site.get_value(),
			is_freebie_po: freebie_po,
		};
	}

	validate_form() {
		const errs = [];
		if (!this.f_customer.get_value()) errs.push(__('Customer is required'));
		if (!this.f_customer_type.get_value()) errs.push(__('Customer Type is required'));
		if (!this.f_po_no.get_value()) errs.push(__('PO Number is required'));
		if (!this.f_po_date.get_value()) errs.push(__('PO Date is required'));
		if (!this.f_dispatch.get_value()) errs.push(__('Dispatch Date is required'));
		if (!this.f_bill_addr.get_value()) errs.push(__('Billing Address is required'));
		if (!this.f_ship_addr.get_value()) errs.push(__('Shipping Address is required'));
		const freebie_po = cint(this.f_freebie_po.get_value());
		if (freebie_po && !this.freebies.length) errs.push(__('Add at least one freebie item'));
		if (!freebie_po && !this.items.length) errs.push(__('Add at least one SKU'));
		return errs;
	}

	save() {
		const errs = this.validate_form();
		if (errs.length) {
			frappe.msgprint({ title: __('Cannot Save'), message: errs.join('<br>'), indicator: 'red' });
			return;
		}
		const method = this.editing
			? 'alpinos.ecom_sales_order_api.update_ecom_sales_order'
			: 'alpinos.ecom_sales_order_api.create_ecom_sales_order';
		const args = this.build_payload();
		if (this.editing) args.name = this.editing;
		frappe.call({
			method, args, freeze: true, freeze_message: __('Saving...'),
			callback: (r) => {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved {0}', [r.message.name]), indicator: 'green' });
				frappe.set_route('ecom-sales-order-entry-list');
			},
		});
	}

	// ---- prefill / clear ---------------------------------------------------
	load_prefill(name) {
		frappe.call({
			method: 'alpinos.ecom_sales_order_api.get_ecom_so_entry_payload',
			args: { sales_order: name },
			freeze: true, freeze_message: __('Loading...'),
			callback: (r) => {
				const d = r.message;
				if (!d) return;
				this.editing = d.name;
				this.page.set_title(__('E-Com Sales Order Entry — {0}', [d.name]));
				this.f_customer.set_value(d.customer);
				this.f_customer_type.set_value(d.order_type);
				const fl = d.flags || {};
				this.f_appointment.set_value(cint(fl.appointment_required));
				this.f_grn.set_value(cint(fl.grn_available));
				this.f_partial.set_value(cint(fl.partial_order_allowed));
				this.f_gst_excl.set_value(cint(fl.gst_exclusive_buyer));
				this.f_site.set_value(d.site_name || '');
				this._site_manual = true;
				this.f_bill_gstin.set_value(d.billing_gstin || '');
				this.f_ship_gstin.set_value(d.shipping_gstin || '');
				this.f_bill_addr.set_value(d.billing_address || '');
				this.f_ship_addr.set_value(d.shipping_address || '');
				this.f_po_no.set_value(d.po_number || '');
				this.f_po_date.set_value(d.po_date || '');
				this.f_po_expiry.set_value(d.po_expiry_date || '');
				this.f_delivery_by.set_value(d.delivery_by_date || '');
				this.f_dispatch.set_value(d.dispatch_date || frappe.datetime.get_today());
				this.f_freebie_po.set_value(cint(d.is_freebie_po));
				this.items = (d.items || []).map((it) => ({
					item_code: it.item_code, item_name: it.item_name, qty: flt(it.qty),
					box: flt(it.box), box_factor: 0, mrp: flt(it.mrp),
					margin_percent: flt(it.margin_percent), gst_percent: flt(it.gst_percent),
					selling_price: flt(it.custom_selling_price),
				}));
				this.freebies = (d.freebies || []).map((f) => ({
					item_code: f.item_code, item_name: f.item_name, qty: flt(f.qty),
				}));
				this.render_items();
				this.render_freebies();
				this.toggle_freebie_po();
			},
		});
	}

	clear_form() {
		this.editing = null;
		this._site_manual = false;
		this.items = [];
		this.freebies = [];
		this.page.set_title(__('E-Com Sales Order Entry'));
		[
			this.f_customer, this.f_customer_type, this.f_appointment, this.f_grn, this.f_partial,
			this.f_gst_excl, this.f_site, this.f_bill_gstin, this.f_ship_gstin, this.f_bill_addr,
			this.f_ship_addr, this.f_po_no, this.f_po_date, this.f_po_expiry, this.f_delivery_by,
			this.f_freebie_po,
		].forEach((f) => f && f.set_value(''));
		this.f_dispatch.set_value(frappe.datetime.get_today());
		this.render_items();
		this.render_freebies();
		this.toggle_freebie_po();
	}
}
