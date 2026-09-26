/**
 * Machine Master — add / edit screen (BRD 2.2.2, 3.1.1).
 *
 * The screen collects values and hands the whole document to the standard client API.
 * Every rule it appears to enforce — a type is mandatory, a capacity needs its unit — is
 * enforced again by Machine.validate on the server, which is the only copy that counts.
 */

frappe.pages['machine_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Machine'),
		single_column: true,
	});
	page.main.html(frappe.render_template('machine_entry'));
	wrapper.machine_entry = new MachineEntry(page);
};

frappe.pages['machine_entry'].on_page_show = function (wrapper) {
	// The list this record belongs to, matching the Back to List button.
	alpinos_production_breadcrumb(__("Machine Master"), "/app/machine_list");
	if (wrapper.machine_entry) wrapper.machine_entry.handle_route();
};

var MachineEntry = class {
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
		const me = this;

		// Shown, never editable: the ID is generated from the MAC-.### series on insert,
		// and it is what every other screen and printout calls this machine. read_only
		// alone would still post the value back, so `collect` leaves it out entirely.
		this._ctl('.field-machine-id', {
			fieldname: 'machine_id', label: __('Machine ID'), fieldtype: 'Data', read_only: 1,
		});

		this._ctl('.field-machine-name', {
			fieldname: 'machine_name', label: __('Machine Name'), fieldtype: 'Data', reqd: 1,
			description: __('The name used on the shop floor.'),
		});

		// A Link, not a Select: the options ARE the Machine Type Master, so a type added
		// there is selectable here with nothing to redeploy (BRD 2.1 system rules 3/4).
		this._ctl('.field-machine-type', {
			fieldname: 'machine_type', label: __('Machine Type'), fieldtype: 'Link',
			options: 'Machine Type', reqd: 1,
			get_query() {
				// An inactive type is a category the factory has retired; a new machine
				// must not be filed under one.
				return { filters: { is_active: 1 } };
			},
			change() { me.render_processes(); },
		});

		// FRD 8.2, the master trigger: the Filling screens read this to decide which input
		// component to draw. Optional -- a mixer or an oven has no filling category.
		this._ctl('.field-filling-category', {
			fieldname: 'filling_process_category', label: __('Filling Process Category'),
			fieldtype: 'Link', options: 'Filling Process Category',
			get_query() { return { filters: { is_active: 1 } }; },
			description: __('Filling lines only.'),
		});
		this._ctl('.field-status', {
			fieldname: 'status', label: __('Current Status'), fieldtype: 'Select',
			options: ['Active', 'Under Maintenance', 'Inactive'], reqd: 1,
			change() { me.render_status_note(); },
		}, 'Active');

		this._ctl('.field-max-capacity', {
			fieldname: 'max_capacity', label: __('Max Capacity'), fieldtype: 'Float',
		});

		// A closed list of four, exactly as the BRD names them — deliberately NOT a Link
		// to the generic UOM master, which would let anyone pick Box or Nos here.
		this._ctl('.field-capacity-uom', {
			fieldname: 'capacity_uom', label: __('Capacity UOM'), fieldtype: 'Select',
			options: ['', 'KG', 'Liters', 'Trays', 'Pieces'],
		});

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
		this.docname = null;
		this.doc = null;
		['machine_name', 'machine_type', 'filling_process_category', 'description'].forEach((f) => this._set(f, ''));
		this._set('max_capacity', '');
		this._set('capacity_uom', '');
		this._set('status', 'Active');
		// Says what will happen rather than leaving an empty box that looks fillable.
		this._set('machine_id', __('Auto'));
		this.page.set_title(__('New Machine'));
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
			method: 'alpinos.production.machine_api.get_machine_form_context',
			args: { machine: docname || '' },
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
				me.render_status_note();
				me.render_processes();
			},
		});
	}

	fill(doc) {
		['machine_name', 'machine_type', 'filling_process_category', 'status',
		 'max_capacity', 'capacity_uom', 'description']
			.forEach((f) => this._set(f, doc[f]));
		this._set('machine_id', doc.name);
		this.page.set_title(`${doc.name} — ${doc.machine_name}`);
	}

	apply_permissions() {
		const locked = !this.ctx.can_write;
		// The Machine ID is never writable, and it has to be switched off BEFORE the sweep
		// below: alpinos_set_readonly snapshots whether each field was already disabled the
		// first time it locks one, and hands that state back on unlock. Disabled after the
		// sweep, the snapshot would say "was editable" and an unlock would open it up.
		this.wrapper.find('.field-machine-id').find('input').prop('disabled', true);
		alpinos_set_readonly(this.wrapper.find('.pm-card'), locked);
	}

	// -------------------------------------------------------------- panels

	render_status_note() {
		const $note = this.wrapper.find('.field-status-note');
		const status = this._val('status');
		if (status === 'Active') {
			$note.html(`<span class="text-muted">${__('This machine is available for production.')}</span>`);
		} else if (status) {
			// Says what the status COSTS, since that is the part a person forgets when
			// flipping a machine to maintenance (BRD 4.2 rule 3).
			$note.html(`<span class="text-warning">${
				__('{0}: this machine cannot be selected during production planning or process assignment.', [__(status)])
			}</span>`);
		} else {
			$note.empty();
		}
	}

	render_processes() {
		const $out = this.wrapper.find('.field-processes');
		const machine_type = this._val('machine_type');
		if (!machine_type) {
			$out.html(`<div class="text-muted">${__('Pick a Machine Type to see which processes this machine can run.')}</div>`);
			return;
		}
		frappe.call({
			method: 'alpinos.production.machine_api.processes_for_machine',
			args: { machine_type: machine_type },
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) {
					$out.html(`<div class="text-muted">${__('No Active process is linked to this Machine Type yet.')}</div>`);
					return;
				}
				const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
				let html = '<table class="table table-bordered table-condensed"><thead><tr>';
				html += `<th style="width:120px;">${__('Process Code')}</th><th>${__('Process Name')}</th>`;
				html += `<th style="width:90px;">${__('Sequence')}</th>`;
				html += '</tr></thead><tbody>';
				rows.forEach((p) => {
					html += `<tr><td>${esc(p.process_code)}</td><td>${esc(p.process_name)}</td>`;
					html += `<td>${esc(p.process_sequence)}</td></tr>`;
				});
				html += '</tbody></table>';
				$out.html(html);
			},
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
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('machine_list'));
	}

	collect() {
		const capacity = this._val('max_capacity');
		return {
			doctype: 'Machine',
			...(this.docname ? { name: this.docname } : {}),
			machine_name: this._val('machine_name'),
			machine_type: this._val('machine_type'),
			filling_process_category: this._val('filling_process_category'),
			status: this._val('status'),
			// flt, not the raw value: an empty box reads as '' and would be stored as 0.
			max_capacity: capacity === '' || capacity === null ? null : flt(capacity),
			capacity_uom: this._val('capacity_uom'),
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
					frappe.set_route('machine_entry', r.message.name);
				},
			});
			return;
		}

		// Read-modify-write against the stored document so nothing the screen does not
		// show (a field added later, say) is silently dropped.
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Machine', name: this.docname },
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
		frappe.confirm(__('Delete machine {0}?', [this.docname]), () => {
			frappe.call({
				method: 'frappe.client.delete',
				args: { doctype: 'Machine', name: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Deleted'), 'orange');
					frappe.set_route('machine_list');
				},
			});
		});
	}
};
