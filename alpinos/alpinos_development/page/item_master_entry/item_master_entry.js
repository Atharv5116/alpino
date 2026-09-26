/**
 * Item Master — add / edit screen (Item Master 1.1).
 *
 * Almost every field here is ERPNext's own Item field under a production-facing label:
 * SKU Code is `item_code`, QC Required is `inspection_required_before_purchase`, and
 * Default Warehouse / Preferred Supplier are the current company's `item_defaults` row.
 * Nothing is shadowed with a second copy, so the Item form and this screen always agree.
 */

frappe.pages['item_master_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Item'),
		single_column: true,
	});
	page.main.html(frappe.render_template('item_master_entry'));
	wrapper.item_entry = new ItemMasterEntry(page);
};

frappe.pages['item_master_entry'].on_page_show = function (wrapper) {
	// The Item list, not the Production workspace: this screen is one item, and the way
	// back from it is the other items. Same destination as the Back to List button.
	alpinos_production_breadcrumb(__('Item Master'), '/app/item_master_list');
	if (wrapper.item_entry) wrapper.item_entry.handle_route();
};

var ItemMasterEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.ctx = {};
		this.make_fields();
		this.handle_route();
	}

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const control = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		control.refresh();
		control.set_value(value === undefined || value === null ? '' : value);
		this.fields[df.fieldname] = control;
		return control;
	}

	_val(f) {
		const c = this.fields[f];
		return c ? c.get_value() : null;
	}

	_set(f, v) {
		const c = this.fields[f];
		if (c) {
			c.refresh();
			c.set_value(v === undefined || v === null ? '' : v);
		}
	}

	_toast(m, i) {
		frappe.show_alert({ message: m, indicator: i || 'blue' }, 5);
	}

	make_fields() {
		const me = this;

		this._ctl('.field-material-type', {
			fieldname: 'custom_material_type', label: __('Material Type'), fieldtype: 'Select',
			options: ['', 'RM', 'PM', 'Additive', 'FG'],
			change: () => me.on_material_type_change(),
		});
		this._ctl('.field-material-category', {
			fieldname: 'custom_material_category', label: __('Material Category'), fieldtype: 'Select',
			options: ['', 'BOX', 'POUCH'],
			description: __('Packaging material only.'),
		});

		this._ctl('.field-item-code', {
			fieldname: 'item_code', label: __('Item SKU Code'), fieldtype: 'Data', reqd: 1,
			description: __('Cannot be changed once the item is created.'),
		});
		this._ctl('.field-item-name', {
			fieldname: 'item_name', label: __('Item Name'), fieldtype: 'Data', reqd: 1,
		});
		this._ctl('.field-item-group', {
			fieldname: 'item_group', label: __('Item Group'), fieldtype: 'Link',
			options: 'Item Group', reqd: 1,
		});
		this._ctl('.field-description', {
			fieldname: 'description', label: __('Description'), fieldtype: 'Small Text',
		});

		this._ctl('.field-stock-uom', {
			fieldname: 'stock_uom', label: __('Stock UOM'), fieldtype: 'Link', options: 'UOM', reqd: 1,
		});
		this._ctl('.field-purchase-uom', {
			fieldname: 'purchase_uom', label: __('Purchase UOM'), fieldtype: 'Link', options: 'UOM',
		});
		this._ctl('.field-sales-uom', {
			fieldname: 'sales_uom', label: __('Sales UOM'), fieldtype: 'Link', options: 'UOM',
		});

		this._ctl('.field-is-stock-item', {
			fieldname: 'is_stock_item', label: __('Maintain Stock'), fieldtype: 'Check',
		}, 1);
		this._ctl('.field-default-warehouse', {
			fieldname: 'default_warehouse', label: __('Default Warehouse'), fieldtype: 'Link',
			options: 'Warehouse',
		});
		this._ctl('.field-preferred-supplier', {
			fieldname: 'default_supplier', label: __('Preferred Supplier'), fieldtype: 'Link',
			options: 'Supplier',
		});
		this._ctl('.field-has-batch-no', {
			fieldname: 'has_batch_no', label: __('Batch No Tracking'), fieldtype: 'Check',
		});
		this._ctl('.field-has-expiry-date', {
			fieldname: 'has_expiry_date', label: __('Expiry Tracking'), fieldtype: 'Check',
		});
		this._ctl('.field-shelf-life', {
			fieldname: 'shelf_life_in_days', label: __('Shelf Life (Days)'), fieldtype: 'Int',
		});
		this._ctl('.field-lead-time', {
			fieldname: 'lead_time_days', label: __('Lead Time (Days)'), fieldtype: 'Int',
		});
		this._ctl('.field-qc-required', {
			fieldname: 'inspection_required_before_purchase', label: __('QC Required'), fieldtype: 'Check',
			description: __('Inspect this item when it is received.'),
		});

		this._ctl('.field-hsn-code', {
			fieldname: 'custom_hsn_code', label: __('HSN Code'), fieldtype: 'Data',
			description: __('Customs / GST classification code.'),
		});
		// The pre-existing GST % field, not a second tax column: most items already carry
		// a value in it, and a new field would split the same number across two places.
		this._ctl('.field-tax-rate', {
			fieldname: 'custom_gst_percent', label: __('Tax Rate (GST %)'), fieldtype: 'Percent',
		});

		// Purchase Order Rate: ERPNext's own last_purchase_rate, not a new column.
		// It is already written on every Purchase Order submit and put back on cancel
		// (erpnext.buying.utils.update_last_purchase_rate), so adding a second field for
		// the same number would give the site two answers and one of them would go stale.
		// Read-only here for the same reason -- the orders are what set it.
		this._ctl('.field-po-rate', {
			fieldname: 'last_purchase_rate', label: __('Purchase Order Rate'),
			fieldtype: 'Currency', read_only: 1,
			description: __('Rate from the most recent submitted Purchase Order. 0 until the item has been ordered once.'),
		});

		this._ctl('.field-loss-percent', {
			fieldname: 'custom_loss_percent', label: __('Loss %'), fieldtype: 'Percent',
			description: __('Expected process loss, 0 to 100.'),
		});

		this._ctl('.field-target-sku-name', {
			fieldname: 'custom_target_sku_name', label: __('Target SKU Name'), fieldtype: 'Data',
			description: __('e.g. 400g Chocolate Oats.'),
		});
		this._ctl('.field-allowed-filling-categories', {
			fieldname: 'allowed_filling_categories',
			label: __('Allowed Filling Categories'),
			fieldtype: 'MultiSelectPills',
			get_data(txt) {
				const wanted = (txt || '').toLowerCase();
				return (me.ctx.filling_categories || [])
					.filter((c) => !wanted || (c.category_name || '').toLowerCase().includes(wanted))
					.map((c) => ({ value: c.name, label: c.category_name, description: c.name }));
			},
		});

		this._ctl('.field-disabled', {
			fieldname: 'disabled', label: __('Disabled'), fieldtype: 'Check',
		});

		this.toggle_category('');
		this.toggle_filling('');
	}

	/**
	 * Show or hide the category. `type` is passed explicitly when loading a document,
	 * because a control's set_value is asynchronous: reading the control right after
	 * filling it returned the PREVIOUS value, so loading a PM item hid the category and
	 * — when this also did the clearing — wiped the value it had just been given.
	 */
	toggle_category(type) {
		const value = type === undefined ? this._val('custom_material_type') : type;
		const is_pm = value === 'PM';
		this.wrapper.find('.field-material-category').toggle(is_pm);
		// Mirrors the field's own mandatory_depends_on so the asterisk appears with the
		// field. The server enforces it either way; this only stops the save being
		// refused for a reason the screen never showed.
		const category = this.fields.custom_material_category;
		if (category && !!category.df.reqd !== is_pm) {
			category.df.reqd = is_pm ? 1 : 0;
			category.refresh();
		}
		return is_pm;
	}

	/**
	 * The Filling card belongs to a finished good only. `type` is passed explicitly when
	 * loading, for the same asynchronous-set_value reason as toggle_category.
	 */
	toggle_filling(type) {
		const value = type === undefined ? this._val('custom_material_type') : type;
		const is_fg = value === 'FG';
		this.wrapper.find('.im-card-filling').toggle(is_fg);
		return is_fg;
	}

	/** Only a real change clears these; loading a document must never do that. */
	on_material_type_change() {
		if (!this.toggle_category()) this._set('custom_material_category', '');
		if (!this.toggle_filling()) {
			this._set('custom_target_sku_name', '');
			this._set('allowed_filling_categories', []);
		}
	}

	// --------------------------------------------------------- route / load

	handle_route() {
		const route = frappe.get_route() || [];
		const name = route[1];
		if (name && name !== this.docname) {
			this.docname = name;
			this.refresh_context();
			return;
		}
		if (!name && this.docname) this.reset();
		else if (!name && !this.docname) this.refresh_context();
	}

	reset() {
		this.docname = null;
		this.doc = null;
		Object.keys(this.fields).forEach((f) => this._set(f, ''));
		this._set('is_stock_item', 1);
		const code = this.fields.item_code;
		if (code) {
			// A new item may have its SKU typed; an existing one may not (see fill()).
			code.df.read_only = 0;
			code.refresh();
		}
		this.page.set_title(__('New Item'));
		this.toggle_category('');
		this.toggle_filling('');
		this.refresh_context();
	}

	refresh_context() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.item_api.get_form_context',
			args: { item: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				me.apply_permissions();
				me.make_actions();
			},
		});
	}

	fill(doc) {
		[
			'item_code', 'item_name', 'item_group', 'description',
			'stock_uom', 'purchase_uom', 'sales_uom',
			'is_stock_item', 'has_batch_no', 'has_expiry_date', 'shelf_life_in_days',
			'inspection_required_before_purchase', 'lead_time_days', 'disabled',
			'custom_material_type', 'custom_material_category', 'custom_loss_percent',
			'custom_hsn_code', 'custom_gst_percent', 'last_purchase_rate',
			'custom_target_sku_name', 'allowed_filling_categories',
			'default_warehouse', 'default_supplier',
		].forEach((f) => this._set(f, doc[f]));

		// The SKU code IS the record id; renaming an item is a different operation.
		const code = this.fields.item_code;
		if (code) {
			code.df.read_only = 1;
			code.refresh();
			code.set_value(doc.item_code);
		}
		this.toggle_category(doc.custom_material_type);
		this.toggle_filling(doc.custom_material_type);
		this.page.set_title(`${doc.item_code} — ${doc.item_name || ''}`);
	}

	apply_permissions() {
		const locked = !this.ctx.can_write;
		alpinos_set_readonly(this.wrapper.find('.im-card'), locked);
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.im-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
		};

		if (this.ctx.can_write) btn(__('Save'), 'btn-primary', () => me.save());
		if (this.docname) {
			btn(__('Open Full Item'), 'btn-default', () => frappe.set_route('Form', 'Item', me.docname));
		}
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('item_master_list'));
	}

	collect() {
		const data = {
			...(this.docname ? { name: this.docname } : { item_code: this._val('item_code') }),
			item_name: this._val('item_name'),
			item_group: this._val('item_group'),
			description: this._val('description'),
			stock_uom: this._val('stock_uom'),
			purchase_uom: this._val('purchase_uom'),
			sales_uom: this._val('sales_uom'),
			is_stock_item: cint(this._val('is_stock_item')),
			has_batch_no: cint(this._val('has_batch_no')),
			has_expiry_date: cint(this._val('has_expiry_date')),
			shelf_life_in_days: cint(this._val('shelf_life_in_days')),
			inspection_required_before_purchase: cint(this._val('inspection_required_before_purchase')),
			lead_time_days: cint(this._val('lead_time_days')),
			disabled: cint(this._val('disabled')),
			custom_material_type: this._val('custom_material_type'),
			custom_material_category: this._val('custom_material_category'),
			custom_loss_percent: flt(this._val('custom_loss_percent')),
			custom_hsn_code: this._val('custom_hsn_code'),
			custom_gst_percent: flt(this._val('custom_gst_percent')),
			custom_target_sku_name: this._val('custom_target_sku_name'),
			allowed_filling_categories: (this._val('allowed_filling_categories') || []).filter(Boolean),
			default_warehouse: this._val('default_warehouse'),
			default_supplier: this._val('default_supplier'),
		};
		return data;
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.item_api.save_item',
			args: { payload: JSON.stringify(this.collect()) },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				me._toast(__('Saved'), 'green');
				if (!me.docname) {
					frappe.set_route('item_master_entry', r.message.name);
					return;
				}
				me.refresh_context();
			},
		});
	}
};
