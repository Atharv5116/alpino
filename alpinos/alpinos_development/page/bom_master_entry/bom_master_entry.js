/**
 * BOM Master — add / edit screen.
 *
 * One unified grid holds the whole recipe: raw materials, additives and packaging
 * together, told apart by the Process Stage and Material Type columns rather than by
 * living in separate tables. That is what lets the Job Card print group the sheet by
 * stage and drop any group that has no rows.
 *
 * Base Batch Size is shown read-only at 1 and set server-side, so the grid quantities
 * always mean "per one batch" and cannot be quietly rescaled.
 */

frappe.pages['bom_master_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('BOM'),
		single_column: true,
	});
	page.main.html(frappe.render_template('bom_master_entry'));
	wrapper.bom_entry = new BomMasterEntry(page);
};

frappe.pages['bom_master_entry'].on_page_show = function (wrapper) {
	// Production > BOM, and the BOM crumb goes to the BOM list, not the workspace. Coming
	// out of a record you almost always want the other records, and the workspace is still
	// one crumb further left.
	alpinos_production_breadcrumb(__('BOM'), '/app/bom_master_list');
	if (wrapper.bom_entry) wrapper.bom_entry.handle_route();
};

var BomMasterEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.rows = [];
		this.docname = null;
		this.doc = null;
		this.ctx = {};
		this.make_fields();
		this.bind_events();
		this.handle_route();
	}

	// ------------------------------------------------------------- helpers

	_ctl(selector, df, value) {
		const parent = typeof selector === 'string' ? this.wrapper.find(selector) : selector;
		if (!parent || !parent.length) return null;
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

	// -------------------------------------------------------------- header

	make_fields() {
		this._ctl('.field-bom-id', {
			fieldname: 'bom_id', label: __('BOM ID'), fieldtype: 'Data', read_only: 1,
			description: __('Generated on save.'),
		});
		this._ctl('.field-fg-item', {
			fieldname: 'item', label: __('FG Item'), fieldtype: 'Link', options: 'Item', reqd: 1,
			get_query() {
				// A BOM says how a finished good is made, so only an FG belongs here. The
				// picker offered all 233 items, RM and PM included, and an RM chosen by
				// mistake gave the Job Card a header nobody could act on.
				//
				// A server query rather than a filter list, because the rule is "FG or not
				// classified yet" and a plain `in ['FG', '']` would be a bug: in frappe an
				// empty string inside `in` also matches NULL, which is only coincidentally
				// what is wanted here and has bitten this codebase before.
				return { query: 'alpinos.production.bom_api.fg_item_query' };
			},
		});
		this._ctl('.field-variation-name', {
			fieldname: 'custom_bom_variation_name', label: __('BOM Variation Name'),
			fieldtype: 'Data', reqd: 1,
			description: __('e.g. Standard, Export Recipe.'),
		});
		this._ctl('.field-is-default', {
			fieldname: 'is_default', label: __('Is Default'), fieldtype: 'Check',
			description: __('Auto-loads during production. Only one per FG Item.'),
		});
		this._ctl('.field-batch-size', {
			fieldname: 'quantity', label: __('Base Batch Size'), fieldtype: 'Float', read_only: 1,
		}, 1);
		// "Batch", fixed: a BOM here is written for exactly one batch. ERPNext keeps its
		// own BOM.uom as the FG item stock UOM for its internal quantity maths and
		// overwrites anything else on save, so that value is not shown or edited here.
		this._ctl('.field-uom', {
			fieldname: 'uom_display', label: __('UOM'), fieldtype: 'Data', read_only: 1,
		}, 'Batch');
		this._ctl('.field-is-active', {
			fieldname: 'is_active', label: __('Is Active'), fieldtype: 'Check',
		}, 1);
	}

	bind_events() {
		const me = this;
		this.wrapper.find('.btn-add-row').on('click', () => {
			me.rows.push({});
			me.render_rows();
		});
	}

	// ---------------------------------------------------------------- grid

	render_rows() {
		const me = this;
		const $body = this.wrapper.find('.materials-table tbody').empty();

		if (!this.rows.length) {
			$body.append(`<tr><td colspan="10" class="text-muted" style="text-align:center;padding:20px;">
				${__('No materials yet. Use Add Material.')}</td></tr>`);
			return;
		}

		this.rows.forEach((row, idx) => {
			const $tr = $(`
				<tr data-idx="${idx}">
					<td class="text-muted">${idx + 1}</td>
					<td class="cell-stage"></td>
					<td class="cell-material-type"></td>
					<td class="cell-item"></td>
					<td class="cell-qty"></td>
					<td class="cell-uom"></td>
					<td class="cell-time"></td>
					<td class="cell-temp"></td>
					<td class="cell-fan"></td>
					<td><button class="btn btn-xs btn-danger btn-remove-row">&times;</button></td>
				</tr>
			`);
			$body.append($tr);

			const cell = (selector, df, value) => {
				const control = frappe.ui.form.make_control({
					df: Object.assign({ fieldtype: 'Data' }, df),
					parent: $tr.find(selector),
					render_input: true,
				});
				control.refresh();
				control.set_value(value === undefined || value === null ? '' : value);
				return control;
			};

			cell('.cell-stage', {
				fieldname: `stage_${idx}`, fieldtype: 'Select',
				options: [''].concat(this.ctx.process_stages || []),
				change() {
					const value = this.get_value();
					// Guard against the redraw: render_rows() sets this control's value,
					// which fires change again -- without this the two call each other
					// forever and the screen locks up.
					if (value === me.rows[idx].custom_process_stage) return;
					me.rows[idx].custom_process_stage = value;
					// Leaving SYREP drops the machine settings with it, matching what the
					// server does on save.
					me.render_rows();
				},
			}, row.custom_process_stage);

			// Read-only: the classification is a fact about the item, filled in by
			// fetch_item and re-checked on the server.
			cell('.cell-material-type', {
				fieldname: `mtype_${idx}`, fieldtype: 'Data', read_only: 1,
			}, row.custom_material_type);

			const item = cell('.cell-item', {
				fieldname: `item_${idx}`, fieldtype: 'Link', options: 'Item',
				get_query() {
					// Narrow the picker to the material type this row is already for, so a
					// PM row cannot be given a raw material.
					const wanted = me.item_material_type(me.rows[idx].custom_material_type);
					if (wanted) return { filters: { disabled: 0, custom_material_type: wanted } };
					// No type chosen yet. The picker used to offer everything, finished
					// goods included -- and an FG is what a BOM MAKES, never a line inside
					// one. A server query rather than a `!= FG` filter, because in SQL that
					// also drops every NULL, which would hide the 226 items here that have
					// no Material Type at all.
					return { query: 'alpinos.production.bom_api.component_item_query' };
				},
				change() {
					const code = this.get_value();
					if (code === me.rows[idx].item_code) return;
					me.rows[idx].item_code = code;
					if (code) me.fetch_item(idx, code);
				},
			}, row.item_code);
			this.fields[`item_${idx}`] = item;

			cell('.cell-qty', {
				fieldname: `qty_${idx}`, fieldtype: 'Float',
				change() { me.rows[idx].qty = flt(this.get_value()); },
			}, row.qty);

			const uom = cell('.cell-uom', {
				fieldname: `uom_${idx}`, fieldtype: 'Link', options: 'UOM',
				change() { me.rows[idx].uom = this.get_value(); },
			}, row.uom);
			this.fields[`uom_${idx}`] = uom;

			// Machine settings are SYREP-only (the FRD calls them SYREP machine settings),
			// so they are locked everywhere else rather than left to be typed and then
			// silently dropped on save.
			const syrep = row.custom_process_stage === 'SYREP';
			cell('.cell-time', {
				fieldname: `time_${idx}`, fieldtype: 'Data', read_only: syrep ? 0 : 1,
				change() { me.rows[idx].custom_time = this.get_value(); },
			}, syrep ? row.custom_time : '');
			cell('.cell-temp', {
				fieldname: `temp_${idx}`, fieldtype: 'Data', read_only: syrep ? 0 : 1,
				change() { me.rows[idx].custom_temp = this.get_value(); },
			}, syrep ? row.custom_temp : '');
			cell('.cell-fan', {
				fieldname: `fan_${idx}`, fieldtype: 'Data', read_only: syrep ? 0 : 1,
				change() { me.rows[idx].custom_fan_speed = this.get_value(); },
			}, syrep ? row.custom_fan_speed : '');

			$tr.find('.btn-remove-row').on('click', () => {
				me.rows.splice(idx, 1);
				me.render_rows();
			});
		});

		this.apply_permissions();
	}

	/**
	 * The Item Master word for a recipe row type. The two vocabularies were different
	 * once ("Additive Item" on the item, "Additive" in the grid) and this translated
	 * between them; they are the same list now, so it is the identity for the three
	 * component types and blank for anything else.
	 */
	item_material_type(bom_type) {
		return ['RM', 'PM', 'Additive'].includes(bom_type) ? bom_type : '';
	}

	/** UOM and classification come from the Item Master, so a recipe line agrees with it. */
	fetch_item(idx, item_code) {
		const me = this;
		frappe.call({
			method: 'alpinos.production.bom_api.get_item_details',
			args: { item_code: item_code },
			callback(r) {
				const info = r.message || {};
				if (!me.rows[idx]) return;
				if (info.uom && !me.rows[idx].uom) {
					me.rows[idx].uom = info.uom;
					const c = me.fields[`uom_${idx}`];
					if (c) c.set_value(info.uom);
				}
				// Always taken from the item, never left as whatever was there before: the
				// server refuses a row whose type disagrees with its item.
				if (info.material_type !== me.rows[idx].custom_material_type) {
					me.rows[idx].custom_material_type = info.material_type || '';
					me.render_rows();
				}
			},
		});
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
		this.rows = [];
		['bom_id', 'item', 'custom_bom_variation_name'].forEach((f) => this._set(f, ''));
		this._set('is_default', 0);
		this._set('is_active', 1);
		this._set('quantity', 1);
		this.page.set_title(__('New BOM'));
		this.refresh_context();
	}

	refresh_context() {
		const me = this;
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.bom_api.get_form_context',
			args: { bom: docname || '' },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				if (docname !== me.docname) return;
				me.ctx = r.message;
				me.doc = r.message.doc;
				if (me.doc) me.fill(me.doc);
				else {
					me._set('quantity', r.message.base_batch_size);
					// Also here, not only in reset(): arriving on the blank route by a fresh
					// page load never goes through reset(), and the heading was left at the
					// default the page was created with, so the same blank form was called
					// "BOM" or "New BOM" depending on how it was reached.
					me.page.set_title(__('New BOM'));
					me.render_rows();
				}
				me.make_actions();
			},
		});
	}

	fill(doc) {
		this._set('bom_id', doc.name);
		// uom_display is not filled from the document: it is always "Batch" (see make_fields).
		['item', 'custom_bom_variation_name', 'is_default', 'is_active', 'quantity']
			.forEach((f) => this._set(f, doc[f]));
		this.rows = (doc.items || []).map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			uom: r.uom,
			custom_process_stage: r.custom_process_stage,
			custom_material_type: r.custom_material_type,
			custom_time: r.custom_time,
			custom_temp: r.custom_temp,
			custom_fan_speed: r.custom_fan_speed,
		}));
		this.render_rows();
		// The BOM id alone. The variation name used to be appended to it, which made a
		// heading that repeated what the labelled field two rows below already says.
		this.page.set_title(doc.name);
	}

	/**
	 * Lock the form when it may not be edited -- no write permission, or already submitted.
	 *
	 * Read-only, not faded. The cards used to drop to 55% opacity with pointer-events off,
	 * and a submitted BOM spends the rest of its life in that state: reading it is the only
	 * thing it is still for, and it was the hardest thing on the screen to read. Text could
	 * not even be selected out of it.
	 *
	 * alpinos_set_readonly is the treatment the Purchase screens already use for exactly
	 * this -- full contrast, every field switched off, Add and Remove hidden because they
	 * are meaningless rather than unavailable -- so both halves of the app close a document
	 * the same way. See public/js/alpinos_readonly.js for why it disables rather than
	 * flipping df.read_only on a page control.
	 */
	apply_permissions() {
		// BOM ID, Base Batch Size and UOM need no handling here. They are declared
		// read_only in make_fields, and a control built read_only from the start renders
		// as a control-value display area with no input element at all -- there is nothing
		// for a lock to switch off, and nothing an unlock could hand back.
		alpinos_set_readonly(this.wrapper.find('.bm-card'), !this.ctx.can_write);
	}

	// -------------------------------------------------------------- actions

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.bm-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
		};

		if (this.ctx.can_write) btn(__('Save'), 'btn-primary', () => me.save());
		if (this.ctx.can_submit) btn(__('Submit'), 'btn-primary', () => me.submit());
		// No Print Job Card button. The BOM Job Card print format still exists and is still
		// reachable through Open Full BOM, but printing a recipe is not what this screen is
		// for -- the sheet that goes to the floor is the Sub PO Job Card.
		if (this.docname) {
			btn(__('Open Full BOM'), 'btn-default', () => frappe.set_route('Form', 'BOM', me.docname));
		}
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('bom_master_list'));

		this.apply_permissions();
	}

	collect() {
		return {
			...(this.docname ? { name: this.docname } : {}),
			item: this._val('item'),
			custom_bom_variation_name: this._val('custom_bom_variation_name'),
			is_default: cint(this._val('is_default')),
			is_active: cint(this._val('is_active')),
			items: this.rows
				.filter((r) => r.item_code)
				.map((r) => ({
					item_code: r.item_code,
					qty: flt(r.qty),
					uom: r.uom,
					custom_process_stage: r.custom_process_stage,
					custom_material_type: r.custom_material_type,
					custom_time: r.custom_time,
					custom_temp: r.custom_temp,
					custom_fan_speed: r.custom_fan_speed,
				})),
		};
	}

	save() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.bom_api.save_bom',
			args: { payload: JSON.stringify(this.collect()) },
			freeze: true,
			freeze_message: __('Saving...'),
			callback(r) {
				if (!r.message) return;
				me._toast(__('Saved'), 'green');
				if (!me.docname) {
					frappe.set_route('bom_master_entry', r.message.name);
					return;
				}
				me.refresh_context();
			},
		});
	}

	submit() {
		const me = this;
		frappe.confirm(__('Submit BOM {0}? It cannot be edited afterwards.', [this.docname]), () => {
			frappe.call({
				method: 'alpinos.production.bom_api.submit_bom',
				args: { bom: me.docname },
				freeze: true,
				callback(r) {
					if (r.exc) return;
					me._toast(__('Submitted'), 'green');
					me.refresh_context();
				},
			});
		});
	}
};
