// Purchase Order list screen — BRD "Purchase Inward Part -1" sections 1.2 - 1.4.
//
// Filtering, counting, sorting and paging all happen on the server
// (alpinos.purchase.po_list_api.get_purchase_order_list), and so do the row buttons:
// the approval transitions come from the same table the PO form and perform_action use,
// so this list can never offer an action the server would refuse. A button that exists
// but is not yet available (Create Inward before Send to Supplier) is drawn disabled with
// the reason as its tooltip, rather than hidden.
//
// Two views share one table. With no SKU Code the rows are orders (BRD 1.2); with an SKU
// Code they become that SKU's receiving position per order (BRD 1.2.1 "SKU Code Filter
// Behavior"), which is what lets a user see which order still has that item pending.

frappe.pages['purchase_order_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Purchase Orders'),
		single_column: true,
	});
	pol_load_options(function (options) {
		wrapper.__pol_list_page = new PurchaseOrderListPage(page, options);
	});
};

// Frappe caches custom pages, so on_page_load runs once: re-render the body on every
// show, or coming back from an order leaves a stale list. The toolbar is built once only.
frappe.pages['purchase_order_list'].on_page_show = function (wrapper) {
	if (wrapper.__pol_list_page) wrapper.__pol_list_page.render_body();
};

// Route key for alpinos.list_prefs — must stay the exact frappe.pages key.
var POL_LIST_ROUTE = 'purchase_order_list';
var POL_PAGE_LENGTHS = [20, 50, 100];

var POL_FALLBACK_OPTIONS = {
	po_types: [
		{ value: '', label: '' },
		{ value: 'RM', label: 'RM' },
		{ value: 'PM', label: 'PM' },
		{ value: 'FG', label: 'FG' },
		{ value: 'MM', label: 'MM' },
	],
	current_statuses:
		'\nDraft\nPending Approval\nApproved\nRejected\nSent to Supplier' +
		'\nPartially Received\nFully Received\nClosed\nCancelled',
	approval_statuses: '\nDraft\nPending Approval\nApproved\nRejected\nSent to Supplier',
	receiving_statuses: '\nPending Receipt\nPartially Received\nFully Received',
	page_lengths: POL_PAGE_LENGTHS,
	can_create: 1,
};

var POL_STATUS_COLORS = {
	Draft: 'gray',
	'Pending Approval': 'orange',
	Approved: 'blue',
	Rejected: 'red',
	'Sent to Supplier': 'purple',
	'Partially Received': 'yellow',
	'Fully Received': 'green',
	Closed: 'darkgrey',
	Cancelled: 'red',
};

var POL_OPTIONS_CACHE = null;

function pol_load_options(callback) {
	if (POL_OPTIONS_CACHE) {
		callback(POL_OPTIONS_CACHE);
		return;
	}
	// `once`: the callback builds the page, and building it twice would duplicate the
	// toolbar buttons on the shared page header.
	let fired = false;
	const once = (options) => {
		if (fired) return;
		fired = true;
		callback(options);
	};
	frappe.call({
		method: 'alpinos.purchase.po_list_api.get_filter_options',
		callback: function (r) {
			POL_OPTIONS_CACHE = (r && r.message) || POL_FALLBACK_OPTIONS;
			once(POL_OPTIONS_CACHE);
		},
		error: function () {
			once(POL_FALLBACK_OPTIONS);
		},
	});
}

// BRD 1.2 columns in the BRD's order, plus the status and the buttons.
var POL_COLUMNS = [
	{ label: 'PO ID', sort: 'name', width: '10%', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
	{ label: 'PO Type', sort: 'custom_inward_type', width: '7%', render: (d, h) => h.type(d) },
	{ label: 'Vendor Name', sort: 'supplier_name', cls: 'pol-col-vendor', width: '12%', render: (d, h) => h.dash(d.supplier_name || d.supplier) },
	{ label: 'PO Date', sort: 'transaction_date', width: '7%', render: (d, h) => h.date(d.transaction_date) },
	{ label: 'PO Order Quantity', sort: 'total_qty', cls: 'text-right', width: '9%', render: (d, h) => h.order_qty(d) },
	{ label: 'Total Items', cls: 'text-right', width: '5%', render: (d, h) => h.dash(d.total_items) },
	{ label: 'PO Value', sort: 'grand_total', cls: 'text-right', width: '8%', render: (d, h) => h.money(d.po_value, d.currency) },
	{ label: 'Expected Delivery', sort: 'schedule_date', width: '8%', render: (d, h) => h.date(d.schedule_date) },
	{ label: 'Status', sort: 'custom_approval_status', width: '10%', render: (d, h) => h.status(d.current_status) },
	{ label: 'Actions', cls: 'pol-col-actions', width: '24%', render: (d, h) => h.actions(d) },
];

// BRD 1.2.1 "SKU Code Filter Behavior" example table.
var POL_SKU_COLUMNS = [
	{ label: 'PO ID', sort: 'name', width: '12%', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
	{ label: 'Vendor', sort: 'supplier_name', cls: 'pol-col-vendor', width: '17%', render: (d, h) => h.dash(d.supplier_name || d.supplier) },
	{ label: 'SKU Code', width: '14%', render: (d, h) => h.sku_code(d) },
	{ label: 'Ordered Qty', cls: 'text-right', width: '10%', render: (d, h) => h.qty(d.sku && d.sku.ordered_qty, d.sku && d.sku.uom) },
	{ label: 'Received Qty', cls: 'text-right', width: '10%', render: (d, h) => h.qty(d.sku && d.sku.received_qty, d.sku && d.sku.uom) },
	{ label: 'Pending Qty', cls: 'text-right', width: '10%', render: (d, h) => h.pending(d) },
	{ label: 'PO Status', sort: 'custom_approval_status', width: '12%', render: (d, h) => h.status(d.current_status) },
	{ label: 'Purchase Inward', cls: 'pol-col-actions', width: '15%', render: (d, h) => h.actions(d, true) },
];

// In the SKU view the last column is "Purchase Inward": only the buttons that move the
// order forward belong there, not View / Edit / the approval transitions.
var POL_SKU_ACTIONS = ['create_inward', 'create_invoice', 'view_invoice', 'view_inwards'];

function pol_body_html() {
	return `
<style>
	.pol-list-container { display: block; }
	.pol-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 10px 14px;
	}
	.pol-grid > * { min-width: 0; }
	.pol-viewbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
	.pol-viewbar-label { font-size: 12px; font-weight: 600; color: var(--text-muted, #6b7280); margin: 0; }
	.pol-mode { font-size: 12px; color: var(--text-muted, #6b7280); margin-left: auto; }
	.pol-mode b { color: var(--text-color, #1f272e); }
	.pol-page-length { width: auto; min-width: 72px; display: inline-block; }
	.pol-table-wrapper { padding: 0; overflow-x: auto; }
	.pol-table-wrapper > .pol-list-table {
		width: 100%;
		min-width: 1080px;
		margin-bottom: 0;
		font-size: 13px;
		border-collapse: collapse;
	}
	.pol-list-table th, .pol-list-table td {
		padding: 9px 12px;
		border-bottom: 1px solid var(--border-color, #e2e2e2);
		white-space: nowrap;
		vertical-align: middle;
	}
	.pol-list-table thead th {
		position: sticky;
		top: 0;
		z-index: 2;
		background: var(--card-bg, #fff);
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
		color: var(--text-muted, #6c7680);
	}
	.pol-list-table tbody tr.pol-list-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	.pol-list-table .indicator-pill {
		height: auto;
		min-height: 20px;
		white-space: nowrap;
		line-height: 1.3;
		padding: 3px 10px;
		border-radius: 100px;
		font-weight: 600;
	}
	/* Headers, vendor names and actions wrap instead of pushing the table past the card:
	   with nowrap the long headers alone (PO ORDER QUANTITY, EXPECTED DELIVERY) left the
	   Actions column off-screen. */
	.pol-list-table thead th { white-space: normal; line-height: 1.35; }
	.pol-list-table td.pol-col-vendor { white-space: normal; min-width: 120px; }
	.pol-list-table td.pol-col-actions { white-space: normal; min-width: 200px; }
	.pol-list-table td.pol-col-actions .btn { margin: 2px 4px 2px 0; }
	.pol-act-disabled { display: inline-block; }
	/* The quantity hover: BRD 1.2 "Add Hover icon on PO Order Quantity". */
	.pol-qty-hint {
		display: inline-flex; align-items: center; justify-content: center;
		width: 15px; height: 15px; margin-left: 6px;
		border-radius: 50%; border: 1px solid var(--border-color, #d1d8dd);
		font-size: 10px; font-weight: 700; line-height: 1;
		color: var(--text-muted, #6c7680); cursor: help; vertical-align: 1px;
	}
	.pol-direct { margin-left: 6px; font-size: 10px; font-weight: 600; letter-spacing: 0.02em; }
	.pol-pending-zero { color: var(--text-muted, #6c7680); }
	.pol-pager { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 12px; }
	.pol-nav { display: flex; align-items: center; gap: 10px; }
</style>

<div class="pol-list-container">
	<div class="pol-list-filters alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="pol-grid">
			<div class="fld-po-type"></div>
			<div class="fld-supplier"></div>
			<div class="fld-po-id"></div>
			<div class="fld-sku-code"></div>
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-delivery-from"></div>
			<div class="fld-delivery-to"></div>
			<div class="fld-current-status"></div>
			<div class="fld-approval-status"></div>
			<div class="fld-receiving-status"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-pol-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-pol-clear">${__('Clear')}</button>
			<span class="pol-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>

	<div class="pol-viewbar">
		<label class="pol-viewbar-label">${__('Rows per page')}</label>
		<select class="form-control input-xs pol-page-length"></select>
		<span class="pol-mode"></span>
	</div>

	<div class="pol-table-wrapper alp-card">
		<table class="pol-list-table">
			<thead><tr></tr></thead>
			<tbody></tbody>
		</table>
	</div>

	<div class="pol-pager">
		<div class="pol-count text-muted"></div>
		<div class="pol-nav">
			<button class="btn btn-default btn-sm btn-pol-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-pol-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseOrderListPage = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || POL_FALLBACK_OPTIONS;
		this.page_lengths = Array.isArray(this.options.page_lengths)
			? this.options.page_lengths.map((v) => cint(v)).filter((v) => v > 0)
			: POL_PAGE_LENGTHS;
		this.page_length = this.page_lengths[0] || 20;
		this.start = 0;
		this._last_meta = { has_more: 0, start: 0, total: 0 };
		this._filter_fields = {};
		this._rows_by_name = {};
		this._suspend_auto = false;
		this._sort = { field: '', dir: 'desc' };
		this._sku_mode = false;
		this.setup_toolbar();
		this.render_body();
	}

	render_body() {
		this.page.main.html(pol_body_html());
		this.wrapper = $(this.page.main);
		this.render_page_length_options();
		this.setup_filters();
		// restore BEFORE the first load and before events bind, so nothing fires mid-restore
		this._restore_view_prefs();
		this._sku_mode = !!this._val('sku_code');
		this.render_header();
		this.bind_events();
		this.load_list();
	}

	get _columns() {
		return this._sku_mode ? POL_SKU_COLUMNS : POL_COLUMNS;
	}

	setup_toolbar() {
		if (cint(this.options.can_create) && frappe.model.can_create('Purchase Order')) {
			this.page.set_primary_action(
				__('New Purchase Order'),
				() => frappe.set_route('purchase_order_entry'),
				'fa fa-plus'
			);
		}
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
	}

	render_page_length_options() {
		const sel = this.wrapper.find('.pol-page-length').empty();
		this.page_lengths.forEach((n) => sel.append(`<option value="${n}">${n}</option>`));
		sel.val(String(this.page_length));
	}

	// --------------------------------------------------------------- filters

	setup_filters() {
		const w = this.wrapper;
		const mk = (key, df, selector) => {
			this._filter_fields[key] = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: key }, df),
				parent: w.find(selector),
				render_input: true,
			});
		};
		mk('po_type', { fieldtype: 'Select', label: __('PO Type'), options: this.options.po_types }, '.fld-po-type');
		mk('supplier', { fieldtype: 'Link', label: __('Vendor Name'), options: 'Supplier' }, '.fld-supplier');
		mk('po_id', { fieldtype: 'Data', label: __('PO ID') }, '.fld-po-id');
		mk('sku_code', { fieldtype: 'Link', label: __('SKU Code'), options: 'Item' }, '.fld-sku-code');
		mk('from_date', { fieldtype: 'Date', label: __('PO Date (From)') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('PO Date (To)') }, '.fld-to-date');
		mk('delivery_from', { fieldtype: 'Date', label: __('Expected Delivery (From)') }, '.fld-delivery-from');
		mk('delivery_to', { fieldtype: 'Date', label: __('Expected Delivery (To)') }, '.fld-delivery-to');
		mk(
			'current_status',
			{ fieldtype: 'Select', label: __('Current Status'), options: this.options.current_statuses },
			'.fld-current-status'
		);
		mk(
			'approval_status',
			{ fieldtype: 'Select', label: __('Approval Status'), options: this.options.approval_statuses },
			'.fld-approval-status'
		);
		mk(
			'receiving_status',
			{ fieldtype: 'Select', label: __('Receiving Status'), options: this.options.receiving_statuses },
			'.fld-receiving-status'
		);
	}

	_val(name) {
		const f = this._filter_fields[name];
		return (f && f.get_value()) || '';
	}

	bind_events() {
		// render_body() runs on every show; clear the namespace or handlers stack up.
		this.wrapper.off('.pollist');

		const reload = () => {
			this.start = 0;
			const sku = !!this._val('sku_code');
			if (sku !== this._sku_mode) {
				this._sku_mode = sku;
				this.render_header();
			}
			this._save_view_prefs();
			this.load_list();
		};

		this.wrapper.find('.btn-pol-apply').on('click', reload);
		this.wrapper.find('.btn-pol-clear').on('click', () => {
			this._suspend_auto = true;
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this._suspend_auto = false;
			reload();
		});
		this.wrapper.find('.pol-page-length').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = this.page_lengths.includes(v) ? v : this.page_lengths[0] || 20;
			$(e.currentTarget).val(String(this.page_length));
			reload();
		});
		this.wrapper.find('.btn-pol-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-pol-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});

		this.wrapper.on('click.pollist', '.pol-list-row', (e) => {
			if ($(e.target).closest('a,button,input,.pol-qty-hint').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_order_entry', String(name));
		});
		this.wrapper.on('click.pollist', '.pol-act-btn', (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this.run_action(String($btn.data('name') || ''), String($btn.data('action') || ''));
		});
		this.wrapper.on('click.pollist', '.pol-sort-th', (e) => {
			const field = $(e.currentTarget).data('sort');
			if (this._sort.field === field) {
				this._sort.dir = this._sort.dir === 'asc' ? 'desc' : 'asc';
			} else {
				this._sort.field = field;
				this._sort.dir = 'asc';
			}
			this.start = 0;
			this.render_header();
			this._save_view_prefs();
			this.load_list();
		});

		// Filters apply as the user types or picks, debounced. The suspend flag is read
		// synchronously here, not inside the debounced body, or a programmatic Clear would
		// still fire a reload once the window elapsed.
		const apply = frappe.utils.debounce(reload, 350);
		const auto = () => {
			if (this._suspend_auto) return;
			apply();
		};
		Object.values(this._filter_fields).forEach((f) => {
			if (f && f.$input) f.$input.on('input change awesomplete-selectcomplete', auto);
		});
	}

	// ----------------------------------------------------------- saved views

	_save_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		const filters = {};
		Object.keys(this._filter_fields).forEach((name) => {
			filters[name] = this._val(name);
		});
		alpinos.list_prefs.save(POL_LIST_ROUTE, {
			filters: filters,
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir === 'asc' ? 'asc' : 'desc',
			page_length: this.page_length,
		});
	}

	// Saved prefs are untrusted localStorage: every value is validated, a Select value
	// that is no longer an option is dropped, and a malformed blob can never blank the page.
	_restore_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		let saved = {};
		try {
			saved = alpinos.list_prefs.load(POL_LIST_ROUTE) || {};
		} catch (e) {
			saved = {};
		}
		if (!saved || typeof saved !== 'object') return;

		this._suspend_auto = true;
		try {
			const filters = saved.filters && typeof saved.filters === 'object' ? saved.filters : {};
			Object.keys(filters).forEach((name) => {
				const field = this._filter_fields[name];
				const value = filters[name];
				if (!field || typeof value !== 'string' || !value) return;
				if (field.df.fieldtype === 'Select' && !pol_option_values(field).includes(value)) return;
				if (typeof field.set_input === 'function') field.set_input(value);
				else field.set_value(value);
			});
			const sortable = POL_COLUMNS.concat(POL_SKU_COLUMNS).filter((c) => c.sort).map((c) => c.sort);
			if (typeof saved.sort_field === 'string' && sortable.includes(saved.sort_field)) {
				this._sort.field = saved.sort_field;
				this._sort.dir = saved.sort_dir === 'asc' ? 'asc' : 'desc';
			}
			const pl = cint(saved.page_length);
			if (this.page_lengths.includes(pl)) this.page_length = pl;
			this.wrapper.find('.pol-page-length').val(String(this.page_length));
		} catch (e) {
			// a bad saved state must never break the page
		}
		this._suspend_auto = false;
		this.start = 0;
	}

	// ------------------------------------------------------------- load/render

	_args() {
		const args = {
			start: this.start,
			page_length: this.page_length,
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir || 'desc',
		};
		Object.keys(this._filter_fields).forEach((name) => {
			args[name] = this._val(name);
		});
		return args;
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.po_list_api.get_purchase_order_list',
			args: me._args(),
			freeze: true,
			freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc) return;
				const msg = r.message || {};
				me._last_meta = {
					has_more: cint(msg.has_more),
					start: cint(msg.start),
					total: cint(msg.total),
				};
				me.render_rows(msg.data || []);
				me.update_pager(msg.sku_code || '');
			},
		});
	}

	render_header() {
		const table = this.wrapper.find('.pol-list-table');
		let cg = table.children('colgroup');
		if (!cg.length) {
			cg = $('<colgroup></colgroup>');
			table.prepend(cg);
		}
		cg.empty();
		this._columns.forEach((c) => cg.append(`<col${c.width ? ` style="width:${c.width}"` : ''}>`));

		const tr = this.wrapper.find('.pol-list-table thead tr').empty();
		this._columns.forEach((c) => {
			if (!c.sort) {
				tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`);
				return;
			}
			const active = this._sort.field === c.sort;
			const arrow = active ? (this._sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${c.cls || ''} pol-sort-th" data-sort="${c.sort}" ` +
					`style="cursor:pointer; user-select:none;" title="${__('Click to sort')}">` +
					`${__(c.label)}<span class="text-muted" style="font-size:10px; opacity:${active ? 1 : 0.4};">${arrow}</span></th>`
			);
		});
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.pol-list-table tbody').empty();
		this._rows_by_name = {};
		if (!rows.length) {
			const empty = this._sku_mode
				? __('No Purchase Orders contain this SKU')
				: __('No Purchase Orders found');
			tb.append(`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${empty}</td></tr>`);
			return;
		}
		// Every interpolated value is escaped: rows are built from template literals, so an
		// unescaped vendor or item name would be stored XSS.
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const num = (v) => {
			const n = flt(v);
			return format_number(n, null, n % 1 ? 2 : 0);
		};
		const helpers = {
			esc,
			dash: (v) => (v == null || v === '' ? '—' : esc(v)),
			date: (v) => (v ? esc(frappe.datetime.str_to_user(v)) : '—'),
			qty: (v, uom) => (uom ? `${esc(num(v))} ${esc(uom)}` : esc(num(v))),
			money: (v, currency) => esc(format_currency(flt(v), currency)),
			type: (d) => {
				const t = d.custom_inward_type ? esc(d.custom_inward_type) : '—';
				return cint(d.custom_direct_purchase_invoice)
					? `${t}<span class="indicator-pill orange pol-direct" title="${esc(__('Direct Purchase Invoice: skips Inward, QC and GRN'))}">${esc(__('Direct'))}</span>`
					: t;
			},
			order_qty: (d) => {
				const parts = (d.qty_by_uom || []).map((u) => `${num(u.qty)}${u.uom ? ' ' + u.uom : ''}`);
				const label = parts.length ? parts.join(' + ') : num(d.total_qty);
				const lines = (d.lines || []).map((l) => `${l.item_code} : ${num(l.qty)}${l.uom ? ' ' + l.uom : ''}`);
				if (!lines.length) return esc(label);
				const tip = [__('SKU code : Qty')].concat(lines).join('\n');
				return `${esc(label)}<span class="pol-qty-hint" title="${esc(tip)}" aria-label="${esc(tip)}">i</span>`;
			},
			sku_code: (d) => {
				const s = d.sku || {};
				return s.item_name && s.item_name !== s.item_code
					? `${esc(s.item_code)}<div class="text-muted" style="font-size:11px;">${esc(s.item_name)}</div>`
					: esc(s.item_code || '');
			},
			pending: (d) => {
				const s = d.sku || {};
				const cls = flt(s.pending_qty) > 0 ? '' : 'pol-pending-zero';
				return `<span class="${cls}">${esc(num(s.pending_qty))}${s.uom ? ' ' + esc(s.uom) : ''}</span>`;
			},
			status: (s) => (s ? `<span class="indicator-pill ${POL_STATUS_COLORS[s] || 'gray'}">${esc(__(s))}</span>` : '—'),
			actions: (d, sku_view) => {
				let acts = Array.isArray(d.actions) ? d.actions : [];
				if (sku_view) acts = acts.filter((a) => POL_SKU_ACTIONS.includes(a.action));
				if (!acts.length) return '—';
				return acts
					.map((a) => {
						const label = esc(a.label || a.action);
						const cls = a.kind === 'transition' || a.kind === 'create' ? 'btn-primary' : 'btn-default';
						if (a.enabled === false) {
							// a disabled button swallows its own tooltip, so the reason sits on a wrapper
							return `<span class="pol-act-disabled" title="${esc(a.reason || __('Not available yet'))}"><button type="button" class="btn btn-xs ${cls}" disabled>${label}</button></span>`;
						}
						return `<button type="button" class="btn btn-xs ${cls} pol-act-btn" data-name="${esc(d.name)}" data-action="${esc(a.action)}">${label}</button>`;
					})
					.join(' ');
			},
		};
		rows.forEach((d) => {
			this._rows_by_name[d.name] = d;
			const cells = this._columns.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`).join('');
			tb.append(`<tr class="pol-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`);
		});
	}

	update_pager(sku_code) {
		const n = this.wrapper.find('.pol-list-table tbody tr.pol-list-row').length;
		const total = cint(this._last_meta.total);
		if (!n) {
			this.wrapper.find('.pol-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			this.wrapper.find('.pol-count').text(__('Showing {0}–{1} of {2}', [from, this._last_meta.start + n, total]));
		}
		this.wrapper.find('.pol-total').text(__('{0} Purchase Order(s)', [total]));
		this.wrapper
			.find('.pol-mode')
			.html(sku_code ? __('SKU view for {0}', [`<b>${frappe.utils.escape_html(sku_code)}</b>`]) : '');
		this.wrapper.find('.btn-pol-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pol-next').prop('disabled', !this._last_meta.has_more);
	}

	// ------------------------------------------------------------- row actions

	run_action(name, action) {
		const d = this._rows_by_name[name];
		if (!d || !action) return;
		const act = (d.actions || []).find((a) => a.action === action);
		if (!act || act.enabled === false) return;

		if (action === 'view' || action === 'edit') {
			frappe.set_route('purchase_order_entry', name);
			return;
		}
		if (action === 'delete') {
			frappe.model.delete_doc('Purchase Order', name, () => this.load_list());
			return;
		}
		if (action === 'create_inward') {
			// the Inward screen takes the order from route_options and pulls its pending lines
			frappe.route_options = { purchase_order: name };
			frappe.set_route('purchase_inward_entry');
			return;
		}
		if (action === 'view_inwards') {
			frappe.set_route('List', 'Purchase Inward', { purchase_order: name });
			return;
		}
		if (action === 'view_invoice') {
			if (d.direct_invoice) frappe.set_route('Form', 'Purchase Invoice', d.direct_invoice);
			return;
		}
		if (action === 'create_invoice') {
			this.create_direct_invoice(name);
			return;
		}
		if (act.kind === 'transition') {
			this.run_transition(name, action);
		}
	}

	create_direct_invoice(name) {
		const me = this;
		frappe.confirm(
			__('Create the Purchase Invoice for {0}? Purchase Inward, QC and GRN are skipped for a Direct Purchase Invoice order.', [name]),
			() =>
				frappe.call({
					method: 'alpinos.purchase.purchase_invoice.create_direct_from_po',
					args: { purchase_order: name },
					freeze: true,
					freeze_message: __('Creating the Purchase Invoice...'),
					callback(r) {
						// the callback also fires when the server refused (already invoiced)
						if (r.exc || !r.message) {
							me.load_list();
							return;
						}
						frappe.set_route('Form', 'Purchase Invoice', r.message.name);
					},
				})
		);
	}

	run_transition(name, action) {
		const me = this;
		const call = (remarks) =>
			frappe.call({
				method: 'alpinos.purchase.purchase_order_approval.perform_action',
				args: { purchase_order: name, action: action, remarks: remarks || null },
				freeze: true,
				freeze_message: __('{0}...', [__(action)]),
				callback(r) {
					// refused actions also reach this callback; reload either way so the
					// row shows the order's real state rather than what was attempted
					me.load_list();
				},
			});

		// VAL-PO-09: Reject needs remarks; Return for Correction takes optional ones.
		const needs = action === 'Reject';
		if (needs || action === 'Return for Correction') {
			const dialog = new frappe.ui.Dialog({
				title: __('{0}: {1}', [__(action), name]),
				fields: [
					{
						fieldname: 'remarks',
						fieldtype: 'Small Text',
						label: needs ? __('Rejection Remarks') : __('Remarks'),
						reqd: needs ? 1 : 0,
					},
				],
				primary_action_label: __(action),
				primary_action(values) {
					dialog.hide();
					call(values.remarks);
				},
			});
			dialog.show();
			return;
		}
		frappe.confirm(__('{0} Purchase Order {1}?', [__(action), name]), () => call(null));
	}
};

// Select options arrive either as a newline string or as [{value, label}] objects.
function pol_option_values(field) {
	const opts = (field && field.df && field.df.options) || '';
	if (Array.isArray(opts)) {
		return opts.map((o) => (o && typeof o === 'object' ? String(o.value) : String(o)));
	}
	return String(opts).split('\n');
}
