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
	// A row no longer leaves the queue when downloaded, so say so on the row instead.
	{ label: 'Downloaded', render: (d, h) => (d.downloaded === 'Yes' ? h.pill('Yes', 'blue') : h.pill('No', 'gray')) },
	{ label: 'Order Date', render: (d, h) => h.date(d.order_date) },
	{ label: 'PO Date', render: (d, h) => h.date(d.po_date) },
	{ label: 'Dispatch Date', render: (d, h) => h.date(d.dispatch_date) },
	{ label: 'Pick List', render: (d, h) => (d.pick_list ? h.link('Pick List', d.pick_list, h.esc(d.pick_list)) : '—') },
	{ label: 'LR Number', render: (d, h) => h.esc(d.lr_number || '—') },
	{ label: 'Customer PO No', render: (d, h) => h.esc(d.customer_po_no || '—') },
	{ label: 'Customer', render: (d, h) => h.esc(d.customer_name || '—') },
	// Changes(HP) #30 "Individual Downloadable files + button": each document on its own.
	// PL is offered only when a pick list exists and Invoice only once the PDF is fetched,
	// so a button is never shown for a file that cannot be produced.
	{
		label: 'Download',
		cls: 'text-center idq-dl-col',
		render: (d, h) => {
			const one = (part, text, on) => {
                                if (!on) return `<span class="text-muted idq-dl-off">${text}</span>`;
				return `<a href="#" class="idq-dl" data-so="${h.esc(d.sales_order)}" data-parts="${part}">${text}</a>`;
			};
			return [
				one('so', __('SO'), true),
				one('pl', __('PL'), !!d.pick_list),
				one('invoice', __('INV'), d.pdf_ready === 'Yes'),
			].join('<span class="idq-dl-sep">·</span>');
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
		// Changes(HP) #30 "club downloadable file + button", both combinations, each
		// named by the naming rule (Sales Order ID + Invoice ID, else Pick List ID).
		this.page.add_inner_button(__('SO + Invoice'), () => this.download_bundle('so,invoice'), __('Club Download'));
		this.page.add_inner_button(__('SO + PL + Invoice'), () => this.download_bundle('so,pl,invoice'), __('Club Download'));
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
		// Per-row individual downloads (delegated so they survive a re-render).
		w.on('click', '.idq-dl', (e) => {
			e.preventDefault();
			const $a = $(e.currentTarget);
			this._download([$a.data('so')], $a.data('parts'));
		});
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
			tb.append(`<tr><td colspan="${this._columns.length + 1}" class="text-muted text-center">${__('No invoices to show')}</td></tr>`);
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
			// Not "pending": a downloaded row stays in the list now (Changes(HP) #30 MAIN
			// NOTE), so the count describes what is listed, not what is outstanding.
			n ? __('{0} selected of {1}', [n, all.length]) : __('{0} invoice(s)', [all.length])
		);
	}

	_download(names, parts) {
		if (!names.length) {
			frappe.msgprint(__('No invoices to download.'));
			return;
		}
		const url = parts
			? '/api/method/alpinos.sales_order_api.download_order_bundle?parts=' +
				encodeURIComponent(parts) +
				'&names=' +
				encodeURIComponent(JSON.stringify(names))
			: '/api/method/alpinos.sales_order_api.download_sales_invoices_zip?names=' +
				encodeURIComponent(JSON.stringify(names));
		const win = window.open(frappe.urllib.get_full_url(url), '_blank');
		if (!win) {
			frappe.msgprint(__('Please allow pop-ups to download the invoices.'));
			return;
		}
		// A downloaded row STAYS in the list (Changes(HP) #30 MAIN NOTE); the refresh is
		// only so the Downloaded column catches up.
		setTimeout(() => this.load_list(), 2500);
	}

	download_bundle(parts) {
		const names = this._selected();
		this._download(names.length ? names : (this._rows || []).map((d) => d.sales_order).filter(Boolean), parts);
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
