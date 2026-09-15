// Purchase Invoice & Payment list screen — BRD "Purchase Invoice & Payment", section 6.1.
//
// Same shape as the Purchase Inward and Purchase QC lists: columns, filters, sorting and
// pagination are server-driven (alpinos.purchase.invoice_list_api.get_invoice_list), and
// the per-row buttons come from that same endpoint, so the list never offers an action
// the server would refuse. Only invoices this module raised are listed -- a GRN's debit
// note and ordinary Accounts invoices stay out.
//
// Status is the invoice's one payment status (Pending Payment / Partially Paid / Paid); the
// document state (Draft / Submitted / Cancelled) has its own column and filter.

frappe.pages['purchase_invoice_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Purchase Invoices'),
		single_column: true,
	});
	pinv_load_options(function (options) {
		wrapper.__pinv_list_page = new PurchaseInvoiceListPage(page, options);
	});
};

// Frappe caches custom pages, so on_page_load runs once — re-render the body on every
// show or navigating back leaves a stale list. The toolbar is built in the constructor only.
frappe.pages['purchase_invoice_list'].on_page_show = function (wrapper) {
	if (wrapper.__pinv_list_page) wrapper.__pinv_list_page.render_body();
};

// Route key for alpinos.list_prefs — must stay the exact frappe.pages key.
var PINV_LIST_ROUTE = 'purchase_invoice_list';
var PINV_PAGE_LENGTHS = [20, 50, 100];
var PINV_DIRECT = 'Direct Purchase Invoice';

// Used only when get_filter_options() is unavailable; the server copy wins.
var PINV_FALLBACK_OPTIONS = {
	statuses: '\nPending Payment\nPartially Paid\nPaid',
	doc_states: '\nDraft\nSubmitted\nCancelled',
	invoice_types: [
		{ value: '', label: '' },
		{ value: 'Normal', label: 'Normal Invoice' },
		{ value: PINV_DIRECT, label: 'Direct Invoice' },
	],
	page_lengths: PINV_PAGE_LENGTHS,
	can_create: 0,
};

var PINV_STATUS_COLORS = {
	'Pending Payment': 'orange',
	'Partially Paid': 'yellow',
	Paid: 'green',
};

var PINV_DOC_STATE_COLORS = {
	Draft: 'gray',
	Submitted: 'blue',
	Cancelled: 'red',
};

var PINV_OPTIONS_CACHE = null;

function pinv_load_options(callback) {
	if (PINV_OPTIONS_CACHE) {
		callback(PINV_OPTIONS_CACHE);
		return;
	}
	frappe.call({
		method: 'alpinos.purchase.invoice_list_api.get_filter_options',
		callback: function (r) {
			PINV_OPTIONS_CACHE = (r && r.message) || PINV_FALLBACK_OPTIONS;
			callback(PINV_OPTIONS_CACHE);
		},
		error: function () {
			callback(PINV_FALLBACK_OPTIONS);
		},
	});
}

// BRD 6.1 columns, in the BRD's order, plus Type, Amount, Pending, Status and the buttons.
// `width` drives the <colgroup> so header and data share one grid.
var PINV_COLUMNS = [
	{
		label: 'Invoice ID',
		sort: 'name',
		width: '9%',
		render: (d, h) => `<strong>${h.esc(d.name)}</strong>`,
	},
	{
		label: 'Purchase Inward ID',
		sort: 'custom_purchase_inward',
		width: '8%',
		render: (d, h) => h.link_btn(d.custom_purchase_inward, 'inward', __('Open Purchase Inward')),
	},
	{
		label: 'GRN ID',
		sort: 'custom_grn',
		width: '8%',
		render: (d, h) => h.link_btn(d.custom_grn, 'grn', __('Open GRN')),
	},
	{
		label: 'PO No.',
		width: '8%',
		render: (d, h) =>
			(d.purchase_orders || []).length
				? d.purchase_orders.map((po) => h.link_btn(po, 'po', __('Open Purchase Order'))).join(' ')
				: '—',
	},
	{
		label: 'Supplier',
		sort: 'supplier_name',
		width: '12%',
		render: (d, h) => h.dash(d.supplier_name || d.supplier),
	},
	{ label: 'Invoice No.', sort: 'bill_no', width: '8%', render: (d, h) => h.dash(d.bill_no) },
	{ label: 'Invoice Date', sort: 'bill_date', width: '7%', render: (d, h) => h.date(d.bill_date) },
	{
		label: 'Payment Due Date',
		sort: 'custom_payment_due_date',
		width: '7%',
		render: (d, h) => h.date(d.custom_payment_due_date),
	},
	{
		label: 'Type',
		width: '6%',
		render: (d, h) =>
			d.invoice_type === PINV_DIRECT
				? `<span class="indicator-pill purple">${__('Direct')}</span>`
				: `<span class="indicator-pill blue">${__('Normal')}</span>`,
	},
	{
		label: 'Amount',
		sort: 'grand_total',
		cls: 'text-right',
		width: '7%',
		render: (d, h) => h.money(d.invoice_amount, d.currency),
	},
	{
		label: 'Pending',
		cls: 'text-right',
		width: '7%',
		render: (d, h) => (cint(d.docstatus) === 1 ? h.money(d.pending_amount, d.currency) : '—'),
	},
	{ label: 'Status', sort: 'custom_unified_status', width: '8%', render: (d, h) => h.status(d) },
	{ label: 'Document', width: '6%', render: (d, h) => h.doc_state(d) },
	{ label: 'Actions', cls: 'pinv-col-actions', width: '10%', render: (d, h) => h.actions(d) },
];

function pinv_body_html() {
	return `
<style>
	.pinv-list-container { display: block; }
	.pinv-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
		gap: 10px 14px;
	}
	.pinv-grid > * { min-width: 0; }
	.pinv-viewbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.pinv-viewbar-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--text-muted, #6b7280);
		margin: 0;
	}
	.pinv-page-length { width: auto; min-width: 72px; display: inline-block; }
	.pinv-table-wrapper { padding: 0; overflow-x: auto; }
	.pinv-table-wrapper > .pinv-list-table {
		width: 100%;
		min-width: 1500px;
		margin-bottom: 0;
		font-size: 13px;
		border-collapse: collapse;
	}
	.pinv-list-table th, .pinv-list-table td {
		padding: 9px 12px;
		border-bottom: 1px solid var(--border-color, #e2e2e2);
		white-space: nowrap;
		vertical-align: middle;
	}
	.pinv-list-table thead th {
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
	.pinv-list-table tbody tr.pinv-list-row:hover { background: var(--bg-light-gray, #f6f7f9); }
	.pinv-list-table td.pinv-col-actions .btn { margin-right: 4px; }
	.pinv-pager {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		margin-top: 12px;
	}
	.pinv-nav { display: flex; align-items: center; gap: 10px; }
</style>

<div class="pinv-list-container">
	<div class="pinv-list-filters alp-card">
		<div class="alp-section-title">${__('Filters')}</div>
		<div class="pinv-grid">
			<div class="fld-invoice-id"></div>
			<div class="fld-grn"></div>
			<div class="fld-supplier"></div>
			<div class="fld-bill-no"></div>
			<div class="fld-from-date"></div>
			<div class="fld-to-date"></div>
			<div class="fld-due-from"></div>
			<div class="fld-due-to"></div>
			<div class="fld-invoice-type"></div>
			<div class="fld-status"></div>
			<div class="fld-doc-state"></div>
		</div>
		<div class="alp-actions" style="margin-top: 14px;">
			<button class="btn btn-primary btn-sm btn-pinv-apply">${__('Apply')}</button>
			<button class="btn btn-default btn-sm btn-pinv-clear">${__('Clear')}</button>
			<span class="pinv-total text-muted" style="margin-left: auto; font-size: 12px;"></span>
		</div>
	</div>

	<div class="pinv-viewbar">
		<label class="pinv-viewbar-label">${__('Rows per page')}</label>
		<select class="form-control input-xs pinv-page-length"></select>
	</div>

	<div class="pinv-table-wrapper alp-card">
		<table class="pinv-list-table">
			<thead><tr></tr></thead>
			<tbody></tbody>
		</table>
	</div>

	<div class="pinv-pager">
		<div class="pinv-count text-muted"></div>
		<div class="pinv-nav">
			<button class="btn btn-default btn-sm btn-pinv-prev">${__('Previous')}</button>
			<button class="btn btn-default btn-sm btn-pinv-next">${__('Next')}</button>
		</div>
	</div>
</div>`;
}

var PurchaseInvoiceListPage = class {
	constructor(page, options) {
		this.page = page;
		this.options = options || PINV_FALLBACK_OPTIONS;
		this.page_lengths = Array.isArray(this.options.page_lengths)
			? this.options.page_lengths.map((v) => cint(v)).filter((v) => v > 0)
			: PINV_PAGE_LENGTHS;
		this.page_length = this.page_lengths[0] || 20;
		this.start = 0;
		this._last_meta = { has_more: 0, start: 0, total: 0 };
		this._filter_fields = {};
		this._rows_by_name = {};
		// guards the auto-apply handler against programmatic writes (Clear, prefs restore)
		this._suspend_auto = false;
		this._sort = { field: '', dir: 'desc' };
		this._columns = PINV_COLUMNS;
		this.setup_toolbar(); // page-header buttons: added ONCE, never on re-render
		this.render_body();
	}

	// Safe to call on every page show; never touches the toolbar.
	render_body() {
		this.page.main.html(pinv_body_html());
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
		// BRD 6.1.2 "+ Create Invoice": from an eligible GRN, or a Direct Purchase Invoice PO.
		if (cint(this.options.can_create)) {
			this.page.set_primary_action(__('Create Invoice'), () => this.create_invoice(), 'fa fa-plus');
		}
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
	}

	render_page_length_options() {
		const sel = this.wrapper.find('.pinv-page-length').empty();
		this.page_lengths.forEach((n) => {
			sel.append(`<option value="${n}">${n}</option>`);
		});
		sel.val(String(this.page_length));
	}

	// --------------------------------------------------------------- filters

	// BRD 6.1.1, in the BRD's order.
	setup_filters() {
		const w = this.wrapper;
		const mk = (key, df, selector) => {
			this._filter_fields[key] = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: key }, df),
				parent: w.find(selector),
				render_input: true,
			});
		};

		mk('invoice_id', { fieldtype: 'Data', label: __('Invoice ID') }, '.fld-invoice-id');
		mk('grn', { fieldtype: 'Data', label: __('GRN ID') }, '.fld-grn');
		mk('supplier', { fieldtype: 'Link', label: __('Supplier'), options: 'Supplier' }, '.fld-supplier');
		mk('bill_no', { fieldtype: 'Data', label: __('Supplier Invoice No.') }, '.fld-bill-no');
		mk('from_date', { fieldtype: 'Date', label: __('Invoice Date (From)') }, '.fld-from-date');
		mk('to_date', { fieldtype: 'Date', label: __('Invoice Date (To)') }, '.fld-to-date');
		mk('due_from', { fieldtype: 'Date', label: __('Payment Due Date (From)') }, '.fld-due-from');
		mk('due_to', { fieldtype: 'Date', label: __('Payment Due Date (To)') }, '.fld-due-to');
		mk(
			'invoice_type',
			{ fieldtype: 'Select', label: __('PO Type'), options: this.options.invoice_types },
			'.fld-invoice-type'
		);
		mk('status', { fieldtype: 'Select', label: __('Status'), options: this.options.statuses }, '.fld-status');
		mk(
			'doc_state',
			{
				fieldtype: 'Select',
				label: __('Document'),
				options: this.options.doc_states || PINV_FALLBACK_OPTIONS.doc_states,
			},
			'.fld-doc-state'
		);
	}

	bind_events() {
		// render_body() runs on every page show; delegated handlers live on the persistent
		// container, so clear the namespace first or they fire N times after N visits.
		this.wrapper.off('.pinvlist');

		this.wrapper.find('.btn-pinv-apply').on('click', () => {
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pinv-clear').on('click', () => {
			this._suspend_auto = true;
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this._suspend_auto = false;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.pinv-page-length').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = this.page_lengths.includes(v) ? v : this.page_lengths[0] || 20;
			$(e.currentTarget).val(String(this.page_length));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pinv-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-pinv-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});

		this.wrapper.on('click.pinvlist', '.pinv-list-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('purchase_invoice_entry', String(name));
		});
		this.wrapper.on('click.pinvlist', '.pinv-act-btn', (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this.run_action(String($btn.data('name') || ''), String($btn.data('action') || ''));
		});
		this.wrapper.on('click.pinvlist', '.pinv-link-btn', (e) => {
			e.preventDefault();
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const target = String($btn.data('target') || '');
			const value = String($btn.data('value') || '');
			if (!value) return;
			if (target === 'po') frappe.set_route('Form', 'Purchase Order', value);
			else if (target === 'grn') frappe.set_route('purchase_grn_view', value);
			else frappe.set_route('purchase_inward_entry', value);
		});
		this.wrapper.on('click.pinvlist', '.pinv-sort-th', (e) => {
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
		alpinos.list_prefs.save(PINV_LIST_ROUTE, {
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
			saved = alpinos.list_prefs.load(PINV_LIST_ROUTE) || {};
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
				if (field.df.fieldtype === 'Select' && !pinv_option_values(field).includes(value)) return;
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
			this.wrapper.find('.pinv-page-length').val(String(this.page_length));
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
			invoice_id: val('invoice_id'),
			grn: val('grn'),
			supplier: val('supplier'),
			bill_no: val('bill_no'),
			from_date: val('from_date'),
			to_date: val('to_date'),
			due_from: val('due_from'),
			due_to: val('due_to'),
			invoice_type: val('invoice_type'),
			status: val('status'),
			doc_state: val('doc_state'),
			sort_field: this._sort.field || '',
			sort_dir: this._sort.dir || 'desc',
			with_actions: 1,
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.purchase.invoice_list_api.get_invoice_list',
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
		const table = this.wrapper.find('.pinv-list-table');
		let cg = table.children('colgroup');
		if (!cg.length) {
			cg = $('<colgroup></colgroup>');
			table.prepend(cg);
		}
		cg.empty();
		this._columns.forEach((c) => cg.append(`<col${c.width ? ` style="width:${c.width}"` : ''}>`));

		const tr = this.wrapper.find('.pinv-list-table thead tr').empty();
		this._columns.forEach((c) => {
			if (!c.sort) {
				tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`);
				return;
			}
			const active = this._sort.field === c.sort;
			const arrow = active ? (this._sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';
			tr.append(
				`<th class="${c.cls || ''} pinv-sort-th" data-sort="${c.sort}" ` +
					`style="cursor:pointer; user-select:none;" title="${__('Click to sort')}">` +
					`${__(c.label)}<span class="text-muted" style="font-size:10px; opacity:${
						active ? 1 : 0.4
					};">${arrow}</span></th>`
			);
		});
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.pinv-list-table tbody').empty();
		this._rows_by_name = {};
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__(
					'No Purchase Invoices found'
				)}</td></tr>`
			);
			return;
		}
		// every interpolated value is escaped — rows are built with template literals
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			dash: (v) => (v == null || v === '' ? '—' : esc(v)),
			date: (v) => (v ? esc(frappe.datetime.str_to_user(v)) : '—'),
			money: (v, currency) => esc(format_currency(flt(v), currency)),
			link_btn: (value, target, title) =>
				value
					? `<button type="button" class="btn btn-xs btn-default pinv-link-btn" data-target="${esc(
							target
					  )}" data-value="${esc(value)}" title="${esc(title)}">${esc(value)}</button>`
					: '—',
			doc_state: (d) => {
				const s = d.doc_state || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PINV_DOC_STATE_COLORS[s] || 'gray'}">${esc(__(s))}</span>`;
			},
			status: (d) => {
				const s = d.status || '';
				if (!s) return '—';
				return `<span class="indicator-pill ${PINV_STATUS_COLORS[s] || 'gray'}">${esc(__(s))}</span>`;
			},
			actions: (d) => {
				const acts = Array.isArray(d.actions) ? d.actions : [];
				if (!acts.length) return '—';
				return acts
					.map((a) => {
						const label = esc(a.label || a.action);
						const cls = a.kind === 'transition' ? 'btn-primary' : 'btn-default';
						return `<button type="button" class="btn btn-xs ${cls} pinv-act-btn" data-name="${esc(
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
				`<tr class="pinv-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`
			);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.pinv-list-table tbody tr.pinv-list-row').length;
		const total = cint(this._last_meta.total);
		if (!n) {
			this.wrapper.find('.pinv-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.pinv-count').text(__('Showing {0}–{1} of {2}', [from, to, total]));
		}
		this.wrapper.find('.pinv-total').text(__('{0} Purchase Invoice(s)', [total]));
		this.wrapper.find('.btn-pinv-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pinv-next').prop('disabled', !this._last_meta.has_more);
	}

	// ------------------------------------------------------------- row actions

	run_action(name, action) {
		const d = this._rows_by_name[name];
		if (!d || !action) return;
		const act = (d.actions || []).find((a) => a.action === action);
		if (!act) return;

		if (action === 'submit') {
			frappe.confirm(
				__('Submit {0}? The supplier bill locks and the invoice moves to the Accounts payment queue.', [name]),
				() =>
					frappe.call({
						method: 'alpinos.purchase.purchase_invoice.submit_invoice',
						args: { purchase_invoice: name },
						freeze: true,
						freeze_message: __('Submitting...'),
						callback: (r) => {
							// a refused submit (VAL-UNF-01..03) also lands here; reload either
							// way so the row shows the invoice's real state
							if (!r.exc) {
								frappe.show_alert({ message: __('{0} submitted', [name]), indicator: 'green' });
							}
							this.load_list();
						},
					})
			);
			return;
		}

		if (action === 'add_payment') {
			// The payment dialog lives on the invoice screen, next to the pending amounts
			// it is checked against.
			frappe.route_options = { add_payment: 1 };
		}
		// view / edit / add_payment all open the invoice screen, which is editable only
		// while the invoice is a Draft.
		frappe.set_route('purchase_invoice_entry', name);
	}

	// ---------------------------------------------------------- create invoice

	create_invoice() {
		const dialog = new frappe.ui.Dialog({
			title: __('Create Purchase Invoice'),
			fields: [
				{
					fieldname: 'source_type',
					fieldtype: 'Select',
					label: __('Create From'),
					options: [
						{ value: 'grn', label: __('Finally submitted GRN (Normal Invoice)') },
						{ value: 'po', label: __('Direct Purchase Invoice PO') },
					],
					default: 'grn',
					reqd: 1,
				},
				{
					fieldname: 'grn',
					fieldtype: 'Link',
					label: __('GRN'),
					options: 'Purchase Receipt',
					depends_on: "eval:doc.source_type=='grn'",
					description: __('Only GRNs finally submitted by the Admin that have no invoice yet.'),
					get_query: () => ({ query: 'alpinos.purchase.invoice_list_api.eligible_grn_query' }),
				},
				{
					fieldname: 'purchase_order',
					fieldtype: 'Link',
					label: __('Purchase Order'),
					options: 'Purchase Order',
					depends_on: "eval:doc.source_type=='po'",
					description: __('Only approved Direct Purchase Invoice orders that have no invoice yet.'),
					get_query: () => ({ query: 'alpinos.purchase.invoice_list_api.eligible_direct_po_query' }),
				},
			],
			primary_action_label: __('Create'),
			primary_action: (values) => {
				const source_type = values.source_type;
				const source = source_type === 'po' ? values.purchase_order : values.grn;
				if (!source) {
					frappe.msgprint(
						source_type === 'po' ? __('Please choose a Purchase Order.') : __('Please choose a GRN.')
					);
					return;
				}
				frappe.call({
					method: 'alpinos.purchase.invoice_list_api.create_invoice',
					args: { source_type: source_type, source: source },
					freeze: true,
					freeze_message: __('Creating the Purchase Invoice...'),
					callback: (r) => {
						if (r.exc || !r.message) return;
						dialog.hide();
						frappe.set_route('purchase_invoice_entry', r.message.name);
					},
				});
			},
		});
		dialog.show();
	}
};

// Select options arrive either as a newline string or as [{value, label}] objects.
function pinv_option_values(field) {
	const opts = (field && field.df && field.df.options) || '';
	if (Array.isArray(opts)) {
		return opts.map((o) => (o && typeof o === 'object' ? String(o.value) : String(o)));
	}
	return String(opts).split('\n');
}
