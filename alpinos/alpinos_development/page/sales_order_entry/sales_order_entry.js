frappe.pages['sales-order-entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Sales Order Entry',
		single_column: true
	});

	page.main.html(frappe.render_template('sales_order_entry'));

	new SalesOrderEntry(page);
};

class SalesOrderEntry {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.items = [];
		this.freebies = [];
		this.scheme_items = [];
		this._box_cache = {};
		this.setup();
	}

	setup() {
		this.make_header_fields();
		this.make_item_table();
		this.make_other_details();
		this.make_totals();
		this.make_actions();
		this.bind_events();
		this.load_recent_orders();
	}

	make_header_fields() {
		let me = this;
		let header = this.wrapper.find('.so-header');

		this.customer_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Customer', label: 'Customer', fieldname: 'customer', reqd: 1 },
			parent: header.find('.field-customer'),
			render_input: true
		});

		// Bind customer change to auto-fetch order type
		let fetch_order_type = function() {
			setTimeout(() => {
				let customer = me.customer_field.get_value();
				if (customer) {
					frappe.db.get_value('Customer', customer, 'custom_order_type', function(r) {
						if (r && r.custom_order_type) {
							me.order_type_field.set_value(r.custom_order_type);
						}
					});
				}
			}, 300);
		};
		this.customer_field.$input.on('change', fetch_order_type);
		this.customer_field.$input.on('awesomplete-selectcomplete', fetch_order_type);

		this.order_type_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Select', options: '\nGT\nMT\nGYM & NUTRITION\nHoReCa', label: 'Customer Type', fieldname: 'order_type', reqd: 1 },
			parent: header.find('.field-order-type'),
			render_input: true
		});

		this.delivery_date_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', label: 'Delivery Date', fieldname: 'delivery_date' },
			parent: header.find('.field-delivery-date'),
			render_input: true
		});

		this.billing_address_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Address', label: 'Billing Address', fieldname: 'billing_address' },
			parent: header.find('.field-billing-address'),
			render_input: true
		});

		this.shipping_address_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Address', label: 'Shipping Address', fieldname: 'shipping_address' },
			parent: header.find('.field-shipping-address'),
			render_input: true
		});

		const get_customer_address_query = () => ({
			query: "erpnext.controllers.queries.address_query",
			filters: {
				link_doctype: "Customer",
				link_name: me.customer_field.get_value()
			}
		});
		this.billing_address_field.get_query = get_customer_address_query;
		this.shipping_address_field.get_query = get_customer_address_query;
	}

	make_item_table() {
		this.add_item_row();
	}

	_make_item_link_field(parent, fieldname) {
		let field = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Link',
				options: 'Item',
				fieldname: fieldname
			},
			parent: parent,
			render_input: true,
			only_input: true
		});
		if (field.$input) {
			field.$input.css('min-width', '140px');
		}
		// Dropdown styling handled via CSS in template
		return field;
	}

	add_item_row(data) {
		let idx = this.items.length;
		let row_data = data || { item_code: '', item_name: '', item_image: '', qty: 0, box: 0, mrp: 0, flat_discount: 0, offer: '', additional_discount: 0, amount: 0 };
		this.items.push(row_data);

		let $tbody = this.wrapper.find('.items-table tbody');
		let $row = $(`
			<tr data-idx="${idx}">
				<td class="text-center" style="vertical-align: middle;">${idx + 1}</td>
				<td class="item-image text-center" style="vertical-align: middle;"><img class="item-image-preview" src="" style="max-height: 36px; max-width: 70px; display: none;" /></td>
				<td class="item-sku"></td>
				<td class="item-name"><span class="item-name-text text-muted" style="font-size: 12px;">-</span></td>
				<td class="item-qty"></td>
				<td class="item-box"></td>
				<td class="item-mrp"></td>
				<td class="item-flat-discount"></td>
				<td class="item-offer"></td>
				<td class="item-additional-discount"></td>
				<td class="item-amount text-right font-weight-bold" style="vertical-align: middle;">0.00</td>
				<td class="text-center" style="vertical-align: middle;"><button class="btn btn-xs btn-danger remove-row"><i class="fa fa-trash"></i></button></td>
			</tr>
		`);
		$tbody.append($row);

		let me = this;

		// SKU field with improved search
		let sku_field = this._make_item_link_field($row.find('.item-sku'), `item_code_${idx}`);
		sku_field.$input.on('change', function() {
			setTimeout(() => {
				let val = sku_field.get_value();
				me.items[idx].item_code = val;
				if (val) {
					me.on_item_select(idx, val, $row);
				}
			}, 200);
		});
		// Also listen for awesomplete select
		if (sku_field.$input) {
			sku_field.$input.on('awesomplete-selectcomplete', function() {
				setTimeout(() => {
					let val = sku_field.get_value();
					me.items[idx].item_code = val;
					if (val) {
						me.on_item_select(idx, val, $row);
					}
				}, 200);
			});
		}
		row_data._sku_field = sku_field;

		// Qty
		let qty_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `qty_${idx}` },
			parent: $row.find('.item-qty'),
			render_input: true,
			only_input: true
		});
		qty_field.$input && qty_field.$input.css('width', '70px');
		qty_field.$input.on('change', function() {
			me.items[idx].qty = flt(qty_field.get_value());
			me.calc_box_from_qty(idx, $row);
			me.calc_row_amount(idx, $row);
		});
		row_data._qty_field = qty_field;

		// Box
		let box_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `box_${idx}` },
			parent: $row.find('.item-box'),
			render_input: true,
			only_input: true
		});
		box_field.$input && box_field.$input.css('width', '70px');
		box_field.$input.on('change', function() {
			me.items[idx].box = flt(box_field.get_value());
			me.calc_qty_from_box(idx, $row);
			me.calc_row_amount(idx, $row);
		});
		row_data._box_field = box_field;

		// MRP
		let mrp_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Currency', fieldname: `mrp_${idx}` },
			parent: $row.find('.item-mrp'),
			render_input: true,
			only_input: true
		});
		mrp_field.$input && mrp_field.$input.css('width', '90px');
		mrp_field.$input.on('change', function() {
			me.items[idx].mrp = flt(mrp_field.get_value());
			me.calc_row_amount(idx, $row);
		});
		row_data._mrp_field = mrp_field;

		// Flat Discount %
		let flat_disc_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `flat_discount_${idx}`, description: '%' },
			parent: $row.find('.item-flat-discount'),
			render_input: true,
			only_input: true
		});
		flat_disc_field.$input && flat_disc_field.$input.css('width', '80px');
		flat_disc_field.$input.on('change', function() {
			me.items[idx].flat_discount = flt(flat_disc_field.get_value());
			me.calc_row_amount(idx, $row);
		});
		row_data._flat_disc_field = flat_disc_field;

		// Offer
		let offer_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `offer_${idx}` },
			parent: $row.find('.item-offer'),
			render_input: true,
			only_input: true
		});
		offer_field.$input && offer_field.$input.css('width', '80px');
		offer_field.$input.on('change', function() {
			me.items[idx].offer = offer_field.get_value();
		});
		row_data._offer_field = offer_field;

		// Additional Discount
		let add_disc_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `additional_discount_${idx}`, description: '%' },
			parent: $row.find('.item-additional-discount'),
			render_input: true,
			only_input: true
		});
		add_disc_field.$input && add_disc_field.$input.css('width', '80px');
		add_disc_field.$input.on('change', function() {
			me.items[idx].additional_discount = flt(add_disc_field.get_value());
			me.calc_row_amount(idx, $row);
		});
		row_data._add_disc_field = add_disc_field;

		// Set values if data was passed
		if (data && data.item_code) {
			sku_field.set_value(data.item_code);
			if (data.qty) qty_field.set_value(data.qty);
			if (data.box) box_field.set_value(data.box);
			if (data.mrp) mrp_field.set_value(data.mrp);
			if (data.flat_discount) flat_disc_field.set_value(data.flat_discount);
			if (data.offer) offer_field.set_value(data.offer);
			if (data.additional_discount) add_disc_field.set_value(data.additional_discount);
			if (data.item_name) {
				$row.find('.item-name-text').text(data.item_name).removeClass('text-muted');
			}
			if (data.item_image) {
				this._set_row_image($row, data.item_image);
			}
			if (data.amount) {
				$row.find('.item-amount').text(format_currency(data.amount));
			}
		}
	}

	on_item_select(idx, item_code, $row) {
		let me = this;
		let customer = this.customer_field.get_value();

		// Fetch item name + image
		frappe.db.get_value('Item', item_code, ['item_name', 'image'], function(r) {
			if (r) {
				if (r.item_name) {
					me.items[idx].item_name = r.item_name;
					$row.find('.item-name-text').text(r.item_name).removeClass('text-muted');
				}
				me.items[idx].item_image = r.image || '';
				me._set_row_image($row, r.image || '');
			}
		});

		// Fetch MRP from Customer master
		if (customer) {
			frappe.call({
				method: 'alpinos.sales_order_api.get_customer_item_mrp',
				args: { customer: customer, item_code: item_code },
				callback: function(r) {
					if (r.message) {
						me.items[idx].mrp = flt(r.message);
						me.items[idx]._mrp_field.set_value(r.message);
						me.calc_row_amount(idx, $row);
					}
				}
			});
		}

		// Fetch Box conversion factor
		frappe.call({
			method: 'alpinos.sales_order_api.get_box_conversion_factor',
			args: { item_code: item_code },
			callback: function(r) {
				if (r.message) {
					me._box_cache[item_code] = r.message;
					// If qty already set, recalculate box
					if (me.items[idx].qty) {
						me.calc_box_from_qty(idx, $row);
					}
				}
			}
		});
	}

	calc_box_from_qty(idx, $row) {
		let item = this.items[idx];
		let cf = this._box_cache[item.item_code];
		if (cf) {
			item.box = Math.ceil(flt(item.qty) / flt(cf));
			item.qty = flt(item.box * cf, 2);
			item._box_field.set_value(item.box);
			item._qty_field.set_value(item.qty);
		}
	}

	calc_qty_from_box(idx, $row) {
		let item = this.items[idx];
		let cf = this._box_cache[item.item_code];
		if (cf) {
			item.box = Math.ceil(flt(item.box));
			item.qty = flt(item.box * cf, 2);
			item._box_field.set_value(item.box);
			item._qty_field.set_value(item.qty);
		}
	}

	calc_row_amount(idx, $row) {
		let item = this.items[idx];
		let qty = flt(item.qty);
		let gross = flt(item.mrp) * qty;
		let flat_disc_amt = gross * flt(item.flat_discount) / 100;
		let after_flat = gross - flat_disc_amt;
		let additional_disc_amt = after_flat * flt(item.additional_discount) / 100;
		item.amount = after_flat - additional_disc_amt;
		if (item.amount < 0) item.amount = 0;
		item.rate = qty ? flt(item.amount / qty, 2) : 0;
		$row.find('.item-amount').text(format_currency(item.amount));
		this.calc_totals();
	}

	_set_row_image($row, image_url) {
		const $img = $row.find('.item-image-preview');
		if (image_url) {
			$img.attr('src', image_url).show();
		} else {
			$img.hide();
		}
	}

	calc_totals() {
		let total_qty = 0, total_amount = 0;
		this.items.forEach(item => {
			total_qty += flt(item.qty);
			total_amount += flt(item.amount);
		});

		let cash_disc_pct = flt(this.cash_discount_field ? this.cash_discount_field.get_value() : 0);
		let cash_disc_amt = total_amount * cash_disc_pct / 100;
		let grand_total = total_amount - cash_disc_amt;

		this.wrapper.find('.total-qty').text(total_qty);
		this.wrapper.find('.total-amount').text(format_currency(total_amount));
		this.wrapper.find('.cash-disc-amount').text(format_currency(cash_disc_amt));
		this.wrapper.find('.grand-total').text(format_currency(grand_total));
	}

	make_other_details() {
		let section = this.wrapper.find('.other-details-section');

		this.cash_discount_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Percent', label: 'Cash Discount (%)', fieldname: 'cash_discount', default: 0 },
			parent: section.find('.field-cash-discount'),
			render_input: true
		});
		this.cash_discount_field.$input.on('change', () => this.calc_totals());

		this.additional_units_damage_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Check', label: 'Additional Units - Damage', fieldname: 'additional_units_damage' },
			parent: section.find('.field-additional-units-damage'),
			render_input: true
		});
		this.additional_units_damage_field.$input.on('change', () => {
			let checked = this.additional_units_damage_field.get_value();
			this.wrapper.find('.scheme-items-section').toggle(!!checked);
		});
	}

	make_totals() {
		// Already rendered in template
	}

	make_actions() {
		let me = this;

		this.page.set_primary_action('Create Sales Order', function() {
			me.create_sales_order();
		}, 'fa fa-check');

		this.page.set_secondary_action('Clear', function() {
			me.clear_form();
		});
	}

	bind_events() {
		let me = this;

		// Add Row button
		this.wrapper.find('.btn-add-row').on('click', function() {
			me.add_item_row();
		});

		// Remove Row
		this.wrapper.on('click', '.remove-row', function() {
			let idx = $(this).closest('tr').data('idx');
			me.items.splice(idx, 1);
			me.redraw_items_table();
		});

		// Add Freebie Row
		this.wrapper.find('.btn-add-freebie').on('click', function() {
			me.add_freebie_row();
		});

		// Remove Freebie
		this.wrapper.on('click', '.remove-freebie', function() {
			let idx = $(this).closest('tr').data('idx');
			me.freebies.splice(idx, 1);
			me.redraw_freebies_table();
		});

		// Add Scheme Row
		this.wrapper.find('.btn-add-scheme').on('click', function() {
			me.add_scheme_row();
		});

		// Remove Scheme
		this.wrapper.on('click', '.remove-scheme', function() {
			let idx = $(this).closest('tr').data('idx');
			me.scheme_items.splice(idx, 1);
			me.redraw_scheme_table();
		});
	}

	add_freebie_row(data) {
		let idx = this.freebies.length;
		let row_data = data || { item_code: '', item_name: '', qty: 0, remarks: '' };
		this.freebies.push(row_data);

		let $tbody = this.wrapper.find('.freebies-table tbody');
		let $row = $(`
			<tr data-idx="${idx}">
				<td class="freebie-item"></td>
				<td class="freebie-name"><span class="text-muted">-</span></td>
				<td class="freebie-qty"></td>
				<td class="freebie-remarks"></td>
				<td class="text-center"><button class="btn btn-xs btn-danger remove-freebie"><i class="fa fa-trash"></i></button></td>
			</tr>
		`);
		$tbody.append($row);
		let me = this;

		let item_field = this._make_item_link_field($row.find('.freebie-item'), `freebie_item_${idx}`);
		item_field.$input.on('change', function() {
			setTimeout(() => {
				let val = item_field.get_value();
				me.freebies[idx].item_code = val;
				if (val) {
					frappe.db.get_value('Item', val, 'item_name', function(r) {
						if (r) {
							me.freebies[idx].item_name = r.item_name;
							$row.find('.freebie-name span').text(r.item_name).removeClass('text-muted');
						}
					});
				}
			}, 200);
		});

		let qty_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `freebie_qty_${idx}` },
			parent: $row.find('.freebie-qty'),
			render_input: true,
			only_input: true
		});
		qty_field.$input && qty_field.$input.css('width', '70px');
		qty_field.$input.on('change', function() { me.freebies[idx].qty = flt(qty_field.get_value()); });

		let remarks_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `freebie_remarks_${idx}` },
			parent: $row.find('.freebie-remarks'),
			render_input: true,
			only_input: true
		});
		remarks_field.$input.on('change', function() { me.freebies[idx].remarks = remarks_field.get_value(); });

		if (data && data.item_code) {
			item_field.set_value(data.item_code);
			if (data.qty) qty_field.set_value(data.qty);
			if (data.remarks) remarks_field.set_value(data.remarks);
			if (data.item_name) {
				$row.find('.freebie-name span').text(data.item_name).removeClass('text-muted');
			}
		}
	}

	add_scheme_row(data) {
		let idx = this.scheme_items.length;
		let row_data = data || { item_code: '', item_name: '', qty: 0, scheme: '', previous_order_id: '' };
		this.scheme_items.push(row_data);

		let $tbody = this.wrapper.find('.scheme-table tbody');
		let $row = $(`
			<tr data-idx="${idx}">
				<td class="scheme-item"></td>
				<td class="scheme-name"><span class="text-muted">-</span></td>
				<td class="scheme-qty"></td>
				<td class="scheme-scheme"></td>
				<td class="scheme-prev-order"></td>
				<td class="text-center"><button class="btn btn-xs btn-danger remove-scheme"><i class="fa fa-trash"></i></button></td>
			</tr>
		`);
		$tbody.append($row);
		let me = this;

		let item_field = this._make_item_link_field($row.find('.scheme-item'), `scheme_item_${idx}`);
		item_field.$input.on('change', function() {
			setTimeout(() => {
				let val = item_field.get_value();
				me.scheme_items[idx].item_code = val;
				if (val) {
					frappe.db.get_value('Item', val, 'item_name', function(r) {
						if (r) {
							me.scheme_items[idx].item_name = r.item_name;
							$row.find('.scheme-name span').text(r.item_name).removeClass('text-muted');
						}
					});
				}
			}, 200);
		});

		let qty_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `scheme_qty_${idx}` },
			parent: $row.find('.scheme-qty'),
			render_input: true,
			only_input: true
		});
		qty_field.$input && qty_field.$input.css('width', '70px');
		qty_field.$input.on('change', function() { me.scheme_items[idx].qty = flt(qty_field.get_value()); });

		let scheme_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `scheme_val_${idx}` },
			parent: $row.find('.scheme-scheme'),
			render_input: true,
			only_input: true
		});
		scheme_field.$input.on('change', function() { me.scheme_items[idx].scheme = scheme_field.get_value(); });

		let prev_order_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `prev_order_${idx}` },
			parent: $row.find('.scheme-prev-order'),
			render_input: true,
			only_input: true
		});
		prev_order_field.$input.on('change', function() { me.scheme_items[idx].previous_order_id = prev_order_field.get_value(); });

		if (data && data.item_code) {
			item_field.set_value(data.item_code);
			if (data.qty) qty_field.set_value(data.qty);
			if (data.scheme) scheme_field.set_value(data.scheme);
			if (data.previous_order_id) prev_order_field.set_value(data.previous_order_id);
			if (data.item_name) {
				$row.find('.scheme-name span').text(data.item_name).removeClass('text-muted');
			}
		}
	}

	redraw_items_table() {
		this.wrapper.find('.items-table tbody').empty();
		let old_items = this.items.slice();
		this.items = [];
		old_items.forEach(item => this.add_item_row(item));
		this.calc_totals();
	}

	redraw_freebies_table() {
		this.wrapper.find('.freebies-table tbody').empty();
		let old = this.freebies.slice();
		this.freebies = [];
		old.forEach(f => this.add_freebie_row(f));
	}

	redraw_scheme_table() {
		this.wrapper.find('.scheme-table tbody').empty();
		let old = this.scheme_items.slice();
		this.scheme_items = [];
		old.forEach(s => this.add_scheme_row(s));
	}

	create_sales_order() {
		let me = this;
		let customer = this.customer_field.get_value();
		let order_type = this.order_type_field.get_value();
		let delivery_date = this.delivery_date_field.get_value();
		let billing_address = this.billing_address_field.get_value();
		let shipping_address = this.shipping_address_field.get_value();

		if (!customer) return frappe.throw('Please select a Customer');
		if (!order_type) return frappe.throw('Please select Customer Type');

		let valid_items = this.items.filter(i => i.item_code && flt(i.qty) > 0);
		if (!valid_items.length) return frappe.throw('Please add at least one item');

		let items = valid_items.map(item => ({
			item_code: item.item_code,
			qty: item.qty,
			rate: item.rate || 0,
			delivery_date: delivery_date,
			custom_box: item.box,
			custom_customer_mrp: item.mrp,
			custom_flat_discount: item.flat_discount,
			custom_offer: item.offer,
			custom_additional_discount: item.additional_discount
		}));

		let freebies = this.freebies.filter(f => f.item_code).map(f => ({
			item_code: f.item_code,
			qty: f.qty,
			remarks: f.remarks
		}));

		let scheme_items = this.scheme_items.filter(s => s.item_code).map(s => ({
			item_code: s.item_code,
			qty: s.qty,
			scheme: s.scheme,
			previous_order_id: s.previous_order_id
		}));

		frappe.call({
			method: 'alpinos.sales_order_api.create_sales_order',
			args: {
				customer: customer,
				order_type: order_type,
				company: frappe.defaults.get_user_default('company'),
				delivery_date: delivery_date,
				billing_address: billing_address,
				shipping_address: shipping_address,
				items: items,
				cash_discount: flt(me.cash_discount_field.get_value()),
				freebies: freebies,
				scheme_items: scheme_items,
				additional_units_damage: me.additional_units_damage_field.get_value() ? 1 : 0,
				submit_now: 1
			},
			freeze: true,
			freeze_message: 'Creating Sales Order...',
			callback: function(r) {
				if (r.message && r.message.name) {
					frappe.show_alert({
						message: `Sales Order <b>${r.message.name}</b> created successfully!`,
						indicator: 'green'
					}, 5);
					frappe.set_route('Form', 'Sales Order', r.message.name);
				}
			}
		});
	}

	load_recent_orders() {
		let me = this;
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Sales Order',
				fields: ['name', 'customer', 'customer_name', 'order_type', 'grand_total', 'status', 'transaction_date', 'delivery_date'],
				order_by: 'creation desc',
				limit_page_length: 20
			},
			callback: function(r) {
				if (r.message) {
					me.render_orders_list(r.message);
				}
			}
		});
	}

	render_orders_list(orders) {
		let $container = this.wrapper.find('.recent-orders-list');
		$container.empty();

		if (!orders || !orders.length) {
			$container.html('<p class="text-muted text-center">No sales orders yet</p>');
			return;
		}

		let status_colors = {
			'Draft': 'orange',
			'To Deliver and Bill': 'blue',
			'To Bill': 'blue',
			'To Deliver': 'blue',
			'Completed': 'green',
			'Cancelled': 'red',
			'Closed': 'grey',
			'On Hold': 'orange',
			'Overdue': 'red'
		};

		let rows = orders.map(o => {
			let color = status_colors[o.status] || 'grey';
			return `
				<tr class="order-row" data-name="${o.name}" style="cursor: pointer;">
					<td><a href="/app/sales-order/${o.name}" target="_blank" style="font-weight: 500;">${o.name}</a></td>
					<td>${o.customer_name || o.customer}</td>
					<td>${o.order_type || '-'}</td>
					<td>${frappe.datetime.str_to_user(o.transaction_date)}</td>
					<td>${o.delivery_date ? frappe.datetime.str_to_user(o.delivery_date) : '-'}</td>
					<td class="text-right">${format_currency(o.grand_total)}</td>
					<td><span class="indicator-pill ${color}">${o.status}</span></td>
				</tr>
			`;
		}).join('');

		$container.html(`
			<table class="table table-hover" style="font-size: 13px;">
				<thead style="background: var(--bg-color);">
					<tr>
						<th>Order #</th>
						<th>Customer</th>
						<th>Type</th>
						<th>Date</th>
						<th>Delivery</th>
						<th class="text-right">Grand Total</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		`);
	}

	clear_form() {
		this.customer_field.set_value('');
		this.order_type_field.set_value('');
		this.delivery_date_field.set_value('');
		this.billing_address_field && this.billing_address_field.set_value('');
		this.shipping_address_field && this.shipping_address_field.set_value('');
		this.items = [];
		this.freebies = [];
		this.scheme_items = [];
		this.wrapper.find('.items-table tbody').empty();
		this.wrapper.find('.freebies-table tbody').empty();
		this.wrapper.find('.scheme-table tbody').empty();
		this.add_item_row();
		this.calc_totals();
	}
}
