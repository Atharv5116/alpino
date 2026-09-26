/**
 * Process Master — add / edit screen (Process Master 3.2 - 3.5).
 *
 * The screen collects values and hands the whole document to the standard client API.
 * Every rule it appears to enforce — at least one Machine Type, a unique name, a
 * sequence of 1 or more — is enforced again by ProcessMaster.validate on the server,
 * which is the only copy that counts. What is done here is done to explain, not to gate.
 */

frappe.pages['process_master_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Process'),
		single_column: true,
	});
	page.main.html(frappe.render_template('process_master_entry'));
	wrapper.process_entry = new ProcessMasterEntry(page);
};

frappe.pages['process_master_entry'].on_page_show = function (wrapper) {
	// The list this record belongs to, matching the Back to List button.
	alpinos_production_breadcrumb(__("Process Master"), "/app/process_master_list");
	if (wrapper.process_entry) wrapper.process_entry.handle_route();
};

var ProcessMasterEntry = class {
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

		this._ctl('.field-process-code', {
			fieldname: 'process_code', label: __('Process Code'), fieldtype: 'Data', reqd: 1,
			description: __('Becomes the ID, e.g. PRC-MIX.'),
		});
		this._ctl('.field-process-name', {
			fieldname: 'process_name', label: __('Process Name'), fieldtype: 'Data', reqd: 1,
		});
		this._ctl('.field-process-sequence', {
			fieldname: 'process_sequence', label: __('Process Sequence'), fieldtype: 'Int', reqd: 1,
		});
		this._ctl('.field-is-active', {
			fieldname: 'is_active', label: __('Is Active'), fieldtype: 'Check',
			description: __('Only an Active process can be put on a Production Order.'),
		}, 1);
		this._ctl('.field-description', {
			fieldname: 'description', label: __('Description'), fieldtype: 'Small Text',
		});

		// MultiSelectPills gives the same "pick several" shape as the doctype's Table
		// MultiSelect, without needing the grid on a custom page.
		this._ctl('.field-machine-types', {
			fieldname: 'machine_types',
			label: __('Linked Machine Type(s)'),
			fieldtype: 'MultiSelectPills',
			reqd: 1,
			get_data(txt) {
				const wanted = (txt || '').toLowerCase();
				return (me.ctx.machine_types || [])
					.filter((t) => !wanted || (t.machine_type_name || '').toLowerCase().includes(wanted))
					.map((t) => ({ value: t.name, label: t.machine_type_name, description: t.name }));
			},
		});
		const machine_types = this.fields.machine_types;
		if (machine_types && machine_types.$input) {
			// Redraw the "machines this reaches" preview as the selection changes.
			machine_types.$wrapper.on('click change', () => setTimeout(() => me.render_machines(), 150));
		}

		this._ctl('.field-qc-required', {
			fieldname: 'qc_required', label: __('QC Required'), fieldtype: 'Check',
			description: __('Ask for a Quality Check when this process finishes.'),
		});
		this._ctl('.field-allow-inward', {
			fieldname: 'allow_inward_entry', label: __('Allow Inward Entry'), fieldtype: 'Check',
			description: __('Let the operator record actual output quantity.'),
		});
		this._ctl('.field-allow-machine', {
			fieldname: 'allow_machine_assignment', label: __('Allow Machine Assignment'), fieldtype: 'Check',
			description: __('Require a machine before this process can start.'),
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
		['process_code', 'process_name', 'description'].forEach((f) => this._set(f, ''));
		this._set('process_sequence', '');
		this._set('is_active', 1);
		['qc_required', 'allow_inward_entry', 'allow_machine_assignment'].forEach((f) => this._set(f, 0));
		this._set('machine_types', []);
		this.page.set_title(__('New Process'));
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
			method: 'alpinos.production.process_api.get_form_context',
			args: { process_master: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				// A route change while this was in flight must not stamp the old document
				// onto the new screen.
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				else if (r.message.next_sequence) me._set('process_sequence', r.message.next_sequence);
				me.apply_permissions();
				me.make_actions();
				me.render_machines();
			},
		});
	}

	fill(doc) {
		[
			'process_code', 'process_name', 'process_sequence', 'description',
			'is_active', 'qc_required', 'allow_inward_entry', 'allow_machine_assignment',
		].forEach((f) => this._set(f, doc[f]));
		this._set('machine_types', (doc.machine_types || []).map((r) => r.machine_type));
		this.page.set_title(`${doc.process_code} — ${doc.process_name}`);
	}

	apply_permissions() {
		const locked = !this.ctx.can_write;
		alpinos_set_readonly(this.wrapper.find('.pm-card'), locked);
	}

	// ------------------------------------------------------------- machines

	render_machines() {
		const $out = this.wrapper.find('.field-available-machines');
		// Only the UNSAVED case asks the picker, because a saved process is answered by
		// the server from its stored rows. Reading the control on load raced it: a
		// MultiSelectPills sets its value asynchronously, so the panel drew "pick a type"
		// on a process that already had one.
		if (!this.docname) {
			const types = this._val('machine_types') || [];
			$out.html(`<div class="text-muted">${
				types.length
					? __('Save the process to see the machines it reaches.')
					: __('Pick a Machine Type to see which machines this process can use.')
			}</div>`);
			return;
		}
		frappe.call({
			method: 'alpinos.alpinos_development.doctype.process_master.process_master.machines_for_process',
			args: { process_master: this.docname },
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) {
					$out.html(`<div class="text-muted">${__('No Active machine is available for these types yet.')}</div>`);
					return;
				}
				const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
				let html = `<div class="text-muted" style="margin-bottom:6px;">${__('Machines available to this process')}</div>`;
				html += '<table class="table table-bordered table-condensed"><thead><tr>';
				html += `<th>${__('Machine')}</th><th>${__('Machine Type')}</th><th>${__('Max Capacity')}</th>`;
				html += '</tr></thead><tbody>';
				rows.forEach((m) => {
					const cap = m.max_capacity
						? esc(alpinos_format_capacity(m.max_capacity, m.capacity_uom))
						: '<span class="text-muted">—</span>';
					html += `<tr><td>${esc(m.machine_name)}</td><td>${esc(m.machine_type)}</td><td>${cap}</td></tr>`;
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
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('process_master_list'));
	}

	collect() {
		const types = (this._val('machine_types') || []).filter(Boolean);
		return {
			doctype: 'Process Master',
			...(this.docname ? { name: this.docname } : {}),
			process_code: this._val('process_code'),
			process_name: this._val('process_name'),
			process_sequence: cint(this._val('process_sequence')),
			description: this._val('description'),
			is_active: cint(this._val('is_active')),
			qc_required: cint(this._val('qc_required')),
			allow_inward_entry: cint(this._val('allow_inward_entry')),
			allow_machine_assignment: cint(this._val('allow_machine_assignment')),
			machine_types: types.map((t) => ({ machine_type: t })),
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
					frappe.set_route('process_master_entry', r.message.name);
				},
			});
			return;
		}

		// Read-modify-write against the stored document so nothing the screen does not
		// show (a field added later, say) is silently dropped.
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Process Master', name: this.docname },
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
		frappe.confirm(__('Delete process {0}?', [this.docname]), () => {
			frappe.call({
				method: 'frappe.client.delete',
				args: { doctype: 'Process Master', name: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Deleted'), 'orange');
					frappe.set_route('process_master_list');
				},
			});
		});
	}
};
