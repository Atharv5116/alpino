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
		this.additional_units_items = [];
		this._box_cache = {};
		this.setup();
	}

	setup() {
		this.default_company = this._get_default_company();
		this.make_header_fields();
		this.make_item_table();
		this.make_other_details();
		this.make_totals();
		this.make_actions();
		this.bind_events();
		this.load_recent_orders();
		this.maybe_prefill_from_quotation();
	}

	_get_default_company() {
		const preferred = 'Alpino Health Foods Pvt. Ltd.';
		if (preferred) return preferred;
		// Frappe default key is usually "Company" (capital C); keep fallbacks for older setups.
		return (
			frappe.defaults.get_user_default('Company') ||
			frappe.defaults.get_user_default('company') ||
			(frappe.boot && frappe.boot.sysdefaults && frappe.boot.sysdefaults.company) ||
			''
		);
	}

	maybe_prefill_from_quotation() {
		let ro = frappe.route_options || {};
		if (!ro.from_quotation) return;
		const qname = ro.from_quotation;
		delete ro.from_quotation;
		frappe.route_options = ro;
		this.prefill_from_quotation(qname);
	}

	prefill_from_quotation(qname) {
		let me = this;
		frappe.call({
			method: 'alpinos.quotation_api.get_sales_order_entry_payload_from_quotation',
			args: { quotation: qname },
			freeze: true,
			freeze_message: __('Loading quotation...'),
			callback(r) {
				if (!r.message) return;
				me._apply_quotation_prefill(r.message);
			},
		});
	}

	_apply_quotation_prefill(d) {
		let me = this;

		me.customer_field.set_value(d.customer);
		me.order_type_field.set_value(d.order_type || '');
		me.delivery_date_field.set_value(d.delivery_date || '');
		me.cash_discount_field.set_value(flt(d.custom_cash_discount));

		frappe.call({
			method: 'alpinos.sales_order_offline_buyer.sync_offline_buyer_master_addresses',
			args: { customer: d.customer },
			callback(sr) {
				const ad = sr.message || {};
				const billing = d.billing_address || ad.default_billing || '';
				const shipping = d.shipping_address || ad.default_shipping || '';
				me._load_address_options(d.customer, { billing, shipping });
					me._refresh_tax_template();
				me._prefill_quotation_after_addresses(d);
			},
		});
	}

	_prefill_quotation_after_addresses(d) {
		let me = this;
		const codes = [...new Set((d.items || []).map((x) => x.item_code).filter(Boolean))];
		const hydrate_and_draw = () => {
			me.items = [];
			me.wrapper.find('.items-table tbody').empty();
			const rows = d.items || [];
			if (!rows.length) me.add_item_row();
			else {
				rows.forEach((it) => me.add_item_row(it));
				rows.forEach((it, idx) => {
					me.items[idx].rate = flt(it.rate);
					me.items[idx].amount = flt(it.amount);
					me.items[idx].custom_item_tax = flt(it.custom_item_tax);
					me.items[idx].description = it.description || '';
					me.items[idx].warehouse = it.warehouse || '';
					me.items[idx].delivery_date = it.delivery_date || d.delivery_date || '';
					const $r = me.wrapper.find('.items-table tbody tr').eq(idx);
					$r.find('.item-amount').text(format_currency(me.items[idx].amount));
					if (it.item_name) {
						$r.find('.item-name-text').text(it.item_name).removeClass('text-muted');
					}
					if (it.image) {
						let url = it.image;
						if (url.indexOf('http') !== 0 && url.charAt(0) === '/') {
							url = window.location.origin + url;
						}
						me.items[idx].item_image = url;
						me._set_row_image($r, url);
					}
				});
			}

			me.freebies = [];
			me.scheme_items = [];
			me.additional_units_items = [];
			me.wrapper.find('.freebies-table tbody').empty();
			me.wrapper.find('.scheme-table tbody').empty();
			me.wrapper.find('.additional-units-table tbody').empty();

			(d.freebies || []).forEach((f) => me.add_freebie_row(f));
			(d.scheme_items || []).forEach((s) => me.add_scheme_row(s));
			me.additional_units_damage_field.set_value(d.additional_units_damage ? 1 : 0);
			if (d.additional_units_damage) {
				me.wrapper.find('.additional-units-section').toggle(true);
				(d.additional_units_items || []).forEach((u) => me.add_additional_units_row(u));
			} else {
				me.wrapper.find('.additional-units-section').toggle(false);
			}

			me.calc_totals();
			frappe.show_alert({
				message: __('Loaded from quotation {0}', [d.quotation]),
				indicator: 'green',
			});
		};

		if (!codes.length) {
			hydrate_and_draw();
			return;
		}
		let left = codes.length;
		codes.forEach((item_code) => {
			frappe.call({
				method: 'alpinos.sales_order_api.get_box_conversion_factor',
				args: { item_code: item_code },
				callback(rr) {
					if (rr.message) me._box_cache[item_code] = rr.message;
					left--;
					if (left <= 0) hydrate_and_draw();
				},
			});
		});
	}

	make_header_fields() {
		let me = this;
		let header = this.wrapper.find('.so-header');

		this.customer_field = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Link',
				options: 'Customer',
				label: 'Customer',
				fieldname: 'customer',
				reqd: 1,
				get_query: () => ({
					query: 'alpinos.sales_order_offline_buyer.sales_order_customer_query',
				}),
			},
			parent: header.find('.field-customer'),
			render_input: true
		});

		this.company_field = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Link',
				options: 'Company',
				label: 'Company',
				fieldname: 'company',
				reqd: 1,
			},
			parent: header.find('.field-company'),
			render_input: true
		});
		this.company_field.set_value(this.default_company || this._get_default_company());
		if (this.company_field.$input) {
			this.company_field.$input.on('change awesomplete-selectcomplete', () => me._refresh_tax_template());
		}
		// Set address field value AND show its human-readable label in the input.
		// Guard: only set_value if the address name is actually in opts (linked to Customer).
		// Calling set_value with an unlinked address name triggers Frappe's "not found" error.
		me._set_address_display = function(field, addr_name, opts) {
			if (!field) return;
			if (!opts || !opts.length) return;
			const opt = opts.find(o => o.value === addr_name);
			const use = opt || opts[0]; // fallback to first available address
			if (!use) return;
			field.set_value(use.value);
			if (field.$input) field.$input.val(use.label);
		};

		// Map an Autocomplete's display label back to its internal Address document name
		me._get_actual_address = function(field) {
			if (!field) return '';
			let val = field.get_value();
			if (!val) return '';
			if (field._opts) {
				let opt = field._opts.find(o => o.label === val || o.value === val);
				if (opt) return opt.value;
			}
			return val;
		};

		// Load address Autocomplete options for a customer and optionally pre-select defaults
		me._load_address_options = function(customer, defaults) {
			if (!customer) {
				me.billing_address_field && me.billing_address_field.set_data([]);
				me.shipping_address_field && me.shipping_address_field.set_data([]);
				return;
			}
			frappe.call({
				method: 'alpinos.sales_order_offline_buyer.get_customer_addresses_for_display',
				args: { customer },
				callback(r) {
					const opts = (r.message || []).map(a => ({ value: a.name, label: a.display }));
					if (me.billing_address_field) {
						me.billing_address_field._opts = opts;
						me.billing_address_field.set_data(opts);
					}
					if (me.shipping_address_field) {
						me.shipping_address_field._opts = opts;
						me.shipping_address_field.set_data(opts);
					}
					if (defaults) {
						me._set_address_display(me.billing_address_field, defaults.billing || '', opts);
						me._set_address_display(me.shipping_address_field, defaults.shipping || '', opts);
					}
				},
			});
		};

		// Bind customer change to auto-fetch order type + addresses
		let on_customer_change = function() {
			setTimeout(() => {
				let customer = me.customer_field.get_value();
				if (customer) {
					frappe.call({
						method: 'alpinos.sales_order_offline_buyer.get_offline_buyer_for_customer',
						args: { customer: customer },
						callback: function(r) {
							if (r.message && r.message.customer_type) {
								me.order_type_field.set_value(r.message.customer_type);
							}
						}
					});
					frappe.call({
						method: 'alpinos.sales_order_offline_buyer.sync_offline_buyer_master_addresses',
						args: { customer: customer },
						callback(r2) {
							const ad = r2.message || {};
							me._load_address_options(customer, {
								billing: ad.default_billing || '',
								shipping: ad.default_shipping || '',
							});
							me._refresh_tax_template();
						},
					});
				} else {
					me.billing_address_field && me.billing_address_field.set_value('');
					me.shipping_address_field && me.shipping_address_field.set_value('');
					me._load_address_options(null);
					if (me.tax_template_field) me.tax_template_field.set_value('');
				}
			}, 300);
		};
		this.customer_field.$input.on('change', on_customer_change);
		this.customer_field.$input.on('awesomplete-selectcomplete', on_customer_change);

		this.order_type_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Offline Buyer Customer Type', label: 'Customer Type', fieldname: 'order_type', reqd: 1 },
			parent: header.find('.field-order-type'),
			render_input: true
		});

		this.delivery_date_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', label: 'Delivery Date', fieldname: 'delivery_date' },
			parent: header.find('.field-delivery-date'),
			render_input: true
		});

		this.billing_address_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Autocomplete', label: 'Billing Address', fieldname: 'billing_address' },
			parent: header.find('.field-billing-address'),
			render_input: true
		});

		this.shipping_address_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Autocomplete', label: 'Shipping Address', fieldname: 'shipping_address' },
			parent: header.find('.field-shipping-address'),
			render_input: true
		});

		this.tax_template_field = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Data',
				label: 'Tax Template (Auto)',
				fieldname: 'taxes_and_charges',
				read_only: 1,
			},
			parent: header.find('.field-tax-template'),
			render_input: true
		});
		this.tax_template_field.$input && this.tax_template_field.$input.prop('readonly', true);

		this._refresh_tax_template = function() {
			const customer = me.customer_field.get_value();
			const billing = me._get_actual_address(me.billing_address_field);
			const shipping = me._get_actual_address(me.shipping_address_field);
			if (!customer || !billing) {
				me.tax_template_field && me.tax_template_field.set_value('');
				return;
			}
			frappe.call({
				method: 'alpinos.sales_order_api.get_tax_template_for_sales_order',
				args: {
					customer: customer,
					company: (me.company_field && me.company_field.get_value()) || me.default_company || me._get_default_company(),
					billing_address: billing,
					shipping_address: shipping,
				},
				callback(r) {
					const x = r.message || {};
					me.tax_template_field && me.tax_template_field.set_value(x.taxes_and_charges || '');
				},
			});
		};

		if (this.billing_address_field && this.billing_address_field.$input) {
			this.billing_address_field.$input.on('change awesomplete-selectcomplete', () => me._refresh_tax_template());
		}
		if (this.shipping_address_field && this.shipping_address_field.$input) {
			this.shipping_address_field.$input.on('change awesomplete-selectcomplete', () => me._refresh_tax_template());
		}
	}

	make_item_table() {
		this.add_item_row();
	}

	_make_item_link_field(parent, fieldname, filterType) {
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
		// Main order lines: all saleable variants (no customer filter on SKU). Other tables: any item.
		if (filterType === 'variants') {
			field.get_query = () => ({
				filters: {
					disabled: 0,
					is_sales_item: 1,
					variant_of: ['!=', ''],
				},
			});
		} else if (filterType === 'nonTemplates') {
			field.get_query = () => ({
				filters: {
					disabled: 0,
					has_variants: 0,
				},
			});
		}
		if (field.$input) {
			field.$input.css('min-width', '140px');
		}
		// Dropdown styling handled via CSS in template
		return field;
	}

	/**
	 * Link fields often commit the value on `awesomplete-selectcomplete` without a separate
	 * `change` event; order lines listen for both — do the same for secondary item grids.
	 */
	_bind_item_link_change(item_field, handler) {
		if (!item_field || !item_field.$input) {
			return;
		}
		const run = () => {
			setTimeout(handler, 200);
		};
		item_field.$input.on('change', run);
		item_field.$input.on('awesomplete-selectcomplete', run);
	}

	add_item_row(data) {
		let idx = this.items.length;
		let row_data = Object.assign(
			{
				item_code: '',
				item_name: '',
				item_image: '',
				qty: 0,
				box: 0,
				mrp: 0,
				gst_percent: 0,
				flat_discount: 0,
				offer: '',
				additional_discount: 0,
				amount: 0,
				rate: 0,
				custom_item_tax: 0,
				description: '',
				warehouse: '',
				delivery_date: '',
			},
			data || {}
		);
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
				<td class="item-gst"></td>
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
		let sku_field = this._make_item_link_field($row.find('.item-sku'), `item_code_${idx}`, 'variants');
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

		// GST % (read-only, from Item)
		let gst_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `gst_${idx}`, read_only: 1 },
			parent: $row.find('.item-gst'),
			render_input: true,
			only_input: true
		});
		gst_field.$input && gst_field.$input.css('width', '70px');
		gst_field.$input && gst_field.$input.prop('readonly', true);
		if (row_data.gst_percent) gst_field.set_value(row_data.gst_percent);
		row_data._gst_field = gst_field;

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
			df: { fieldtype: 'Float', fieldname: `offer_${idx}`, description: '%' },
			parent: $row.find('.item-offer'),
			render_input: true,
			only_input: true
		});
		offer_field.$input && offer_field.$input.css('width', '80px');
		offer_field.$input.on('change', function() {
			me.items[idx].offer = flt(offer_field.get_value());
			me.calc_row_amount(idx, $row);
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
			if (data.qty !== undefined && data.qty !== null) qty_field.set_value(data.qty);
			if (data.box !== undefined && data.box !== null) box_field.set_value(data.box);
			if (data.mrp !== undefined && data.mrp !== null && data.mrp !== '') {
				mrp_field.set_value(data.mrp);
			}
			if (data.flat_discount !== undefined && data.flat_discount !== null && data.flat_discount !== '') {
				flat_disc_field.set_value(data.flat_discount);
			}
			if (data.offer !== undefined && data.offer !== null) {
				offer_field.set_value(data.offer);
			}
			if (
				data.additional_discount !== undefined &&
				data.additional_discount !== null &&
				data.additional_discount !== ''
			) {
				add_disc_field.set_value(data.additional_discount);
			}
			if (data.item_name) {
				$row.find('.item-name-text').text(data.item_name).removeClass('text-muted');
			}
			if (data.item_image) {
				this._set_row_image($row, data.item_image);
			}
			if (data.amount !== undefined && data.amount !== null) {
				$row.find('.item-amount').text(format_currency(data.amount));
			}
		}
	}

	on_item_select(idx, item_code, $row) {
		let me = this;
		let customer = this.customer_field.get_value();

		// Fetch item name + image + GST %
		frappe.db.get_value('Item', item_code, ['item_name', 'image', 'custom_gst_percent'], function(r) {
			if (r) {
				if (r.item_name) {
					me.items[idx].item_name = r.item_name;
					$row.find('.item-name-text').text(r.item_name).removeClass('text-muted');
				}
				me.items[idx].item_image = r.image || '';
				me._set_row_image($row, r.image || '');
				me.items[idx].gst_percent = flt(r.custom_gst_percent);
				if (me.items[idx]._gst_field) me.items[idx]._gst_field.set_value(me.items[idx].gst_percent);
				me.calc_row_amount(idx, $row);
			}
		});

		// Pricing: if this SKU is on Offline Buyer Master for the customer → MRP + margin from master.
		// Otherwise → Customer Item MRP, else Item standard rate (user can edit row discounts).
		const apply_obm_pricing = (msg) => {
			me.items[idx].mrp = flt(msg.mrp);
			me.items[idx]._mrp_field.set_value(msg.mrp);
			const m = flt(msg.margin_percent || 0);
			me.items[idx].flat_discount = m;
			me.items[idx]._flat_disc_field.set_value(m > 0 ? m : '');
			me.items[idx].offer = '';
			me.items[idx]._offer_field.set_value('');
			me.items[idx].additional_discount = 0;
			me.items[idx]._add_disc_field.set_value('');
			me.calc_row_amount(idx, $row);
		};
		const clear_extra_discounts_and_recalc = () => {
			me.items[idx].offer = '';
			me.items[idx]._offer_field.set_value('');
			me.items[idx].additional_discount = 0;
			me.items[idx]._add_disc_field.set_value('');
			me.calc_row_amount(idx, $row);
		};
		const apply_mrp_only = (mrp_val) => {
			const m = flt(mrp_val);
			if (m > 0) {
				me.items[idx].mrp = m;
				me.items[idx]._mrp_field.set_value(m);
			} else {
				me.items[idx].mrp = 0;
				me.items[idx]._mrp_field.set_value('');
			}
			me.items[idx].flat_discount = 0;
			me.items[idx]._flat_disc_field.set_value('');
			clear_extra_discounts_and_recalc();
		};

		if (customer) {
			frappe.call({
				method: 'alpinos.sales_order_offline_buyer.get_offline_buyer_item_rate',
				args: { customer: customer, item_code: item_code },
				callback: function(r) {
					const msg = r.message;
					if (msg && typeof msg.mrp === 'number' && msg.mrp > 0) {
						apply_obm_pricing(msg);
						return;
					}
					frappe.call({
						method: 'alpinos.sales_order_api.get_customer_item_mrp',
						args: { customer: customer, item_code: item_code },
						callback: function(r2) {
							if (r2.message) {
								apply_mrp_only(r2.message);
								return;
							}
							frappe.db.get_value('Item', item_code, 'standard_rate', function(ir) {
								apply_mrp_only(ir && ir.standard_rate);
							});
						},
					});
				},
			});
		} else {
			frappe.db.get_value('Item', item_code, 'standard_rate', function(ir) {
				apply_mrp_only(ir && ir.standard_rate);
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
		const gst_pct = flt(item.gst_percent);

		// MRP is treated as GST-inclusive.
		const gross_incl = flt(item.mrp) * qty;
		const flat_disc_amt = gross_incl * flt(item.flat_discount) / 100;
		const after_flat = gross_incl - flat_disc_amt;
		const offer_amt = after_flat * flt(item.offer) / 100;
		const after_offer = after_flat - offer_amt;
		const additional_disc_amt = after_offer * flt(item.additional_discount) / 100;
		const final_incl = Math.max(after_offer - additional_disc_amt, 0);

		const div = 1 + (gst_pct / 100);
		const taxable = div > 0 ? (final_incl / div) : final_incl;
		const gst_amt = Math.max(final_incl - taxable, 0);

		item.taxable_amount = flt(taxable, 2);
		item.custom_item_tax = flt(gst_amt, 2);
		item.amount = flt(final_incl, 2); // UI shows incl-GST line total
		item.rate = qty ? flt(item.taxable_amount / qty, 2) : 0; // net rate (excl GST)

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
		let total_qty = 0, total_taxable = 0, total_gst = 0, total_incl = 0;
		this.items.forEach(item => {
			total_qty += flt(item.qty);
			total_taxable += flt(item.taxable_amount);
			total_gst += flt(item.custom_item_tax);
			total_incl += flt(item.amount);
		});

		let cash_disc_pct = flt(this.cash_discount_field ? this.cash_discount_field.get_value() : 0);
		let cash_disc_amt = total_incl * cash_disc_pct / 100;
		let grand_total = total_incl - cash_disc_amt;

		this.wrapper.find('.total-qty').text(total_qty);
		this.wrapper.find('.total-amount').text(format_currency(total_taxable));
		this.wrapper.find('.gst-amount').text(format_currency(total_gst));
		this.wrapper.find('.total-incl-gst').text(format_currency(total_incl));
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
			this.wrapper.find('.additional-units-section').toggle(!!checked);
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

		this.page.add_inner_button(__('Sales Order List'), function() {
			frappe.set_route('sales-order-entry-list');
		});
	}

	bind_events() {
		let me = this;

		// Add Row button
		this.wrapper.find('.btn-add-row').on('click', function() {
			me.add_item_row();
		});

		this.wrapper.on('click', '.order-row', function () {
			const name = $(this).data('name');
			if (!name) return;
			frappe.set_route('sales-order-entry-view', name);
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

		// Add Additional Units Row
		this.wrapper.find('.btn-add-additional-units').on('click', function() {
			me.add_additional_units_row();
		});

		// Remove Additional Units
		this.wrapper.on('click', '.remove-additional-unit', function() {
			let idx = $(this).closest('tr').data('idx');
			me.additional_units_items.splice(idx, 1);
			me.redraw_additional_units_table();
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

		let item_field = this._make_item_link_field($row.find('.freebie-item'), `freebie_item_${idx}`, 'nonTemplates');
		this._bind_item_link_change(item_field, function() {
			let val = item_field.get_value();
			me.freebies[idx].item_code = val || '';
			if (!val) {
				me.freebies[idx].item_name = '';
				$row.find('.freebie-name span').text('-').addClass('text-muted');
				return;
			}
			frappe.db.get_value('Item', val, 'item_name', function (r) {
				let nm = r && r.item_name;
				if (nm) {
					me.freebies[idx].item_name = nm;
					$row.find('.freebie-name span').text(nm).removeClass('text-muted');
				}
			});
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
			} else {
				frappe.db.get_value('Item', data.item_code, 'item_name', function (r) {
					const nm = r && r.item_name;
					if (nm) {
						me.freebies[idx].item_name = nm;
						$row.find('.freebie-name span').text(nm).removeClass('text-muted');
					}
				});
			}
		}
	}

	add_scheme_row(data) {
		let idx = this.scheme_items.length;
		let row_data = data || { item_code: '', item_name: '', qty: 0, scheme: '' };
		this.scheme_items.push(row_data);

		let $tbody = this.wrapper.find('.scheme-table tbody');
		let $row = $(`
			<tr data-idx="${idx}">
				<td class="scheme-item"></td>
				<td class="scheme-name"><span class="text-muted">-</span></td>
				<td class="scheme-qty"></td>
				<td class="scheme-scheme"></td>
				<td class="text-center"><button class="btn btn-xs btn-danger remove-scheme"><i class="fa fa-trash"></i></button></td>
			</tr>
		`);
		$tbody.append($row);
		let me = this;

		let item_field = this._make_item_link_field($row.find('.scheme-item'), `scheme_item_${idx}`, 'nonTemplates');
		this._bind_item_link_change(item_field, function() {
			let val = item_field.get_value();
			me.scheme_items[idx].item_code = val || '';
			if (!val) {
				me.scheme_items[idx].item_name = '';
				$row.find('.scheme-name span').text('-').addClass('text-muted');
				return;
			}
			frappe.db.get_value('Item', val, 'item_name', function (r) {
				let nm = r && r.item_name;
				if (nm) {
					me.scheme_items[idx].item_name = nm;
					$row.find('.scheme-name span').text(nm).removeClass('text-muted');
				}
			});
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

		if (data && data.item_code) {
			item_field.set_value(data.item_code);
			if (data.qty) qty_field.set_value(data.qty);
			if (data.scheme) scheme_field.set_value(data.scheme);
			if (data.item_name) {
				$row.find('.scheme-name span').text(data.item_name).removeClass('text-muted');
			} else {
				frappe.db.get_value('Item', data.item_code, 'item_name', function (r) {
					const nm = r && r.item_name;
					if (nm) {
						me.scheme_items[idx].item_name = nm;
						$row.find('.scheme-name span').text(nm).removeClass('text-muted');
					}
				});
			}
		}
	}

	add_additional_units_row(data) {
		let idx = this.additional_units_items.length;
		let row_data = Object.assign(
			{
				item_code: '',
				item_name: '',
				qty: 0,
				previous_order_id: '',
				remarks: ''
			},
			data || {}
		);
		this.additional_units_items.push(row_data);

		let $tbody = this.wrapper.find('.additional-units-table tbody');
		let $row = $(`
			<tr data-idx="${idx}">
				<td class="au-item"></td>
				<td class="au-name"><span class="text-muted">-</span></td>
				<td class="au-qty"></td>
				<td class="au-prev-order"></td>
				<td class="au-remarks"></td>
				<td class="text-center"><button class="btn btn-xs btn-danger remove-additional-unit"><i class="fa fa-trash"></i></button></td>
			</tr>
		`);
		$tbody.append($row);
		let me = this;

		let item_field = this._make_item_link_field($row.find('.au-item'), `au_item_${idx}`, 'variants');
		this._bind_item_link_change(item_field, function() {
			let val = item_field.get_value();
			me.additional_units_items[idx].item_code = val || '';
			if (!val) {
				me.additional_units_items[idx].item_name = '';
				$row.find('.au-name span').text('-').addClass('text-muted');
				return;
			}
			frappe.db.get_value('Item', val, 'item_name', function (r) {
				let nm = r && r.item_name;
				if (nm) {
					me.additional_units_items[idx].item_name = nm;
					$row.find('.au-name span').text(nm).removeClass('text-muted');
				}
			});
		});

		let qty_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `au_qty_${idx}` },
			parent: $row.find('.au-qty'),
			render_input: true,
			only_input: true
		});
		qty_field.$input && qty_field.$input.css('width', '70px');
		qty_field.$input.on('change', function() { me.additional_units_items[idx].qty = flt(qty_field.get_value()); });

		let prev_order_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `au_prev_order_${idx}` },
			parent: $row.find('.au-prev-order'),
			render_input: true,
			only_input: true
		});
		prev_order_field.$input.on('change', function() { me.additional_units_items[idx].previous_order_id = prev_order_field.get_value(); });

		let remarks_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Small Text', fieldname: `au_remarks_${idx}`, label: 'Remark' },
			parent: $row.find('.au-remarks'),
			render_input: true
		});
		if (remarks_field.$input) remarks_field.$input.css('min-width', '120px');
		remarks_field.$input.on('change', function() { me.additional_units_items[idx].remarks = remarks_field.get_value(); });

		if (data && data.item_code) {
			item_field.set_value(data.item_code);
			if (data.qty) qty_field.set_value(data.qty);
			if (data.previous_order_id) prev_order_field.set_value(data.previous_order_id);
			if (data.remarks !== undefined && data.remarks !== null) remarks_field.set_value(data.remarks);
			if (data.item_name) {
				$row.find('.au-name span').text(data.item_name).removeClass('text-muted');
			} else {
				frappe.db.get_value('Item', data.item_code, 'item_name', function (r) {
					const nm = r && r.item_name;
					if (nm) {
						me.additional_units_items[idx].item_name = nm;
						$row.find('.au-name span').text(nm).removeClass('text-muted');
					}
				});
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

	redraw_additional_units_table() {
		this.wrapper.find('.additional-units-table tbody').empty();
		let old = this.additional_units_items.slice();
		this.additional_units_items = [];
		old.forEach(s => this.add_additional_units_row(s));
	}

	_sync_other_detail_rows_from_ui() {
		const w = this.wrapper;
		w.find('.freebies-table tbody tr').each((i, tr) => {
			const row = this.freebies[i];
			if (!row) return;
			row.item_code = ($(tr).find('.freebie-item input').val() || '').trim();
			row.qty = flt($(tr).find('.freebie-qty input').val());
			row.remarks = ($(tr).find('.freebie-remarks input').val() || '').trim();
		});
		w.find('.scheme-table tbody tr').each((i, tr) => {
			const row = this.scheme_items[i];
			if (!row) return;
			row.item_code = ($(tr).find('.scheme-item input').val() || '').trim();
			row.qty = flt($(tr).find('.scheme-qty input').val());
			row.scheme = ($(tr).find('.scheme-scheme input').val() || '').trim();
		});
		w.find('.additional-units-table tbody tr').each((i, tr) => {
			const row = this.additional_units_items[i];
			if (!row) return;
			row.item_code = ($(tr).find('.au-item input').val() || '').trim();
			row.qty = flt($(tr).find('.au-qty input').val());
			row.previous_order_id = ($(tr).find('.au-prev-order input').val() || '').trim();
			row.remarks = ($(tr).find('.au-remarks textarea, .au-remarks input').val() || '').trim();
		});
	}

	create_sales_order() {
		let me = this;
		let customer = this.customer_field.get_value();
		let order_type = this.order_type_field.get_value();
		let delivery_date = this.delivery_date_field.get_value();
		let billing_address = me._get_actual_address(this.billing_address_field);
		let shipping_address = me._get_actual_address(this.shipping_address_field);

		if (!customer) return frappe.throw('Please select a Customer');
		if (!order_type) return frappe.throw('Please select Customer Type');

		let valid_items = this.items.filter(i => i.item_code && flt(i.qty) > 0);
		if (!valid_items.length) return frappe.throw('Please add at least one item');

		// Ensure latest link/input values are captured even if the user clicks create
		// immediately after selecting from awesomplete.
		this._sync_other_detail_rows_from_ui();

		let items = valid_items.map(item => ({
			item_code: item.item_code,
			qty: item.qty,
			rate: item.rate || 0,
			delivery_date: item.delivery_date || delivery_date,
			description: item.description || '',
			warehouse: item.warehouse || '',
			custom_box: item.box,
			custom_customer_mrp: item.mrp,
			custom_gst_percent: flt(item.gst_percent),
			custom_flat_discount: item.flat_discount,
			buyer_margin_percent: item.buyer_margin_percent || item.custom_buyer_margin_percent || 0,
			custom_offer: item.offer,
			custom_additional_discount: item.additional_discount,
			custom_item_tax: flt(item.custom_item_tax)
		}));

		let freebies = this.freebies.filter(f => f.item_code).map(f => ({
			item_code: f.item_code,
			item_name: f.item_name || '',
			qty: f.qty,
			remarks: f.remarks || ''
		}));

		let scheme_items = this.scheme_items.filter(s => s.item_code).map(s => ({
			item_code: s.item_code,
			item_name: s.item_name || '',
			qty: s.qty,
			scheme: s.scheme || ''
		}));

		let additional_units_items = this.additional_units_items.filter(s => s.item_code).map(s => ({
			item_code: s.item_code,
			item_name: s.item_name || '',
			qty: s.qty,
			previous_order_id: s.previous_order_id || '',
			remarks: s.remarks || ''
		}));

		frappe.call({
			method: 'alpinos.sales_order_api.create_sales_order',
			args: {
				customer: customer,
				order_type: order_type,
				company: (me.company_field && me.company_field.get_value()) || me.default_company || me._get_default_company(),
				delivery_date: delivery_date,
				billing_address: billing_address,
				shipping_address: shipping_address,
				taxes_and_charges: me.tax_template_field ? me.tax_template_field.get_value() : '',
				items: items,
				cash_discount: flt(me.cash_discount_field.get_value()),
				freebies: freebies,
				scheme_items: scheme_items,
				additional_units_items: additional_units_items,
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
					frappe.set_route('sales-order-entry-view', r.message.name);
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
			const nm = frappe.utils.escape_html(o.name || '');
			return `
				<tr class="order-row" data-name="${nm}" style="cursor: pointer;">
					<td><span class="text-primary" style="font-weight: 500;">${nm}</span></td>
					<td>${frappe.utils.escape_html(o.customer_name || o.customer || '')}</td>
					<td>${frappe.utils.escape_html(o.order_type || '-')}</td>
					<td>${frappe.datetime.str_to_user(o.transaction_date)}</td>
					<td>${o.delivery_date ? frappe.datetime.str_to_user(o.delivery_date) : '-'}</td>
					<td class="text-right">${format_currency(o.grand_total)}</td>
					<td><span class="indicator-pill ${color}">${frappe.utils.escape_html(o.status || '')}</span></td>
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
		this.additional_units_items = [];
		this.wrapper.find('.items-table tbody').empty();
		this.wrapper.find('.freebies-table tbody').empty();
		this.wrapper.find('.scheme-table tbody').empty();
		this.wrapper.find('.additional-units-table tbody').empty();
		this.add_item_row();
		this.calc_totals();
	}
}
