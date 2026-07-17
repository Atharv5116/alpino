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
		this.toggle_freebie_po();
		this.add_item_row();
		this.render_total();
		this.load_recent_orders();
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
	}

	// ---- events ------------------------------------------------------------
	bind_events() {
		const w = this.wrapper;
		w.find('.btn-add-item').on('click', () => this.add_item_row());
		w.find('.btn-add-freebie').on('click', () => this.add_freebie_row());
		w.find('.btn-eso-save').on('click', () => this.save());
		w.find('.btn-eso-clear').on('click', () => this.clear_form());
		w.on('click', '.recent-orders-list .order-row', (e) => {
			const name = $(e.currentTarget).data('name');
			// Open the shared Sales Order view (workflow action bar), same as the list.
			if (name) frappe.set_route('sales-order-entry-view', name);
		});
	}

	handle_route_entry() {
		const ro = frappe.route_options || {};
		if (ro.edit_eso) {
			const name = ro.edit_eso;
			delete ro.edit_eso;
			this.clear_form();
			this.load_prefill(name, 'edit');
		} else if (ro.duplicate_eso) {
			const name = ro.duplicate_eso;
			delete ro.duplicate_eso;
			this.clear_form();
			this.load_prefill(name, 'duplicate');
		} else {
			// Plain "New" visit — the page instance is reused across visits, so
			// clear stale data from the previously created/edited order and
			// refresh the recent-orders list (shows the just-created order).
			this.clear_form();
			this.load_recent_orders();
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

	// ---- per-row SKU link (awesomplete, mirrors the offline page) ----------
	_make_item_link_field(parent, fieldname) {
		const field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Item', fieldname },
			parent, render_input: true, only_input: true,
		});
		field.get_query = () => ({ filters: { disabled: 0 } });
		if (field.$input) field.$input.css('min-width', '120px');
		return field;
	}

	// ---- ordered products (inline Add Row) ---------------------------------
	add_item_row(data) {
		const me = this;
		const row = Object.assign({
			item_code: '', item_name: '', qty: 0, box: 0, box_factor: 0,
			mrp: 0, margin_percent: 0, gst_percent: 0, selling_price: 0,
		}, data || {});
		this.items.push(row);

		const $row = $(`<tr>
			<td class="cell-sku"></td>
			<td class="cell-name"><span class="text-muted" style="font-size:12px;">-</span></td>
			<td class="cell-qty"></td>
			<td class="cell-box text-right readonly-cell">—</td>
			<td class="cell-mrp"></td>
			<td class="cell-margin"></td>
			<td class="cell-selling text-right readonly-cell">0.00</td>
			<td class="text-center"><button type="button" class="btn btn-xs btn-danger btn-del-row">&times;</button></td>
		</tr>`);
		this.wrapper.find('.eso-items-table tbody').append($row);
		row._$row = $row;

		const sku_field = this._make_item_link_field($row.find('.cell-sku'), 'eso_item');
		const commit = () => setTimeout(() => {
			const val = sku_field.get_value();
			row.item_code = val;
			if (val) me.on_item_select(row, val);
		}, 200);
		sku_field.$input.on('change', commit);
		sku_field.$input.on('awesomplete-selectcomplete', commit);
		row._sku_field = sku_field;

		const mk_input = (cell, field, extra) => {
			const $i = $('<input type="number" class="form-control input-xs eso-cell-input" min="0" ' + (extra || '') + '>');
			if (flt(row[field])) $i.val(flt(row[field]));
			$row.find(cell).append($i);
			$i.on('input change', () => { row[field] = flt($i.val()); me.recalc_row(row); });
			return $i;
		};
		row._qty = mk_input('.cell-qty', 'qty');
		row._mrp = mk_input('.cell-mrp', 'mrp');
		row._margin = mk_input('.cell-margin', 'margin_percent', 'max="90"');

		$row.find('.btn-del-row').on('click', () => {
			const i = me.items.indexOf(row);
			if (i > -1) me.items.splice(i, 1);
			$row.remove();
			me.render_total();
		});

		if (data) {
			if (data.item_name) $row.find('.cell-name').html(frappe.utils.escape_html(data.item_name)).removeClass('text-muted');
			if (data.item_code) sku_field.set_value(data.item_code);
		}
		this._paint_row(row);
		return row;
	}

	on_item_select(row, item_code) {
		const me = this;
		frappe.call({
			method: 'alpinos.ecom_sales_order_api.get_ecom_item_defaults',
			args: { customer: this.f_customer.get_value() || '', item_code },
			callback: (r) => {
				const d = r.message || {};
				row.item_name = d.item_name || '';
				row.box_factor = flt(d.box_factor);
				row.mrp = flt(d.mrp);
				row.margin_percent = flt(d.margin_percent);
				row.gst_percent = flt(d.gst_percent);
				row.selling_price = flt(d.selling_price);
				row._$row.find('.cell-name').html(frappe.utils.escape_html(row.item_name)).removeClass('text-muted');
				row._mrp.val(flt(row.mrp) || '');
				row._margin.val(flt(row.margin_percent) || '');
				me.recalc_row(row);
			},
		});
	}

	recalc_row(row) {
		row.selling_price = flt(flt(row.mrp) * (1 - flt(row.margin_percent) / 100), 2);
		if (row.box_factor && row.qty) row.box = Math.ceil(flt(row.qty) / row.box_factor);
		this._paint_row(row);
		this.render_total();
	}

	_paint_row(row) {
		if (!row._$row) return;
		row._$row.find('.cell-box').text(flt(row.box) ? flt(row.box) : '—');
		row._$row.find('.cell-selling').text(format_number(flt(row.selling_price), null, 2));
	}

	render_total() {
		let total = 0;
		this.items.forEach((r) => { total += flt(r.qty) * flt(r.selling_price); });
		this.wrapper.find('.eso-total').text(__('Order Value (incl. GST): {0}', [format_number(total, null, 2)]));
	}

	// ---- freebies (inline Add Freebie) -------------------------------------
	add_freebie_row(data) {
		const me = this;
		const row = Object.assign({ item_code: '', item_name: '', qty: 0 }, data || {});
		this.freebies.push(row);

		const $row = $(`<tr>
			<td class="cell-sku"></td>
			<td class="cell-name"><span class="text-muted" style="font-size:12px;">-</span></td>
			<td class="cell-qty"></td>
			<td class="text-center"><button type="button" class="btn btn-xs btn-danger btn-del-row">&times;</button></td>
		</tr>`);
		this.wrapper.find('.eso-freebies-table tbody').append($row);
		row._$row = $row;

		const sku_field = this._make_item_link_field($row.find('.cell-sku'), 'eso_free');
		const commit = () => setTimeout(() => {
			const val = sku_field.get_value();
			row.item_code = val;
			if (val) {
				frappe.db.get_value('Item', val, 'item_name').then((r) => {
					row.item_name = (r.message || {}).item_name || '';
					$row.find('.cell-name').html(frappe.utils.escape_html(row.item_name)).removeClass('text-muted');
				});
			}
		}, 200);
		sku_field.$input.on('change', commit);
		sku_field.$input.on('awesomplete-selectcomplete', commit);
		row._sku_field = sku_field;

		const $q = $('<input type="number" class="form-control input-xs eso-cell-input" min="0">');
		if (flt(row.qty)) $q.val(flt(row.qty));
		$row.find('.cell-qty').append($q);
		$q.on('input change', () => { row.qty = flt($q.val()); });

		$row.find('.btn-del-row').on('click', () => {
			const i = me.freebies.indexOf(row);
			if (i > -1) me.freebies.splice(i, 1);
			$row.remove();
		});

		if (data) {
			if (data.item_name) $row.find('.cell-name').html(frappe.utils.escape_html(data.item_name)).removeClass('text-muted');
			if (data.item_code) sku_field.set_value(data.item_code);
		}
		return row;
	}

	toggle_freebie_po() {
		const on = cint(this.f_freebie_po.get_value());
		this.wrapper.find('.eso-ordered-products').toggle(!on);
		this.wrapper.find('.eso-freebies-title').text(on ? __('Freebie Items (Entire PO)') : __('Freebies'));
	}

	// ---- recent orders (mirrors the offline entry page) --------------------
	load_recent_orders() {
		const me = this;
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Sales Order',
				filters: { custom_channel: 'E-com' },
				fields: ['name', 'customer', 'customer_name', 'custom_po_number', 'po_no',
					'grand_total', 'custom_workflow_status', 'transaction_date', 'custom_dispatch_date'],
				order_by: 'creation desc',
				limit_page_length: 15,
			},
			callback: (r) => me.render_orders_list(r.message || []),
		});
	}

	render_orders_list(orders) {
		const $c = this.wrapper.find('.recent-orders-list').empty();
		if (!orders.length) {
			$c.html('<p class="text-muted text-center">No e-com sales orders yet</p>');
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const rows = orders.map((o) => `
			<tr class="order-row" data-name="${esc(o.name)}" style="cursor: pointer;">
				<td><span class="text-primary" style="font-weight: 500;">${esc(o.name)}</span></td>
				<td>${esc(o.customer_name || o.customer || '')}</td>
				<td>${esc(o.custom_po_number || o.po_no || '—')}</td>
				<td>${o.transaction_date ? frappe.datetime.str_to_user(o.transaction_date) : '—'}</td>
				<td>${o.custom_dispatch_date ? frappe.datetime.str_to_user(o.custom_dispatch_date) : '—'}</td>
				<td class="text-right">${format_currency(o.grand_total)}</td>
				<td>${esc(o.custom_workflow_status || '—')}</td>
			</tr>`).join('');
		$c.html(`
			<table class="table table-hover" style="font-size: 13px;">
				<thead style="background: var(--bg-color);">
					<tr>
						<th>Order #</th><th>Customer</th><th>PO No</th><th>Date</th>
						<th>Dispatch</th><th class="text-right">Grand Total</th><th>Status</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>`);
	}

	// ---- save --------------------------------------------------------------
	_valid_items() {
		return this.items.filter((r) => r.item_code && flt(r.qty) > 0);
	}
	_valid_freebies() {
		return this.freebies.filter((f) => f.item_code && flt(f.qty) > 0);
	}

	build_payload() {
		const freebie_po = cint(this.f_freebie_po.get_value());
		const valid_items = this._valid_items();
		const valid_freebies = this._valid_freebies();
		let items, freebies;
		if (freebie_po) {
			items = valid_freebies.map((f) => ({
				item_code: f.item_code, qty: flt(f.qty),
				custom_box: 0, custom_customer_mrp: 0, custom_selling_price: 0,
				margin_percent: 0, custom_gst_percent: 0,
			}));
			freebies = [];
		} else {
			items = valid_items.map((r) => ({
				item_code: r.item_code, qty: flt(r.qty), custom_box: flt(r.box),
				custom_customer_mrp: flt(r.mrp), custom_selling_price: flt(r.selling_price),
				margin_percent: flt(r.margin_percent), custom_gst_percent: flt(r.gst_percent),
			}));
			freebies = valid_freebies.map((f) => ({ item_code: f.item_code, item_name: f.item_name, qty: flt(f.qty) }));
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
		if (freebie_po && !this._valid_freebies().length) errs.push(__('Add at least one freebie item'));
		if (!freebie_po && !this._valid_items().length) errs.push(__('Add at least one SKU'));
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
	load_prefill(name, mode) {
		mode = mode || 'edit';
		frappe.call({
			method: 'alpinos.ecom_sales_order_api.get_ecom_so_entry_payload',
			args: { sales_order: name },
			freeze: true, freeze_message: __('Loading...'),
			callback: (r) => {
				const d = r.message;
				if (!d) return;
				// Duplicate: prefill only — leave editing null so save creates a NEW order.
				if (mode === 'duplicate') {
					this.editing = null;
					this.page.set_title(__('E-Com Sales Order Entry — Copy of {0}', [d.name]));
				} else {
					this.editing = d.name;
					this.page.set_title(__('E-Com Sales Order Entry — {0}', [d.name]));
				}
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

				this.items = [];
				this.freebies = [];
				this.wrapper.find('.eso-items-table tbody').empty();
				this.wrapper.find('.eso-freebies-table tbody').empty();
				(d.items || []).forEach((it) => this.add_item_row({
					item_code: it.item_code, item_name: it.item_name, qty: flt(it.qty),
					box: flt(it.box), box_factor: 0, mrp: flt(it.mrp),
					margin_percent: flt(it.margin_percent), gst_percent: flt(it.gst_percent),
					selling_price: flt(it.custom_selling_price),
				}));
				(d.freebies || []).forEach((f) => this.add_freebie_row({
					item_code: f.item_code, item_name: f.item_name, qty: flt(f.qty),
				}));
				if (!this.items.length) this.add_item_row();
				this.render_total();
				this.toggle_freebie_po();
			},
		});
	}

	clear_form() {
		this.editing = null;
		this._site_manual = false;
		this.items = [];
		this.freebies = [];
		this.wrapper.find('.eso-items-table tbody').empty();
		this.wrapper.find('.eso-freebies-table tbody').empty();
		this.page.set_title(__('E-Com Sales Order Entry'));
		[
			this.f_customer, this.f_customer_type, this.f_appointment, this.f_grn, this.f_partial,
			this.f_gst_excl, this.f_site, this.f_bill_gstin, this.f_ship_gstin, this.f_bill_addr,
			this.f_ship_addr, this.f_po_no, this.f_po_date, this.f_po_expiry, this.f_delivery_by,
			this.f_freebie_po,
		].forEach((f) => f && f.set_value(''));
		this.f_dispatch.set_value(frappe.datetime.get_today());
		this.add_item_row();
		this.render_total();
		this.toggle_freebie_po();
	}
}
