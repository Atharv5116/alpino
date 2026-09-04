// Purchase Inward list screen — BRD "Purchase Inward Part -1" sections 1.1 - 1.4.
//
// Columns, filters, sorting and pagination are all server-driven
// (alpinos.purchase.inward_list_api.get_purchase_inward_list). The per-row action
// buttons come from alpinos.purchase.workflow.available_actions() through that same
// endpoint — there is deliberately NO status-to-buttons map in this file, so the list
// can never offer an action the server would refuse. A transition whose guard fails is
// rendered disabled with the guard reason as its tooltip.
//
// This page route is not registered in alpinos_pages.css, so the skin below is
// page-local; only the globally defined .alp-* utilities and .indicator-pill colour
// tints are borrowed from the shared sheet.

frappe.pages['purchase_inward_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Purchase Inwards'),
		single_column: true,
	});
	// vocabulary is fetched once so the Select options stay single-sourced in
	// alpinos.purchase.constants; the page still renders if that call fails
	piw_load_options(function (options) {
		wrapper.__piw_list_page = new PurchaseInwardListPage(page, options);
	});
};

// Frappe caches custom pages, so on_page_load runs once — re-render the body on every
// show or navigating back leaves a stale list. The toolbar is built in the constructor
// only; re-adding its buttons here would duplicate them on every visit.
frappe.pages['purchase_inward_list'].on_page_show = function (wrapper) {
	if (wrapper.__piw_list_page) wrapper.__piw_list_page.render_body();
};

// Route key for alpinos.list_prefs — must stay the exact frappe.pages key.
var PIW_LIST_ROUTE = 'purchase_inward_list';
var PIW_PAGE_LENGTHS = [20, 50, 100];

// Used only when get_filter_options() is unavailable; the server copy wins.
var PIW_FALLBACK_OPTIONS = {
	inward_types: [
		{ value: '', label: '' },
		{ value: 'RM', label: 'RM' },
		{ value: 'PM', label: 'PM' },
		{ value: 'FG', label: 'FG' },
		{ value: 'MM', label: 'MM' },
	],
	inward_statuses:
		'\nDraft\nPending Material Receipt\nPending QC\nQC In Progress\nQC Completed' +
		'\nGRN Generated\nPayment Pending\nCompleted\nCancelled',
	qc_statuses:
		'\nPending QC\nQC In Progress\nQC SLA Breached\nQC Ready for Decision' +
		'\nQC Completed\nCancelled',
	page_lengths: PIW_PAGE_LENGTHS,
	can_create: 1,
};

var PIW_STATUS_COLORS = {
	Draft: 'gray',
	'Pending Material Receipt': 'orange',
	'Pending QC': 'yellow',
	'QC In Progress': 'blue',
	'QC Completed': 'blue',
	'GRN Generated': 'purple',
	'Payment Pending': 'orange',
	Completed: 'green',
	Cancelled: 'red',
};

var PIW_OPTIONS_CACHE = null;

function piw_load_options(callback) {
	if (PIW_OPTIONS_CACHE) {
		callback(PIW_OPTIONS_CACHE);
		return;
	}
	// `once` because callback constructs the page: firing it twice would build a
	// second instance and duplicate every toolbar button on the shared page header.
	let fired = false;
	const once = (options) => {
		if (fired) return;
		fired = true;
		callback(options);
	};
	frappe.call({
		method: 'alpinos.purchase.inward_list_api.get_filter_options',
		callback: function (r) {
			PIW_OPTIONS_CACHE = (r && r.message) || PIW_FALLBACK_OPTIONS;
			once(PIW_OPTIONS_CACHE);
		},
		error: function () {
			once(PIW_FALLBACK_OPTIONS);
		},
	});
}

// BRD 1.1 columns, in the BRD's order, plus Status and the action buttons.
// `width` drives the <colgroup> so header and data share one fixed column grid.
var PIW_COLUMNS = [
	{
		label: 'Inward ID',
		sort: 'name',
		width: '11%',
		render: (d, h) => `<strong>${h.esc(d.name)}</strong>`,
	},
	{
		label: 'Purchase Order No.',
		sort: 'purchase_order',
		width: '11%',
		render: (d, h) => h.po(d),
	},
	{ label: 'Inward Type', sort: 'inward_type', width: '8%', render: (d, h) => h.dash(d.inward_type) },
	{
		label: 'Vendor Name',
		sort: 'supplier_name',
		width: '16%',
		render: (d, h) => h.dash(d.supplier_name || d.supplier),
	},
	{
		label: 'Order Qty',
		sort: 'total_order_qty',
		cls: 'text-right',
		width: '10%',
		render: (d, h) => h.qty(d.total_order_qty, d.uom),
	},
	{
		label: 'Vehicle No.',
		// sorts on the same COALESCE the cell renders, not on actual_vehicle_no alone
		sort: 'vehicle_no',
		width: '11%',
		render: (d, h) => h.dash(d.vehicle_no),
	},
	{
		label: 'Total Items',
		sort: 'total_items',
		cls: 'text-right',
		width: '7%',
		render: (d, h) => h.dash(d.total_items),
	},
	{
		label: 'Received Qty',
		sort: 'total_received_qty',
		cls: 'text-right',
		width: '10%',
		render: (d, h) => h.qty(d.total_received_qty, d.uom),
	},
	{ label: 'Status', sort: 'inward_status', width: '12%', render: (d, h) => h.status(d) },
	{ label: 'Actions', cls: 'piw-col-actions', width: '14%', render: (d, h) => h.actions(d) },
];

// Row buttons that open another document rather than the inward itself.
var PIW_LINKED_ROUTES = {
	view_qc: ['Purchase QC', 'purchase_qc'],
	view_qc_report: ['Purchase QC', 'purchase_qc'],
	view_grn: ['Purchase Receipt', 'purchase_receipt'],
	view_invoice: ['Purchase Invoice', 'purchase_invoice'],
	// BRD 5.2.3 "View Debit Note". The engine offers this action to the list as well as
	// the form, so without a route here the row button would open the wrong document.
	view_debit_note: ['Purchase Invoice', 'debit_note'],
};

function piw_body_html() {
	return `
<style>
	.piw-list-container { display: block; }
	.piw-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 10px 14px;
	}
	.piw-grid > * { min-width: 0; }
	.piw-viewbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.piw-viewbar-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-muted, #6b7280);
		margin: 0;
	}
	.piw-page-length { width: auto; min-width: 72px; display: inline-block; }
	.piw-table-wrapper { padding: 0; overflow-x: auto; }
	.piw-table-wrapper > .piw-list-table {
		width: 100%;
		min-width: 1240px;
		margin-bottom: 0;
		font-size: 13px;
		border-collapse: collapse;
	}
	.piw-list-table th, .piw-list-table td {
		padding: 9px 12px;
		border-bottom: 1px solid var(--border-color, #e2e2e2);
		white-space: nowrap;
		vertical-align: middle;
	}
	.piw-list-table thead th {
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
	.piw-list-table tbody tr.piw-list-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	/* The shared sheet tints .indicator-pill only inside its registered
	   [data-page-route="..."] list, and this route is not on it yet, so the pill
	   shape is mirrored locally. Statuses here are long ("Pending Material
	   Receipt"), and Frappe core pins .indicator-pill to height:20px with centered
	   content, which makes a two-word label spill above and below the chip. */
	.piw-list-table .indicator-pill {
		height: auto;
		min-height: 20px;
		white-space: nowrap;
		line-height: 1.3;
		padding: 3px 10px;
		border-radius: 100px;
		font-weight: 600;
	}
	.piw-list-table td.piw-col-actions { white-space: nowrap; }
	.piw-list-table td.piw-col-actions .btn { margin-right: 4px; }
	.piw-act-disabled { display: inline-block; }
	.piw-pager {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 12px;
	}
	.piw-nav { display: flex; align-items: center; gap: 10px; }
</style>

<div class="piw-list-container">
	<div class="piw-list-filters alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="piw-grid">
			<div class="fld-search"></div>
			<div class="fld-inward-type"></div>
			<div class="fld-supplier"></div>
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-purchase-order"></div>
			<div class="fld-supplier-order-no"></div>
			<div class="fld-vehicle-no"></div>
			<div class="fld-qc-status"></div>
			<div class="fld-inward-status"></div>
			<div class="fld-created-by"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-piw-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-piw-clear">${__('Clear')}</button>
			<span class="piw-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>

	<div class="piw-viewbar">
		<label class="piw-viewbar-label">${__('Rows per page')}</label>
		<select class="form-control input-xs piw-page-length"></select>
	</div>

	<div class="piw-table-wrapper alp-card">
		<table class="piw-list-table">
			<thead><tr></tr></thead>
			<tbody></tbody>
		</table>
	</div>

	<div class="piw-pager">
		<div class="piw-count text-muted"></div>
		<div class="piw-nav">
			<button class="btn btn-default btn-sm btn-piw-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-piw-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseInwardListPage = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || PIW_FALLBACK_OPTIONS;
		this.page_lengths = Array.isArray(this.options.page_lengths)
			? this.options.page_lengths.map((v) => cint(v)).filter((v) => v > 0)
			: PIW_PAGE_LENGTHS;
		this.page_length = this.page_lengths[0] || 20;
		this.start = 0;
		this._last_meta = { has_more: 0, start: 0, total: 0 };
		this._filter_fields = {};
		this._rows_by_name = {};
		// guards the auto-apply handler against programmatic writes (Clear, prefs restore)
		this._suspend_auto = false;
		this._sort = { field: '', dir: 'desc' };
		this._columns = PIW_COLUMNS;
		this.setup_toolbar(); // page-header buttons: added ONCE, never on re-render
		this.render_body();
	}

	// Safe to call on every page show; never touches the toolbar.
	render_body() {
		this.page.main.html(piw_body_html());
		this.wrapper = $(this.page.main);
		this.render_page_length_options();
		this.setup_filters();
		this.render_header();
		// restore BEFORE the first load and before events bind, so nothing fires mid-restore
		this._restore_view_prefs();
		this.bind_events();
		this.load_list();
	}

	setup_toolbar() {
		if (cint(this.options.can_create) && frappe.model.can_create('Purchase Inward')) {
			this.page.set_primary_action(
				__('New Purchase Inward'),
				// The BRD entry screen, not the raw desk form — every other route out of
				// this list goes there, and new_doc() would have been the one exception.
				() => frappe.set_route('purchase_inward_entry'),
				'fa fa-plus'
			);
		}
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
	}

	render_page_length_options() {
		const sel = this.wrapper.find('.piw-page-length').empty();
		this.page_lengths.forEach((n) => {
			sel.append(`<option value="${n}">${n}</option>`);
		});
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

		mk('search', { fieldtype: 'Data', label: __('Search (ID, Vendor, Invoice No.)') }, '.fld-search');
		mk(
			'inward_type',
			{ fieldtype: 'Select', label: __('Inward Type'), options: this.options.inward_types },
			'.fld-inward-type'
		);
		mk('supplier', { fieldtype: 'Link', label: __('Vendor Name'), options: 'Supplier' }, '.fld-supplier');
		mk('from_date', { fieldtype: 'Date', label: __('Inward Date (From)') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('Inward Date (To)') }, '.fld-to-date');
		mk(
			'purchase_order',
			{ fieldtype: 'Link', label: __('PO Number'), options: 'Purchase Order' },
			'.fld-purchase-order'
		);
		mk('supplier_order_no', { fieldtype: 'Data', label: __('Order No.') }, '.fld-supplier-order-no');
		mk('vehicle_no', { fieldtype: 'Data', label: __('Vehicle Number') }, '.fld-vehicle-no');
		mk(
			'qc_status',
			{ fieldtype: 'Select', label: __('QC Status'), options: this.options.qc_statuses },
			'.fld-qc-status'
		);
		mk(
			'inward_status',
			{ fieldtype: 'Select', label: __('Current Status'), options: this.options.inward_statuses },
			'.fld-inward-status'
		);
		mk('created_by', { fieldtype: 'Link', label: __('Created By'), options: 'User' }, '.fld-created-by');
	}

	bind_events() {
		// render_body() runs on every page show; delegated handlers live on the persistent
		// container, so clear the namespace first or they fire N times after N visits.
		this.wrapper.off('.piwlist');

		this.wrapper.find('.btn-piw-apply').on('click', () => {
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-piw-clear').on('click', () => {
			this._suspend_auto = true;
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this._suspend_auto = false;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.piw-page-length').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = this.page_lengths.includes(v) ? v : this.page_lengths[0] || 20;
			$(e.currentTarget).val(String(this.page_length));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-piw-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-piw-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});

		this.wrapper.on('click.piwlist', '.piw-list-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_inward_entry', String(name));
		});
		this.wrapper.on('click.piwlist', '.piw-act-btn', (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this.run_action(String($btn.data('name') || ''), String($btn.data('action') || ''));
		});
		this.wrapper.on('click.piwlist', '.piw-po-link', (e) => {
			e.preventDefault();
			e.stopPropagation();
			const po = $(e.currentTarget).data('po');
			if (po) frappe.set_route('Form', 'Purchase Order', String(po));
		});
		this.wrapper.on('click.piwlist', '.piw-sort-th', (e) => {
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
		const apply = frappe.utils.debounce(() => {
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		}, 350);
		// the flag is read here, synchronously, not inside the debounced body — by the
		// time a 350ms window elapses Clear/restore has already cleared it, and the
		// suppressed reload would fire anyway.
		const auto = () => {
			if (this._suspend_auto) return;
			apply();
		};
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
		alpinos.list_prefs.save(PIW_LIST_ROUTE, {
			filters: {
				search: val('search'),
				inward_type: val('inward_type'),
				supplier: val('supplier'),
				from_date: val('from_date'),
				to_date: val('to_date'),
				purchase_order: val('purchase_order'),
				supplier_order_no: val('supplier_order_no'),
				vehicle_no: val('vehicle_no'),
				qc_status: val('qc_status'),
				inward_status: val('inward_status'),
				created_by: val('created_by'),
			},
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
			saved = alpinos.list_prefs.load(PIW_LIST_ROUTE) || {};
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
				if (field.df.fieldtype === 'Select' && !piw_option_values(field).includes(value)) return;
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
			this.wrapper.find('.piw-page-length').val(String(this.page_length));
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
			search: val('search'),
			inward_type: val('inward_type'),
			supplier: val('supplier'),
			from_date: val('from_date'),
			to_date: val('to_date'),
			purchase_order: val('purchase_order'),
			supplier_order_no: val('supplier_order_no'),
			vehicle_no: val('vehicle_no'),
			qc_status: val('qc_status'),
			inward_status: val('inward_status'),
			created_by: val('created_by'),
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir || 'desc',
			with_actions: 1,
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.inward_list_api.get_purchase_inward_list',
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
				me.render_rows(msg.data || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		// colgroup so the header row and the data rows share one column grid
		const table = this.wrapper.find('.piw-list-table');
		let cg = table.children('colgroup');
		if (!cg.length) {
			cg = $('<colgroup></colgroup>');
			table.prepend(cg);
		}
		cg.empty();
		this._columns.forEach((c) => cg.append(`<col${c.width ? ` style="width:${c.width}"` : ''}>`));

		const tr = this.wrapper.find('.piw-list-table thead tr').empty();
		this._columns.forEach((c) => {
			if (!c.sort) {
				tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`);
				return;
			}
			const active = this._sort.field === c.sort;
			const arrow = active ? (this._sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${c.cls || ''} piw-sort-th" data-sort="${c.sort}" ` +
					`style="cursor:pointer; user-select:none;" title="${__('Click to sort')}">` +
					`${__(c.label)}<span class="text-muted" style="font-size:10px; opacity:${
						active ? 1 : 0.4
					};">${arrow}</span></th>`
			);
		});
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.piw-list-table tbody').empty();
		this._rows_by_name = {};
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__(
					'No Purchase Inwards found'
				)}</td></tr>`
			);
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
			po: (d) =>
				d.purchase_order
					? `<button type="button" class="btn btn-xs btn-default piw-po-link" data-po="${esc(
							d.purchase_order
					  )}" title="${esc(__('Open Purchase Order'))}">${esc(d.purchase_order)}</button>`
					: '—',
			status: (d) => {
				const s = d.inward_status || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PIW_STATUS_COLORS[s] || 'gray'}">${esc(s)}</span>`;
			},
			actions: (d) => {
				const acts = Array.isArray(d.actions) ? d.actions : [];
				if (!acts.length) return '—';
				return acts
					.map((a) => {
						const label = esc(a.label || a.action);
						const cls = a.kind === 'transition' ? 'btn-primary' : 'btn-default';
						if (a.enabled === false) {
							// a disabled button swallows its own tooltip, so the guard reason
							// (BRD 1.4) is carried on a wrapper span instead
							return `<span class="piw-act-disabled" title="${esc(
								a.reason || __('Not available at this stage')
							)}"><button type="button" class="btn btn-xs ${cls}" disabled>${label}</button></span>`;
						}
						return `<button type="button" class="btn btn-xs ${cls} piw-act-btn" data-name="${esc(
							d.name
						)}" data-action="${esc(a.action)}" title="${label}">${label}</button>`;
					})
					.join(' ');
			},
		};
		rows.forEach((d) => {
			this._rows_by_name[d.name] = d;
			const cells = this._columns
				.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`)
				.join('');
			tb.append(
				`<tr class="piw-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`
			);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.piw-list-table tbody tr.piw-list-row').length;
		const total = cint(this._last_meta.total);
		if (!n) {
			this.wrapper.find('.piw-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.piw-count').text(__('Showing {0}–{1} of {2}', [from, to, total]));
		}
		this.wrapper.find('.piw-total').text(__('{0} Purchase Inward(s)', [total]));
		this.wrapper.find('.btn-piw-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-piw-next').prop('disabled', !this._last_meta.has_more);
	}

	// ------------------------------------------------------------- row actions

	run_action(name, action) {
		const d = this._rows_by_name[name];
		if (!d || !action) return;
		const act = (d.actions || []).find((a) => a.action === action);
		if (!act || act.enabled === false) return;

		if (action === 'print') {
			frappe.set_route('print', 'Purchase Inward', name);
			return;
		}
		if (action === 'delete') {
			frappe.model.delete_doc('Purchase Inward', name, () => this.load_list());
			return;
		}

		const linked = PIW_LINKED_ROUTES[action];
		if (linked) {
			const target = d[linked[1]];
			if (!target) {
				frappe.msgprint(__('No linked {0} yet for {1}.', [linked[0], name]));
				return;
			}
			// The module's own documents open on their purpose-built entry screens
			// (BRD 2 / BRD 4); anything else falls back to the desk form.
			if (linked[0] === 'Purchase QC') frappe.set_route('purchase_qc_entry', String(target));
			else frappe.set_route('Form', linked[0], String(target));
			return;
		}

		// view / edit / continue receiving and every workflow transition are performed on
		// the document itself, whose buttons come from the same workflow engine — the list
		// opens it rather than running a second, divergent copy of the transition here.
		if (act.kind === 'transition') {
			frappe.show_alert({ message: __('Opening {0} to {1}', [name, act.label]), indicator: 'blue' });
		}
		frappe.set_route('purchase_inward_entry', name);
	}
};

// Select options arrive either as a newline string or as [{value, label}] objects.
function piw_option_values(field) {
	const opts = (field && field.df && field.df.options) || '';
	if (Array.isArray(opts)) {
		return opts.map((o) => (o && typeof o === 'object' ? String(o.value) : String(o)));
	}
	return String(opts).split('\n');
}
