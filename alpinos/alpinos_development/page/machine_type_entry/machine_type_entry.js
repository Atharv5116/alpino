/**
 * Machine Type Master — add / edit screen (BRD 2.1).
 *
 * BRD 2.1.1 says only a Backend Admin or Super Admin may manage types; everyone else
 * selects from what exists. That rule is held by the DocPerm matrix in
 * alpinos.production.roles, not by this screen. What the screen does is read the same
 * permission back and say so plainly, so a Production User who opens a type sees a
 * read-only record rather than a Save button that throws.
 */

frappe.pages['machine_type_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Machine Type'),
		single_column: true,
	});
	page.main.html(frappe.render_template('machine_type_entry'));
	wrapper.machine_type_entry = new MachineTypeEntry(page);
};

frappe.pages['machine_type_entry'].on_page_show = function (wrapper) {
	// The list this record belongs to, matching the Back to List button.
	alpinos_production_breadcrumb(__("Machine Type Master"), "/app/machine_type_list");
	if (wrapper.machine_type_entry) wrapper.machine_type_entry.handle_route();
};

var MachineTypeEntry = class {
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
		// TYP-MIX comes from this code. It forms the record ID, so the doctype marks it
		// set_only_once and the screen locks it the moment the record exists.
		this._ctl('.field-type-code', {
			fieldname: 'type_code', label: __('Type Code'), fieldtype: 'Data',
			description: __('Short code for the ID, e.g. MIX gives TYP-MIX.'),
		});
		this._ctl('.field-machine-type-name', {
			fieldname: 'machine_type_name', label: __('Machine Type Name'), fieldtype: 'Data', reqd: 1,
			description: __('The category name, for example Mixing Machine.'),
		});
		this._ctl('.field-is-active', {
			fieldname: 'is_active', label: __('Is Active'), fieldtype: 'Check',
			description: __('Only an Active type can be chosen on a new machine.'),
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
		// Undo BOTH halves of the lock fill() applies, and clear the value with them.
		// Clearing df.read_only alone left the input carrying the readonly attribute fill()
		// set directly on it, and the old code still in it -- so New, reached from a saved
		// type, opened showing that type's code and refusing to let it be changed.
		const code = this.fields.type_code;
		if (code) {
			code.df.read_only = 0;
			code.refresh();
			code.set_value('');
			if (code.$input) code.$input.prop('readonly', false).removeAttr('title');
		}
		this.docname = null;
		this.doc = null;
		this._set('machine_type_name', '');
		this._set('description', '');
		this._set('is_active', 1);
		this.page.set_title(__('New Machine Type'));
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
			method: 'alpinos.production.machine_api.get_machine_type_form_context',
			args: { machine_type: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				// A route change while this was in flight must not stamp the old document
				// onto the new screen.
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				me.apply_permissions();
				me.make_actions();
				me.render_machines();
				me.render_processes();
			},
		});
	}

	fill(doc) {
		['type_code', 'machine_type_name', 'is_active', 'description'].forEach((f) => this._set(f, doc[f]));
		// set_only_once on the doctype: the code is part of the ID, so it is shown but not
		// editable once the record exists.
		//
		// df.read_only plus refresh() is how a FORM control locks; on a page control built
		// by make_control it left the input typeable, and collect() drops type_code on an
		// edit -- so a retyped code was accepted on screen, silently discarded, and the
		// record kept its old ID with no complaint. Lock the input itself, which does not
		// depend on how frappe resolves disp_status outside a form.
		const code = this.fields.type_code;
		if (code) {
			code.df.read_only = 1;
			code.refresh();
			code.set_value(doc.type_code);
			if (code.$input) {
				code.$input.prop('readonly', true)
					.attr('title', __('The code forms the ID and cannot be changed.'));
			}
		}
		this.page.set_title(`${doc.name} — ${doc.machine_type_name}`);
	}

	apply_permissions() {
		const locked = !this.ctx.can_write;
		alpinos_set_readonly(this.wrapper.find('.pm-card'), locked);

		const $banner = this.wrapper.find('.pm-readonly-banner').empty();
		if (locked) {
			$banner.html(`<div class="alert alert-info" style="margin-bottom:0;">${
				__('Machine Types are managed by an administrator. You can view this one and select it on a machine, but not change it.')
			}</div>`);
		}
	}

	// -------------------------------------------------------------- panels

	render_machines() {
		const $out = this.wrapper.find('.field-machines');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Save the type, then file machines under it.')}</div>`);
			return;
		}
		const rows = this.ctx.machines || [];
		if (!rows.length) {
			$out.html(`<div class="text-muted">${__('No machine is filed under this type yet.')}</div>`);
			return;
		}
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const pill = { 'Active': 'green', 'Under Maintenance': 'orange', 'Inactive': 'red' };
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th style="width:120px;">${__('Machine ID')}</th><th>${__('Machine Name')}</th>`;
		html += `<th style="width:160px;">${__('Max Capacity')}</th><th style="width:150px;">${__('Status')}</th>`;
		html += '</tr></thead><tbody>';
		rows.forEach((m) => {
			const cap = m.max_capacity
				? esc(alpinos_format_capacity(m.max_capacity, m.capacity_uom))
				: '<span class="text-muted">—</span>';
			html += `<tr class="pm-machine-row" data-machine="${esc(m.name)}" style="cursor:pointer;">`;
			html += `<td>${esc(m.name)}</td><td>${esc(m.machine_name)}</td><td>${cap}</td>`;
			html += `<td><span class="indicator-pill ${pill[m.status] || 'gray'}">${esc(m.status)}</span></td></tr>`;
		});
		html += '</tbody></table>';
		$out.html(html);
		$out.find('.pm-machine-row').on('click', function () {
			frappe.set_route('machine_entry', $(this).attr('data-machine'));
		});
	}

	render_processes() {
		const $out = this.wrapper.find('.field-processes');
		if (!this.docname) {
			$out.html(`<div class="text-muted">${__('Save the type, then link it from a process.')}</div>`);
			return;
		}
		const rows = this.ctx.processes || [];
		if (!rows.length) {
			$out.html(`<div class="text-muted">${__('No Active process uses this type.')}</div>`);
			return;
		}
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		let html = '<table class="table table-bordered table-condensed"><thead><tr>';
		html += `<th style="width:120px;">${__('Process Code')}</th><th>${__('Process Name')}</th>`;
		html += `<th style="width:90px;">${__('Sequence')}</th>`;
		html += '</tr></thead><tbody>';
		rows.forEach((p) => {
			html += `<tr class="pm-process-row" data-process="${esc(p.name)}" style="cursor:pointer;">`;
			html += `<td>${esc(p.process_code)}</td><td>${esc(p.process_name)}</td>`;
			html += `<td>${esc(p.process_sequence)}</td></tr>`;
		});
		html += '</tbody></table>';
		$out.html(html);
		$out.find('.pm-process-row').on('click', function () {
			frappe.set_route('process_master_entry', $(this).attr('data-process'));
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
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('machine_type_list'));
	}

	collect() {
		return {
			...(this.docname ? {} : { type_code: this._val('type_code') }),
			doctype: 'Machine Type',
			...(this.docname ? { name: this.docname } : {}),
			machine_type_name: this._val('machine_type_name'),
			is_active: cint(this._val('is_active')),
			description: this._val('description'),
		};
	}

	save() {
		const me = this;
		const payload = this.collect();

		if (!this.docname) {
			frappe.call({
				method: 'frappe.client.insert',
				args: { doc: payload },
				freeze: true,
				freeze_message: __('Saving...'),
				callback(r) {
					if (!r.message) return;
					me._toast(__('Created'), 'green');
					frappe.set_route('machine_type_entry', r.message.name);
				},
			});
			return;
		}

		// Read-modify-write against the stored document so nothing the screen does not
		// show (a field added later, say) is silently dropped.
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Machine Type', name: this.docname },
			callback(g) {
				if (!g.message) return;
				const doc = Object.assign({}, g.message, payload);
				frappe.call({
					method: 'frappe.client.save',
					args: { doc: doc },
					freeze: true,
					freeze_message: __('Saving...'),
					callback(r) {
						if (!r.message) return;
						me._toast(__('Saved'), 'green');
						me.refresh_context();
					},
				});
			},
		});
	}

	remove() {
		const me = this;
		// Named outright, because MachineType.on_trash will refuse a type a process uses
		// and the count is the reason why.
		const machines = (this.ctx.machines || []).length;
		const processes = (this.ctx.processes || []).length;
		let warning = __('Delete machine type {0}?', [this.docname]);
		if (machines || processes) {
			warning += '<br><br>' + __('{0} machine(s) and {1} process(es) still reference it.', [machines, processes]);
		}
		frappe.confirm(warning, () => {
			frappe.call({
				method: 'frappe.client.delete',
				args: { doctype: 'Machine Type', name: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Deleted'), 'orange');
					frappe.set_route('machine_type_list');
				},
			});
		});
	}
};
