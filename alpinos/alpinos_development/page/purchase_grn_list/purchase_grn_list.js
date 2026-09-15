// GRN List — the goods receipts this module raised (BRD 5.1).
//
// Same shape as the Purchase Inward, QC and Invoice lists: filters, sorting and pagination
// are server-driven (alpinos.purchase.grn_list_api.get_grn_list), and the per-row buttons
// come from that same endpoint.
//
// The GRN is ERPNext's Purchase Receipt, so this list draws a boundary the others do not:
// only receipts carrying a Purchase Inward link, and never a Purchase Return
// (make_purchase_return copies that link off the receipt it returns). The boundary lives
// in grn_list_api._module_filters, server-side, so it cannot be argued with from here.
//
// Both Draft and Completed GRNs are listed (5.1), and Cancelled ones too, since this is
// where a cancelled GRN is found again to be amended. Rows open the GRN screen.

frappe.pages['purchase_grn_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('GRN List'),
		single_column: true,
	});
	pgrn_load_options(function (options) {
		wrapper.__pgrn_list_page = new PurchaseGRNListPage(page, options);
	});
};

// Frappe caches custom pages, so on_page_load runs once — re-render the body on every
// show or navigating back leaves a stale list. The toolbar is built in the constructor only.
frappe.pages['purchase_grn_list'].on_page_show = function (wrapper) {
	if (wrapper.__pgrn_list_page) wrapper.__pgrn_list_page.render_body();
};

// Route key for alpinos.list_prefs — must stay the exact frappe.pages key.
var PGRN_LIST_ROUTE = 'purchase_grn_list';
var PGRN_PAGE_LENGTHS = [20, 50, 100];

// Used only when get_filter_options() is unavailable; the server copy wins.
var PGRN_FALLBACK_OPTIONS = {
	grn_statuses: ['Draft', 'Completed', 'Cancelled'],
	page_lengths: PGRN_PAGE_LENGTHS,
};

var PGRN_STATUS_COLORS = {
	Draft: 'orange',
	Completed: 'green',
	Cancelled: 'red',
};

var PGRN_OPTIONS_CACHE = null;

function pgrn_load_options(callback) {
	if (PGRN_OPTIONS_CACHE) {
		callback(PGRN_OPTIONS_CACHE);
		return;
	}
	frappe.call({
		method: 'alpinos.purchase.grn_list_api.get_filter_options',
		callback: function (r) {
			PGRN_OPTIONS_CACHE = (r && r.message) || PGRN_FALLBACK_OPTIONS;
			callback(PGRN_OPTIONS_CACHE);
		},
		error: function () {
			callback(PGRN_FALLBACK_OPTIONS);
		},
	});
}

// BRD 5.1.2 columns, in order, plus GRN Status and the buttons.
// `width` drives the <colgroup> so header and data share one grid.
var PGRN_COLUMNS = [
	{
		label: 'GRN ID',
		sort: 'name',
		width: '10%',
		render: (d, h) => `<strong>${h.esc(d.name)}</strong>`,
	},
	{
		label: 'Purchase Inward ID',
		sort: 'custom_purchase_inward',
		width: '10%',
		render: (d, h) => h.link_btn(d.custom_purchase_inward, 'inward', __('Open Purchase Inward')),
	},
	{
		label: 'PO No.',
		width: '10%',
		// A merged inward can carry lines from more than one PO.
		render: (d, h) =>
			(d.purchase_orders || []).length
				? d.purchase_orders.map((po) => h.link_btn(po, 'po', __('Open Purchase Order'))).join(' ')
				: '—',
	},
	{
		label: 'Vendor Name',
		sort: 'supplier_name',
		width: '14%',
		render: (d, h) => h.dash(d.supplier_name || d.supplier),
	},
	{
		label: 'Target Location',
		width: '14%',
		// A line can land outside the inward's target location (a quarantine store).
		render: (d, h) => h.dash((d.target_locations || []).join(', ')),
	},
	{ label: 'Received Qty', cls: 'text-right', width: '8%', render: (d, h) => h.qty(d.received_qty) },
	{ label: 'Approved Qty', cls: 'text-right', width: '8%', render: (d, h) => h.qty(d.accepted_qty) },
	{
		label: 'Rejected Qty',
		cls: 'text-right',
		width: '8%',
		render: (d, h) =>
			flt(d.rejected_qty)
				? `<span class="text-danger">${h.qty(d.rejected_qty)}</span>`
				: h.qty(d.rejected_qty),
	},
	{ label: 'GRN Status', sort: 'custom_grn_status', width: '8%', render: (d, h) => h.status(d) },
	{ label: 'Actions', cls: 'pgrn-col-actions', width: '10%', render: (d, h) => h.actions(d) },
];

function pgrn_body_html() {
	return `
<style>
	.pgrn-list-container { display: block; }
	.pgrn-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 10px 14px;
	}
	.pgrn-grid > * { min-width: 0; }
	.pgrn-viewbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.pgrn-viewbar-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-muted, #6b7280);
		margin: 0;
	}
	.pgrn-page-length { width: auto; min-width: 72px; display: inline-block; }
	.pgrn-table-wrapper { padding: 0; overflow-x: auto; }
	.pgrn-table-wrapper > .pgrn-list-table {
		width: 100%;
		min-width: 1250px;
		margin-bottom: 0;
		font-size: 13px;
		border-collapse: collapse;
	}
	.pgrn-list-table th, .pgrn-list-table td {
		padding: 9px 12px;
		border-bottom: 1px solid var(--border-color, #e2e2e2);
		white-space: nowrap;
		vertical-align: middle;
	}
	.pgrn-list-table thead th {
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
	.pgrn-list-table tbody tr.pgrn-list-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	.pgrn-list-table td.pgrn-col-actions .btn { margin-right: 4px; }
	.pgrn-pager {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 12px;
	}
	.pgrn-nav { display: flex; align-items: center; gap: 10px; }
</style>

<div class="pgrn-list-container">
	<div class="pgrn-list-filters alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="pgrn-grid">
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-purchase-inward"></div>
			<div class="fld-purchase-order"></div>
			<div class="fld-supplier"></div>
			<div class="fld-target-location"></div>
			<div class="fld-grn-status"></div>
			<div class="fld-purchase-qc"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-pgrn-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-pgrn-clear">${__('Clear')}</button>
			<span class="pgrn-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>

	<div class="pgrn-viewbar">
		<label class="pgrn-viewbar-label">${__('Rows per page')}</label>
		<select class="form-control input-xs pgrn-page-length"></select>
	</div>

	<div class="pgrn-table-wrapper alp-card">
		<table class="pgrn-list-table">
			<thead><tr></tr></thead>
			<tbody></tbody>
		</table>
	</div>

	<div class="pgrn-pager">
		<div class="pgrn-count text-muted"></div>
		<div class="pgrn-nav">
			<button class="btn btn-default btn-sm btn-pgrn-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-pgrn-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseGRNListPage = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || PGRN_FALLBACK_OPTIONS;
		this.page_lengths = Array.isArray(this.options.page_lengths)
			? this.options.page_lengths.map((v) => cint(v)).filter((v) => v > 0)
			: PGRN_PAGE_LENGTHS;
		this.page_length = this.page_lengths[0] || 20;
		this.start = 0;
		this._last_meta = { has_more: 0, start: 0, total: 0 };
		this._filter_fields = {};
		this._rows_by_name = {};
		// guards the auto-apply handler against programmatic writes (Clear, prefs restore)
		this._suspend_auto = false;
		this._sort = { field: '', dir: 'desc' };
		this._columns = PGRN_COLUMNS;
		this.setup_toolbar(); // page-header buttons: added ONCE, never on re-render
		this.render_body();
	}

	// Safe to call on every page show; never touches the toolbar.
	render_body() {
		this.page.main.html(pgrn_body_html());
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
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
	}

	render_page_length_options() {
		const sel = this.wrapper.find('.pgrn-page-length').empty();
		this.page_lengths.forEach((n) => {
			sel.append(`<option value="${n}">${n}</option>`);
		});
		sel.val(String(this.page_length));
	}

	// --------------------------------------------------------------- filters

	// BRD 5.1.1, plus GRN Status (5.1 lists Draft and Completed GRNs together) and the QC.
	setup_filters() {
		const w = this.wrapper;
		const mk = (key, df, selector) => {
			this._filter_fields[key] = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: key }, df),
				parent: w.find(selector),
				render_input: true,
			});
		};

		mk('from_date', { fieldtype: 'Date', label: __('GRN Date (From)') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('GRN Date (To)') }, '.fld-to-date');
		mk(
			'purchase_inward',
			{ fieldtype: 'Link', label: __('Purchase Inward ID'), options: 'Purchase Inward' },
			'.fld-purchase-inward'
		);
		mk(
			'purchase_order',
			{ fieldtype: 'Link', label: __('PO Number'), options: 'Purchase Order' },
			'.fld-purchase-order'
		);
		mk('supplier', { fieldtype: 'Link', label: __('Vendor Name'), options: 'Supplier' }, '.fld-supplier');
		mk(
			'target_location',
			{
				fieldtype: 'Link',
				label: __('Target Location'),
				options: 'Warehouse',
				get_query: () => ({ filters: { is_group: 0 } }),
			},
			'.fld-target-location'
		);
		mk(
			'grn_status',
			{
				fieldtype: 'Select',
				label: __('GRN Status'),
				options: [''].concat(this.options.grn_statuses || PGRN_FALLBACK_OPTIONS.grn_statuses).join('\n'),
			},
			'.fld-grn-status'
		);
		mk(
			'purchase_qc',
			{ fieldtype: 'Link', label: __('Purchase QC ID'), options: 'Purchase QC' },
			'.fld-purchase-qc'
		);
	}

	bind_events() {
		// render_body() runs on every page show; delegated handlers live on the persistent
		// container, so clear the namespace first or they fire N times after N visits.
		this.wrapper.off('.pgrnlist');

		this.wrapper.find('.btn-pgrn-apply').on('click', () => {
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pgrn-clear').on('click', () => {
			this._suspend_auto = true;
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this._suspend_auto = false;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.pgrn-page-length').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = this.page_lengths.includes(v) ? v : this.page_lengths[0] || 20;
			$(e.currentTarget).val(String(this.page_length));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pgrn-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-pgrn-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});

		this.wrapper.on('click.pgrnlist', '.pgrn-list-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_grn_view', String(name));
		});
		this.wrapper.on('click.pgrnlist', '.pgrn-act-btn', (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this.run_action(String($btn.data('name') || ''), String($btn.data('action') || ''));
		});
		this.wrapper.on('click.pgrnlist', '.pgrn-link-btn', (e) => {
			e.preventDefault();
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const target = String($btn.data('target') || '');
			const value = String($btn.data('value') || '');
			if (!value) return;
			if (target === 'po') frappe.set_route('Form', 'Purchase Order', value);
			else frappe.set_route('purchase_inward_entry', value);
		});
		this.wrapper.on('click.pgrnlist', '.pgrn-sort-th', (e) => {
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

	_save_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		const f = this._filter_fields;
		const filters = {};
		Object.keys(f).forEach((name) => {
			filters[name] = (f[name] && f[name].get_value()) || '';
		});
		alpinos.list_prefs.save(PGRN_LIST_ROUTE, {
			filters: filters,
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir === 'asc' ? 'asc' : 'desc',
			page_length: this.page_length,
		});
	}

	// Saved prefs are untrusted localStorage: every value is validated and the whole
	// restore is wrapped so a malformed blob can never blank the page.
	_restore_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		let saved = {};
		try {
			saved = alpinos.list_prefs.load(PGRN_LIST_ROUTE) || {};
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
				if (field.df.fieldtype === 'Select' && !String(field.df.options || '').split('\n').includes(value)) {
					return;
				}
				// set_input applies synchronously so the first load_list() sees it
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
			this.wrapper.find('.pgrn-page-length').val(String(this.page_length));
		} catch (e) {
			// a bad saved state must never break the page
		}
		this._suspend_auto = false;
		this.start = 0;
	}

	// ------------------------------------------------------------- load/render

	_args() {
		const f = this._filter_fields;
		const val = (name) => (f[name] && f[name].get_value()) || '';
		return {
			start: this.start,
			page_length: this.page_length,
			from_date: val('from_date'),
			to_date: val('to_date'),
			purchase_inward: val('purchase_inward'),
			purchase_order: val('purchase_order'),
			supplier: val('supplier'),
			target_location: val('target_location'),
			grn_status: val('grn_status'),
			purchase_qc: val('purchase_qc'),
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir || 'desc',
			with_actions: 1,
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.grn_list_api.get_grn_list',
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
				me.render_rows(msg.data || msg.rows || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		const table = this.wrapper.find('.pgrn-list-table');
		let cg = table.children('colgroup');
		if (!cg.length) {
			cg = $('<colgroup></colgroup>');
			table.prepend(cg);
		}
		cg.empty();
		this._columns.forEach((c) => cg.append(`<col${c.width ? ` style="width:${c.width}"` : ''}>`));

		const tr = this.wrapper.find('.pgrn-list-table thead tr').empty();
		this._columns.forEach((c) => {
			if (!c.sort) {
				tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`);
				return;
			}
			const active = this._sort.field === c.sort;
			const arrow = active ? (this._sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${c.cls || ''} pgrn-sort-th" data-sort="${c.sort}" ` +
					`style="cursor:pointer; user-select:none;" title="${__('Click to sort')}">` +
					`${__(c.label)}<span class="text-muted" style="font-size:10px; opacity:${
						active ? 1 : 0.4
					};">${arrow}</span></th>`
			);
		});
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.pgrn-list-table tbody').empty();
		this._rows_by_name = {};
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__(
					'No GRN matches these filters. A GRN appears here once a Purchase QC is completed.'
				)}</td></tr>`
			);
			return;
		}
		// every interpolated value is escaped — rows are built with template literals
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			dash: (v) => (v == null || v === '' ? '—' : esc(v)),
			qty: (v) => esc(format_number(flt(v), null, 3)),
			link_btn: (value, target, title) =>
				value
					? `<button type="button" class="btn btn-xs btn-default pgrn-link-btn" data-target="${esc(
							target
					  )}" data-value="${esc(value)}" title="${esc(title)}">${esc(value)}</button>`
					: '—',
			status: (d) => {
				const s = d.custom_grn_status || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PGRN_STATUS_COLORS[s] || 'gray'}">${esc(__(s))}</span>`;
			},
			actions: (d) => {
				const acts = Array.isArray(d.actions) ? d.actions : [];
				if (!acts.length) return '—';
				return acts
					.map((a) => {
						const label = esc(a.label || a.action);
						const cls = a.kind === 'transition' ? 'btn-primary' : 'btn-default';
						return `<button type="button" class="btn btn-xs ${cls} pgrn-act-btn" data-name="${esc(
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
				`<tr class="pgrn-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`
			);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.pgrn-list-table tbody tr.pgrn-list-row').length;
		const total = cint(this._last_meta.total);
		if (!n) {
			this.wrapper.find('.pgrn-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.pgrn-count').text(__('Showing {0}–{1} of {2}', [from, to, total]));
		}
		this.wrapper.find('.pgrn-total').text(__('{0} GRN(s)', [total]));
		this.wrapper.find('.btn-pgrn-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pgrn-next').prop('disabled', !this._last_meta.has_more);
	}

	// ------------------------------------------------------------- row actions

	run_action(name, action) {
		const d = this._rows_by_name[name];
		if (!d || !(d.actions || []).some((a) => a.action === action)) return;
		// View and Edit both open the GRN screen: a Draft is editable there for whoever
		// may change it, and read-only for everyone else.
		frappe.set_route('purchase_grn_view', name);
	}
};
