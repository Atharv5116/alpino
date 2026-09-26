/**
 * Filling Process Category — add / edit screen (FRD 4.9 Phase 8, 8.2).
 *
 * The two dependent lists are read-only on this screen on purpose. A machine holds exactly
 * one category and an SKU holds many, so each side owns its own end of the link; editing
 * them from here would mean writing another doctype behind the user back, and the two
 * screens that do own them are one click away.
 *
 * What this screen adds over the plain desk form is the answer to "is it safe to retire
 * this": the counts and the two lists are on the page before the Delete button is pressed,
 * and filling.delete_category refuses while either side still points here.
 */

frappe.pages['filling_category_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Filling Process Category'),
		single_column: true,
	});
	page.main.html(frappe.render_template('filling_category_entry'));
	wrapper.filling_category_entry = new FillingCategoryEntry(page);
};

frappe.pages['filling_category_entry'].on_page_show = function (wrapper) {
	// The list this record belongs to, matching the Back to List button.
	alpinos_production_breadcrumb(__("Filling Process Category"), "/app/filling_category_list");
	if (wrapper.filling_category_entry) wrapper.filling_category_entry.handle_route();
};

var FillingCategoryEntry = class {
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
		control.refresh();
		control.set_value(value === undefined || value === null ? '' : value);
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
			c.refresh();
			c.set_value(value === undefined || value === null ? '' : value);
		}
	}

	_toast(message, indicator) {
		frappe.show_alert({ message: message, indicator: indicator || 'blue' }, 5);
	}

	// -------------------------------------------------------------- fields

	make_fields() {
		this._ctl('.field-category-name', {
			fieldname: 'category_name', label: __('Category Name'), fieldtype: 'Data', reqd: 1,
			description: __('Becomes the ID, e.g. Oats Production.'),
		});
		this._ctl('.field-is-active', {
			fieldname: 'is_active', label: __('Is Active'), fieldtype: 'Check',
			description: __('An inactive category is hidden from every category picker.'),
		}, 1);
		this._ctl('.field-description', {
			fieldname: 'description', label: __('Description'), fieldtype: 'Small Text',
		});
	}

	// --------------------------------------------------------- route / load

	handle_route() {
		const route = frappe.get_route() || [];
		const name = route[1];
		if (name && name !== this.docname) {
			this.load(name);
			return;
		}
		if (!name && this.docname) this.reset();
		if (!name && !this.docname) this.refresh_context();
	}

	reset() {
		// The name becomes the ID, so it is locked once the record exists (see fill) and has
		// to be unlocked again on the way back to a blank screen.
		const nameField = this.fields.category_name;
		if (nameField) {
			nameField.df.read_only = 0;
			nameField.refresh();
			if (nameField.$input) nameField.$input.prop('readonly', false).removeAttr('title');
		}
		this.docname = null;
		this.doc = null;
		this._set('category_name', '');
		this._set('description', '');
		this._set('is_active', 1);
		this.page.set_title(__('New Filling Process Category'));
		this.refresh_context();
	}

	load(name) {
		this.docname = name;
		this.refresh_context();
	}

	refresh_context() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.filling.get_category_form_context',
			args: { category: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				// A route change while this was in flight must not stamp the old record onto
				// the new screen.
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				me.apply_permissions();
				me.make_actions();
				me.render_machines();
				me.render_skus();
			},
		});
	}

	fill(doc) {
		['category_name', 'is_active', 'description'].forEach((f) => this._set(f, doc[f]));
		// The name IS the ID (autoname field:category_name), so renaming it here would mean
		// renaming the record and every Machine and Item row pointing at it. Locking the
		// input rather than only setting df.read_only, because on a page control built by
		// make_control the flag alone leaves the input typeable.
		const nameField = this.fields.category_name;
		if (nameField) {
			nameField.df.read_only = 1;
			nameField.refresh();
			nameField.set_value(doc.category_name);
			if (nameField.$input) {
				nameField.$input.prop('readonly', true)
					.attr('title', __('The name forms the ID and cannot be changed here.'));
			}
		}
		this.page.set_title(doc.category_name || doc.name);
	}

	apply_permissions() {
		const locked = !this.ctx.can_write;
		alpinos_set_readonly(this.wrapper.find('.pm-card'), locked);

		const $banner = this.wrapper.find('.pm-readonly-banner').empty();
		if (locked) {
			$banner.html(`<div class="alert alert-info" style="margin-bottom:0;">${
				__('Filling Process Categories are managed by an administrator. You can view this one and select it on a machine or an item, but not change it.')
			}</div>`);
		}
	}

	// ------------------------------------------------------- dependent lists

	render_machines() {
		const $out = this.wrapper.find('.field-machines');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Save the category, then set it on a filling machine.')}</div>`);
			return;
		}
		const rows = this.ctx.machines || [];
		if (!rows.length) {
			$out.html(`<div class="text-muted">${__('No machine is set to this category yet.')}</div>`);
			return;
		}
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const pill = { 'Active': 'green', 'Under Maintenance': 'orange', 'Inactive': 'red' };
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th style="width:120px;">${__('Machine ID')}</th><th>${__('Machine Name')}</th>`;
		html += `<th style="width:170px;">${__('Machine Type')}</th><th style="width:150px;">${__('Status')}</th>`;
		html += '</tr></thead><tbody>';
		rows.forEach((m) => {
			html += `<tr class="pm-machine-row" data-machine="${esc(m.name)}" style="cursor:pointer;">`;
			html += `<td>${esc(m.name)}</td><td>${esc(m.machine_name)}</td><td>${esc(m.machine_type)}</td>`;
			html += `<td><span class="indicator-pill ${pill[m.status] || 'gray'}">${esc(m.status)}</span></td></tr>`;
		});
		html += '</tbody></table>';
		$out.html(html);
		$out.find('.pm-machine-row').on('click', function () {
			frappe.set_route('machine_entry', $(this).attr('data-machine'));
		});
	}

	render_skus() {
		const $out = this.wrapper.find('.field-skus');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Save the category, then allow it on an item under Filling.')}</div>`);
			return;
		}
		const rows = this.ctx.skus || [];
		if (!rows.length) {
			$out.html(`<div class="text-muted">${__('No item allows this category yet, so nothing can be filled on it.')}</div>`);
			return;
		}
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th>${__('Item')}</th>`;
		html += '</tr></thead><tbody>';
		rows.forEach((s) => {
			html += `<tr class="pm-sku-row" data-item="${esc(s.item_code)}" style="cursor:pointer;">`;
			html += `<td>${esc(s.item_code)}</td></tr>`;
		});
		html += '</tbody></table>';
		$out.html(html);
		$out.find('.pm-sku-row').on('click', function () {
			frappe.set_route('item_master_entry', $(this).attr('data-item'));
		});
	}

	// -------------------------------------------------------------- actions

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.pm-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
			return $b;
		};

		if (this.ctx.can_write) {
			btn(__('Save'), 'btn-primary', () => me.save());
		}
		if (this.docname && this.ctx.can_delete) {
			btn(__('Delete'), 'btn-danger', () => me.remove());
		}
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('filling_category_list'));
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			category_name: this.docname
				? (this.doc ? this.doc.category_name : this._val('category_name'))
				: this._val('category_name'),
			is_active: cint(this._val('is_active')),
			description: this._val('description'),
		};
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.filling.save_category',
			args: { payload: this.collect() },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				const created = !me.docname;
				me._toast(created ? __('Created') : __('Saved'), 'green');
				if (created) {
					frappe.set_route('filling_category_entry', r.message.name);
				} else {
					me.refresh_context();
				}
			},
		});
	}

	remove() {
		const me = this;
		// The counts are named outright, because delete_category will refuse while either
		// side still points here and the numbers are the reason why.
		const machines = (this.ctx.machines || []).length;
		const skus = (this.ctx.skus || []).length;
		let warning = __('Delete filling process category {0}?', [this.docname]);
		if (machines || skus) {
			warning += '<br><br>' + __('{0} machine(s) and {1} item(s) still reference it, so this will be refused. Clear those first, or clear Is Active to retire it instead.', [machines, skus]);
		}
		frappe.confirm(warning, () => {
			frappe.call({
				method: 'alpinos.production.filling.delete_category',
				args: { category: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Deleted'), 'orange');
					frappe.set_route('filling_category_list');
				},
			});
		});
	}
};
