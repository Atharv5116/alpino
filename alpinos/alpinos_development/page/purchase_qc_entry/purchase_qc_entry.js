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
		c.set_value(value === undefined || value === null ? '' : value);
		c.refresh();
		this.fields[df.fieldname] = c;
		return c;
	}

	_val(f) { const c = this.fields[f]; return c ? c.get_value() : null; }
	_set(f, v) {
		const c = this.fields[f];
		if (c) { c.set_value(v === undefined || v === null ? '' : v); c.refresh(); }
	}
	_toast(m, i) { frappe.show_alert({ message: m, indicator: i || 'blue' }, 5); }

	// ------------------------------------------------- BRD 4.1.1 (read only)

	make_header_fields() {
		const ro = (fieldname, label, fieldtype, options) =>
			this._ctl(`.field-${fieldname.replace(/_/g, '-')}`, {
				fieldname, label, fieldtype: fieldtype || 'Data', options, read_only: 1,
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

	make_done_flags() {
		const me = this;
		[
			['vehicle', 'vehicle_inspection_done', 'Vehicle inspection complete'],
			['material', 'material_inspection_done', 'Material inspection complete'],
			['packaging', 'packaging_inspection_done', 'Packaging inspection complete'],
			['sample', 'sample_testing_done', 'Sample testing complete'],
		].forEach(([key, fieldname, label]) => {
			me._ctl(`.field-${key}-done`, {
				fieldname, label, fieldtype: 'Check',
			});
		});
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

	// ------------------------------------------------------------- grids

	_mk_cell($tr, sel, key, idx, df, value, onchange) {
		const me = this;
		const name = `${key}_${df.fieldname}_${idx}`;
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldname: name }, df),
			parent: $tr.find(sel),
			render_input: true,
		});
		c.set_value(value === undefined || value === null ? '' : value);
		me.fields[name] = c;
		if (onchange && c.$input) c.$input.on('change', onchange);
		return c;
	}

	_item_options() {
		// Sample / control rows must be able to name WHICH decision line they came from
		// (qc_item_idx), because one item code can legitimately occupy several lines.
		return (this.tables.decision || []).map((r, i) => `${i + 1}`).join('\n');
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
				data.vehicle_no, function () { data.vehicle_no = $(this).val(); });
			this._mk_cell($tr, '.c-cond', key, idx,
				{ fieldtype: 'Select', fieldname: 'vehicle_condition', options: PQC_CONDITION.join('\n') },
				data.vehicle_condition || 'Good', function () { data.vehicle_condition = $(this).val(); });
			this._mk_cell($tr, '.c-dmg', key, idx, { fieldtype: 'Check', fieldname: 'vehicle_damage' },
				data.vehicle_damage, function () { data.vehicle_damage = cint($(this).prop('checked')); });
			this._mk_cell($tr, '.c-reason', key, idx, { fieldtype: 'Data', fieldname: 'damage_reason' },
				data.damage_reason, function () { data.damage_reason = $(this).val(); });
			this._mk_cell($tr, '.c-att', key, idx, { fieldtype: 'Attach', fieldname: 'attachment' },
				data.attachment, function () { data.attachment = $(this).val(); });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'inspector_remarks' },
				data.inspector_remarks, function () { data.inspector_remarks = $(this).val(); });

		} else if (key === 'material' || key === 'packaging') {
			const cond_field = key === 'material' ? 'material_condition' : 'packaging_condition';
			const dmg_field = key === 'material' ? 'material_damage' : 'packaging_damage';
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-item"></td><td class="c-cond"></td><td class="c-dmg"></td>
				<td class="c-qty"></td><td class="c-reason"></td><td class="c-att"></td>
				<td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-item', key, idx,
				{ fieldtype: 'Link', fieldname: 'item_code', options: 'Item' },
				data.item_code, function () { data.item_code = $(this).val(); });
			this._mk_cell($tr, '.c-cond', key, idx,
				{ fieldtype: 'Select', fieldname: cond_field, options: PQC_CONDITION.join('\n') },
				data[cond_field] || 'Good', function () { data[cond_field] = $(this).val(); });
			this._mk_cell($tr, '.c-dmg', key, idx, { fieldtype: 'Check', fieldname: dmg_field },
				data[dmg_field], function () { data[dmg_field] = cint($(this).prop('checked')); });
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'damaged_qty' },
				data.damaged_qty, function () { data.damaged_qty = flt($(this).val()); });
			this._mk_cell($tr, '.c-reason', key, idx, { fieldtype: 'Data', fieldname: 'damage_reason' },
				data.damage_reason, function () { data.damage_reason = $(this).val(); });
			this._mk_cell($tr, '.c-att', key, idx, { fieldtype: 'Attach', fieldname: 'attachment' },
				data.attachment, function () { data.attachment = $(this).val(); });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'inspector_remarks' },
				data.inspector_remarks, function () { data.inspector_remarks = $(this).val(); });

		} else if (key === 'sample') {
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-item"></td><td class="c-line"></td><td class="c-sbatch"></td>
				<td class="c-ibatch"></td><td class="c-qty"></td><td class="c-id"></td>
				<td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-item', key, idx,
				{ fieldtype: 'Link', fieldname: 'item_code', options: 'Item' },
				data.item_code, function () { data.item_code = $(this).val(); });
			this._mk_cell($tr, '.c-line', key, idx,
				{ fieldtype: 'Select', fieldname: 'qc_item_idx', options: '\n' + this._item_options() },
				data.qc_item_idx, function () { data.qc_item_idx = $(this).val(); });
			this._mk_cell($tr, '.c-sbatch', key, idx, { fieldtype: 'Data', fieldname: 'supplier_batch_no' },
				data.supplier_batch_no, function () { data.supplier_batch_no = $(this).val(); });
			this._mk_cell($tr, '.c-ibatch', key, idx,
				{ fieldtype: 'Data', fieldname: 'internal_batch_no', read_only: 1 }, data.internal_batch_no);
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'sample_qty' },
				data.sample_qty, function () { data.sample_qty = flt($(this).val()); });
			this._mk_cell($tr, '.c-id', key, idx,
				{ fieldtype: 'Data', fieldname: 'sample_id', read_only: 1 }, data.sample_id);
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'remarks' },
				data.remarks, function () { data.remarks = $(this).val(); });

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
				data.section || 'Vehicle', function () { data.section = $(this).val(); });
			this._mk_cell($tr, '.c-file', key, idx, { fieldtype: 'Attach', fieldname: 'file' },
				data.file, function () { data.file = $(this).val(); });
			this._mk_cell($tr, '.c-kind', key, idx,
				{ fieldtype: 'Select', fieldname: 'kind', options: 'Photo\nVideo\nDocument' },
				data.kind || 'Photo', function () { data.kind = $(this).val(); });
			this._mk_cell($tr, '.c-item', key, idx,
				{ fieldtype: 'Link', fieldname: 'item_code', options: 'Item' },
				data.item_code, function () { data.item_code = $(this).val(); });
			this._mk_cell($tr, '.c-desc', key, idx, { fieldtype: 'Data', fieldname: 'description' },
				data.description, function () { data.description = $(this).val(); });

		} else if (key === 'control') {
			$tr = $(`<tr data-idx="${idx}"><td class="text-muted">${idx + 1}</td>
				<td class="c-taken"></td><td class="c-item"></td><td class="c-line"></td>
				<td class="c-batch"></td><td class="c-qty"></td><td class="c-loc"></td>
				<td class="c-retain"></td><td class="c-rem"></td>${del}</tr>`);
			$body.append($tr);
			this._mk_cell($tr, '.c-taken', key, idx,
				{ fieldtype: 'Check', fieldname: 'control_sample_taken' },
				data.control_sample_taken === undefined ? 1 : data.control_sample_taken,
				function () { data.control_sample_taken = cint($(this).prop('checked')); });
			this._mk_cell($tr, '.c-item', key, idx,
				{ fieldtype: 'Link', fieldname: 'item_code', options: 'Item' },
				data.item_code, function () { data.item_code = $(this).val(); });
			this._mk_cell($tr, '.c-line', key, idx,
				{ fieldtype: 'Select', fieldname: 'qc_item_idx', options: '\n' + this._item_options() },
				data.qc_item_idx, function () { data.qc_item_idx = $(this).val(); });
			this._mk_cell($tr, '.c-batch', key, idx, { fieldtype: 'Data', fieldname: 'batch_no' },
				data.batch_no, function () { data.batch_no = $(this).val(); });
			this._mk_cell($tr, '.c-qty', key, idx, { fieldtype: 'Float', fieldname: 'control_sample_qty' },
				data.control_sample_qty, function () { data.control_sample_qty = flt($(this).val()); });
			this._mk_cell($tr, '.c-loc', key, idx,
				{ fieldtype: 'Link', fieldname: 'storage_location', options: 'Warehouse' },
				data.storage_location, function () { data.storage_location = $(this).val(); });
			this._mk_cell($tr, '.c-retain', key, idx, { fieldtype: 'Date', fieldname: 'retention_until' },
				data.retention_until, function () { data.retention_until = $(this).val(); });
			this._mk_cell($tr, '.c-rem', key, idx, { fieldtype: 'Data', fieldname: 'remarks' },
				data.remarks, function () { data.remarks = $(this).val(); });
		}
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
				<td class="c-result text-muted">${frappe.utils.escape_html(row.qc_result || '')}</td>
			</tr>`);
			$body.append($tr);

			me._mk_cell($tr, '.c-appr', 'decision', idx,
				{ fieldtype: 'Float', fieldname: 'approved_qty' }, row.approved_qty,
				function () { row.approved_qty = flt($(this).val()); me.recalc_totals(); });
			me._mk_cell($tr, '.c-rej', 'decision', idx,
				{ fieldtype: 'Float', fieldname: 'rejected_qty' }, row.rejected_qty,
				function () { row.rejected_qty = flt($(this).val()); me.recalc_totals(); });
			me._mk_cell($tr, '.c-reason', 'decision', idx,
				{ fieldtype: 'Data', fieldname: 'rejection_reason' }, row.rejection_reason,
				function () { row.rejection_reason = $(this).val(); });
		});
		this.recalc_totals();
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
				].forEach((f) => me._set(f, doc[f]));

				me.tables.decision = (doc.items || []).slice();
				me.render_decision();

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

				me.apply_state();
				me.page.set_title(`${doc.name} — Purchase QC`);
			},
		});
	}

	apply_state() {
		const doc = this.doc || {};
		this.wrapper.find('.field-stage-badge').text(doc.qc_status || '');

		const $sla = this.wrapper.find('.field-sla-badge');
		if (doc.sla_due) {
			const breached = cint(doc.sla_breached);
			$sla.text(breached ? `SLA breached (due ${doc.sla_due})` : `SLA due ${doc.sla_due}`)
				.toggleClass('pqc-breached', !!breached);
		} else {
			$sla.text('');
		}

		// Everything is read-only once the inspection is submitted.
		const locked = cint(doc.docstatus) !== 0;
		this.wrapper.find('.pqc-section').toggleClass('pqc-locked', locked);
		this.wrapper.find('.decision-table').closest('.eso-card').toggleClass('pqc-locked', locked);
		this.make_actions();
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
		const btn = (label, cls, handler) => {
			$(`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`)
				.on('click', handler)
				.appendTo($bar);
		};

		if (cint(doc.docstatus) === 0) {
			btn(__('Save'), 'btn-primary', () => me.save());
			btn(__('Complete QC'), 'btn-primary', () => {
				frappe.confirm(__('Submit this inspection? The GRN is drafted from it.'), () => {
					frappe.call({
						method: 'alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.complete_qc',
						args: { purchase_qc: me.docname },
						freeze: true,
						freeze_message: __('Completing QC...'),
						callback() {
							me._toast(__('QC completed'), 'green');
							me.load(me.docname);
						},
					});
				});
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

	save() {
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
				});
				frappe.call({
					method: 'frappe.client.save',
					args: { doc: doc },
					freeze: true,
					freeze_message: __('Saving...'),
					callback(r) {
						if (!r.message) return;
						me._toast(__('Saved'), 'green');
						me.load(r.message.name);
					},
				});
			},
		});
	}
};
