/**
 * Purchase Inward Entry — BRD "Purchase Inward Part -1", section 2 (Screen Layout).
 *
 * One screen shared by two teams (BR-PI-01): Purchase fills the header and the item
 * lines against an approved Purchase Order, Store records the physical receipt and
 * hands it to QC. Which half is editable is decided by the SERVER
 * (inward_api.get_form_context -> roles.get_section_access), never by this file — the
 * dimming here is only so each team can see whose turn it is.
 *
 * Design language matches the other alpinos entry pages (sales_order_entry): eso-card /
 * eso-card-title / eso-subtitle / eso-fld / alp-scroll / alp-actions, all defined in
 * public/css/alpinos_pages.css, which scopes on data-page-route.
 */

frappe.pages['purchase_inward_entry'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase Inward Entry',
		single_column: true,
	});
	page.main.html(frappe.render_template('purchase_inward_entry'));
	wrapper.piw_entry = new PurchaseInwardEntry(page);
};

// Fires on every visit; the route decides whether we open blank or load a document.
frappe.pages['purchase_inward_entry'].on_page_show = function (wrapper) {
	if (wrapper.piw_entry) wrapper.piw_entry.handle_route_entry();
};

var PIW_INWARD_TYPES = ['RM', 'PM', 'FG', 'MM'];

var PurchaseInwardEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.items = [];
		this.attachments = [];
		this.docname = null;
		this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
		this.setup();
	}

	setup() {
		this.make_header_fields();
		this.make_receiving_fields();
		this.make_totals();
		this.bind_events();
		this.apply_context();
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
		control.set_value(value === undefined ? '' : value);
		control.refresh();
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
			c.set_value(value === undefined || value === null ? '' : value);
			c.refresh();
		}
	}

	_toast(message, indicator) {
		frappe.show_alert({ message: message, indicator: indicator || 'blue' }, 5);
	}

	// ------------------------------------------------------- BRD 2.1.1 header

	make_header_fields() {
		const me = this;

		this._ctl('.field-purchase-order', {
			fieldname: 'purchase_order',
			label: 'Purchase Order',
			fieldtype: 'Link',
			options: 'Purchase Order',
			reqd: 1,
			// VAL-PO-15 / VAL-PO-13: only an approved, non-direct-invoice PO can be inwarded.
			get_query: () => ({
				filters: {
					docstatus: 1,
					custom_direct_purchase_invoice: 0,
					status: ['not in', ['Closed', 'On Hold']],
				},
			}),
			change: () => me.on_purchase_order_change(),
		});

		this._ctl('.field-inward-type', {
			fieldname: 'inward_type',
			label: 'Inward Type',
			fieldtype: 'Select',
			options: [''].concat(PIW_INWARD_TYPES).join('\n'),
			// BRD 2.1.1 "Auto Fetch" — the server forces it to the PO's type anyway.
			read_only: 1,
		});
		this._ctl('.field-supplier', {
			fieldname: 'supplier',
			label: 'Vendor',
			fieldtype: 'Link',
			options: 'Supplier',
			read_only: 1,
		});
		this._ctl('.field-supplier-order-no', {
			fieldname: 'supplier_order_no',
			label: 'Supplier Order No.',
			fieldtype: 'Data',
			read_only: 1,
		});
		this._ctl('.field-invoice-number', {
			fieldname: 'invoice_number',
			label: 'Invoice Number',
			fieldtype: 'Data',
			reqd: 1,
			description: 'Unique per vendor (BR-PI-15).',
		});
		this._ctl('.field-invoice-date', {
			fieldname: 'invoice_date',
			label: 'Invoice Date',
			fieldtype: 'Date',
		});
		this._ctl('.field-challan-no', {
			fieldname: 'challan_no',
			label: 'Challan / DC No.',
			fieldtype: 'Data',
		});
		this._ctl('.field-gross-weight', {
			fieldname: 'gross_weight',
			label: 'Gross Weight',
			fieldtype: 'Float',
		});
		this._ctl('.field-inward-datetime', {
			fieldname: 'inward_datetime',
			label: 'Inward Date & Time',
			fieldtype: 'Datetime',
		}, frappe.datetime.now_datetime());
		this._ctl('.field-attachment', {
			fieldname: 'attachment',
			label: 'Attachment',
			fieldtype: 'Attach',
		});
		this._ctl('.field-remarks', {
			fieldname: 'remarks',
			label: 'Remarks',
			fieldtype: 'Small Text',
		});
	}

	on_purchase_order_change() {
		const po = this._val('purchase_order');
		if (!po) return;
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_purchase_order_items',
			args: { purchase_order: po },
			callback(r) {
				if (!r.message) return;
				const d = r.message;
				me._set('inward_type', d.inward_type);
				me._set('supplier', d.supplier);
				me.company = d.company;
				frappe.db.get_value('Purchase Order', po, [
					'custom_supplier_order_no',
					'custom_vehicle_no',
					'custom_driver_contact_no',
				]).then((res) => {
					const v = (res && res.message) || {};
					me._set('supplier_order_no', v.custom_supplier_order_no);
					me._set('po_vehicle_no', v.custom_vehicle_no);
					me._set('po_driver_contact_no', v.custom_driver_contact_no);
				});
				if (!me.items.length) me.load_items(d.items || [], d.skipped || []);
			},
		});
	}

	load_items(rows, skipped) {
		this.items = [];
		this.wrapper.find('.items-table tbody').empty();
		(rows || []).forEach((row) => this.add_item_row(row));
		this.render_receiving_rows();
		this.recalc_totals();
		if (skipped && skipped.length) {
			this._toast(
				`${skipped.length} Purchase Order line(s) were not offered (fully received or a different inward type).`,
				'orange'
			);
		}
	}

	// -------------------------------------------------------- BRD 2.2.2 grid

	add_item_row(data) {
		data = data || {};
		const idx = this.items.length;
		const row = Object.assign(
			{
				item_code: '',
				item_name: '',
				stock_uom: '',
				order_qty: 0,
				previously_received_qty: 0,
				pending_qty: 0,
				received_qty: 0,
				excess_qty: 0,
				po_detail: '',
				target_warehouse: '',
				batch_no: '',
				manufacturing_date: '',
				expiry_date: '',
				mrp: 0,
				usp: '',
				item_remarks: '',
			},
			data
		);
		this.items.push(row);

		const $tr = $(`
			<tr data-idx="${idx}">
				<td class="text-muted">${idx + 1}</td>
				<td class="cell-item-code"></td>
				<td class="cell-item-name"></td>
				<td class="cell-uom"></td>
				<td class="piw-num cell-order-qty"></td>
				<td class="piw-num cell-prev-qty"></td>
				<td class="piw-num cell-pending-qty"></td>
				<td class="cell-remarks"></td>
				<td class="text-center">
					<button class="btn btn-xs btn-link btn-remove-row" title="Remove">
						<i class="fa fa-trash text-danger"></i>
					</button>
				</td>
			</tr>
		`);
		this.wrapper.find('.items-table tbody').append($tr);

		$tr.find('.cell-item-code').text(row.item_code || '');
		$tr.find('.cell-item-name').text(row.item_name || '');
		$tr.find('.cell-uom').text(row.stock_uom || '');
		$tr.find('.cell-order-qty').text(format_number(row.order_qty, null, 2));
		$tr.find('.cell-prev-qty').text(format_number(row.previously_received_qty, null, 2));
		$tr.find('.cell-pending-qty').text(format_number(row.pending_qty, null, 2));

		const me = this;
		const remarks = frappe.ui.form.make_control({
			df: { fieldname: `item_remarks_${idx}`, fieldtype: 'Data', placeholder: 'Remarks' },
			parent: $tr.find('.cell-remarks'),
			render_input: true,
		});
		remarks.set_value(row.item_remarks || '');
		remarks.$input && remarks.$input.on('change', function () {
			me.items[idx].item_remarks = $(this).val();
		});
	}

	// ------------------------------------------------- BRD 2.2.1 store fields

	make_receiving_fields() {
		const me = this;
		this._ctl('.field-po-vehicle-no', {
			fieldname: 'po_vehicle_no', label: 'Planned Vehicle (PO)',
			fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-po-driver-contact', {
			fieldname: 'po_driver_contact_no', label: 'Planned Driver (PO)',
			fieldtype: 'Data', read_only: 1,
		});
		this._ctl('.field-actual-vehicle-no', {
			fieldname: 'actual_vehicle_no', label: 'Actual Vehicle No.', fieldtype: 'Data',
		});
		this._ctl('.field-actual-driver-contact', {
			fieldname: 'actual_driver_contact_no', label: 'Actual Driver Contact',
			fieldtype: 'Data',
		});
		this._ctl('.field-actual-arrival', {
			fieldname: 'actual_arrival_datetime', label: 'Actual Arrival Date & Time',
			fieldtype: 'Datetime',
		});
		this._ctl('.field-vehicle-verified', {
			fieldname: 'vehicle_details_verified', label: 'Vehicle Details Verified',
			fieldtype: 'Check',
			// VAL-PI-05: ticking it means the fetched details were WRONG, so the corrected
			// ones become mandatory. Left unticked, the PO's details are accepted as-is.
			description: 'Tick only if the actual vehicle/driver differ from the PO.',
		});
		this._ctl('.field-allow-excess', {
			fieldname: 'allow_excess_qty', label: 'Allow Excess Quantity',
			fieldtype: 'Check',
			description: 'BR-PI-14 — receive more than the pending quantity.',
			change: () => me.recalc_totals(),
		});
		this._ctl('.field-target-warehouse', {
			fieldname: 'target_warehouse', label: 'Default Target Location',
			fieldtype: 'Link', options: 'Warehouse',
			change: () => me.apply_default_warehouse(),
		});
		this._ctl('.field-receiving-remarks', {
			fieldname: 'receiving_remarks', label: 'Receiving Remarks', fieldtype: 'Small Text',
		});

		// dispute evidence (task 301)
		this._ctl('.field-dispute-file', {
			fieldname: 'dispute_file', label: 'File', fieldtype: 'Attach',
		});
		this._ctl('.field-dispute-kind', {
			fieldname: 'dispute_kind', label: 'Kind', fieldtype: 'Select',
			options: ['Photo', 'Video', 'Document'].join('\n'),
		}, 'Photo');
		this._ctl('.field-dispute-description', {
			fieldname: 'dispute_description', label: 'Description', fieldtype: 'Data',
		});
	}

	apply_default_warehouse() {
		const wh = this._val('target_warehouse');
		if (!wh) return;
		this.items.forEach((row, idx) => {
			if (!row.target_warehouse) {
				row.target_warehouse = wh;
				const c = this.fields[`target_warehouse_${idx}`];
				if (c) c.set_value(wh);
			}
		});
	}

	render_receiving_rows() {
		const me = this;
		const $body = this.wrapper.find('.receiving-table tbody').empty();

		this.items.forEach((row, idx) => {
			const $tr = $(`
				<tr data-idx="${idx}">
					<td class="text-muted">${idx + 1}</td>
					<td>${frappe.utils.escape_html(row.item_code || '')}<br>
						<span class="text-muted" style="font-size:11px;">
							${frappe.utils.escape_html(row.item_name || '')}</span></td>
					<td class="piw-num cell-pending">${format_number(row.pending_qty, null, 2)}</td>
					<td class="cell-received"></td>
					<td class="piw-num cell-excess">0</td>
					<td class="cell-warehouse"></td>
					<td class="cell-batch"></td>
					<td class="cell-mfg"></td>
					<td class="cell-expiry"></td>
					<td class="cell-mrp"></td>
					<td class="cell-usp"></td>
				</tr>
			`);
			$body.append($tr);

			const mk = (sel, df, value, onchange) => {
				const c = frappe.ui.form.make_control({
					df: Object.assign({ fieldname: `${df.fieldname}_${idx}` }, df),
					parent: $tr.find(sel),
					render_input: true,
				});
				c.set_value(value === undefined || value === null ? '' : value);
				me.fields[`${df.fieldname}_${idx}`] = c;
				if (onchange && c.$input) c.$input.on('change', onchange);
				return c;
			};

			mk('.cell-received', { fieldtype: 'Float', fieldname: 'received_qty' },
				row.received_qty, function () {
					me.items[idx].received_qty = flt($(this).val());
					me.recalc_row(idx);
					me.recalc_totals();
				});
			mk('.cell-warehouse', { fieldtype: 'Link', fieldname: 'target_warehouse', options: 'Warehouse' },
				row.target_warehouse, function () {
					me.items[idx].target_warehouse = $(this).val();
				});
			mk('.cell-batch', { fieldtype: 'Data', fieldname: 'batch_no' },
				row.batch_no, function () { me.items[idx].batch_no = $(this).val(); });
			mk('.cell-mfg', { fieldtype: 'Date', fieldname: 'manufacturing_date' },
				row.manufacturing_date, function () {
					me.items[idx].manufacturing_date = $(this).val();
				});
			// Expiry is derived server-side from Item.shelf_life_in_days; shown read-only
			// so the Store user can see what will be stored.
			mk('.cell-expiry', { fieldtype: 'Date', fieldname: 'expiry_date', read_only: 1 },
				row.expiry_date);
			mk('.cell-mrp', { fieldtype: 'Currency', fieldname: 'mrp' },
				row.mrp, function () { me.items[idx].mrp = flt($(this).val()); });
			mk('.cell-usp', { fieldtype: 'Data', fieldname: 'usp' },
				row.usp, function () { me.items[idx].usp = $(this).val(); });
		});
	}

	recalc_row(idx) {
		const row = this.items[idx];
		const over = flt(row.received_qty) - flt(row.pending_qty);
		row.excess_qty = over > 0 ? over : 0;
		const $tr = this.wrapper.find(`.receiving-table tbody tr[data-idx="${idx}"]`);
		$tr.find('.cell-excess').text(format_number(row.excess_qty, null, 2));
		$tr.toggleClass('text-danger', row.excess_qty > 0 && !cint(this._val('allow_excess_qty')));
	}

	// ------------------------------------------------------------- totals

	make_totals() {
		[
			['total-order-qty', 'total_order_qty', 'Total Order Qty'],
			['total-received-qty', 'total_received_qty', 'Total Received Qty'],
			['total-pending-qty', 'total_pending_qty', 'Total Pending Qty'],
			['total-excess-qty', 'total_excess_qty', 'Total Excess Qty'],
		].forEach(([sel, fieldname, label]) => {
			this._ctl(`.field-${sel}`, {
				fieldname: fieldname, label: label, fieldtype: 'Float', read_only: 1,
			}, 0);
		});
	}

	recalc_totals() {
		let order = 0, received = 0, pending = 0, excess = 0;
		this.items.forEach((row, idx) => {
			this.recalc_row(idx);
			order += flt(row.order_qty);
			received += flt(row.received_qty);
			pending += flt(row.pending_qty);
			excess += flt(row.excess_qty);
		});
		this._set('total_order_qty', order);
		this._set('total_received_qty', received);
		this._set('total_pending_qty', pending);
		this._set('total_excess_qty', excess);
	}

	// ----------------------------------------------------------- attachments

	add_attachment_row(data) {
		const idx = this.attachments.length;
		this.attachments.push(data);
		const $tr = $(`
			<tr data-idx="${idx}">
				<td class="text-muted">${idx + 1}</td>
				<td><a href="${frappe.utils.escape_html(data.file)}" target="_blank">
					${frappe.utils.escape_html(data.file)}</a></td>
				<td>${frappe.utils.escape_html(data.kind || '')}</td>
				<td>${frappe.utils.escape_html(data.description || '')}</td>
				<td class="text-muted">${frappe.utils.escape_html(data.uploaded_by || frappe.session.user)}</td>
				<td class="text-center">
					<button class="btn btn-xs btn-link btn-remove-attachment" title="Remove">
						<i class="fa fa-trash text-danger"></i>
					</button>
				</td>
			</tr>
		`);
		this.wrapper.find('.attachments-table tbody').append($tr);
	}

	// --------------------------------------------------------------- events

	bind_events() {
		const me = this;

		this.wrapper.on('click', '.btn-get-items', () => {
			const po = me._val('purchase_order');
			if (!po) {
				frappe.msgprint(__('Please select a Purchase Order first.'));
				return;
			}
			frappe.call({
				method: 'alpinos.purchase.inward_api.get_purchase_order_items',
				args: { purchase_order: po, purchase_inward: me.docname || undefined },
				freeze: true,
				freeze_message: __('Fetching Purchase Order lines...'),
				callback(r) {
					if (r.message) me.load_items(r.message.items || [], r.message.skipped || []);
				},
			});
		});

		this.wrapper.on('click', '.btn-add-row', () => {
			me.add_item_row({});
			me.render_receiving_rows();
		});

		this.wrapper.on('click', '.btn-remove-row', function () {
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.items.splice(idx, 1);
			me.redraw_items();
		});

		this.wrapper.on('click', '.btn-add-attachment', () => {
			const file = me._val('dispute_file');
			if (!file) {
				frappe.msgprint(__('Please attach a file first.'));
				return;
			}
			me.add_attachment_row({
				file: file,
				kind: me._val('dispute_kind'),
				description: me._val('dispute_description'),
			});
			me._set('dispute_file', '');
			me._set('dispute_description', '');
		});

		this.wrapper.on('click', '.btn-remove-attachment', function () {
			const idx = cint($(this).closest('tr').attr('data-idx'));
			me.attachments.splice(idx, 1);
			me.redraw_attachments();
		});
	}

	redraw_items() {
		const rows = this.items.slice();
		this.items = [];
		this.wrapper.find('.items-table tbody').empty();
		rows.forEach((r) => this.add_item_row(r));
		this.render_receiving_rows();
		this.recalc_totals();
	}

	redraw_attachments() {
		const rows = this.attachments.slice();
		this.attachments = [];
		this.wrapper.find('.attachments-table tbody').empty();
		rows.forEach((r) => this.add_attachment_row(r));
	}

	// ----------------------------------------------------------- route / load

	handle_route_entry() {
		const route = frappe.get_route() || [];
		const name = route[1] || (frappe.route_options && frappe.route_options.purchase_inward);
		if (frappe.route_options) delete frappe.route_options.purchase_inward;
		if (name && name !== this.docname) {
			this.load(name);
		} else if (!name && this.docname) {
			this.reset();
		}
	}

	//: Header + receiving controls that live in the template and are never destroyed.
	//  Per-ROW controls are keyed "<field>_<idx>" and their DOM is emptied when the grids
	//  are cleared, so calling set_value on them afterwards operates on detached inputs.
	//  reset() therefore clears the standing fields only and drops the row controls.
	static get STANDING_FIELDS() {
		return [
			'purchase_order', 'inward_type', 'supplier', 'supplier_order_no',
			'invoice_number', 'invoice_date', 'challan_no', 'gross_weight',
			'inward_datetime', 'attachment', 'remarks',
			'po_vehicle_no', 'po_driver_contact_no', 'actual_vehicle_no',
			'actual_driver_contact_no', 'actual_arrival_datetime',
			'vehicle_details_verified', 'allow_excess_qty', 'target_warehouse',
			'receiving_remarks', 'dispute_file', 'dispute_kind', 'dispute_description',
			'total_order_qty', 'total_received_qty', 'total_pending_qty', 'total_excess_qty',
		];
	}

	reset() {
		this.docname = null;
		this.company = null;
		this.items = [];
		this.attachments = [];
		this.wrapper.find('.items-table tbody, .receiving-table tbody, .attachments-table tbody').empty();

		const standing = PurchaseInwardEntry.STANDING_FIELDS;
		Object.keys(this.fields).forEach((k) => {
			if (standing.indexOf(k) === -1) delete this.fields[k];
		});
		standing.forEach((k) => this._set(k, ''));

		this._set('inward_datetime', frappe.datetime.now_datetime());
		this._set('dispute_kind', 'Photo');
		this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
		this.page.set_title(__('Purchase Inward Entry'));
		this.apply_context();
	}

	load(name) {
		const me = this;
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Inward', name: name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = r.message;
				me.docname = doc.name;
				me.company = doc.company;

				[
					'purchase_order', 'inward_type', 'supplier', 'supplier_order_no',
					'invoice_number', 'invoice_date', 'challan_no', 'gross_weight',
					'inward_datetime', 'attachment', 'remarks', 'po_vehicle_no',
					'po_driver_contact_no', 'actual_vehicle_no', 'actual_driver_contact_no',
					'actual_arrival_datetime', 'vehicle_details_verified', 'allow_excess_qty',
					'target_warehouse', 'receiving_remarks',
				].forEach((f) => me._set(f, doc[f]));

				me.items = [];
				me.wrapper.find('.items-table tbody').empty();
				(doc.items || []).forEach((row) => me.add_item_row(row));
				me.render_receiving_rows();

				me.attachments = [];
				me.wrapper.find('.attachments-table tbody').empty();
				(doc.dispute_attachments || []).forEach((row) => me.add_attachment_row(row));

				me.recalc_totals();
				me.refresh_context();
				me.page.set_title(`${doc.name} — Purchase Inward`);
			},
		});
	}

	refresh_context() {
		if (!this.docname) {
			this.ctx = { status: 'Draft', docstatus: 0, actions: [], sections: {} };
			this.apply_context();
			return;
		}
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_api.get_form_context',
			args: { name: this.docname },
			callback(r) {
				if (r.message) me.ctx = r.message;
				me.apply_context();
			},
		});
	}

	// ------------------------------------------------- server-driven gating

	apply_context() {
		const ctx = this.ctx || {};
		const status = ctx.status || 'Draft';

		this.wrapper.find('.field-stage-badge').text(status);
		this.wrapper.find('.field-receiving-badge').text(
			ctx.docstatus === 1 ? 'Store' : 'awaiting submit'
		);

		// The server owns the decision; this only reflects it.
		const header_open = ctx.header_editable !== false && cint(ctx.docstatus) === 0;
		this.wrapper.find('.piw-header').toggleClass('piw-locked', !header_open);
		this.wrapper.find('.items-table').closest('.eso-card').toggleClass('piw-locked', !header_open);

		const receiving = (ctx.sections || {}).receiving;
		const receiving_open = receiving ? receiving.editable !== false : cint(ctx.docstatus) === 1;
		this.wrapper.find('.piw-receiving').toggleClass('piw-locked', !receiving_open);

		this.make_actions();
	}

	make_actions() {
		const me = this;
		const $bar = this.wrapper.find('.piw-actionbar').empty();
		const btn = (label, cls, handler, disabled, reason) => {
			const $b = $(
				`<button class="btn btn-sm ${cls}" style="margin-left:8px;">${frappe.utils.escape_html(label)}</button>`
			);
			if (disabled) {
				$b.prop('disabled', true);
				if (reason) $b.attr('title', reason);
			} else {
				$b.on('click', handler);
			}
			$bar.append($b);
			return $b;
		};

		if (cint(this.ctx.docstatus) === 0) {
			btn(__('Save'), 'btn-primary', () => me.save(false));
			if (this.docname) btn(__('Submit'), 'btn-primary', () => me.save(true));
			if (this.docname) {
				btn(__('Cancel'), 'btn-default', () => {
					frappe.confirm(__('Discard this draft Purchase Inward?'), () => {
						frappe.call({
							method: 'alpinos.purchase.inward_api.cancel_draft',
							args: { purchase_inward: me.docname },
							callback() {
								me._toast(__('Draft discarded'), 'orange');
								frappe.set_route('purchase_inward_list');
							},
						});
					});
				});
			}
		} else {
			btn(__('Save Receipt'), 'btn-primary', () => me.save(false));
		}

		// Workflow transitions, exactly as the engine reports them (task 295 / BRD 1.4).
		(this.ctx.actions || []).forEach((action) => {
			if (action.kind !== 'transition' || action.action === 'submit') return;
			btn(
				action.label,
				'btn-default',
				() => me.run_action(action.action, action.label),
				!action.enabled,
				action.reason
			);
		});

		if (this.docname) {
			btn(__('Print'), 'btn-default', () => {
				frappe.set_route('print', 'Purchase Inward', me.docname);
			});
		}
	}

	run_action(action, label) {
		const me = this;
		frappe.confirm(__('Run "{0}" on {1}?', [label, this.docname]), () => {
			frappe.call({
				method: 'alpinos.purchase.inward_api.run_action',
				args: { purchase_inward: me.docname, action: action },
				freeze: true,
				freeze_message: __('Working...'),
				callback(r) {
					me._toast(__('{0} done', [label]), 'green');
					me.load(me.docname);
					if (r.message && r.message.inward_status) {
						me.ctx.status = r.message.inward_status;
					}
				},
			});
		});
	}

	// ----------------------------------------------------------------- save

	collect_doc() {
		const doc = {
			doctype: 'Purchase Inward',
			purchase_order: this._val('purchase_order'),
			invoice_number: this._val('invoice_number'),
			invoice_date: this._val('invoice_date'),
			challan_no: this._val('challan_no'),
			gross_weight: flt(this._val('gross_weight')),
			inward_datetime: this._val('inward_datetime'),
			attachment: this._val('attachment'),
			remarks: this._val('remarks'),
			actual_vehicle_no: this._val('actual_vehicle_no'),
			actual_driver_contact_no: this._val('actual_driver_contact_no'),
			actual_arrival_datetime: this._val('actual_arrival_datetime'),
			vehicle_details_verified: cint(this._val('vehicle_details_verified')),
			allow_excess_qty: cint(this._val('allow_excess_qty')),
			target_warehouse: this._val('target_warehouse'),
			receiving_remarks: this._val('receiving_remarks'),
			items: this.items.map((row) => ({
				item_code: row.item_code,
				po_detail: row.po_detail,
				received_qty: flt(row.received_qty),
				target_warehouse: row.target_warehouse,
				batch_no: row.batch_no,
				manufacturing_date: row.manufacturing_date || null,
				mrp: flt(row.mrp),
				usp: row.usp,
				item_remarks: row.item_remarks,
			})),
			dispute_attachments: this.attachments.map((a) => ({
				file: a.file, kind: a.kind, description: a.description,
			})),
		};
		if (this.docname) doc.name = this.docname;
		if (this.company) doc.company = this.company;
		return doc;
	}

	save(then_submit) {
		const me = this;
		if (!this._val('purchase_order')) {
			frappe.msgprint(__('Please select a Purchase Order.'));
			return;
		}
		if (!this.items.length) {
			frappe.msgprint(__('Please add at least one item to the Purchase Inward.'));
			return;
		}

		const finish = (name) => {
			me.docname = name;
			me._toast(then_submit ? __('Submitted') : __('Saved'), 'green');
			me.load(name);
		};

		if (!this.docname) {
			frappe.call({
				method: 'frappe.client.insert',
				args: { doc: this.collect_doc() },
				freeze: true,
				freeze_message: __('Saving...'),
				callback(r) {
					if (!r.message) return;
					if (then_submit) me.submit_doc(r.message.name, finish);
					else finish(r.message.name);
				},
			});
			return;
		}

		// Update in place: frappe.client.get -> apply -> save keeps the doc's own
		// validate()/before_update_after_submit() gates in charge.
		frappe.call({
			method: 'frappe.client.get',
			args: { doctype: 'Purchase Inward', name: this.docname },
			callback(g) {
				if (!g.message) return;
				const doc = Object.assign({}, g.message, me.collect_doc());
				frappe.call({
					method: 'frappe.client.save',
					args: { doc: doc },
					freeze: true,
					freeze_message: __('Saving...'),
					callback(r) {
						if (!r.message) return;
						if (then_submit) me.submit_doc(r.message.name, finish);
						else finish(r.message.name);
					},
				});
			},
		});
	}

	submit_doc(name, done) {
		frappe.call({
			method: 'alpinos.purchase.inward_api.run_action',
			args: { purchase_inward: name, action: 'submit' },
			freeze: true,
			freeze_message: __('Submitting...'),
			callback() { done(name); },
		});
	}
};
