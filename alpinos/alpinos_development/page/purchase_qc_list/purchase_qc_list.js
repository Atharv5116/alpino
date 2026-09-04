// Purchase QC list screen — BRD "Purchase Inward Part -1" sections 3.1 - 3.5.
//
// This is the "QC Dashboard" the BRD refers to from BR-QC-01: every Purchase Inward
// handed to QC lands here, carrying its 2-hour SLA clock (BR-QC-03 / BR-QC-04) so the
// QC team sees the countdown rather than discovering the breach in an escalation mail.
//
// Columns, filters, sorting and pagination are all server-driven
// (alpinos.purchase.qc_list_api.get_purchase_qc_list). The per-row action buttons come
// from that same endpoint, which reads them off the workflow engine for the linked
// Purchase Inward — there is deliberately NO status-to-buttons map in this file, so the
// list can never offer an action the server would refuse. Per BRD 3.4 the Complete QC
// button is NOT here: it lives inside the QC screen, and an in-progress row only gets
// Continue QC, which reopens the inspection.
//
// This page route is not registered in alpinos_pages.css, so the skin below is
// page-local; only the globally defined .alp-* utilities and .indicator-pill colour
// tints are borrowed from the shared sheet.

frappe.pages['purchase_qc_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Purchase QC'),
		single_column: true,
	});
	// vocabulary is fetched once so the Select options stay single-sourced in
	// alpinos.purchase.constants; the page still renders if that call fails
	pqc_load_options(function (options) {
		wrapper.__pqc_list_page = new PurchaseQCListPage(page, options);
	});
};

// Frappe caches custom pages, so on_page_load runs once — re-render the body on every
// show or navigating back leaves a stale list. The toolbar is built in the constructor
// only; re-adding its buttons here would duplicate them on every visit.
frappe.pages['purchase_qc_list'].on_page_show = function (wrapper) {
	if (wrapper.__pqc_list_page) wrapper.__pqc_list_page.render_body();
};

// Route key for alpinos.list_prefs — must stay the exact frappe.pages key.
var PQC_LIST_ROUTE = 'purchase_qc_list';
var PQC_PAGE_LENGTHS = [20, 50, 100];
// The print format created by alpinos.purchase.print_formats (BR-QC-16).
var PQC_PRINT_FORMAT = 'QC Inspection Report';
// How often the SLA countdown is redrawn from the last server reading.
var PQC_SLA_TICK_MS = 30000;

// Used only when get_filter_options() is unavailable; the server copy wins.
var PQC_FALLBACK_OPTIONS = {
	inward_types: [
		{ value: '', label: '' },
		{ value: 'RM', label: 'RM' },
		{ value: 'PM', label: 'PM' },
		{ value: 'FG', label: 'FG' },
		{ value: 'MM', label: 'MM' },
	],
	qc_statuses:
		'\nPending QC\nQC In Progress\nQC SLA Breached\nQC Ready for Decision' +
		'\nQC Completed\nCancelled',
	qc_results: '\nPending\nApproved\nPartially Approved\nRejected\nExcess Qty Approved',
	sla_states: [
		{ value: '', label: '' },
		{ value: 'breached', label: 'SLA Breached' },
		{ value: 'within', label: 'Within SLA' },
	],
	page_lengths: PQC_PAGE_LENGTHS,
	sla_hours: 2,
};

var PQC_STATUS_COLORS = {
	'Pending QC': 'orange',
	'QC In Progress': 'blue',
	'QC SLA Breached': 'red',
	'QC Ready for Decision': 'yellow',
	'QC Completed': 'green',
	Cancelled: 'gray',
};

var PQC_RESULT_COLORS = {
	Pending: 'gray',
	Approved: 'green',
	'Partially Approved': 'yellow',
	Rejected: 'red',
	'Excess Qty Approved': 'purple',
};

var PQC_OPTIONS_CACHE = null;

function pqc_load_options(callback) {
	if (PQC_OPTIONS_CACHE) {
		callback(PQC_OPTIONS_CACHE);
		return;
	}
	frappe.call({
		method: 'alpinos.purchase.qc_list_api.get_filter_options',
		callback: function (r) {
			PQC_OPTIONS_CACHE = (r && r.message) || PQC_FALLBACK_OPTIONS;
			callback(PQC_OPTIONS_CACHE);
		},
		error: function () {
			callback(PQC_FALLBACK_OPTIONS);
		},
	});
}

// Signed seconds -> "1h 12m" / "45m" / "2d 3h". Sign is handled by the caller.
function pqc_duration(seconds) {
	var s = Math.abs(Math.round(seconds));
	var d = Math.floor(s / 86400);
	var h = Math.floor((s % 86400) / 3600);
	var m = Math.floor((s % 3600) / 60);
	if (d) return d + 'd ' + h + 'h';
	if (h) return h + 'h ' + m + 'm';
	if (m) return m + 'm';
	return '<1m';
}

// BRD 3.1 columns, in the BRD's order, plus QC Status, QC Result, the SLA clock and
// the action buttons. `width` drives the <colgroup> so header and data share one grid.
var PQC_COLUMNS = [
	{
		label: 'QC ID',
		sort: 'name',
		width: '8%',
		render: (d, h) => `<strong>${h.esc(d.name)}</strong>`,
	},
	{
		label: 'Purchase Inward ID',
		sort: 'purchase_inward',
		width: '8%',
		render: (d, h) => h.link_btn(d.purchase_inward, 'inward', __('Open Purchase Inward')),
	},
	{
		label: 'Vendor Name',
		sort: 'supplier_name',
		width: '12%',
		render: (d, h) => h.dash(d.supplier_name || d.supplier),
	},
	{ label: 'Inward Type', sort: 'inward_type', width: '5%', render: (d, h) => h.dash(d.inward_type) },
	{
		label: 'Order No.',
		width: '8%',
		render: (d, h) =>
			d.purchase_order
				? h.link_btn(d.purchase_order, 'po', __('Open Purchase Order'))
				: h.dash(d.supplier_order_no),
	},
	{
		label: 'Received Qty',
		sort: 'received_qty',
		cls: 'text-right',
		width: '8%',
		render: (d, h) => h.qty(d.received_qty, d.uom),
	},
	{
		label: 'Inspector',
		sort: 'inspector',
		width: '9%',
		render: (d, h) => h.dash(d.inspector_full_name || d.inspector),
	},
	{
		label: 'Inspection Date',
		sort: 'inspection_date',
		width: '9%',
		render: (d, h) => h.datetime(d.inspection_date),
	},
	{ label: 'QC Status', sort: 'qc_status', width: '9%', render: (d, h) => h.qc_status(d) },
	{ label: 'QC Result', sort: 'qc_result', width: '8%', render: (d, h) => h.qc_result(d) },
	{ label: 'SLA', sort: 'sla_due', width: '7%', render: (d, h) => h.sla(d) },
	{ label: 'Actions', cls: 'pqc-col-actions', width: '9%', render: (d, h) => h.actions(d) },
];

function pqc_body_html() {
	return `
<style>
	.pqc-list-container { display: block; }
	.pqc-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 10px 14px;
	}
	.pqc-grid > * { min-width: 0; }
	.pqc-viewbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.pqc-viewbar-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-muted, #6b7280);
		margin: 0;
	}
	.pqc-page-length { width: auto; min-width: 72px; display: inline-block; }
	.pqc-table-wrapper { padding: 0; overflow-x: auto; }
	.pqc-table-wrapper > .pqc-list-table {
		width: 100%;
		min-width: 1440px;
		margin-bottom: 0;
		font-size: 13px;
		border-collapse: collapse;
	}
	.pqc-list-table th, .pqc-list-table td {
		padding: 9px 12px;
		border-bottom: 1px solid var(--border-color, #e2e2e2);
		white-space: nowrap;
		vertical-align: middle;
	}
	.pqc-list-table thead th {
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
	.pqc-list-table tbody tr.pqc-list-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	.pqc-list-table td.pqc-col-actions { white-space: nowrap; }
	.pqc-list-table td.pqc-col-actions .btn { margin-right: 4px; }
	.pqc-act-disabled { display: inline-block; }
	/* BR-QC-04: a blown SLA has to be visible without reading the column */
	.pqc-list-table tbody tr.pqc-row-breached > td:first-child {
		box-shadow: inset 3px 0 0 var(--red-500, #e03636);
	}
	.pqc-list-table tbody tr.pqc-row-breached { background: var(--red-50, #fff5f5); }
	.pqc-sla-breached { color: var(--red-600, #c0392b); font-weight: 600; }
	.pqc-sla-ok { color: var(--text-color, #36414c); }
	.pqc-sla-met { color: var(--green-600, #1f7a4d); }
	.pqc-pager {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 12px;
	}
	.pqc-nav { display: flex; align-items: center; gap: 10px; }
	.pqc-breach-count { font-weight: 600; }
</style>

<div class="pqc-list-container">
	<div class="pqc-list-filters alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="pqc-grid">
			<div class="fld-qc-id"></div>
			<div class="fld-purchase-inward"></div>
			<div class="fld-supplier"></div>
			<div class="fld-supplier-order-no"></div>
			<div class="fld-invoice-number"></div>
			<div class="fld-inward-type"></div>
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-inspector"></div>
			<div class="fld-qc-result"></div>
			<div class="fld-qc-status"></div>
			<div class="fld-sla-state"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-pqc-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-pqc-clear">${__('Clear')}</button>
			<span class="pqc-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>

	<div class="pqc-viewbar">
		<label class="pqc-viewbar-label">${__('Rows per page')}</label>
		<select class="form-control input-xs pqc-page-length"></select>
		<span class="pqc-breach-count text-danger" style="margin-left: auto; font-size: 12px;"></span>
	</div>

	<div class="pqc-table-wrapper alp-card">
		<table class="pqc-list-table">
			<thead><tr></tr></thead>
			<tbody></tbody>
		</table>
	</div>

	<div class="pqc-pager">
		<div class="pqc-count text-muted"></div>
		<div class="pqc-nav">
			<button class="btn btn-default btn-sm btn-pqc-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-pqc-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseQCListPage = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || PQC_FALLBACK_OPTIONS;
		this.page_lengths = Array.isArray(this.options.page_lengths)
			? this.options.page_lengths.map((v) => cint(v)).filter((v) => v > 0)
			: PQC_PAGE_LENGTHS;
		this.page_length = this.page_lengths[0] || 20;
		this.start = 0;
		this._last_meta = { has_more: 0, start: 0, total: 0 };
		this._filter_fields = {};
		this._rows_by_name = {};
		// server clock reading the SLA countdown ticks forward from
		this._loaded_at = Date.now();
		// guards the auto-apply handler against programmatic writes (Clear, prefs restore)
		this._suspend_auto = false;
		this._sort = { field: '', dir: 'desc' };
		this._columns = PQC_COLUMNS;
		this.setup_toolbar(); // page-header buttons: added ONCE, never on re-render
		this.render_body();
	}

	// Safe to call on every page show; never touches the toolbar.
	render_body() {
		this.page.main.html(pqc_body_html());
		this.wrapper = $(this.page.main);
		this.render_page_length_options();
		this.setup_filters();
		this.render_header();
		// restore BEFORE the first load and before events bind, so nothing fires mid-restore
		this._restore_view_prefs();
		this.bind_events();
		this.start_sla_clock();
		this.load_list();
	}

	setup_toolbar() {
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		// the dashboard's own shortcut: everything currently past its 2-hour SLA
		this.page.add_inner_button(__('SLA Breached'), () => {
			const f = this._filter_fields.sla_state;
			if (!f) return;
			this._suspend_auto = true;
			if (typeof f.set_input === 'function') f.set_input('breached');
			else f.set_value('breached');
			this._suspend_auto = false;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
	}

	render_page_length_options() {
		const sel = this.wrapper.find('.pqc-page-length').empty();
		this.page_lengths.forEach((n) => {
			sel.append(`<option value="${n}">${n}</option>`);
		});
		sel.val(String(this.page_length));
	}

	// --------------------------------------------------------------- filters

	// BRD 3.3, in the BRD's order.
	setup_filters() {
		const w = this.wrapper;
		const mk = (key, df, selector) => {
			this._filter_fields[key] = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: key }, df),
				parent: w.find(selector),
				render_input: true,
			});
		};

		mk('qc_id', { fieldtype: 'Data', label: __('QC ID') }, '.fld-qc-id');
		mk(
			'purchase_inward',
			{ fieldtype: 'Data', label: __('Purchase Inward ID') },
			'.fld-purchase-inward'
		);
		mk('supplier', { fieldtype: 'Link', label: __('Vendor Name'), options: 'Supplier' }, '.fld-supplier');
		mk(
			'supplier_order_no',
			{ fieldtype: 'Data', label: __('Supplier Order No.') },
			'.fld-supplier-order-no'
		);
		mk('invoice_number', { fieldtype: 'Data', label: __('Invoice Number') }, '.fld-invoice-number');
		mk(
			'inward_type',
			{ fieldtype: 'Select', label: __('Inward Type'), options: this.options.inward_types },
			'.fld-inward-type'
		);
		mk('from_date', { fieldtype: 'Date', label: __('Inspection Date (From)') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('Inspection Date (To)') }, '.fld-to-date');
		mk('inspector', { fieldtype: 'Link', label: __('Inspector'), options: 'User' }, '.fld-inspector');
		mk(
			'qc_result',
			{ fieldtype: 'Select', label: __('QC Result'), options: this.options.qc_results },
			'.fld-qc-result'
		);
		mk(
			'qc_status',
			{ fieldtype: 'Select', label: __('Current Status'), options: this.options.qc_statuses },
			'.fld-qc-status'
		);
		mk(
			'sla_state',
			{ fieldtype: 'Select', label: __('SLA'), options: this.options.sla_states },
			'.fld-sla-state'
		);
	}

	bind_events() {
		// render_body() runs on every page show; delegated handlers live on the persistent
		// container, so clear the namespace first or they fire N times after N visits.
		this.wrapper.off('.pqclist');

		this.wrapper.find('.btn-pqc-apply').on('click', () => {
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pqc-clear').on('click', () => {
			this._suspend_auto = true;
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this._suspend_auto = false;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.pqc-page-length').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = this.page_lengths.includes(v) ? v : this.page_lengths[0] || 20;
			$(e.currentTarget).val(String(this.page_length));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pqc-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-pqc-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});

		this.wrapper.on('click.pqclist', '.pqc-list-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_qc_entry', String(name));
		});
		this.wrapper.on('click.pqclist', '.pqc-act-btn', (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this.run_action(String($btn.data('name') || ''), String($btn.data('action') || ''));
		});
		this.wrapper.on('click.pqclist', '.pqc-link-btn', (e) => {
			e.preventDefault();
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const target = String($btn.data('target') || '');
			const value = String($btn.data('value') || '');
			if (!value) return;
			if (target === 'po') frappe.set_route('Form', 'Purchase Order', value);
			else frappe.set_route('purchase_inward_entry', value);
		});
		this.wrapper.on('click.pqclist', '.pqc-sort-th', (e) => {
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

		// filters apply as the user types/picks, debounced; Apply stays for an explicit trigger.
		// _suspend_auto keeps programmatic writes (Clear, restore) from looping back in here.
		const auto = frappe.utils.debounce(() => {
			if (this._suspend_auto) return;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		}, 350);
		Object.values(this._filter_fields).forEach((f) => {
			if (f && f.$input) f.$input.on('input change awesomplete-selectcomplete', auto);
		});
	}

	// ----------------------------------------------------------- saved views

	// snapshots filters + sort + page size (never the pagination offset) via alpinos.list_prefs
	_save_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		const f = this._filter_fields;
		const val = (name) => (f[name] && f[name].get_value()) || '';
		const filters = {};
		Object.keys(f).forEach((name) => {
			filters[name] = val(name);
		});
		alpinos.list_prefs.save(PQC_LIST_ROUTE, {
			filters: filters,
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir === 'asc' ? 'asc' : 'desc',
			page_length: this.page_length,
		});
	}

	// Saved prefs are untrusted localStorage: every value is validated, a Select value
	// that is no longer an option is dropped, and the whole restore is wrapped so a
	// malformed blob can never blank the page.
	_restore_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		let saved = {};
		try {
			saved = alpinos.list_prefs.load(PQC_LIST_ROUTE) || {};
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
				if (field.df.fieldtype === 'Select' && !pqc_option_values(field).includes(value)) return;
				// set_input applies synchronously so the first load_list() sees it via
				// get_value(); set_value is promise-based and can land after the request.
				if (typeof field.set_input === 'function') field.set_input(value);
				else field.set_value(value);
			});

			const sortable = this._columns.filter((c) => c.sort).map((c) => c.sort);
			if (typeof saved.sort_field === 'string' && sortable.includes(saved.sort_field)) {
				this._sort.field = saved.sort_field;
				this._sort.dir = saved.sort_dir === 'asc' ? 'asc' : 'desc';
				this.render_header();
			}

			const pl = cint(saved.page_length);
			if (this.page_lengths.includes(pl)) this.page_length = pl;
			this.wrapper.find('.pqc-page-length').val(String(this.page_length));
		} catch (e) {
			// a bad saved state must never break the page
		}
		this._suspend_auto = false;

		// pagination offset is deliberately never restored — the list always opens on page 1
		this.start = 0;
	}

	// ------------------------------------------------------------- load/render

	_args() {
		const f = this._filter_fields;
		const val = (name) => (f[name] && f[name].get_value()) || '';
		return {
			start: this.start,
			page_length: this.page_length,
			qc_id: val('qc_id'),
			purchase_inward: val('purchase_inward'),
			supplier: val('supplier'),
			supplier_order_no: val('supplier_order_no'),
			invoice_number: val('invoice_number'),
			inward_type: val('inward_type'),
			from_date: val('from_date'),
			to_date: val('to_date'),
			inspector: val('inspector'),
			qc_result: val('qc_result'),
			qc_status: val('qc_status'),
			sla_state: val('sla_state'),
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir || 'desc',
			with_actions: 1,
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.qc_list_api.get_purchase_qc_list',
			args: me._args(),
			freeze: true,
			freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc) return;
				const msg = r.message || {};
				me._last_meta = {
					has_more: cint(msg.has_more),
					start: cint(msg.start),
					page_length: cint(msg.page_length),
					total: cint(msg.total),
				};
				// the countdown ticks forward from the server reading, not the browser
				// clock, so a skewed workstation clock cannot fake or hide a breach
				me._loaded_at = Date.now();
				me.render_rows(msg.data || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		// colgroup so the header row and the data rows share one column grid
		const table = this.wrapper.find('.pqc-list-table');
		let cg = table.children('colgroup');
		if (!cg.length) {
			cg = $('<colgroup></colgroup>');
			table.prepend(cg);
		}
		cg.empty();
		this._columns.forEach((c) => cg.append(`<col${c.width ? ` style="width:${c.width}"` : ''}>`));

		const tr = this.wrapper.find('.pqc-list-table thead tr').empty();
		this._columns.forEach((c) => {
			if (!c.sort) {
				tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`);
				return;
			}
			const active = this._sort.field === c.sort;
			const arrow = active ? (this._sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${c.cls || ''} pqc-sort-th" data-sort="${c.sort}" ` +
					`style="cursor:pointer; user-select:none;" title="${__('Click to sort')}">` +
					`${__(c.label)}<span class="text-muted" style="font-size:10px; opacity:${
						active ? 1 : 0.4
					};">${arrow}</span></th>`
			);
		});
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.pqc-list-table tbody').empty();
		this._rows_by_name = {};
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__(
					'No Purchase QC records found'
				)}</td></tr>`
			);
			this.wrapper.find('.pqc-breach-count').text('');
			return;
		}
		// every interpolated value is escaped — these rows are built with template
		// literals, so an unescaped vendor name would be stored XSS
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			dash: (v) => (v == null || v === '' ? '—' : esc(v)),
			qty: (v, uom) => {
				const n = flt(v);
				const num = format_number(n, null, n % 1 ? 2 : 0);
				return uom ? `${esc(num)} ${esc(uom)}` : esc(num);
			},
			datetime: (v) => (v ? esc(frappe.datetime.str_to_user(v)) : '—'),
			link_btn: (value, target, title) =>
				value
					? `<button type="button" class="btn btn-xs btn-default pqc-link-btn" data-target="${esc(
							target
					  )}" data-value="${esc(value)}" title="${esc(title)}">${esc(value)}</button>`
					: '—',
			qc_status: (d) => {
				const s = d.qc_status || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PQC_STATUS_COLORS[s] || 'gray'}">${esc(s)}</span>`;
			},
			qc_result: (d) => {
				const s = d.qc_result || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PQC_RESULT_COLORS[s] || 'gray'}">${esc(s)}</span>`;
			},
			// BR-QC-03 / BR-QC-04 — the 2-hour clock, live on every row
			sla: (d) => pqc_sla_html(d, 0),
			actions: (d) => {
				const acts = Array.isArray(d.actions) ? d.actions : [];
				if (!acts.length) return '—';
				return acts
					.map((a) => {
						const label = esc(a.label || a.action);
						const cls = a.kind === 'transition' ? 'btn-primary' : 'btn-default';
						if (a.enabled === false) {
							// a disabled button swallows its own tooltip, so the guard reason
							// (BRD 3.5) is carried on a wrapper span instead
							return `<span class="pqc-act-disabled" title="${esc(
								a.reason || __('Not available at this stage')
							)}"><button type="button" class="btn btn-xs ${cls}" disabled>${label}</button></span>`;
						}
						return `<button type="button" class="btn btn-xs ${cls} pqc-act-btn" data-name="${esc(
							d.name
						)}" data-action="${esc(a.action)}" title="${label}">${label}</button>`;
					})
					.join(' ');
			},
		};
		let breached = 0;
		rows.forEach((d) => {
			this._rows_by_name[d.name] = d;
			if (cint(d.sla_is_breached)) breached += 1;
			const cells = this._columns
				.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`)
				.join('');
			const row_cls = 'pqc-list-row' + (cint(d.sla_is_breached) ? ' pqc-row-breached' : '');
			tb.append(
				`<tr class="${row_cls}" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`
			);
		});
		this.wrapper
			.find('.pqc-breach-count')
			.text(breached ? __('{0} on this page have breached the QC SLA', [breached]) : '');
	}

	// The countdown is redrawn locally rather than re-fetched: elapsed browser time is
	// added to the server reading, so no request is needed to watch the clock run out.
	start_sla_clock() {
		if (this._sla_timer) clearInterval(this._sla_timer);
		this._sla_timer = setInterval(() => this.tick_sla(), PQC_SLA_TICK_MS);
	}

	tick_sla() {
		if (!this.wrapper || !this.wrapper.is(':visible')) return;
		const elapsed = (Date.now() - this._loaded_at) / 1000;
		const rows = this._rows_by_name;
		this.wrapper.find('.pqc-list-table tbody tr.pqc-list-row').each(function () {
			const $tr = $(this);
			const d = rows[String($tr.data('name'))];
			if (!d) return;
			$tr.find('.pqc-sla').replaceWith(pqc_sla_html(d, elapsed));
			// a row that runs out of SLA between loads must go red now, not on refresh
			const open = d.sla_state === 'ok' || d.sla_state === 'breached';
			if (open && d.sla_due && flt(d.sla_seconds_left) - elapsed < 0) {
				$tr.addClass('pqc-row-breached');
			}
		});
	}

	update_pager() {
		const n = this.wrapper.find('.pqc-list-table tbody tr.pqc-list-row').length;
		const total = cint(this._last_meta.total);
		if (!n) {
			this.wrapper.find('.pqc-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.pqc-count').text(__('Showing {0}–{1} of {2}', [from, to, total]));
		}
		this.wrapper.find('.pqc-total').text(__('{0} Purchase QC record(s)', [total]));
		this.wrapper.find('.btn-pqc-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pqc-next').prop('disabled', !this._last_meta.has_more);
	}

	// ------------------------------------------------------------- row actions

	run_action(name, action) {
		const d = this._rows_by_name[name];
		if (!d || !action) return;
		const act = (d.actions || []).find((a) => a.action === action);
		if (!act || act.enabled === false) return;

		if (action === 'print') {
			// BRD 3.4 "Print the completed QC Inspection report" — the module's own
			// format, not whichever one the print view happens to default to.
			const url =
				'/printview?doctype=' +
				encodeURIComponent('Purchase QC') +
				'&name=' +
				encodeURIComponent(name) +
				'&format=' +
				encodeURIComponent(PQC_PRINT_FORMAT) +
				'&trigger_print=1';
			const w = window.open(url);
			if (!w) frappe.msgprint(__('Please allow pop-ups to print the QC Report.'));
			return;
		}

		if (action === 'start_qc') {
			// BRD 3.4 "Open the QC Inspection screen and begin the inspection process".
			// start_qc runs workflow.assert_transition against the linked Purchase
			// Inward, so the engine — not this button — decides whether it is allowed.
			frappe.call({
				method: 'alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.start_qc',
				args: { purchase_qc: name },
				freeze: true,
				freeze_message: __('Starting QC...'),
				callback: (r) => {
					if (r.exc) return;
					frappe.show_alert({ message: __('QC started for {0}', [name]), indicator: 'green' });
					frappe.set_route('purchase_qc_entry', name);
				},
			});
			return;
		}

		// continue_qc / view_qc_report both open the QC screen: Complete QC lives inside
		// it (BRD 3.4 note), and a submitted QC opens read-only on its own.
		frappe.set_route('purchase_qc_entry', name);
	}
};

// Rendered both on load and on every tick, so it takes the elapsed seconds to add to
// the server reading rather than reading the clock itself.
function pqc_sla_html(d, elapsed) {
	const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
	// a QC raised before the SLA fields were stamped has no clock to show
	if (!d.sla_due) return '<span class="pqc-sla text-muted">—</span>';
	const due_title = esc(__('SLA due {0}', [frappe.datetime.str_to_user(d.sla_due)]));

	if (d.sla_state === 'met') {
		return `<span class="pqc-sla pqc-sla-met" title="${due_title}">${__('Met')}</span>`;
	}
	if (d.sla_state === 'missed') {
		return `<span class="pqc-sla pqc-sla-breached" title="${due_title}">${__('Breached')}</span>`;
	}
	if (d.sla_seconds_left === null || d.sla_seconds_left === undefined) {
		return '<span class="pqc-sla text-muted">—</span>';
	}

	const left = flt(d.sla_seconds_left) - flt(elapsed);
	if (left < 0) {
		return `<span class="pqc-sla pqc-sla-breached" title="${due_title}">${__('Overdue {0}', [
			pqc_duration(left),
		])}</span>`;
	}
	return `<span class="pqc-sla pqc-sla-ok" title="${due_title}">${__('{0} left', [
		pqc_duration(left),
	])}</span>`;
}

// Select options arrive either as a newline string or as [{value, label}] objects.
function pqc_option_values(field) {
	const opts = (field && field.df && field.df.options) || '';
	if (Array.isArray(opts)) {
		return opts.map((o) => (o && typeof o === 'object' ? String(o.value) : String(o)));
	}
	return String(opts).split('\n');
}
