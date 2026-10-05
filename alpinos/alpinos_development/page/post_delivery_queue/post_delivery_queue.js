frappe.pages['post-delivery-queue'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Post Dispatch'),
		single_column: true,
	});
	page.main.html(frappe.render_template('post_delivery_queue'));
	new PostDeliveryQueue(page);
};

var PDQ_ROUTE = 'post-delivery-queue';
var PDQ_PAGE_LENGTHS = [20, 50, 100];

var PDQ_STATUS_OPTIONS = '\nNot Started\nIn Progress\nCompleted';

// Every filter on the page, in one list: the controls, the saved view and the server args
// all read it (Changes(HP) #48).
var PDQ_FILTER_KEYS = [
	'search',
	'sales_order',
	'customer_po',
	'invoice_no',
	'dispatch_from',
	'dispatch_to',
	'customer',
	'channel',
	'status',
	'lr_no',
];

var PDQ_STATUS_COLORS = {
	'Not Started': 'gray',
	'In Progress': 'orange',
	Completed: 'green',
};
var PDQ_ASN_COLORS = { Pending: 'gray', Uploaded: 'blue', Accepted: 'green', Rejected: 'red' };
var PDQ_GRN_COLORS = { Pending: 'gray', Partial: 'orange', Completed: 'green', Rejected: 'red' };

var PDQ_COLUMNS = [
	{ label: 'Delivery Note', render: (d, h) => `<strong>${h.esc(d.delivery_note)}</strong>` },
	{ label: 'Sales Order', render: (d, h) => h.esc(d.sales_order) },
	{ label: "Customer's Purchase No.", render: (d, h) => h.esc(d.customer_po_no || '—') },
	{ label: 'Invoice', render: (d, h) => d.invoice_no ? (h.esc(d.invoice_no) + (d.invoice_pdf ? ` &nbsp;<a href="${h.esc(d.invoice_pdf)}" target="_blank" rel="noopener">PDF</a>` : '')) : '—' },
	{ label: 'Customer', render: (d, h) => h.esc(d.customer_name || d.customer) },
	{ label: 'Channel', render: (d, h) => h.esc(d.channel || '—') },
	{ label: 'Dispatch Date', render: (d, h) => h.date(d.dispatch_date) },
	{ label: 'Transporter', render: (d, h) => h.esc(d.transporter || '—') },
	// Changes(HP) #61: the number a transporter query starts from.
	{ label: 'LR No.', render: (d, h) => h.esc(d.lr_awb_no || '—') },
	{ label: 'ASN', render: (d, h) => h.pill(d.asn_status, PDQ_ASN_COLORS) },
	{ label: 'GRN', render: (d, h) => (cint(d.grn_available) ? h.pill(d.grn_status, PDQ_GRN_COLORS) : '—') },
	{ label: 'Status', render: (d, h) => h.pill(d.post_delivery_status, PDQ_STATUS_COLORS) },
	{ label: 'Action', cls: 'text-center', render: (d, h) => h.action(d) },
];

var PostDeliveryQueue = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._last_meta = { has_more: 0 };
		this._filters = {};
		this._columns = PDQ_COLUMNS;
		this.render_header();
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.setup_filters();
		this.bind_events();
		this._restore_view_prefs();
		this.load_list();
	}

	setup_filters() {
		const w = this.wrapper;
		this._filters.search = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'search', label: __('Search (DN, SO, customer)') },
			parent: w.find('.fld-search'), render_input: true,
		});
		this._filters.status = frappe.ui.form.make_control({
			df: { fieldtype: 'Select', fieldname: 'status', label: __('Status'), options: PDQ_STATUS_OPTIONS },
			parent: w.find('.fld-status'), render_input: true,
		});
		this._filters.customer = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', fieldname: 'customer', label: __('Customer'), options: 'Customer' },
			parent: w.find('.fld-customer'), render_input: true,
		});
		this._filters.sales_order = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'sales_order', label: __('Sales Order') },
			parent: w.find('.fld-sales-order'), render_input: true,
		});
		this._filters.customer_po = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'customer_po', label: __("Customer's Purchase No.") },
			parent: w.find('.fld-customer-po'), render_input: true,
		});
		this._filters.invoice_no = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'invoice_no', label: __('Invoice No.') },
			parent: w.find('.fld-invoice-no'), render_input: true,
		});
		this._filters.dispatch_from = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'dispatch_from', label: __('Dispatch Date - From') },
			parent: w.find('.fld-dispatch-from'), render_input: true,
		});
		this._filters.dispatch_to = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'dispatch_to', label: __('Dispatch Date - To') },
			parent: w.find('.fld-dispatch-to'), render_input: true,
		});
		this._filters.channel = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', fieldname: 'channel', label: __('Channel'), options: 'Channel' },
			parent: w.find('.fld-channel'), render_input: true,
		});
		this._filters.lr_no = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'lr_no', label: __('LR No.') },
			parent: w.find('.fld-lr-no'), render_input: true,
		});
	}

	bind_events() {
		const w = this.wrapper;
		w.find('.btn-pdq-apply').on('click', () => { this.start = 0; this._save_view_prefs(); this.load_list(); });
		w.find('.btn-pdq-clear').on('click', () => {
			Object.values(this._filters).forEach((f) => f && f.set_value(''));
			this.start = 0; this._save_view_prefs(); this.load_list();
		});
		w.find('.pdq-page-size').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = PDQ_PAGE_LENGTHS.includes(v) ? v : 20;
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		w.find('.btn-pdq-prev').on('click', () => { this.start = Math.max(0, this.start - this.page_length); this.load_list(); });
		w.find('.btn-pdq-next').on('click', () => { if (this._last_meta.has_more) { this.start += this.page_length; this.load_list(); } });
		w.on('click', '.pdq-start-btn', (e) => {
			const dn = $(e.currentTarget).data('dn');
			this.start_post_delivery(dn);
		});
		w.on('click', '.pdq-open-btn', (e) => {
			const pd = $(e.currentTarget).data('pd');
			frappe.set_route('Form', 'Post Dispatch', pd);
		});
	}

	start_post_delivery(delivery_note) {
		frappe.call({
			method: 'alpinos.post_delivery_api.start_post_delivery',
			args: { delivery_note },
			freeze: true, freeze_message: __('Starting Post Dispatch...'),
			callback: (r) => {
				if (r.message && r.message.name) {
					frappe.set_route('Form', 'Post Dispatch', r.message.name);
				}
			},
		});
	}

	_args() {
		const f = this._filters;
		var args = { start: this.start, page_length: this.page_length };
		PDQ_FILTER_KEYS.forEach(function (k) {
			args[k] = (f[k] && f[k].get_value()) || '';
		});
		return args;
	}

	_save_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		const f = this._filters;
		var saved = { page_length: this.page_length };
		PDQ_FILTER_KEYS.forEach(function (k) {
			saved[k] = (f[k] && f[k].get_value()) || '';
		});
		alpinos.list_prefs.save(PDQ_ROUTE, saved);
	}

	_restore_view_prefs() {
		if (!window.alpinos || !alpinos.list_prefs) return;
		const saved = alpinos.list_prefs.load(PDQ_ROUTE);
		if (!saved || typeof saved !== 'object') return;
		const f = this._filters;
		// set_input applies synchronously so the first load_list() sees it; set_value is promise-based
		const set_sync = (c, v) => {
			if (!c) return;
			if (typeof c.set_input === 'function') c.set_input(v);
			else c.set_value(v);
		};
		// unknown/renamed keys are ignored, bad values dropped
		PDQ_FILTER_KEYS.forEach(function (k) {
			var v = saved[k];
			if (typeof v !== 'string' || !v || !f[k]) return;
			// A status outside the list is dropped rather than sent to the server.
			if (k === 'status' && !PDQ_STATUS_OPTIONS.split('\n').includes(v)) return;
			set_sync(f[k], v);
		});
		const pl = cint(saved.page_length);
		if (PDQ_PAGE_LENGTHS.includes(pl)) {
			this.page_length = pl;
			this.wrapper.find('.pdq-page-size').val(String(pl));
		}
		// never restore pagination offset — always begin at page 1
		this.start = 0;
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.post_delivery_api.get_post_delivery_queue',
			args: me._args(),
			freeze: true, freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc) return;
				const msg = r.message || {};
				me._last_meta = { has_more: cint(msg.has_more), start: cint(msg.start), page_length: cint(msg.page_length) };
				me.render_rows(msg.data || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		const tr = this.wrapper.find('.pdq-table thead tr').empty();
		this._columns.forEach((c) => tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`));
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.pdq-table tbody').empty();
		if (!rows.length) {
			tb.append(`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__('Nothing pending post-delivery')}</td></tr>`);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			date: (v) => (v && frappe.datetime.str_to_user(String(v))) || '—',
			pill: (v, colors) => {
				const val = v || 'Pending';
				const c = (colors && colors[val]) || 'gray';
				return `<span class="indicator-pill ${c}">${esc(val)}</span>`;
			},
			action: (d) => {
				if (d.post_delivery) {
					return `<button type="button" class="btn btn-xs btn-default pdq-open-btn" data-pd="${esc(d.post_delivery)}">${__('Open')}</button>`;
				}
				return `<button type="button" class="btn btn-xs btn-primary pdq-start-btn" data-dn="${esc(d.delivery_note)}">${__('Start Post Dispatch')}</button>`;
			},
		};
		rows.forEach((d) => {
			const cells = this._columns.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`).join('');
			tb.append(`<tr>${cells}</tr>`);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.pdq-table tbody tr').length;
		const has_rows = n && !this.wrapper.find('.pdq-table tbody .text-muted').length;
		if (!has_rows) {
			this.wrapper.find('.pdq-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.pdq-count').text(__('Showing {0}–{1}', [from, to]));
		}
		this.wrapper.find('.btn-pdq-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pdq-next').prop('disabled', !this._last_meta.has_more);
	}
}
