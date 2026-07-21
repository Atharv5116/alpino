frappe.pages['sales-order-entry'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Alpino Sales Order Entry',
		single_column: true
	});

	page.main.html(frappe.render_template('sales_order_entry'));

	wrapper.soe_instance = new SalesOrderEntry(page);
};

// Fires on every visit (including right after on_page_load): the form always
// starts blank unless route_options ask for a prefill (quotation / edit /
// duplicate), so navigating away and coming back never shows stale data.
frappe.pages['sales-order-entry'].on_page_show = function(wrapper) {
	if (wrapper.soe_instance) wrapper.soe_instance.handle_route_entry();
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
		this.setup_awesomplete_portal();
		this.load_recent_orders();
		// Prefills (quotation / edit / duplicate) are handled per-visit by
		// handle_route_entry(), triggered from on_page_show.
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

	handle_route_entry() {
		const ro = frappe.route_options || {};
		if (ro.from_quotation) {
			const qname = ro.from_quotation;
			delete ro.from_quotation;
			this.clear_form();
			this.prefill_from_quotation(qname);
		} else if (ro.edit_so) {
			const name = ro.edit_so;
			delete ro.edit_so;
			this.clear_form();
			this.load_so_prefill(name, 'edit');
		} else if (ro.duplicate_so) {
			const name = ro.duplicate_so;
			delete ro.duplicate_so;
			this.clear_form();
			this.load_so_prefill(name, 'duplicate');
		} else {
			// Plain visit (or refresh): always start with a blank form.
			this.clear_form();
		}
	}

	// Load an existing Sales Order into the form. mode 'edit' rewrites the same
	// draft on save; mode 'duplicate' prefills only — creating gives a fresh doc
	// with its own workflow state, status and Created By.
	load_so_prefill(name, mode) {
		let me = this;
		frappe.call({
			method: 'alpinos.sales_order_api.get_so_entry_payload',
			args: { sales_order: name },
			freeze: true,
			freeze_message: mode === 'edit' ? __('Loading Sales Order...') : __('Copying Sales Order...'),
			callback(r) {
				if (!r.message) return;
				const d = r.message;
				if (mode === 'edit') {
					if (cint(d.docstatus) !== 0) {
						frappe.msgprint(__('Only draft Sales Orders can be edited.'));
						return;
					}
					me.editing_so = d.sales_order;
					me.page.set_title(__('Alpino Sales Order Entry — {0}', [d.sales_order]));
					me.page.set_primary_action(__('Update Sales Order'), () => me.create_sales_order(), 'fa fa-check');
					if (me.created_by_field) me.created_by_field.set_value(d.owner_full_name || d.owner);
					d._alert_message = __('Loaded {0} for editing', [d.sales_order]);
				} else {
					d._alert_message = __('Prefilled from {0} — saving creates a new order', [d.sales_order]);
				}
				if (me.customer_po_field) me.customer_po_field.set_value(d.po_no || '');
				if (me.po_expiry_field) me.po_expiry_field.set_value(d.po_expiry_date || '');
				if (me.po_pdf_no_field) me.po_pdf_no_field.set_value(d.po_no_for_pdf || '');
				if (me.site_name_field && d.site_name) {
					// Keep the stored (possibly hand-edited) site name — the
					// customer/address auto-fill must not overwrite it.
					me.site_name_field.set_value(d.site_name);
					me._site_name_manual = true;
				}
				if (me.dispatch_date_field && d.dispatch_date) me.dispatch_date_field.set_value(d.dispatch_date);
				// Stash saved MT/e-com values so the async buyer autofill applies these
				// (not the buyer defaults) when the customer is set during prefill.
				if (d.ecom) me._mt_saved = d.ecom;
				me._apply_quotation_prefill(d);
			}
		});
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
		// Source quotation (from-quotation flow or an edited SO that was created
		// from one) — sent on save so SO items keep their prevdoc link.
		me._from_quotation = d.quotation || d.from_quotation || null;

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
				me._load_family_sites(d.customer);
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
					// The stored line `amount`/`rate` are NET of item-GST (ERPNext
					// convention); the item-GST lives in custom_item_tax. The UI model
					// carries the incl-GST amount and a separate taxable_amount, so derive
					// all three here. This works for both the SO-edit payload and the
					// quotation payload (neither of which is guaranteed to send
					// custom_selling_price / gst_percent), and — unlike leaving
					// taxable_amount unset — makes the totals correct on load instead of
					// reading 0 until a price/discount is touched.
					const it_tax = flt(it.custom_item_tax);
					me.items[idx].rate = flt(it.rate);
					me.items[idx].taxable_amount = flt(it.amount);
					me.items[idx].custom_item_tax = it_tax;
					me.items[idx].amount = flt(it.amount) + it_tax;
					me.items[idx].remarks = it.custom_remarks || it.remarks || '';
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
				message: d._alert_message || __('Loaded from quotation {0}', [d.quotation]),
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
		// Company stays on the doc (single-company site) but is hidden — the
		// slot shows the buyer's Site Name instead. Editable: the shipping
		// address's site (or the buyer master's) is only the default; once the
		// user types a value it is never overwritten by auto-fill.
		this.company_field.$wrapper && this.company_field.$wrapper.hide();
		this._site_name_manual = false;
		this._obm_site_name = '';
		this._from_quotation = null;
		this.site_name_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Autocomplete', label: 'Site Name', fieldname: 'site_name' },
			parent: header.find('.field-company'),
			render_input: true
		});
		this.site_name_field.$input && this.site_name_field.$input.on('input', function() {
			me._site_name_manual = true;
		});
		// Dropdown options = every Site Name in the buyer family (parent + children).
		me._load_family_sites = function(customer) {
			if (!customer || !me.site_name_field || !me.site_name_field.set_data) return;
			frappe.call({
				method: 'alpinos.sales_order_offline_buyer.get_customer_family_sites',
				args: { customer },
				callback: (r) => me.site_name_field.set_data((r.message || []).map((s) => ({ value: s, label: s }))),
			});
		};
		me._set_site_name_default = function(value) {
			if (me._site_name_manual) return;
			me.site_name_field && me.site_name_field.set_value(value || '');
		};
		me._update_site_from_shipping = function() {
			if (me._site_name_manual) return;
			const ship = me._get_actual_address(me.shipping_address_field);
			if (!ship) {
				me._set_site_name_default(me._obm_site_name);
				return;
			}
			frappe.db.get_value('Address', ship, 'custom_site_name', function(r) {
				me._set_site_name_default((r && r.custom_site_name) || me._obm_site_name);
			});
		};
		// Set address field value AND show its human-readable label in the input.
		// Guard: only set_value if the address name is actually in opts (linked to Customer).
		// Calling set_value with an unlinked address name triggers Frappe's "not found" error.
		me._set_address_display = function(field, addr_name, opts) {
			if (!field) return;
			if (!opts || !opts.length) return;
			const opt = opts.find(o => o.value === addr_name);
			let use = opt;
			if (!use) {
				// If no specific default (or it's not in the list), look for an address of type "Billing"
				use = opts.find(o => (o.label || '').includes('(Billing)'));
			}
			if (!use) use = opts[0]; // fallback to first available
			if (!use) return;
			field.set_value(use.value);
			if (field.$input) field.$input.val(use.label);
		};

		// Map an Autocomplete's display label back to its internal Address document name
		me._get_actual_address = function(field) {
			if (!field) return '';
			let val = (field.get_value() || '').trim();
			if (!val) return '';
			if (field._opts) {
				let opt = field._opts.find(o => (o.label || '').trim() === val || (o.value || '').trim() === val);
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
							me._obm_site_name = (r.message && r.message.site_name) || '';
							me._update_site_from_shipping();
							// Modern Trade: reveal + default the e-com extra fields.
							me.apply_mt_buyer_flags(r.message);
							me.toggle_mt_ecom();
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
							me._load_family_sites(customer);
							me._refresh_tax_template();
						},
					});
				} else {
					me.billing_address_field && me.billing_address_field.set_value('');
					me.shipping_address_field && me.shipping_address_field.set_value('');
					me._load_address_options(null);
					if (me.tax_template_field) me.tax_template_field.set_value('');
					me._obm_site_name = '';
					me._set_site_name_default('');
				}
			}, 300);
		};
		this.customer_field.$input.on('change', on_customer_change);
		this.customer_field.$input.on('awesomplete-selectcomplete', on_customer_change);

		this.order_type_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Alpino Customer Type', label: 'Customer Type', fieldname: 'order_type', reqd: 1,
				onchange: () => me.toggle_mt_ecom() },
			parent: header.find('.field-order-type'),
			render_input: true
		});

		// E-Com extra fields surface on the offline order too, but only for
		// Modern Trade customers (channel stays Offline). Built once, toggled by type.
		this.make_mt_ecom_fields();

		this.delivery_date_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', label: 'Delivery Date', fieldname: 'delivery_date' },
			parent: header.find('.field-delivery-date'),
			render_input: true
		});

		this.dispatch_date_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', label: 'Dispatch Date', fieldname: 'custom_dispatch_date', reqd: 1 },
			parent: header.find('.field-dispatch-date'),
			render_input: true
		});
		// Set default using 2pm cutoff logic for new SOs
		frappe.call({
			method: 'alpinos.dispatch_date_utils.get_default_dispatch_date',
			callback: function(r) {
				if (r.message && me.dispatch_date_field && !me.dispatch_date_field.get_value()) {
					me.dispatch_date_field.set_value(r.message.date);
				}
			}
		});
		// Validate on change
		this.dispatch_date_field.$input && this.dispatch_date_field.$input.on('change', function() {
			let val = me.dispatch_date_field.get_value();
			if (!val) return;
			frappe.call({
				method: 'alpinos.dispatch_date_utils.validate_dispatch_date',
				args: { date: val },
				callback: function(r) {
					if (r.message && !r.message.valid) {
						frappe.msgprint({ title: __('Invalid Dispatch Date'), message: r.message.message, indicator: 'red' });
						me.dispatch_date_field.set_value('');
					}
				}
			});
		});

		this.customer_po_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', label: 'Customer PO No.', fieldname: 'po_no' },
			parent: header.find('.field-customer-po'),
			render_input: true
		});

		this.po_expiry_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', label: 'PO Expiry Date', fieldname: 'custom_po_expiry_date' },
			parent: header.find('.field-po-expiry'),
			render_input: true
		});

		// PO No for PDF: file name in the Alpino General Settings PO folder;
		// the PDF is fetched and attached automatically right after save.
		this.po_pdf_no_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', label: 'PO No for PDF', fieldname: 'custom_po_no_for_pdf' },
			parent: header.find('.field-po-pdf-no'),
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

		// Created By: read-only; the session user for new orders (Frappe stores
		// it as the doc owner on insert), the original owner when editing.
		this.created_by_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', label: 'Created By', fieldname: 'created_by', read_only: 1 },
			parent: header.find('.field-created-by'),
			render_input: true
		});
		this.created_by_field.$input && this.created_by_field.$input.prop('readonly', true);
		this.created_by_field.set_value(frappe.session.user_fullname || frappe.session.user);

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
			this.shipping_address_field.$input.on('change awesomplete-selectcomplete', () => {
				me._refresh_tax_template();
				me._update_site_from_shipping();
			});
		}
	}

	make_item_table() {
		this.add_item_row();
	}

	// The item/freebie/scheme/damage tables sit inside .alp-scroll wrappers
	// (overflow-x: auto) so phones scroll the table instead of the whole page.
	// That overflow would clip the awesomplete dropdowns, so while a list is
	// open inside a scroll wrapper we pin it to the viewport (position: fixed
	// escapes ancestor overflow clipping) and restore it on close.
	setup_awesomplete_portal() {
		const me = this;
		me._portal_ul = null;
		me._portal_input = null;
		const place = function(input, ul) {
			const rect = input.getBoundingClientRect();
			const vw = window.innerWidth || document.documentElement.clientWidth;
			const width = Math.min(450, Math.max(240, vw - 16));
			const left = Math.max(8, Math.min(rect.left, vw - width - 8));
			ul.style.setProperty('position', 'fixed', 'important');
			ul.style.setProperty('left', left + 'px', 'important');
			ul.style.setProperty('right', 'auto', 'important');
			ul.style.setProperty('top', (rect.bottom + 2) + 'px', 'important');
			ul.style.setProperty('min-width', Math.min(350, width) + 'px', 'important');
			ul.style.setProperty('max-width', width + 'px', 'important');
			ul.style.setProperty('z-index', '10050', 'important');
		};
		const reset = function(ul) {
			if (!ul) return;
			['position', 'left', 'right', 'top', 'min-width', 'max-width', 'z-index'].forEach(function(p) {
				ul.style.removeProperty(p);
			});
		};
		this.wrapper.on('awesomplete-open', 'input', function() {
			const $input = $(this);
			if (!$input.closest('.alp-scroll').length) return;
			const ul = $input.closest('.awesomplete').children('ul').get(0);
			if (!ul) return;
			me._portal_ul = ul;
			me._portal_input = this;
			place(this, ul);
		});
		this.wrapper.on('awesomplete-close', 'input', function() {
			const ul = $(this).closest('.awesomplete').children('ul').get(0);
			reset(ul);
			if (me._portal_ul === ul) {
				me._portal_ul = null;
				me._portal_input = null;
			}
		});
		// Keep an open pinned list glued to its input while anything scrolls
		// (capture phase also catches the .alp-scroll wrappers themselves).
		document.addEventListener('scroll', function() {
			if (me._portal_ul && me._portal_input) {
				place(me._portal_input, me._portal_ul);
			}
		}, true);
	}

	// ---- Modern Trade e-com extras (offline channel) -----------------------
	_is_modern_trade() {
		return (this.order_type_field.get_value() || '').trim().toLowerCase() === 'modern trade';
	}

	make_mt_ecom_fields() {
		const me = this;
		const $card = $(`
			<div class="mt-ecom-card" style="display:none; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin: 0 0 16px 0;">
				<h6 style="margin-top:0; margin-bottom:12px; font-weight:600;">Modern Trade / E-Com Details</h6>
				<div class="row">
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-appointment"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-grn"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-partial"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-gst-excl"></div></div>
				</div>
				<div class="row">
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-po-number"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-po-date"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-billing-gstin"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-shipping-gstin"></div></div>
				</div>
				<div class="row">
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-delivery-by"></div></div>
					<div class="col-md-3 col-sm-6" style="margin-bottom:8px;"><div class="mt-fld-freebie-po"></div></div>
				</div>
				<div class="row">
					<div class="col-md-12" style="margin-bottom:8px;">
						<label class="control-label" style="font-size:12px;">Sticker Attachments</label>
						<div class="mt-stickers-empty text-muted" style="font-size:12px; margin-bottom:6px;">No sticker files uploaded.</div>
						<div class="alp-scroll" style="margin-bottom:8px;">
							<table class="table table-bordered mt-stickers-table" style="font-size:13px; margin-bottom:0; display:none;">
								<thead><tr><th style="min-width:220px;">File</th><th style="min-width:160px;">Remarks</th><th style="width:36px;"></th></tr></thead>
								<tbody></tbody>
							</table>
						</div>
						<button type="button" class="btn btn-sm btn-light btn-mt-add-sticker"><i class="fa fa-upload"></i> Upload Sticker</button>
					</div>
				</div>
			</div>`);
		this.wrapper.find('.so-header').after($card);
		const mk = (sel, df) => frappe.ui.form.make_control({ df, parent: $card.find(sel), render_input: true });
		this.mt = {
			appointment: mk('.mt-fld-appointment', { fieldtype: 'Check', fieldname: 'appointment_required', label: 'Appointment Required' }),
			grn: mk('.mt-fld-grn', { fieldtype: 'Check', fieldname: 'grn_available', label: 'GRN Available' }),
			partial: mk('.mt-fld-partial', { fieldtype: 'Check', fieldname: 'partial_order_allowed', label: 'Partial Order Allowed' }),
			gst_excl: mk('.mt-fld-gst-excl', { fieldtype: 'Check', fieldname: 'gst_exclusive_buyer', label: 'GST-Exclusive Buyer' }),
			po_number: mk('.mt-fld-po-number', { fieldtype: 'Data', fieldname: 'po_number', label: 'PO Number' }),
			po_date: mk('.mt-fld-po-date', { fieldtype: 'Date', fieldname: 'po_date', label: 'PO Date' }),
			billing_gstin: mk('.mt-fld-billing-gstin', { fieldtype: 'Data', fieldname: 'billing_gstin', label: 'Billing GSTIN' }),
			shipping_gstin: mk('.mt-fld-shipping-gstin', { fieldtype: 'Data', fieldname: 'shipping_gstin', label: 'Shipping GSTIN' }),
			delivery_by: mk('.mt-fld-delivery-by', { fieldtype: 'Date', fieldname: 'delivery_by_date', label: 'Delivery By Date' }),
			freebie_po: mk('.mt-fld-freebie-po', { fieldtype: 'Check', fieldname: 'is_freebie_po', label: 'Freebies (Entire PO Free)' }),
		};
		this.mt_stickers = []; // [{attachment, file_name, remarks}]
		$card.find('.btn-mt-add-sticker').on('click', () => this.upload_mt_sticker());
		this.$mt_card = $card;
	}

	upload_mt_sticker() {
		new frappe.ui.FileUploader({
			allow_multiple: true,
			on_success: (file_doc) => {
				this.mt_stickers.push({
					attachment: file_doc.file_url,
					file_name: file_doc.file_name || '',
					remarks: '',
				});
				this.render_mt_stickers();
			},
		});
	}

	render_mt_stickers() {
		if (!this.$mt_card) return;
		const $table = this.$mt_card.find('.mt-stickers-table');
		const $body = $table.find('tbody').empty();
		const $empty = this.$mt_card.find('.mt-stickers-empty');
		if (!this.mt_stickers || !this.mt_stickers.length) {
			$table.hide();
			$empty.show();
			return;
		}
		$empty.hide();
		$table.show();
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		this.mt_stickers.forEach((s, idx) => {
			const $row = $(`<tr>
				<td><a href="${esc(s.attachment)}" target="_blank">${esc(s.file_name || s.attachment)}</a></td>
				<td class="cell-remarks"></td>
				<td class="text-center"><button type="button" class="btn btn-xs btn-danger btn-del-sticker">&times;</button></td>
			</tr>`);
			const $rm = $('<input type="text" class="form-control input-xs">');
			$rm.val(s.remarks || '');
			$row.find('.cell-remarks').append($rm);
			$rm.on('input change', () => { this.mt_stickers[idx].remarks = $rm.val(); });
			$row.find('.btn-del-sticker').on('click', () => {
				this.mt_stickers.splice(idx, 1);
				this.render_mt_stickers();
			});
			$body.append($row);
		});
	}

	toggle_mt_ecom() {
		if (!this.$mt_card) return;
		this.$mt_card.toggle(this._is_modern_trade());
	}

	// Fills the MT flags when a Modern Trade customer is picked. On edit-prefill,
	// saved SO values (me._mt_saved) win over buyer defaults; on a fresh pick, the
	// buyer master flags are used.
	apply_mt_buyer_flags(buyer) {
		if (!this.mt) return;
		if (this._mt_saved) {
			const s = this._mt_saved, fl = s.flags || {};
			this.mt.appointment.set_value(cint(fl.appointment_required));
			this.mt.grn.set_value(cint(fl.grn_available));
			this.mt.partial.set_value(cint(fl.partial_order_allowed));
			this.mt.gst_excl.set_value(cint(fl.gst_exclusive_buyer));
			this.mt.po_number.set_value(s.po_number || '');
			this.mt.po_date.set_value(s.po_date || '');
			this.mt.delivery_by.set_value(s.delivery_by_date || '');
			this.mt.billing_gstin.set_value(s.billing_gstin || '');
			this.mt.shipping_gstin.set_value(s.shipping_gstin || '');
			this.mt.freebie_po.set_value(cint(s.is_freebie_po));
			this.mt_stickers = (s.sticker_attachments || []).map((st) => ({
				attachment: st.attachment || '', file_name: st.file_name || '', remarks: st.remarks || '',
			}));
			this.render_mt_stickers();
			this._mt_saved = null;
			return;
		}
		if (!buyer) return;
		this.mt.appointment.set_value(cint(buyer.appointment_required));
		this.mt.grn.set_value(cint(buyer.grn_available));
		this.mt.partial.set_value(cint(buyer.partial_order_allowed));
		this.mt.gst_excl.set_value(cint(buyer.gst_exclusive_buyer));
		if (buyer.gst_no) {
			if (!this.mt.billing_gstin.get_value()) this.mt.billing_gstin.set_value(buyer.gst_no);
			if (!this.mt.shipping_gstin.get_value()) this.mt.shipping_gstin.set_value(buyer.gst_no);
		}
	}

	mt_ecom_payload() {
		if (!this.mt || !this._is_modern_trade()) return null;
		return {
			flags: {
				appointment_required: cint(this.mt.appointment.get_value()),
				grn_available: cint(this.mt.grn.get_value()),
				partial_order_allowed: cint(this.mt.partial.get_value()),
				gst_exclusive_buyer: cint(this.mt.gst_excl.get_value()),
			},
			po_number: this.mt.po_number.get_value() || '',
			po_date: this.mt.po_date.get_value() || '',
			delivery_by_date: this.mt.delivery_by.get_value() || '',
			billing_gstin: this.mt.billing_gstin.get_value() || '',
			shipping_gstin: this.mt.shipping_gstin.get_value() || '',
			is_freebie_po: cint(this.mt.freebie_po.get_value()),
			sticker_attachments: (this.mt_stickers || []).filter((s) => s.attachment).map((s) => ({
				attachment: s.attachment, file_name: s.file_name || '', remarks: s.remarks || '',
			})),
		};
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
		const me = this;
		// Main order lines: saleable variants, gated by the selected Customer Type so only
		// items that allow it appear. Other tables: any item.
		if (filterType === 'variants') {
			// Variants OR bundles (bundle SKUs have an empty variant_of, so a plain
			// variant_of filter would drop them); templates stay hidden.
			field.get_query = () => {
				const ct = me.order_type_field && me.order_type_field.get_value();
				return {
					query: 'alpinos.offline_buyer_api.sellable_item_link_query',
					filters: ct ? { customer_type: ct } : {},
				};
			};
		} else if (filterType === 'nonTemplates') {
			field.get_query = () => ({
				filters: {
					disabled: 0,
					is_sales_item: 1,
					has_variants: 0,
				},
			});
		}
		if (field.$input) {
			field.$input.css('min-width', '90px');
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
				remarks: '',
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
				<td class="item-image text-center" style="vertical-align: middle;"><img class="item-image-preview" src="" style="max-height: 32px; max-width: 44px; display: none;" /></td>
				<td class="item-sku"></td>
				<td class="item-name"><span class="item-name-text text-muted" style="font-size: 12px;">-</span></td>
				<td class="item-qty"></td>
				<td class="item-box"></td>
				<td class="item-mrp"></td>
				<td class="item-selling-price"></td>
				<td class="item-gst"></td>
				<td class="item-flat-discount"></td>
				<td class="item-offer"></td>
				<td class="item-additional-discount"></td>
				<td class="item-remarks"></td>
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
		qty_field.$input && qty_field.$input.css('width', '44px');
		qty_field.$input.on('change', function() {
			me.items[idx].qty = flt(qty_field.get_value());
			me.calc_box_from_qty(idx, $row);
			// Preserve the unit Selling Price (a qty change must not rederive it
			// from MRP minus discounts and wipe a manual override).
			me.calc_row_amount(idx, $row, true);
		});
		row_data._qty_field = qty_field;

		// Box
		let box_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `box_${idx}` },
			parent: $row.find('.item-box'),
			render_input: true,
			only_input: true
		});
		box_field.$input && box_field.$input.css('width', '44px');
		box_field.$input.on('change', function() {
			me.items[idx].box = flt(box_field.get_value());
			me.calc_qty_from_box(idx, $row);
			// Preserve the unit Selling Price (box drives qty, not the unit price).
			me.calc_row_amount(idx, $row, true);
		});
		row_data._box_field = box_field;

		// MRP (read-only)
		let mrp_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Currency', fieldname: `mrp_${idx}`, read_only: 1 },
			parent: $row.find('.item-mrp'),
			render_input: true,
			only_input: true
		});
		mrp_field.$input && mrp_field.$input.css('width', '56px');
		mrp_field.$input && mrp_field.$input.prop('readonly', true);
		row_data._mrp_field = mrp_field;

		// Selling Price (editable)
		let selling_price_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Currency', fieldname: `selling_price_${idx}` },
			parent: $row.find('.item-selling-price'),
			render_input: true,
			only_input: true
		});
		selling_price_field.$input && selling_price_field.$input.css('width', '60px');
		selling_price_field.$input.on('change', function() {
			me.items[idx].custom_selling_price = flt(selling_price_field.get_value());
			me.calc_row_amount(idx, $row, true);
		});
		row_data._selling_price_field = selling_price_field;

		// GST % (read-only, from Item)
		let gst_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Float', fieldname: `gst_${idx}`, read_only: 1 },
			parent: $row.find('.item-gst'),
			render_input: true,
			only_input: true
		});
		gst_field.$input && gst_field.$input.css('width', '40px');
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
		flat_disc_field.$input && flat_disc_field.$input.css('width', '46px');
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
		offer_field.$input && offer_field.$input.css('width', '46px');
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
		add_disc_field.$input && add_disc_field.$input.css('width', '46px');
		add_disc_field.$input.on('change', function() {
			me.items[idx].additional_discount = flt(add_disc_field.get_value());
			// Additional discount applies on top of the current Selling Price; it
			// must not rederive (and reset) that price from MRP minus flat/offer.
			me.calc_row_amount(idx, $row, true);
		});
		row_data._add_disc_field = add_disc_field;

		// Remarks — mandatory (server-enforced) when this item's qty is reduced
		// vs the source Quotation.
		let remarks_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: `remarks_${idx}` },
			parent: $row.find('.item-remarks'),
			render_input: true,
			only_input: true
		});
		remarks_field.$input && remarks_field.$input.css('min-width', '74px');
		remarks_field.$input.on('change', function() {
			me.items[idx].remarks = remarks_field.get_value();
		});
		row_data._remarks_field = remarks_field;

		// Set values if data was passed
		if (data && data.item_code) {
			sku_field.set_value(data.item_code);
			if (data.qty !== undefined && data.qty !== null) qty_field.set_value(data.qty);
			if (data.box !== undefined && data.box !== null) box_field.set_value(data.box);
			if (data.mrp !== undefined && data.mrp !== null && data.mrp !== '') {
				mrp_field.set_value(data.mrp);
			}
			if (data.custom_selling_price !== undefined || data.selling_price !== undefined) {
				selling_price_field.set_value(data.custom_selling_price || data.selling_price || 0);
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
			if (data.remarks || data.custom_remarks) {
				remarks_field.set_value(data.remarks || data.custom_remarks);
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

		// The same SKU must not appear on more than one line — flag it and clear the row.
		const dup = me.items.some((it, i) => i !== idx && it && it.item_code === item_code);
		if (dup) {
			frappe.msgprint({
				title: __('Duplicate SKU'),
				message: __('SKU {0} is already in the item table. Update its quantity on the existing row instead of adding it again.', [item_code]),
				indicator: 'orange',
			});
			me.items[idx].item_code = '';
			if (me.items[idx]._sku_field) me.items[idx]._sku_field.set_value('');
			$row.find('.item-name-text').text('-').addClass('text-muted');
			me._set_row_image($row, '');
			me.items[idx].item_name = '';
			return;
		}

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

		// Pricing: if this SKU is on Buyer Master for the customer → MRP + margin from master.
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

			if (msg.source === 'offline_buyer_items' && msg.rate) {
				me.items[idx].custom_selling_price = flt(msg.rate);
			} else {
				me.items[idx].custom_selling_price = flt(msg.mrp * (1 - m / 100));
			}
			if (me.items[idx]._selling_price_field) {
				me.items[idx]._selling_price_field.set_value(me.items[idx].custom_selling_price);
			}

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
					if (msg && (flt(msg.mrp) > 0 || flt(msg.margin_percent) > 0)) {
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
							frappe.db.get_value('Item', item_code, 'valuation_rate', function(ir) {
								apply_mrp_only(ir && ir.valuation_rate);
							});
						},
					});
				},
			});
		} else {
			frappe.db.get_value('Item', item_code, 'valuation_rate', function(ir) {
				apply_mrp_only(ir && ir.valuation_rate);
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
		// Derive box count for display only — the typed qty is never rounded up.
		// Whole-box compliance (qty + freebies as a multiple of the box factor)
		// is validated on save instead.
		let item = this.items[idx];
		let cf = this._box_cache[item.item_code];
		if (cf) {
			item.box = Math.ceil(flt(item.qty) / flt(cf));
			item._box_field.set_value(item.box);
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

	calc_row_amount(idx, $row, selling_price_edited) {
		let item = this.items[idx];
		let qty = flt(item.qty);
		const gst_pct = flt(item.gst_percent);

		let selling_price = flt(item.custom_selling_price);

		if (!selling_price_edited) {
			// Recalculate Selling Price (unit price after flat and offer discounts)
			const unit_mrp = flt(item.mrp);
			const flat_disc = flt(item.flat_discount);
			const offer = flt(item.offer);
			selling_price = unit_mrp * (1 - flat_disc / 100) * (1 - offer / 100);
			item.custom_selling_price = flt(selling_price, 2);
			if (item._selling_price_field) {
				item._selling_price_field.set_value(item.custom_selling_price);
			}
		}

		// Apply additional discount directly on selling price
		const gross_incl = selling_price * qty;
		const additional_disc_amt = gross_incl * flt(item.additional_discount) / 100;
		const final_incl = Math.max(gross_incl - additional_disc_amt, 0);

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
			if (!val) {
				me.freebies[idx].item_code = '';
				me.freebies[idx].item_name = '';
				$row.find('.freebie-name span').text('-').addClass('text-muted');
				return;
			}
			// Fetch group + name together. Freebies can only be given for items
			// already in the order Items table — EXCEPT Marketing Material items
			// (promo inserts, discount cards), which are standalone giveaways.
			frappe.db.get_value('Item', val, ['item_name', 'item_group'], function (r) {
				const info = r || {};
				const isMarketing = info.item_group === 'Marketing Material';
				if (!isMarketing && !me.items.some(it => it.item_code === val)) {
					frappe.msgprint({
						title: __('Not an ordered item'),
						message: __('Marketing Freebie {0} is not in the Items table. Add it to the order items first.', [val.bold()]),
						indicator: 'orange'
					});
					item_field.set_value('');
					me.freebies[idx].item_code = '';
					me.freebies[idx].item_name = '';
					$row.find('.freebie-name span').text('-').addClass('text-muted');
					return;
				}
				me.freebies[idx].item_code = val;
				me.freebies[idx].item_name = info.item_name || '';
				$row.find('.freebie-name span').text(info.item_name || '-').removeClass('text-muted');
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
			if (data.remarks) remarks_field.set_value(data.remarks);
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
			// Send the entered Selling Price so a direct edit persists — without it the
			// server recomputes the price from MRP minus discounts and drops the typed
			// value. Read the live input in case the change event hasn't fired yet.
			custom_selling_price: flt((item._selling_price_field && item._selling_price_field.get_value()) || item.custom_selling_price || 0),
			custom_gst_percent: flt(item.gst_percent),
			custom_flat_discount: item.flat_discount,
			buyer_margin_percent: item.buyer_margin_percent || item.custom_buyer_margin_percent || 0,
			custom_offer: item.offer,
			custom_additional_discount: item.additional_discount,
			custom_item_tax: flt(item.custom_item_tax),
			// Read the live input too — the change event may not have fired if the
			// user clicks save straight after typing (and prefill sets the model).
			custom_remarks: (item._remarks_field && item._remarks_field.get_value()) || item.remarks || ''
		}));

		let freebies = this.freebies.filter(f => f.item_code).map(f => ({
			item_code: f.item_code,
			item_name: f.item_name || '',
			qty: f.qty,
			remarks: f.remarks || ''
		}));

		// Freebies must reference ordered items (a row can go stale if its item
		// was later removed from the Items table), and every ordered item must
		// fill whole boxes — qty + freebies when freebies exist, qty alone
		// otherwise. Mirrors the server-side validate hook.
		let ordered_codes = new Set(valid_items.map(i => i.item_code));
		let stale_freebie = freebies.find(f => !ordered_codes.has(f.item_code));
		if (stale_freebie) {
			return frappe.throw(__('Marketing Freebie {0} is not in the Items table. Add it to the order items or remove the freebie row.', [stale_freebie.item_code.bold()]));
		}
		let order_qty_by_code = {};
		valid_items.forEach(i => {
			order_qty_by_code[i.item_code] = (order_qty_by_code[i.item_code] || 0) + flt(i.qty);
		});
		for (let item_code of Object.keys(order_qty_by_code)) {
			let cf = flt(me._box_cache[item_code]);
			if (!cf) continue;
			let has_freebies = freebies.some(f => f.item_code === item_code);
			let freebie_qty = freebies.filter(f => f.item_code === item_code)
				.reduce((s, f) => s + flt(f.qty), 0);
			let qty = order_qty_by_code[item_code];
			let total = qty + freebie_qty;
			let rem = total % cf;
			if (Math.min(rem, cf - rem) > 0.0001) {
				let detail = has_freebies
					? __('ordered qty {0} + freebies {1} = {2}', [qty, freebie_qty, total])
					: __('ordered qty {0}', [qty]);
				return frappe.throw(__('{0}: a box holds {1} units — {2} must be a multiple of {3}.', [item_code.bold(), cf, detail, cf]));
			}
		}

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

		const is_edit = !!me.editing_so;
		let args = {
			customer: customer,
			order_type: order_type,
			company: (me.company_field && me.company_field.get_value()) || me.default_company || me._get_default_company(),
			delivery_date: delivery_date,
			po_no: me.customer_po_field ? me.customer_po_field.get_value() : '',
			po_expiry_date: me.po_expiry_field ? me.po_expiry_field.get_value() : '',
			po_no_for_pdf: me.po_pdf_no_field ? me.po_pdf_no_field.get_value() : '',
			site_name: me.site_name_field ? me.site_name_field.get_value() : '',
			from_quotation: me._from_quotation || '',
			dispatch_date: me.dispatch_date_field ? me.dispatch_date_field.get_value() : '',
			billing_address: billing_address,
			shipping_address: shipping_address,
			taxes_and_charges: me.tax_template_field ? me.tax_template_field.get_value() : '',
			items: items,
			cash_discount: flt(me.cash_discount_field.get_value()),
			freebies: freebies,
			scheme_items: scheme_items,
			additional_units_items: additional_units_items,
			additional_units_damage: me.additional_units_damage_field.get_value() ? 1 : 0
		};
		if (is_edit) {
			args.name = me.editing_so;
		} else {
			args.submit_now = 0;
		}
		// Modern Trade offline orders carry the e-com extra fields (channel stays Offline).
		const mt_payload = me.mt_ecom_payload();
		if (mt_payload) args.ecom_fields = JSON.stringify(mt_payload);

		frappe.call({
			method: is_edit ? 'alpinos.sales_order_api.update_sales_order' : 'alpinos.sales_order_api.create_sales_order',
			args: args,
			freeze: true,
			freeze_message: is_edit ? 'Updating Sales Order...' : 'Creating Sales Order...',
			callback: function(r) {
				if (r.message && r.message.name) {
					frappe.show_alert({
						message: is_edit
							? `Sales Order <b>${r.message.name}</b> updated.`
							: `Sales Order <b>${r.message.name}</b> saved as Draft. Review it, then click "Send for Warehouse Approval".`,
						indicator: 'green'
					}, 6);
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
			<div class="alp-scroll">
				<table class="table table-hover" style="font-size: 13px;">
					<thead>
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
			</div>
		`);
	}

	clear_form() {
		let me = this;
		// Leave edit mode: back to a fresh "create" form.
		this.editing_so = null;
		this.page.set_title(__('Alpino Sales Order Entry'));
		this.page.set_primary_action(__('Create Sales Order'), () => me.create_sales_order(), 'fa fa-check');

		this.customer_field.set_value('');
		this.order_type_field.set_value('');
		this.delivery_date_field.set_value('');
		this.dispatch_date_field && this.dispatch_date_field.set_value('');
		this.customer_po_field && this.customer_po_field.set_value('');
		this.po_expiry_field && this.po_expiry_field.set_value('');
		this.po_pdf_no_field && this.po_pdf_no_field.set_value('');
		this._site_name_manual = false;
		this._obm_site_name = '';
		this.site_name_field && this.site_name_field.set_value('');
		this.billing_address_field && this.billing_address_field.set_value('');
		this.shipping_address_field && this.shipping_address_field.set_value('');
		this.tax_template_field && this.tax_template_field.set_value('');
		this.cash_discount_field && this.cash_discount_field.set_value(0);
		this.created_by_field && this.created_by_field.set_value(frappe.session.user_fullname || frappe.session.user);
		this.additional_units_damage_field && this.additional_units_damage_field.set_value(0);
		this.wrapper.find('.additional-units-section').toggle(false);
		// Reset the Modern Trade / e-com card.
		this._mt_saved = null;
		if (this.mt) {
			Object.values(this.mt).forEach((f) => f && f.set_value(''));
		}
		this.toggle_mt_ecom();
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
		// Re-apply the 2pm-cutoff default dispatch date for a fresh order.
		frappe.call({
			method: 'alpinos.dispatch_date_utils.get_default_dispatch_date',
			callback: function(r) {
				if (r.message && me.dispatch_date_field && !me.dispatch_date_field.get_value()) {
					me.dispatch_date_field.set_value(r.message.date);
				}
			}
		});
	}
}
