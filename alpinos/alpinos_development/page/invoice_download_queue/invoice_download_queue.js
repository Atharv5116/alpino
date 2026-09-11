/**
 * Invoice Download Queue.
 *
 * THE DOWNLOAD LOGIC IN THIS FILE IS UNCHANGED. `_download`, `download_bundle`,
 * `download_selected`, `download_all`, the per-row SO / PL / INV links and the
 * Club Download buttons behave exactly as they did; everything new is built around
 * them. The Download column is pinned first and is neither sortable nor movable,
 * because it is an action rather than data.
 *
 * Rows, columns, filters, sorting and export all come from
 * alpinos.invoice_queue_api, which enforces the channel rules on the DATA. Nothing
 * here decides who may see what: the page only draws what the server returns, so a
 * saved view or a hand-edited URL cannot widen access.
 */

// var, not const: desk pages are re-evaluated on navigation and a re-declared const
// blanks the page.
var IDQ_ROUTE = 'invoice-download-queue';
var IDQ_PAGE_LENGTH = 50;

frappe.pages['invoice-download-queue'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Invoice Download Queue'),
		single_column: true,
	});
	page.main.html(frappe.render_template('invoice_download_queue'));
	wrapper.idq = new InvoiceDownloadQueue(page);
};

frappe.pages['invoice-download-queue'].on_page_show = function (wrapper) {
	if (wrapper.idq) wrapper.idq.load_list();
};

var InvoiceDownloadQueue = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this._filters = {};
		this._catalogue = {};
		this._columns = [];
		this._rows = [];
		this._sort_field = 'order_date';
		this._sort_dir = 'desc';
		this._start = 0;
		this._total = 0;
		this._access = { locked: false, selectable: [] };

		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.page.add_inner_button(__('Columns'), () => this.open_column_picker());
		this.page.add_inner_button(__('Export'), () => this.export_view());
		this.page.add_inner_button(__('Save View'), () => this.save_view(), __('Views'));
		this.page.add_inner_button(__('Manage Views'), () => this.open_view_manager(), __('Views'));

		// ---- unchanged download entry points ----
		this.btn_dl_selected = this.page.add_inner_button(__('Download Selected'), () => this.download_selected());
		this.page.add_inner_button(__('Download All'), () => this.download_all());
		this.page.add_inner_button(__('SO + Invoice'), () => this.download_bundle('so,invoice'), __('Club Download'));
		this.page.add_inner_button(__('SO + PL + Invoice'), () => this.download_bundle('so,pl,invoice'), __('Club Download'));

		this.bind_events();
		this.bootstrap();
	}

	// ------------------------------------------------------------ bootstrap

	bootstrap() {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.get_columns',
			callback(r) {
				if (!r.message) return;
				(r.message.available || []).forEach((c) => { me._catalogue[c.key] = c; });
				me._columns = r.message.default.slice();
				frappe.call({
					method: 'alpinos.invoice_queue_api.get_access',
					callback(a) {
						if (!a.message) return;
						me._access = a.message;
						me.setup_filters();
						me.apply_default_view();
					},
				});
			},
		});
	}

	apply_default_view() {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.list_views',
			callback(r) {
				me._views = r.message || [];
				const def = me._views.find((v) => cint(v.is_default));
				if (def) me._apply_view(def);
				else me.load_list();
			},
		});
	}

	// -------------------------------------------------------------- filters

	setup_filters() {
		const w = this.wrapper;
		const mk = (sel, df) => {
			const c = frappe.ui.form.make_control({
				df: Object.assign({ fieldtype: 'Data' }, df),
				parent: w.find(sel), render_input: true,
			});
			c.refresh();
			this._filters[df.fieldname] = c;
			return c;
		};

		// Channel first: the role decides whether it is the user to change.
		const chan = mk('.fld-channel', {
			fieldtype: 'Select', fieldname: 'channel', label: __('Channel'),
			options: [''].concat(this._access.selectable || []).join('\n'),
		});
		if (this._access.default_channel) chan.set_value(this._access.default_channel);
		if (this._access.locked) {
			chan.df.read_only = 1;
			chan.refresh();
			chan.$wrapper.attr(
				'title',
				__('Your role fixes this page to the {0} channel.', [this._access.default_channel])
			);
		} else {
			// Changing the channel narrows the customer list, and a customer from the
			// old channel must not silently survive the change.
			chan.$input && chan.$input.on('change', () => this.on_channel_change());
		}

		mk('.fld-order-date-from', { fieldtype: 'Date', fieldname: 'order_date_from', label: __('Order Date From') });
		mk('.fld-order-date-to', { fieldtype: 'Date', fieldname: 'order_date_to', label: __('Order Date To') });
		mk('.fld-dispatch-date-from', { fieldtype: 'Date', fieldname: 'dispatch_date_from', label: __('Dispatch From') });
		mk('.fld-dispatch-date-to', { fieldtype: 'Date', fieldname: 'dispatch_date_to', label: __('Dispatch To') });
		mk('.fld-customer-type', { fieldtype: 'Select', fieldname: 'customer_type', label: __('Customer Type'), options: '' });
		mk('.fld-sales-order', { fieldtype: 'Data', fieldname: 'sales_order', label: __('Sales Order ID') });
		mk('.fld-customer-po-no', { fieldtype: 'Data', fieldname: 'customer_po_no', label: __('Customer PO No.') });
		mk('.fld-invoice-id', { fieldtype: 'Data', fieldname: 'invoice_id', label: __('Invoice Number') });
		mk('.fld-lr-number', { fieldtype: 'Data', fieldname: 'lr_number', label: __('LR No.') });
		mk('.fld-state', { fieldtype: 'Select', fieldname: 'state', label: __('State'), options: '' });

		// Customer is a Link whose query is narrowed to the channel, server-side.
		const me = this;
		const cust = mk('.fld-customer', {
			fieldtype: 'Link', fieldname: 'customer', label: __('Customer'), options: 'Customer',
			get_query() {
				return {
					query: 'alpinos.invoice_queue_api.customer_link_query',
					filters: { channel: me._filters.channel ? me._filters.channel.get_value() : '' },
				};
			},
		});
		this._customer_ctl = cust;

		this.refresh_filter_options();
	}

	refresh_filter_options() {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.get_filter_options',
			args: { channel: this._filters.channel ? this._filters.channel.get_value() : '' },
			callback(r) {
				if (!r.message) return;
				const set = (key, values) => {
					const c = me._filters[key];
					if (!c) return;
					const keep = c.get_value();
					c.df.options = [''].concat(values).join('\n');
					c.refresh();
					if (keep && values.indexOf(keep) !== -1) c.set_value(keep);
				};
				set('customer_type', r.message.customer_types || []);
				set('state', r.message.states || []);
			},
		});
	}

	on_channel_change() {
		const me = this;
		const chosen = this._customer_ctl && this._customer_ctl.get_value();
		this.refresh_filter_options();
		if (!chosen) { this.load_list(); return; }
		// A customer that does not belong to the newly chosen channel is cleared
		// rather than left filtering the list down to nothing.
		frappe.call({
			method: 'alpinos.invoice_queue_api.customer_in_channel',
			args: { customer: chosen, channel: this._filters.channel.get_value() },
			callback(r) {
				if (r.message === false) {
					me._customer_ctl.set_value('');
					frappe.show_alert({
						message: __('Customer cleared: not in the selected Channel'),
						indicator: 'orange',
					});
				}
				me.load_list();
			},
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

	// ----------------------------------------------------------------- load

	load_list() {
		const me = this;
		if (!this._columns.length) return;
		frappe.call({
			method: 'alpinos.invoice_queue_api.get_rows',
			args: {
				filters: this._args(),
				columns: this._columns,
				sort_field: this._sort_field,
				sort_dir: this._sort_dir,
				start: this._start,
				page_length: IDQ_PAGE_LENGTH,
			},
			freeze: true,
			freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc || !r.message) return;
				me._rows = r.message.rows || [];
				me._total = cint(r.message.total);
				me.render_header();
				me.render_rows(me._rows);
				me.update_selection();
				me.render_pager();
			},
		});
	}

	render_pager() {
		const to = Math.min(this._start + IDQ_PAGE_LENGTH, this._total);
		this.wrapper.find('.idq-range').text(
			this._total ? __('Showing {0} to {1} of {2}', [this._start + 1, to, this._total]) : ''
		);
	}

	// -------------------------------------------------------------- columns

	render_header() {
		const tr = this.wrapper.find('.idq-table thead tr').empty();
		tr.append('<th class="idq-check-col"><input type="checkbox" class="idq-select-all"></th>');
		// Download is pinned first and carries no sort: there is nothing in it to order by.
		tr.append(`<th class="idq-dl-col">${__('Download')}</th>`);
		this._columns.forEach((key) => {
			const meta = this._catalogue[key] || { label: key, sortable: true };
			const sorted = this._sort_field === key;
			const arrow = sorted ? (this._sort_dir === 'asc' ? '&#9650;' : '&#9660;') : '&#9660;';
			const cls = [
				meta.sortable === false ? '' : 'idq-sortable',
				sorted ? 'idq-sorted' : '',
			].join(' ');
			tr.append(
				`<th class="${cls}" data-key="${frappe.utils.escape_html(key)}">${frappe.utils.escape_html(meta.label)}` +
				(meta.sortable === false ? '' : `<span class="idq-sort-arrow">${arrow}</span>`) +
				'</th>'
			);
		});
	}

	open_column_picker() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Columns'),
			size: 'large',
			fields: [{ fieldname: 'holder', fieldtype: 'HTML' }],
			primary_action_label: __('Apply'),
			primary_action() {
				const chosen = [];
				d.$wrapper.find('.idq-col-item:not(.idq-locked)').each(function () {
					if ($(this).find('input').prop('checked')) chosen.push($(this).data('key'));
				});
				d.hide();
				me._columns = chosen.length ? chosen : me._columns;
				me._start = 0;
				me.load_list();
			},
		});

		const $box = $('<div></div>');
		$box.append(
			`<p class="text-muted" style="font-size:12px;">${__(
				'Tick to show, drag to reorder. Download is an action, so it always stays first.'
			)}</p>`
		);
		$box.append(
			'<div class="idq-col-item idq-locked" data-key="download">' +
			'<span class="idq-col-handle">&#8942;&#8942;</span>' +
			`<span class="idq-col-label">${__('Download')}</span>` +
			`<span class="text-muted" style="font-size:11px;">${__('pinned')}</span></div>`
		);

		const $list = $('<div class="idq-col-list"></div>').appendTo($box);
		const ordered = this._columns.concat(
			Object.keys(this._catalogue).filter((k) => this._columns.indexOf(k) === -1)
		);
		ordered.forEach((key) => {
			const meta = this._catalogue[key];
			if (!meta) return;
			const on = this._columns.indexOf(key) !== -1 ? 'checked' : '';
			$list.append(
				`<div class="idq-col-item" draggable="true" data-key="${frappe.utils.escape_html(key)}">
					<span class="idq-col-handle">&#8942;&#8942;</span>
					<input type="checkbox" ${on}>
					<span class="idq-col-label">${frappe.utils.escape_html(meta.label)}</span>
				</div>`
			);
		});

		// Plain HTML5 drag and drop: no library, and the row order IS the column order.
		let dragged = null;
		$list.on('dragstart', '.idq-col-item', function (e) {
			dragged = this;
			e.originalEvent.dataTransfer.effectAllowed = 'move';
		});
		$list.on('dragover', '.idq-col-item', function (e) {
			e.preventDefault();
			if (!dragged || dragged === this) return;
			const rect = this.getBoundingClientRect();
			const after = (e.originalEvent.clientY - rect.top) > rect.height / 2;
			this.parentNode.insertBefore(dragged, after ? this.nextSibling : this);
		});
		$list.on('dragend', () => { dragged = null; });

		d.fields_dict.holder.$wrapper.append($box);
		d.show();
	}

	// -------------------------------------------------------------- rows

	render_rows(rows) {
		const tb = this.wrapper.find('.idq-table tbody').empty();
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length + 2}" class="idq-empty">${__(
					'No invoices match these filters.'
				)}</td></tr>`
			);
			return;
		}

		rows.forEach((d) => {
			const cells = this._columns.map((key) => {
				const meta = this._catalogue[key] || {};
				return `<td class="${meta.type === 'Currency' || meta.type === 'Float' ? 'idq-num' : ''}">${this.cell(key, d)}</td>`;
			}).join('');
			tb.append(
				`<tr><td class="idq-check-col"><input type="checkbox" class="idq-row-select" data-so="${esc(d.sales_order)}"></td>` +
				`<td class="idq-dl-col">${this.download_cell(d)}</td>${cells}</tr>`
			);
		});
	}

	cell(key, d) {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const meta = this._catalogue[key] || {};
		const v = d[key];

		// The Sales Order ID opens the Sales Order View screen. It is a normal link, so
		// the user lands there under their own permissions; if they may not open it,
		// that screen refuses them rather than this one pretending they can.
		if (key === 'sales_order') {
			return `<a href="/app/sales-order-entry-view/${encodeURIComponent(d.sales_order)}"><strong>${esc(d.sales_order)}</strong></a>`;
		}
		if (key === 'pick_list' && v) {
			return `<a href="/app/pick_list_entry/${encodeURIComponent(v)}">${esc(v)}</a>`;
		}
		if (v === null || v === undefined || v === '') return '<span class="text-muted">&mdash;</span>';
		if (meta.type === 'Date') return esc(frappe.datetime.str_to_user(String(v)));
		if (meta.type === 'Currency') return format_currency(v);
		if (meta.type === 'Float') return format_number(v, null, 2);
		if (key === 'pdf_ready' || key === 'downloaded') {
			return `<span class="indicator-pill ${v === 'Yes' ? 'green' : 'gray'}">${esc(v)}</span>`;
		}
		return esc(v);
	}

	// ===================== DOWNLOAD COLUMN - UNCHANGED =====================
	// Changes(HP) #30 "Individual Downloadable files + button": each document on its
	// own. PL is offered only when a pick list exists and Invoice only once the PDF is
	// fetched, so a button is never shown for a file that cannot be produced.
	download_cell(d) {
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const one = (part, text, on) => {
			if (!on) return `<span class="text-muted idq-dl-off">${text}</span>`;
			return `<a href="#" class="idq-dl" data-so="${esc(d.sales_order)}" data-parts="${part}">${text}</a>`;
		};
		return [
			one('so', __('SO'), true),
			one('pl', __('PL'), !!d.pick_list),
			one('invoice', __('INV'), d.pdf_ready === 'Yes'),
		].join('<span class="idq-dl-sep">&middot;</span>');
	}

	// ------------------------------------------------------------- events

	bind_events() {
		const w = this.wrapper;
		w.on('click', '.btn-idq-apply', () => { this._start = 0; this.load_list(); });
		w.on('click', '.btn-idq-clear', () => {
			Object.keys(this._filters).forEach((k) => {
				if (k === 'channel' && this._access.locked) return;
				this._filters[k] && this._filters[k].set_value('');
			});
			this._start = 0;
			this.load_list();
		});
		w.on('click', '.btn-idq-prev', () => {
			this._start = Math.max(this._start - IDQ_PAGE_LENGTH, 0);
			this.load_list();
		});
		w.on('click', '.btn-idq-next', () => {
			if (this._start + IDQ_PAGE_LENGTH < this._total) {
				this._start += IDQ_PAGE_LENGTH;
				this.load_list();
			}
		});
		// Clicking a header toggles the direction, or switches the sort to that column.
		w.on('click', '.idq-table th.idq-sortable', (e) => {
			const key = $(e.currentTarget).data('key');
			if (!key) return;
			if (this._sort_field === key) {
				this._sort_dir = this._sort_dir === 'asc' ? 'desc' : 'asc';
			} else {
				this._sort_field = key;
				this._sort_dir = 'desc';
			}
			this._start = 0;
			this.load_list();
		});

		// ---- unchanged selection + download wiring ----
		w.on('change', '.idq-select-all', (e) => {
			w.find('.idq-row-select').prop('checked', $(e.target).prop('checked'));
			this.update_selection();
		});
		w.on('change', '.idq-row-select', () => this.update_selection());
		w.on('click', '.idq-dl', (e) => {
			e.preventDefault();
			const $a = $(e.currentTarget);
			this._download([$a.data('so')], $a.data('parts'));
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
			n ? __('{0} selected of {1}', [n, all.length]) : __('{0} invoice(s)', [this._total])
		);
	}

	// ===================== DOWNLOAD LOGIC - UNCHANGED ======================

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
		if (names.length) { this._download(names, parts); return; }
		// "no selection" has always meant EVERYTHING in the current filter. The queue
		// is paged now, so that set has to be fetched rather than read off the screen,
		// or the button would quietly have become "download this page".
		this._all_filtered((all) => this._download(all, parts));
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
		this._all_filtered((all) => this._download(all));
	}

	/** Every Sales Order the current filters match, across all pages. */
	_all_filtered(then) {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.get_all_sales_orders',
			args: { filters: this._args() },
			freeze: true,
			freeze_message: __('Collecting orders...'),
			callback(r) {
				if (r.exc) return;
				then(r.message || []);
			},
		});
	}

	// ==================== END UNCHANGED DOWNLOAD LOGIC =====================

	// -------------------------------------------------------------- export

	export_view() {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.export_rows',
			args: {
				filters: this._args(),
				columns: this._columns,
				sort_field: this._sort_field,
				sort_dir: this._sort_dir,
			},
			freeze: true,
			freeze_message: __('Preparing the export...'),
			callback(r) {
				if (r.exc || !r.message) return;
				const data = [r.message.header].concat(r.message.rows);
				// The Download column is not in the payload at all: the server never
				// offers it as data, so it cannot reach a file.
				frappe.tools.downloadify(data, null, 'Invoice Download Queue');
				frappe.show_alert({
					message: __('Exported {0} row(s)', [r.message.total]),
					indicator: 'green',
				});
			},
		});
	}

	// --------------------------------------------------------- saved views

	save_view() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Save View'),
			fields: [
				{ fieldname: 'view_name', fieldtype: 'Data', label: __('View Name'), reqd: 1 },
				{
					fieldname: 'is_default', fieldtype: 'Check',
					label: __('Open this view by default'),
				},
				{
					fieldname: 'note', fieldtype: 'HTML',
					options: `<p class="text-muted" style="font-size:12px;">${__(
						'Saves the columns and their order, the filters, and the sort. Saved to your account, so it follows you to another browser.'
					)}</p>`,
				},
			],
			primary_action_label: __('Save'),
			primary_action(v) {
				frappe.call({
					method: 'alpinos.invoice_queue_api.save_view',
					args: {
						view_name: v.view_name,
						columns: me._columns,
						filters: me._args(),
						sort_field: me._sort_field,
						sort_dir: me._sort_dir,
						is_default: v.is_default ? 1 : 0,
					},
					callback(r) {
						if (r.exc) return;
						d.hide();
						frappe.show_alert({ message: __('View saved'), indicator: 'green' });
					},
				});
			},
		});
		d.show();
	}

	open_view_manager() {
		const me = this;
		frappe.call({
			method: 'alpinos.invoice_queue_api.list_views',
			callback(r) {
				const views = r.message || [];
				const d = new frappe.ui.Dialog({ title: __('Saved Views'), size: 'large',
					fields: [{ fieldname: 'holder', fieldtype: 'HTML' }] });
				const $box = $('<div></div>');
				if (!views.length) {
					$box.append(`<p class="text-muted">${__('No saved views yet.')}</p>`);
				}
				views.forEach((v) => {
					const $row = $(
						`<div class="idq-col-item">
							<span class="idq-col-label">${frappe.utils.escape_html(v.view_name)}${
								cint(v.is_default) ? ` <span class="text-muted">(${__('default')})</span>` : ''
							}</span>
							<button class="btn btn-xs btn-default idq-apply-view">${__('Apply')}</button>
							<button class="btn btn-xs btn-default idq-del-view">${__('Delete')}</button>
						</div>`
					);
					$row.find('.idq-apply-view').on('click', () => { d.hide(); me._apply_view(v); });
					$row.find('.idq-del-view').on('click', () => {
						frappe.confirm(__('Delete the view {0}?', [v.view_name]), () => {
							frappe.call({
								method: 'alpinos.invoice_queue_api.delete_view',
								args: { name: v.name },
								callback(res) {
									if (res.exc) return;
									d.hide();
									frappe.show_alert({ message: __('View deleted'), indicator: 'orange' });
								},
							});
						});
					});
					$box.append($row);
				});
				d.fields_dict.holder.$wrapper.append($box);
				d.show();
			},
		});
	}

	_apply_view(v) {
		if (Array.isArray(v.columns) && v.columns.length) this._columns = v.columns.slice();
		if (v.sort_field) this._sort_field = v.sort_field;
		if (v.sort_dir) this._sort_dir = v.sort_dir;
		const f = v.filters || {};
		Object.keys(this._filters).forEach((k) => {
			// A locked Channel is the role talking, not the view: a saved view must not
			// be able to put a user onto a channel they may not see. The server would
			// refuse it anyway; this stops the pointless round trip.
			if (k === 'channel' && this._access.locked) return;
			this._filters[k] && this._filters[k].set_value(f[k] || '');
		});
		this._start = 0;
		this.load_list();
	}
};
