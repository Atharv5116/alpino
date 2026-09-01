frappe.pages['invoice-download-queue'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Invoice Download Queue'),
		single_column: false,
	});
	page.main.html(frappe.render_template('invoice_download_queue'));
	new InvoiceDownloadQueue(page);
};

var IDQ_SETTINGS_KEY = 'invoice_download_queue';

var IDQ_COLUMNS = [
	{ label: 'Sales Order', render: (d, h) => h.link('Sales Order', d.sales_order, `<strong>${h.esc(d.sales_order)}</strong>`) },
	{ label: 'Invoice ID', render: (d, h) => h.esc(d.invoice_id || '—') },
	{ label: 'PDF Ready', render: (d, h) => (d.pdf_ready === 'Yes' ? h.pill('Yes', 'green') : h.pill('No', 'gray')) },
	{ label: 'Order Date', render: (d, h) => h.date(d.order_date) },
	{ label: 'PO Date', render: (d, h) => h.date(d.po_date) },
	{ label: 'Dispatch Date', render: (d, h) => h.date(d.dispatch_date) },
	{ label: 'Pick List', render: (d, h) => (d.pick_list ? h.link('Pick List', d.pick_list, h.esc(d.pick_list)) : '—') },
	{ label: 'LR Number', render: (d, h) => h.esc(d.lr_number || '—') },
	{ label: 'Customer PO No', render: (d, h) => h.esc(d.customer_po_no || '—') },
	{ label: 'Customer', render: (d, h) => h.esc(d.customer_name || '—') },
	{
		label: 'Download',
		cls: 'text-center',
		render: (d, h) => {
			if (d.pdf_ready !== 'Yes') return '<span class="text-muted">—</span>';
			const url = '/api/method/alpinos.sales_order_api.download_single_invoice?name=' + encodeURIComponent(d.sales_order);
			return `<a href="${h.esc(url)}" class="btn btn-xs btn-default">${__('Download')}</a>`;
		},
	},
];

var InvoiceDownloadQueue = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this._filters = {};
		this._columns = IDQ_COLUMNS;
		this._rows = [];
		this.render_header();
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.btn_dl_selected = this.page.add_inner_button(__('Download Selected'), () => this.download_selected());
		this.page.add_inner_button(__('Download All'), () => this.download_all());
		this.setup_filters();
		this.render_sidebar();
		this.bind_events();
		this.restore_last_filters();
		this.load_list();
	}

	setup_filters() {
		const w = this.wrapper;
		this._filters.sales_order = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'sales_order', label: __('Sales Order ID') },
			parent: w.find('.fld-sales-order'), render_input: true,
		});
		this._filters.order_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'order_date', label: __('Order Date') },
			parent: w.find('.fld-order-date'), render_input: true,
		});
		this._filters.po_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'po_date', label: __('PO Date') },
			parent: w.find('.fld-po-date'), render_input: true,
		});
		this._filters.dispatch_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'dispatch_date', label: __('Dispatch Date') },
			parent: w.find('.fld-dispatch-date'), render_input: true,
		});
		this._filters.customer = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', fieldname: 'customer', label: __('Customer'), options: 'Customer' },
			parent: w.find('.fld-customer'), render_input: true,
		});
	}

	// ----- saved filters -----
	_settings() {
		return frappe.get_user_settings(IDQ_SETTINGS_KEY) || {};
	}

	_saved_filters() {
		const s = this._settings();
		return Array.isArray(s.saved_filters) ? s.saved_filters : [];
	}

	_store(key, value) {
		const s = this._settings();
		s[key] = value;
		frappe.model.user_settings.save(IDQ_SETTINGS_KEY, key, value);
	}

	restore_last_filters() {
		const last = this._settings().last_filters;
		if (last) this._apply_values(last);
	}

	_apply_values(vals) {
		Object.keys(this._filters).forEach((k) => {
			const f = this._filters[k];
			if (f) f.set_value(vals && vals[k] ? vals[k] : '');
		});
	}

	save_current_filter() {
		const vals = this._args();
		if (!Object.keys(vals).length) {
			frappe.msgprint(__('Set at least one filter before saving.'));
			return;
		}
		frappe.prompt(
			[{ fieldname: 'title', fieldtype: 'Data', label: __('Filter Name'), reqd: 1 }],
			({ title }) => {
				const list = this._saved_filters().filter((f) => f.title !== title);
				list.push({ title: title, filters: vals });
				this._store('saved_filters', list);
				this.render_sidebar();
				frappe.show_alert({ message: __('Filter saved'), indicator: 'green' });
			},
			__('Save Filter'),
			__('Save')
		);
	}

	render_sidebar() {
		const sb = this.page.sidebar;
		if (!sb || !sb.length) return;
		sb.empty();
		const list = this._saved_filters();
		const $box = $('<div class="idq-sidebar"></div>').appendTo(sb);
		$box.append(`<div class="sidebar-label">${__('Saved Filters')}</div>`);
		if (!list.length) {
			$box.append(`<p class="text-muted small">${__('No saved filters yet.')}</p>`);
			return;
		}
		const $ul = $('<ul class="list-unstyled idq-saved-list"></ul>').appendTo($box);
		list.forEach((f, i) => {
			const title = frappe.utils.escape_html(f.title);
			$ul.append(
				`<li class="idq-saved-item" data-idx="${i}">
					<a href="#" class="idq-apply-saved">${title}</a>
					<a href="#" class="idq-remove-saved text-muted pull-right" title="${__('Remove')}">&times;</a>
				</li>`
			);
		});
	}

	_args() {
		const a = {};
		Object.keys(this._filters).forEach((k) => {
			const v = this._filters[k] && this._filters[k].get_value();
			if (v) a[k] = v;
		});
		return a;
	}

	bind_events() {
		const w = this.wrapper;
		w.find('.btn-idq-apply').on('click', () => this.load_list());
		w.find('.btn-idq-clear').on('click', () => {
			Object.values(this._filters).forEach((f) => f && f.set_value(''));
			this.load_list();
		});
		w.find('.btn-idq-save-filter').on('click', () => this.save_current_filter());
		// Saved filters live in the sidebar, which is outside this.wrapper.
		$(this.page.sidebar).on('click', '.idq-apply-saved', (e) => {
			e.preventDefault();
			const idx = $(e.target).closest('.idq-saved-item').data('idx');
			const entry = this._saved_filters()[idx];
			if (!entry) return;
			this._apply_values(entry.filters);
			this.load_list();
		});
		$(this.page.sidebar).on('click', '.idq-remove-saved', (e) => {
			e.preventDefault();
			const idx = $(e.target).closest('.idq-saved-item').data('idx');
			const list = this._saved_filters();
			list.splice(idx, 1);
			this._store('saved_filters', list);
			this.render_sidebar();
		});
		// Select-all + per-row selection (delegated so it survives re-renders).
		w.on('change', '.idq-select-all', (e) => {
			w.find('.idq-row-select').prop('checked', $(e.target).prop('checked'));
			this.update_selection();
		});
		w.on('change', '.idq-row-select', () => this.update_selection());
	}

	load_list() {
		const me = this;
		const args = me._args();
		me._store('last_filters', args);
		frappe.call({
			method: 'alpinos.pending_invoice_api.get_pending_invoice_downloads',
			args: args,
			freeze: true, freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc) return;
				me._rows = (r.message || {}).data || [];
				me.render_rows(me._rows);
				me.update_selection();
			},
		});
	}

	render_header() {
		const tr = this.wrapper.find('.idq-table thead tr').empty();
		tr.append('<th class="idq-check-col"><input type="checkbox" class="idq-select-all"></th>');
		this._columns.forEach((c) => tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`));
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.idq-table tbody').empty();
		if (!rows.length) {
			tb.append(`<tr><td colspan="${this._columns.length + 1}" class="text-muted text-center">${__('No pending invoice downloads')}</td></tr>`);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			date: (v) => (v && frappe.datetime.str_to_user(String(v))) || '—',
			pill: (v, c) => `<span class="indicator-pill ${c}">${esc(v)}</span>`,
			link: (doctype, name, label) =>
				`<a href="/app/${encodeURIComponent(frappe.router.slug(doctype))}/${encodeURIComponent(name)}">${label}</a>`,
		};
		rows.forEach((d) => {
			const cells = this._columns.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`).join('');
			tb.append(
				`<tr><td class="idq-check-col"><input type="checkbox" class="idq-row-select" data-so="${esc(d.sales_order)}"></td>${cells}</tr>`
			);
		});
	}

	_selected() {
		const names = [];
		this.wrapper.find('.idq-row-select:checked').each((i, el) => names.push($(el).data('so')));
		return names;
	}

	update_selection() {
		const all = this.wrapper.find('.idq-row-select');
		const checked = this.wrapper.find('.idq-row-select:checked');
		this.wrapper.find('.idq-select-all').prop('checked', all.length > 0 && checked.length === all.length);
		const n = checked.length;
		this.wrapper.find('.idq-count').text(
			n ? __('{0} selected of {1}', [n, all.length]) : __('{0} pending invoice(s)', [all.length])
		);
	}

	_download(names) {
		if (!names.length) {
			frappe.msgprint(__('No invoices to download.'));
			return;
		}
		const url =
			'/api/method/alpinos.sales_order_api.download_sales_invoices_zip?names=' +
			encodeURIComponent(JSON.stringify(names));
		const win = window.open(frappe.urllib.get_full_url(url), '_blank');
		if (!win) {
			frappe.msgprint(__('Please allow pop-ups to download the invoices.'));
			return;
		}
		// Downloading marks those orders — refresh so they drop off the queue.
		setTimeout(() => this.load_list(), 2500);
	}

	download_selected() {
		const names = this._selected();
		if (!names.length) {
			frappe.msgprint(__('Tick one or more rows first, or use Download All.'));
			return;
		}
		this._download(names);
	}

	download_all() {
		this._download((this._rows || []).map((d) => d.sales_order).filter(Boolean));
	}
};
