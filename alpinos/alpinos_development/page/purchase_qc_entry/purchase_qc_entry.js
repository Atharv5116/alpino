/**
 * Purchase QC Entry — BRD "Purchase Inward Part -1", section 4 (Purchase QC Screen Layout).
 *
 * The inward header is read-only (4.1.1). Vehicle, Material, Packaging and Sample Testing
 * are INDEPENDENT sections (BR-QC-05: "can be started and performed in parallel ... no
 * mandatory inspection sequence"), so each carries its own completion tick rather than
 * being a wizard step. Final submission is gated on those ticks (BR-QC-06), and that gate
 * lives on the server (purchase_qc._validate_mandatory_inspections) — this page only
 * mirrors it.
 *
 * Design language matches the other alpinos entry pages (sales_order_entry).
 */

// A Datetime straight out of the database carries microseconds
// (2026-09-06 07:20:44.774097). frappe.datetime.validate parses strictly against
// YYYY-MM-DD HH:mm:ss, so the control rejects the value, raises a msgprint and
// blanks the field. Trim the fraction before any value reaches a control.
// var, not const: desk pages are re-evaluated on navigation.
var ALP_TRIM_MICROSECONDS = function (v) {
	if (typeof v !== 'string') return v;
	var m = v.match(/^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.\d+$/);
	return m ? m[1] : v;
};

frappe.pages['purchase_qc_entry'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase QC Entry',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_qc_entry'));
	wrapper.pqc_entry = new PurchaseQCEntry(page);
};

frappe.pages['purchase_qc_entry'].on_page_show = function (wrapper) {
	if (wrapper.pqc_entry) wrapper.pqc_entry.handle_route_entry();
};

var PQC_CONDITION = ['Good', 'Damaged'];

// BR-QC-05: the four parallel inspections, as [section key, done fieldname, short
// title, full label]. Declared with var, not const: desk pages are re-evaluated on
// navigation and a re-declared const blanks the page.
var PQC_SECTIONS = [
	['vehicle', 'vehicle_inspection_done', 'Vehicle', 'Vehicle Inspection'],
	['material', 'material_inspection_done', 'Material', 'Material Inspection'],
	['packaging', 'packaging_inspection_done', 'Packaging', 'Packaging / Box Inspection'],
	['sample', 'sample_testing_done', 'Sample Testing', 'Sample Testing'],
];

var PurchaseQCEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.docname = null;
		this.doc = null;
		this.tables = { vehicle: [], material: [], packaging: [], sample: [], control: [], evidence: [], decision: [] };
		this.setup();
	}

	setup() {
		this.make_header_fields();
		this.make_done_flags();
		this.make_summary_fields();
		this.make_quarantine_fields();
		this.bind_events();
		this.make_actions();
	}

	// ------------------------------------------------------------- helpers

	_ctl(selector, df, value) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data' }, df),
			parent: parent,
			render_input: true,
		});
		c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value));
		c.refresh();
		this.fields[df.fieldname] = c;
		return c;
	}

	_val(f) { const c = this.fields[f]; return c ? c.get_value() : null; }
	_set(f, v) {
		const c = this.fields[f];
		if (c) { c.set_value(v === undefined || v === null ? '' : ALP_TRIM_MICROSECONDS(v)); c.refresh(); }
	}
	_toast(m, i) { frappe.show_alert({ message: m, indicator: i || 'blue' }, 5); }

	// ------------------------------------------------- BRD 4.1.1 (read only)

	make_header_fields() {
		// hide_timezone stops the Datetime control appending the site time zone to
		// df.description, which rendered as a loose "Asia/Kolkata" under Inspection Date.
		// It is inert on the other field types this helper builds.
		const ro = (fieldname, label, fieldtype, options) =>
			this._ctl(`.field-${fieldname.replace(/_/g, '-')}`, {
				fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1,
				hide_timezone: 1,
			});

		ro('purchase_inward', 'Purchase Inward ID', 'Link', 'Purchase Inward');
		ro('supplier', 'Vendor Name', 'Link', 'Supplier');
		ro('supplier_order_no', 'Supplier Order No.');
		ro('invoice_number', 'Invoice Number');
		ro('inward_type', 'Inward Type');
		ro('received_qty', 'Received Quantity', 'Float');
		ro('inspection_date', 'Inspection Date', 'Datetime');
		ro('inspector', 'Inspector', 'Link', 'User');
		this._ctl('.field-overall-remarks', {
			fieldname: 'overall_remarks', label: 'Overall Remarks', fieldtype: 'Small Text',
		});
	}

	// The tick belongs to its section heading, so the label only has to say
	// "Complete" -- the card title already names the inspection.
	make_done_flags() {
		const me = this;
		PQC_SECTIONS.forEach(([key, fieldname]) => {
			const c = me._ctl(`.field-${key}-done`, {
				fieldname, label: __('Complete'), fieldtype: 'Check',
			});
			if (c && c.$input) c.$input.on('change', () => me.on_done_toggle(key, fieldname));
		});
		this.sync_done_flags();
	}

	// VAL-QC-02 on the tick itself: a section cannot be marked Complete before it holds
	// its inspection. The server refuses the same save
	// (purchase_qc._validate_completed_sections); this stops the tick claiming it meanwhile.
	on_done_toggle(key, fieldname) {
		if (cint(this._val(fieldname))) {
			const problem = this.section_problem(key);
			if (problem) {
				this._untick(fieldname);
				frappe.msgprint({ title: __('Cannot mark Complete'), message: problem, indicator: 'orange' });
			}
		}
		this.sync_done_flags();
	}

	/** Why a section may not be ticked Complete yet, or null when it may. */
	section_problem(key) {
		const spec = PQC_SECTIONS.find((s) => s[0] === key);
		const label = __(spec ? spec[3] : key);
		const rows = this.tables[key] || [];
		if (!rows.length) {
			return __('{0} has no rows yet. Add at least one row before marking it Complete.', [label]);
		}
		const blank = (v) => !cstr(v).trim();
		for (let i = 0; i < rows.length; i++) {
			const r = rows[i];
			let missing = null;
			if (key === 'vehicle') {
				const damaged = cint(r.vehicle_damage) || r.vehicle_condition === 'Damaged';
				if (blank(r.vehicle_no)) missing = __('Vehicle No.');
				else if (damaged && blank(r.damage_reason)) missing = __('Damage Reason');
			} else if (!r.item_code) {
				missing = key === 'sample' ? __('SKU') : __('Item');
			} else if (key === 'sample') {
				if (flt(r.sample_qty) <= 0) missing = __('Sample Qty');
			} else {
				const cond = key === 'material' ? r.material_condition : r.packaging_condition;
				const flag = key === 'material' ? r.material_damage : r.packaging_damage;
				const damaged = cint(flag) || cond === 'Damaged';
				if (damaged && flt(r.damaged_qty) <= 0) {
					missing = key === 'material' ? __('Damaged Qty') : __('Damaged Pkgs');
				} else if ((damaged || flt(r.damaged_qty) > 0) && blank(r.damage_reason)) {
					missing = __('Damage Reason');
				}
			}
			if (missing) {
				return __('{0} row {1}: enter the {2} before marking it Complete.', [label, i + 1, missing]);
			}
		}
		return null;
	}

	/**
	 * Clear a Complete tick the section no longer supports -- its last row removed, or a
	 * draft saved before this rule existed. Returns the section label when it cleared one.
	 */
	drop_invalid_tick(key) {
		const spec = PQC_SECTIONS.find((s) => s[0] === key);
		if (!spec || !cint(this._val(spec[1])) || !this.section_problem(key)) return null;
		this._untick(spec[1]);
		return __(spec[3]);
	}

	_untick(fieldname) {
		this._set(fieldname, 0);
		const c = this.fields[fieldname];
		if (c && c.$input) c.$input.prop('checked', false);
	}

	// BR-QC-05/06: each inspection is ticked on its own and every tick gates the
	// submit, so a done section is tinted and whatever is still outstanding is
	// named next to the button it blocks.
	sync_done_flags() {
		const me = this;
		const pending = [];
		PQC_SECTIONS.forEach(([key, fieldname, title]) => {
			const done = cint(me._val(fieldname));
			me.wrapper.find(`.pqc-section[data-section="${key}"]`)
				.toggleClass('pqc-complete', !!done);
			if (!done) pending.push(title);
		});
		const $gate = this.wrapper.find('.pqc-gate');
		if (!$gate.length) return;
		$gate.toggleClass('pqc-gate-open', pending.length > 0).text(
			pending.length
				? __('Still open: {0}', [pending.join(', ')])
				: __('All four inspections marked complete')
		);
	}

	make_summary_fields() {
		this._ctl('.field-total-received', {
			fieldname: 'total_received_qty', label: 'Total Received', fieldtype: 'Float', read_only: 1,
		}, 0);
		this._ctl('.field-total-approved', {
			fieldname: 'total_approved_qty', label: 'Total Approved', fieldtype: 'Float', read_only: 1,
		}, 0);
		this._ctl('.field-total-rejected', {
			fieldname: 'total_rejected_qty', label: 'Total Rejected', fieldtype: 'Float', read_only: 1,
		}, 0);
		this._ctl('.field-qc-result', {
			fieldname: 'qc_result', label: 'QC Result', fieldtype: 'Data', read_only: 1,
			description: 'Derived from the quantities (BRD 4.6.2).',
		});
		this._ctl('.field-rejection-reason', {
			fieldname: 'rejection_reason', label: 'Rejection Reason', fieldtype: 'Small Text',
			description: 'Mandatory when anything is rejected (VAL-QC-04).',
		});
		this._ctl('.field-final-remarks', {
			fieldname: 'final_qc_remarks', label: 'Final QC Remarks', fieldtype: 'Small Text',
		});
	}

	// ------------------------------------------------------------- quarantine

	// QC decides quarantine (alpinos.purchase.quarantine): the approved quantity of the
	// ticked lines is received into the Quarantine warehouse and moves to its warehouse only
	// when it is released from the Quarantine document.
	make_quarantine_fields() {
		const me = this;
		const on_change = (c) => { if (c && c.$input) c.$input.on('change', () => me.apply_quarantine_ui()); };
		this._ctl('.field-quarantine-reminder', {
			fieldname: 'quarantine_reminder_days', label: 'Remind After (Days)', fieldtype: 'Int',
			description: 'One reminder for the whole Quarantine document.',
		});
		this._ctl('.field-quarantine-reason', {
			fieldname: 'quarantine_reason', label: 'Quarantine Reason', fieldtype: 'Small Text',
		});
	}

	/** True when any item is ticked for quarantine. */
	_quarantining() {
		return (this.tables.decision || []).some((row) => cint(row.quarantine));
	}

	/**
	 * The Quarantine column is always offered. Ticking an item brings up the reminder and
	 * reason, which belong to the Quarantine document those items go into. The server derives
	 * the same thing on save (quarantine.apply_qc_selection).
	 */
	apply_quarantine_ui() {
		const doc = this.doc || {};
		const draft = cint(doc.docstatus) === 0;
		const on = this._quarantining();
		this.wrapper.find('.purchase-qc-entry').toggleClass('pqc-quarantining', on);
		const esc = frappe.utils.escape_html;
		let hint = '';
		if (doc.quarantine_document) {
			hint = __('Quarantine Document {0} holds these items. They were received into the Quarantine warehouse and move to their warehouse when released there.', [
				`<a href="/app/purchase_quarantine_view/${encodeURIComponent(doc.quarantine_document)}">${esc(doc.quarantine_document)}</a>`,
			]);
		} else if (draft && !on) {
			hint = __('To hold an item in the Quarantine warehouse until it is released, tick it in the Quarantine column above.');
		} else if (on && draft) {
			hint = __('When QC is completed, the approved quantity of the ticked items is received into the Quarantine warehouse on the GRN, and moves to its warehouse when it is released from the Quarantine document. Rejected quantity still goes to the debit note.');
		}
		this.wrapper.find('.pqc-quarantine-hint').html(hint);
	}

	// ------------------------------------------------------------- grids

	_mk_cell($tr, sel, key, idx, df, value, onchange) {
		const me = this;
		const name = `${key}_${df.fieldname}_${idx}`;
		// The handler runs from Frappe's own df.change, which base_control calls for every
		// value it accepts: a typed value on blur, a tick, and a pick from a Link dropdown.
		// This used to listen for the input's native 'change' event instead, and a Link pick
		// never fires one -- link.js sets the value through parse_validate_and_set_in_model
		// -- so a chosen item was never written to the row and the save failed with
		// "MandatoryError: item_code".
		//
		// df.change also fires for the programmatic set_value below; `ready` ignores that
		// one, so loading a row does not replay its own handlers.
		let ready = false;
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldname: name }, df, {
				change: () => {
					if (!ready || !onchange) return;
					// The PARSED value, never the raw input text: for a Date control that is
					// the user format (dd-mm-yyyy), which reaches the DATE column as an
					// invalid date (MariaDB 1292). `this` is the input, because several
					// handlers still read $(this).prop('checked'); called unbound inside
					// this class, `this` was undefined and every Damage / Control Sample
					// Taken tick was recorded as 0.
					onchange.call(c.$input ? c.$input.get(0) : null, c.get_value());
				},
			}),
			parent: $tr.find(sel),
			render_input: true,
		});
		Promise.resolve(
			c.set_value(value === undefined || value === null ? '' : ALP_TRIM_MICROSECONDS(value))
		).then(() => {
			ready = true;
		});
		me.fields[name] = c;
		if (df.fieldtype === 'Link') me._float_dropdown(c);
		return c;
	}

	/**
	 * Let a Link cell's suggestion list escape the grid it sits in.
	 *
	 * Every inspection grid lives in .alp-scroll, which is overflow-x:auto so a wide table
	 * can scroll sideways. CSS will not keep the other axis visible in that case -- it
	 * computes overflow-y to auto as well -- so the awesomplete list, which hangs below
	 * the row, was clipped to the table's height and showed one squashed option behind a
	 * scrollbar. Making the wrapper overflow:visible would fix the list but push the whole
	 * page sideways on a narrow screen, so the list is taken out of the flow instead:
	 * position:fixed against the input's own rectangle, kept in place while anything
	 * scrolls, and flipped above the input when there is no room below it.
	 */
	_float_dropdown(c) {
		if (!c || !c.$input || !c.awesomplete || !c.awesomplete.ul) return;
		const input = c.$input.get(0);
		const ul = c.awesomplete.ul;
		const GAP = 2;

		const place = () => {
			const r = input.getBoundingClientRect();
			ul.style.position = 'fixed';
			ul.style.left = `${r.left}px`;
			ul.style.width = `${Math.max(r.width, 260)}px`;
			ul.style.minWidth = '0';
			ul.style.zIndex = '1060';
			const below = window.innerHeight - r.bottom;
			const needed = ul.offsetHeight || 0;
			ul.style.top = needed > below && r.top > below
				? `${Math.max(r.top - needed - GAP, 4)}px`
				: `${r.bottom + GAP}px`;
		};

		c.$input.on('awesomplete-open', () => {
			place();
			// The list is filled after it opens, so measure again once it has a height.
			requestAnimationFrame(place);
			window.addEventListener('scroll', place, true);
			window.addEventListener('resize', place);
		});
		c.$input.on('awesomplete-close', () => {
			window.removeEventListener('scroll', place, true);
			window.removeEventListener('resize', place);
		});
	}

	/**
	 * {item_code: item_name} for the lines this inward actually delivered.
	 *
	 * The decision table is seeded from the inward's received rows, so it is the page's
	 * own copy of "what arrived" and needs no extra round trip.
	 */
	_inward_item_names() {
		const out = {};
		(this.tables.decision || []).forEach((row) => {
			if (row.item_code) out[row.item_code] = row.item_name || '';
		});
		return out;
	}

	/**
	 * The Item cell shared by the material, packaging, sample and control grids.
	 *
	 * Two things a bare Link to Item got wrong. It offered EVERY item in the system, so an
	 * inspection row could name something the consignment never contained and nothing
	 * downstream could reconcile it. And it showed the bare code in a narrow box, which is
	 * unreadable next to a decision table that prints the code with its name underneath.
	 */
	_mk_item_cell($tr, key, idx, data) {
		const me = this;
		const names = this._inward_item_names();
		const codes = Object.keys(names);
		const $name = $('<div class="text-muted" style="font-size:11px;line-height:1.3;margin-top:2px;"></div>');
		const paint = (code) => $name.text(names[code] || '');

		this._mk_cell(
			$tr,
			'.c-item',
			key,
			idx,
			{
				fieldtype: 'Link',
				fieldname: 'item_code',
				options: 'Item',
				// An empty allow-list must match nothing, not everything: ['in', []] is
				// ignored by the query builder and would quietly reopen the full Item list.
				get_query: () => ({ filters: { name: ['in', codes.length ? codes : ['__none__']] } }),
			},
			data.item_code,
			function (val) {
				data.item_code = val;
				paint(val);
				// Changing the item moves its quantities to a different decision line.
				if (key === 'material') me.recalc_damage_rollup();
				else if (key === 'sample' || key === 'control') {
					me._match_line(key, idx, data);
					me.recalc_sample_rollup();
				}
			}
		);
		$tr.find('.c-item').append($name);
		paint(data.item_code);
	}

	_item_options() {
		// Sample / control rows must be able to name WHICH decision line they came from
		// (qc_item_idx), because one item code can legitimately occupy several lines. The
		// item code rides along in the label: a bare "1" / "2" was picked the wrong way round.
		return [{ value: '', label: '' }].concat(
			(this.tables.decision || []).map((r, i) => ({
				value: String(i + 1),
				label: `${i + 1} · ${r.item_code || ''}`,
			}))
		);
	}

	/**
	 * Keep a sample / control row's Line on a decision line that carries its SKU.
	 *
	 * An item on exactly one line decides the line by itself, so it is filled in (and a
	 * line picked for another item is corrected); only an item on several lines is left for
	 * the QC user to choose. The server applies the same rule (_bind_child_rows).
	 */
	_match_line(key, idx, data) {
		const lines = [];
		(this.tables.decision || []).forEach((r, i) => {
			if (data.item_code && r.item_code === data.item_code) lines.push(String(i + 1));
		});
		const current = data.qc_item_idx ? String(cint(data.qc_item_idx)) : '';
		let next = current;
		if (lines.length === 1) next = lines[0];
		else if (current && !lines.includes(current)) next = '';
		if (next === current) return;
		if (current && next) {
			this._toast(__('Line {0} is not {1}; set to line {2}.', [current, data.item_code, next]), 'orange');
		}
		data.qc_item_idx = next;
		const c = this.fields[`${key}_qc_item_idx_${idx}`];
		if (c) c.set_value(next);
	}

	add_row(key, data) {
		data = data || {};
		const me = this;
		const idx = this.tables[key].length;
		this.tables[key].push(data);
		const $body = this.wrapper.find(`.${key}-table tbody`);
		const del = `<td class="text-center"><button class="btn btn-xs btn-link btn-remove" data-table="${key}" title="Remove"><i class="fa fa-trash text-danger"></i></button></td>`;
		let $tr;

		if (key === 'vehicle') {
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-no"></td><td class="c-cond"></td><td class="c-dmg"></td>
				<td class="c-reason"></td><td class="c-att"></td><td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-no', key, idx, { fieldtype: 'Data', fieldname: 'vehicle_no' },
				data.vehicle_no, function (val) { data.vehicle_no = val; });
			this._mk_cell($tr, '.c-cond', key, idx,
				{ fieldtype: 'Select', fieldname: 'vehicle_condition', options: PQC_CONDITION.join('\n') },
				data.vehicle_condition || 'Good', function (val) { data.vehicle_condition = val; });
			this._mk_cell($tr, '.c-dmg', key, idx, { fieldtype: 'Check', fieldname: 'vehicle_damage' },
				data.vehicle_damage, function () { data.vehicle_damage = cint($(this).prop('checked')); });
			this._mk_cell($tr, '.c-reason', key, idx, { fieldtype: 'Data', fieldname: 'damage_reason' },
				data.damage_reason, function (val) { data.damage_reason = val; });
			this._mk_cell($tr, '.c-att', key, idx, { fieldtype: 'Attach', fieldname: 'attachment' },
				data.attachment, function (val) { data.attachment = val; });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'inspector_remarks' },
				data.inspector_remarks, function (val) { data.inspector_remarks = val; });

		} else if (key === 'material' || key === 'packaging') {
			const cond_field = key === 'material' ? 'material_condition' : 'packaging_condition';
			const dmg_field = key === 'material' ? 'material_damage' : 'packaging_damage';
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-item"></td><td class="c-cond"></td><td class="c-dmg"></td>
				<td class="c-qty"></td><td class="c-reason"></td><td class="c-att"></td>
				<td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_item_cell($tr, key, idx, data);
			// Material damage feeds the QC Decision's Rejected quantity (packaging does not).
			const damage_changed = () => {
				if (key === 'material') me.recalc_damage_rollup();
			};
			this._mk_cell($tr, '.c-cond', key, idx,
				{ fieldtype: 'Select', fieldname: cond_field, options: PQC_CONDITION.join('\n') },
				data[cond_field] || 'Good', function (val) { data[cond_field] = val; damage_changed(); });
			this._mk_cell($tr, '.c-dmg', key, idx, { fieldtype: 'Check', fieldname: dmg_field },
				data[dmg_field], function () { data[dmg_field] = cint($(this).prop('checked')); damage_changed(); });
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'damaged_qty' },
				data.damaged_qty, function (val) { data.damaged_qty = flt(val); damage_changed(); });
			this._mk_cell($tr, '.c-reason', key, idx, { fieldtype: 'Data', fieldname: 'damage_reason' },
				data.damage_reason, function (val) { data.damage_reason = val; damage_changed(); });
			this._mk_cell($tr, '.c-att', key, idx, { fieldtype: 'Attach', fieldname: 'attachment' },
				data.attachment, function (val) { data.attachment = val; });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'inspector_remarks' },
				data.inspector_remarks, function (val) { data.inspector_remarks = val; });

		} else if (key === 'sample') {
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-item"></td><td class="c-line"></td><td class="c-sbatch"></td>
				<td class="c-ibatch"></td><td class="c-qty"></td><td class="c-id"></td>
				<td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_item_cell($tr, key, idx, data);
			this._mk_cell($tr, '.c-line', key, idx,
				{ fieldtype: 'Select', fieldname: 'qc_item_idx', options: this._item_options() },
				data.qc_item_idx, function (val) {
					data.qc_item_idx = val;
					me._match_line(key, idx, data);
					me.recalc_sample_rollup();
				});
			this._mk_cell($tr, '.c-sbatch', key, idx, { fieldtype: 'Data', fieldname: 'supplier_batch_no' },
				data.supplier_batch_no, function (val) { data.supplier_batch_no = val; });
			this._mk_cell($tr, '.c-ibatch', key, idx,
				{ fieldtype: 'Data', fieldname: 'internal_batch_no', read_only: 1 }, data.internal_batch_no);
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'sample_qty' },
				data.sample_qty, function (val) { data.sample_qty = flt(val); me.recalc_sample_rollup(); });
			this._mk_cell($tr, '.c-id', key, idx,
				{ fieldtype: 'Data', fieldname: 'sample_id', read_only: 1 }, data.sample_id);
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'remarks' },
				data.remarks, function (val) { data.remarks = val; });

		} else if (key === 'evidence') {
			// BRD 4.1.2-4.1.4 want one or more images/video per inspection. The per-row
			// Attach holds the primary shot; extras live here so the QC user does not have
			// to add a whole inspection row (and re-state the condition) for each photo.
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-sec"></td><td class="c-file"></td><td class="c-kind"></td>
				<td class="c-item"></td><td class="c-desc"></td>
				<td class="text-muted">${frappe.utils.escape_html(data.uploaded_by || '')}</td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-sec', key, idx,
				{ fieldtype: 'Select', fieldname: 'section',
					options: 'Vehicle\nMaterial\nPackaging\nSample\nControl Sample\nGeneral' },
				data.section || 'Vehicle', function (val) { data.section = val; });
			this._mk_cell($tr, '.c-file', key, idx, { fieldtype: 'Attach', fieldname: 'file' },
				data.file, function (val) { data.file = val; });
			this._mk_cell($tr, '.c-kind', key, idx,
				{ fieldtype: 'Select', fieldname: 'kind', options: 'Photo\nVideo\nDocument' },
				data.kind || 'Photo', function (val) { data.kind = val; });
			this._mk_item_cell($tr, key, idx, data);
			this._mk_cell($tr, '.c-desc', key, idx, { fieldtype: 'Data', fieldname: 'description' },
				data.description, function (val) { data.description = val; });

		} else if (key === 'control') {
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-taken"></td><td class="c-item"></td><td class="c-line"></td>
				<td class="c-batch"></td><td class="c-qty"></td><td class="c-loc"></td>
				<td class="c-retain"></td><td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-taken', key, idx,
				{ fieldtype: 'Check', fieldname: 'control_sample_taken' },
				data.control_sample_taken === undefined ? 1 : data.control_sample_taken,
				function () { data.control_sample_taken = cint($(this).prop('checked')); me.recalc_sample_rollup(); });
			this._mk_item_cell($tr, key, idx, data);
			this._mk_cell($tr, '.c-line', key, idx,
				{ fieldtype: 'Select', fieldname: 'qc_item_idx', options: this._item_options() },
				data.qc_item_idx, function (val) {
					data.qc_item_idx = val;
					me._match_line(key, idx, data);
					me.recalc_sample_rollup();
				});
			this._mk_cell($tr, '.c-batch', key, idx, { fieldtype: 'Data', fieldname: 'batch_no' },
				data.batch_no, function (val) { data.batch_no = val; });
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'control_sample_qty' },
				data.control_sample_qty, function (val) { data.control_sample_qty = flt(val); me.recalc_sample_rollup(); });
			this._mk_cell($tr, '.c-loc', key, idx,
				{ fieldtype: 'Link', fieldname: 'storage_location', options: 'Warehouse' },
				data.storage_location, function (val) { data.storage_location = val; });
			this._mk_cell($tr, '.c-retain', key, idx, { fieldtype: 'Date', fieldname: 'retention_until' },
				data.retention_until, function (val) { data.retention_until = val; });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'remarks' },
				data.remarks, function (val) { data.remarks = val; });
		}
	}

	/**
	 * {decision row: {qty, reasons}} for the damaged material recorded in Material Inspection.
	 *
	 * "Damaged" is the server's own definition (purchase_qc._validate_material_inspection):
	 * the Damage tick OR Condition = Damaged, with a damaged quantity. A row binds to its
	 * decision line exactly as samples do -- the stored line (qc_item_idx) when there is
	 * one, otherwise the first line carrying that item.
	 */
	_damaged_by_line() {
		const decision = this.tables.decision || [];
		const by_idx = {};
		const first_by_item = {};
		decision.forEach((row, i) => {
			by_idx[i + 1] = row;
			if (row.item_code && first_by_item[row.item_code] === undefined) {
				first_by_item[row.item_code] = row;
			}
		});
		const out = new Map();
		(this.tables.material || []).forEach((r) => {
			const damaged = cint(r.material_damage) || r.material_condition === 'Damaged';
			if (!damaged || flt(r.damaged_qty) <= 0) return;
			const line = by_idx[cint(r.qc_item_idx)] || first_by_item[r.item_code];
			if (!line) return;
			const cur = out.get(line) || { qty: 0, reasons: [] };
			cur.qty += flt(r.damaged_qty);
			if ((r.damage_reason || '').trim()) cur.reasons.push(r.damage_reason.trim());
			out.set(line, cur);
		});
		return out;
	}

	/** What the damage roll-up has already put into each line's Rejected, as of load. */
	seed_damage_baseline() {
		const damaged = this._damaged_by_line();
		this._damage_applied = new WeakMap();
		(this.tables.decision || []).forEach((row) => {
			this._damage_applied.set(row, (damaged.get(row) || { qty: 0 }).qty);
		});
	}

	/**
	 * Damaged material is rejected material: carry it into the QC Decision as it is entered.
	 *
	 * Applied as a DELTA against what this put there last, never an overwrite, so a QC user
	 * can still reject more on the same line for another reason (a failed sample, say) and
	 * that extra survives when the damage is edited or un-ticked. The baseline is seeded on
	 * load, so reopening a saved QC does not count its damage twice. A blank line-level
	 * Rejection Reason takes the damage reason, which also satisfies VAL-QC-04; one the user
	 * typed is never replaced.
	 *
	 * Packaging damage is left out on purpose: a crushed carton is not necessarily rejected
	 * product.
	 */
	recalc_damage_rollup() {
		const decision = this.tables.decision || [];
		if (!decision.length) return;
		if (!this._damage_applied) this._damage_applied = new WeakMap();

		const damaged = this._damaged_by_line();
		decision.forEach((row) => {
			const now = damaged.get(row) || { qty: 0, reasons: [] };
			const before = this._damage_applied.get(row) || 0;
			if (now.qty !== before) {
				row.rejected_qty = Math.max(flt(row.rejected_qty) + (now.qty - before), 0);
				this._damage_applied.set(row, now.qty);
			}
			if (now.qty > 0 && now.reasons.length && !(row.rejection_reason || '').trim()) {
				row.rejection_reason = __('Damaged: {0}', [now.reasons.join('; ')]);
			}
		});

		this.render_decision();
	}

	/**
	 * Mirror purchase_qc._roll_up_sample_qty on the client.
	 *
	 * sample_qty and control_sample_qty on a decision line are a ROLL-UP of the Sample
	 * Testing and Control Sample tables -- the server recomputes them on every save and
	 * never trusts the stored value. The decision grid printed them as static text taken
	 * from the last load, so a quantity typed into Sample Testing only appeared after a
	 * save AND a reload, which reads as the number simply not updating.
	 *
	 * Binding matches the server: the Line select (qc_item_idx, 1-based position in the
	 * decision table) when it is set, otherwise the first decision line carrying that
	 * item -- so a row whose Line is still blank is counted here exactly as it will be
	 * counted on save, rather than silently showing nothing.
	 */
	recalc_sample_rollup() {
		const decision = this.tables.decision || [];
		if (!decision.length) return;

		const by_idx = {};
		const first_by_item = {};
		decision.forEach((row, i) => {
			row.sample_qty = 0;
			row.control_sample_qty = 0;
			by_idx[i + 1] = row;
			if (row.item_code && first_by_item[row.item_code] === undefined) {
				first_by_item[row.item_code] = row;
			}
		});
		const target = (r) => by_idx[cint(r.qc_item_idx)] || first_by_item[r.item_code];

		(this.tables.sample || []).forEach((r) => {
			const line = target(r);
			if (line) line.sample_qty = flt(line.sample_qty) + flt(r.sample_qty);
		});
		(this.tables.control || []).forEach((r) => {
			if (!cint(r.control_sample_taken)) return;
			const line = target(r);
			if (line) line.control_sample_qty = flt(line.control_sample_qty) + flt(r.control_sample_qty);
		});

		this.render_decision();
	}

	render_decision() {
		const me = this;
		const $body = this.wrapper.find('.decision-table tbody').empty();
		(this.tables.decision || []).forEach((row, idx) => {
			const $tr = $(`<tr data-idx="${idx}">
				<td class="text-muted">${idx + 1}</td>
				<td>${frappe.utils.escape_html(row.item_code || '')}<br>
					<span class="text-muted" style="font-size:11px;">
						${frappe.utils.escape_html(row.item_name || '')}</span></td>
				<td class="pqc-num">${format_number(row.received_qty, null, 2)}</td>
				<td class="pqc-num">${format_number(row.sample_qty, null, 2)}</td>
				<td class="c-appr"></td><td class="c-rej"></td><td class="c-reason"></td>
				<td class="c-quar pqc-col-quarantine text-center"></td>
				<td class="c-result text-muted">${frappe.utils.escape_html(row.qc_result || '')}</td>
			</tr>`);
			$body.append($tr);

			me._mk_cell($tr, '.c-appr', 'decision', idx,
				{ fieldtype: 'Float', fieldname: 'approved_qty' }, row.approved_qty,
				function (val) { row.approved_qty = flt(val); me.recalc_totals(); me.apply_quarantine_ui(); });
			me._mk_cell($tr, '.c-rej', 'decision', idx,
				{ fieldtype: 'Float', fieldname: 'rejected_qty' }, row.rejected_qty,
				function (val) { row.rejected_qty = flt(val); me.recalc_totals(); });
			me._mk_cell($tr, '.c-reason', 'decision', idx,
				{ fieldtype: 'Data', fieldname: 'rejection_reason' }, row.rejection_reason,
				function (val) { row.rejection_reason = val; });
			if (cint((me.doc || {}).docstatus) === 0) {
				me._mk_cell($tr, '.c-quar', 'decision', idx,
					{ fieldtype: 'Check', fieldname: 'quarantine' }, row.quarantine,
					function (val) { row.quarantine = cint(val); me.apply_quarantine_ui(); });
			} else if (cint(row.quarantine)) {
				// Completed QC: where the held quantity stands on the Quarantine document.
				const state = (me.quarantine_states || {})[row.name] || 'Quarantined';
				$tr.find('.c-quar').html(
					`<span class="indicator-pill ${state === 'Released' ? 'green' : 'red'}" style="font-size:10px;">${frappe.utils.escape_html(__(state))}</span>`
				);
			}
		});
		this.recalc_totals();
		this.apply_quarantine_ui();
	}

	recalc_totals() {
		let received = 0, approved = 0, rejected = 0;
		(this.tables.decision || []).forEach((r) => {
			received += flt(r.received_qty);
			approved += flt(r.approved_qty);
			rejected += flt(r.rejected_qty);
		});
		this._set('total_received_qty', received);
		this._set('total_approved_qty', approved);
		this._set('total_rejected_qty', rejected);
	}

	// --------------------------------------------------------------- events

	bind_events() {
		const me = this;
		this.wrapper.on('click', '.btn-add', function () {
			me.add_row($(this).attr('data-table'), {});
		});
		this.wrapper.on('click', '.btn-remove', function () {
			const key = $(this).attr('data-table');
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.tables[key].splice(idx, 1);
			me.redraw(key);
			// A removed row takes its quantities with it.
			if (key === 'material') me.recalc_damage_rollup();
			else if (key === 'sample' || key === 'control') me.recalc_sample_rollup();
			const cleared = me.drop_invalid_tick(key);
			if (cleared) {
				me._toast(__('{0} is no longer marked Complete: {1}', [cleared, me.section_problem(key)]), 'orange');
				me.sync_done_flags();
			}
		});
		this.wrapper.on('click', '.btn-print-sticker', () => {
			if (!me.docname) {
				frappe.msgprint(__('Save the QC first.'));
				return;
			}
			// NOT set_route('print', dt, name, {format}): the print page builds the docname
			// as route.slice(2).join('/'), so a 4th argument becomes part of the name and
			// the route breaks. The print view only ever honours meta.default_print_format
			// (which is the QC Inspection Report), so the sticker is opened through the
			// standard printview endpoint, which does take a format.
			const url =
				'/printview?doctype=' + encodeURIComponent('Purchase QC') +
				'&name=' + encodeURIComponent(me.docname) +
				'&format=' + encodeURIComponent('QC Sample Sticker') +
				'&no_letterhead=1&_lang=' + encodeURIComponent(frappe.boot.lang || 'en');
			window.open(url, '_blank');
		});
	}

	redraw(key) {
		const rows = this.tables[key].slice();
		this.tables[key] = [];
		this.wrapper.find(`.${key}-table tbody`).empty();
		rows.forEach((r) => this.add_row(key, r));
	}

	// ----------------------------------------------------------- route/load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1] || (frappe.route_options && frappe.route_options.purchase_qc);
		if (frappe.route_options) delete frappe.route_options.purchase_qc;
		if (name && name !== this.docname) {
			// Drop the resting card before the fetch so the form is not swapped in
			// behind the freeze overlay.
			this.wrapper.find('.purchase-qc-entry').removeClass('pqc-blank');
			this.load(name);
		} else if (!name && this.docname) {
			// Opened bare after viewing an inspection: the previous document must not
			// linger on screen looking like the current one.
			this.docname = null;
			this.doc = null;
			Object.keys(this.tables).forEach((k) => { this.tables[k] = []; });
			this.wrapper.find('tbody').empty();
			this.page.set_title(__('Purchase QC Entry'));
			this.apply_state();
		}
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase QC', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				me.docname = doc.name;
				me.doc = doc;

				[
					'purchase_inward', 'supplier', 'supplier_order_no', 'invoice_number',
					'inward_type', 'received_qty', 'inspection_date', 'inspector',
					'overall_remarks', 'rejection_reason', 'final_qc_remarks', 'qc_result',
					'vehicle_inspection_done', 'material_inspection_done',
					'packaging_inspection_done', 'sample_testing_done',
					'quarantine_reminder_days', 'quarantine_reason',
				].forEach((f) => me._set(f, doc[f]));

				me.quarantine_states = {};
				me.tables.decision = (doc.items || []).slice();
				me.render_decision();
				// set_value lands asynchronously, so the Quarantine Items tick read inside
				// render_decision can still be the previous document's; apply it once settled.
				setTimeout(() => { if (me.doc === doc) me.apply_quarantine_ui(); }, 0);
				if (doc.quarantine_document) {
					frappe.call({
						method: 'alpinos.purchase.quarantine.get_quarantine_context',
						args: { purchase_quarantine: doc.quarantine_document },
						callback(c) {
							if (me.doc !== doc || !c.message) return;
							me.quarantine_states = c.message.line_states || {};
							me.render_decision();
						},
					});
				}

				[
					['vehicle', 'vehicle_inspection'],
					['material', 'material_inspection'],
					['packaging', 'packaging_inspection'],
					['sample', 'sample_testing'],
					['control', 'control_sample'],
					['evidence', 'inspection_evidence'],
				].forEach(([key, field]) => {
					me.tables[key] = [];
					me.wrapper.find(`.${key}-table tbody`).empty();
					(doc[field] || []).forEach((row) => me.add_row(key, Object.assign({}, row)));
				});
				// The saved Rejected already includes this damage; record that, so the next
				// edit applies only the difference.
				me.seed_damage_baseline();

				// A draft saved before VAL-QC-02 covered the tick can still carry Complete over
				// an empty section. Show it unticked; the next save stores that.
				if (cint(doc.docstatus) === 0) {
					const cleared = PQC_SECTIONS.map(([key]) => me.drop_invalid_tick(key)).filter(Boolean);
					if (cleared.length) {
						me._toast(__('Unticked Complete on {0}: nothing is recorded there yet.', [cleared.join(', ')]), 'orange');
					}
				}

				me.apply_state();
				me.page.set_title(`${doc.name} — Purchase QC`);
			},
		});
	}

	apply_state() {
		const doc = this.doc || {};
		// With no document loaded the form describes nothing, so the template swaps in
		// its resting card. The badges below collapse on their own when left empty.
		this.wrapper.find('.purchase-qc-entry').toggleClass('pqc-blank', !this.docname);
		this.wrapper.find('.field-stage-badge').text(doc.qc_status || '');

		const $sla = this.wrapper.find('.field-sla-badge');
		if (doc.sla_due) {
			const breached = cint(doc.sla_breached);
			// The raw field carries microseconds; show it the way the rest of the desk does.
			const due = frappe.datetime.str_to_user(doc.sla_due);
			$sla.text(breached ? `SLA breached (due ${due})` : `SLA due ${due}`)
				.toggleClass('pqc-breached', !!breached);
		} else {
			$sla.text('');
		}

		// Everything is read-only once the inspection is submitted.
		const locked = cint(doc.docstatus) !== 0;
		this.wrapper.find('.pqc-section').toggleClass('pqc-locked', locked);
		this.wrapper.find('.decision-table').closest('.eso-card').toggleClass('pqc-locked', locked);
		this.make_actions();
		this.sync_done_flags();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.pqc-actionbar').empty();
		if (!this.docname) {
			$bar.append(
				`<span class="text-muted">${__('Open a Purchase QC from the QC list to begin.')}</span>`
			);
			return;
		}
		const doc = this.doc || {};
		// BR-QC-06 gates the submit on the four ticks, so say what is still open right
		// beside the button that is blocked. Filled by sync_done_flags().
		if (cint(doc.docstatus) === 0) $bar.append('<span class="pqc-gate"></span>');
		const btn = (label, cls, handler) => {
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		};

		if (cint(doc.docstatus) === 0) {
			btn(__('Save'), 'btn-primary', () => me.save());
			btn(__('Complete QC'), 'btn-primary', () => {
				// Save first. complete_qc works on the STORED document and receives only its
				// name, so ticks and inspection rows still on screen were never seen: the
				// footer read "All four inspections marked complete" while the server
				// answered VAL-QC-02 with every inspection pending. A save the server refuses
				// shows its own error and stops here, so nothing is submitted half-recorded.
				frappe.confirm(__('Submit this inspection? The GRN is drafted from it.'), () => me.save(() => {
					frappe.call({
						method: 'alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.complete_qc',
						args: { purchase_qc: me.docname },
						freeze: true,
						freeze_message: __('Completing QC...'),
						callback(r) {
							// The callback fires even when the server threw. Without this
							// guard a refused Complete QC -- VAL-QC-08, or an unticked
							// inspection under BR-QC-06 -- still popped a green "QC
							// completed" and reloaded unchanged, which reads as the button
							// doing nothing while claiming it worked.
							if (r.exc) {
								// the save above did land, so show what is now stored
								me.load(me.docname);
								return;
							}
							me._toast(__('QC completed'), 'green');
							me.load(me.docname);
						},
					});
				}));
			});
		}
		// Completing QC raises the GRN; reviewing and submitting it is the next step.
		if (doc.purchase_receipt) {
			btn(__('View GRN'), 'btn-primary', () => {
				frappe.set_route('purchase_grn_view', doc.purchase_receipt);
			});
		}
		if (doc.quarantine_document) {
			btn(__('Open Quarantine'), 'btn-default', () => {
				frappe.set_route('purchase_quarantine_view', doc.quarantine_document);
			});
		}
		btn(__('Print Report'), 'btn-default', () => {
			frappe.set_route('print', 'Purchase QC', me.docname);
		});
		if (doc.purchase_inward) {
			btn(__('Open Inward'), 'btn-default', () => {
				frappe.set_route('purchase_inward_entry', doc.purchase_inward);
			});
		}
	}

	// ----------------------------------------------------------------- save

	/** Save the QC. `then` runs only after the server has stored it. */
	save(then) {
		const me = this;
		if (!this.docname) return;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase QC', name: this.docname },
			callback(g) {
				if (!g.message) return;
				const doc = g.message;
				doc.overall_remarks = me._val('overall_remarks');
				doc.rejection_reason = me._val('rejection_reason');
				doc.final_qc_remarks = me._val('final_qc_remarks');
				// Derived from the ticks; the server derives it again (quarantine.apply_qc_selection).
				doc.quarantine_items = me._quarantining() ? 1 : 0;
				doc.quarantine_all_items = 0;
				doc.quarantine_reminder_days = cint(me._val('quarantine_reminder_days'));
				doc.quarantine_reason = me._val('quarantine_reason');
				['vehicle_inspection_done', 'material_inspection_done',
					'packaging_inspection_done', 'sample_testing_done'].forEach((f) => {
					doc[f] = cint(me._val(f));
				});
				doc.vehicle_inspection = me.tables.vehicle;
				doc.material_inspection = me.tables.material;
				doc.packaging_inspection = me.tables.packaging;
				doc.sample_testing = me.tables.sample;
				doc.control_sample = me.tables.control;
				doc.inspection_evidence = me.tables.evidence;
				(doc.items || []).forEach((row, i) => {
					const edited = me.tables.decision[i];
					if (!edited) return;
					row.approved_qty = flt(edited.approved_qty);
					row.rejected_qty = flt(edited.rejected_qty);
					row.rejection_reason = edited.rejection_reason;
					row.quarantine = cint(edited.quarantine);
				});
				frappe.call({
					method: 'frappe.client.save',
					args: { doc: doc },
					freeze: true,
					freeze_message: __('Saving...'),
					callback(r) {
						if (!r.message) return;
						if (then) {
							then();
							return;
						}
						me._toast(__('Saved'), 'green');
						me.load(r.message.name);
					},
				});
			},
		});
	}
};
