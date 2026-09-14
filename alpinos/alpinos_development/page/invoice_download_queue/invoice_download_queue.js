/**
 * Invoice Download Queue.
 *
 * THE FILES A DOWNLOAD PRODUCES ARE UNCHANGED. The per-row SO / PL / INV links and the
 * Club Downloads still call alpinos.sales_order_api.download_order_bundle, and Download
 * Selected / Download All still produce alpinos.sales_order_api's invoice ZIP. The only
 * difference is that both now pass a channel check first, so a hand-edited download
 * URL cannot fetch an order from a channel the user may not see.
 *
 * Rows, columns, filters, sorting and export all come from
 * alpinos.invoice_queue_api, which enforces the channel rules on the DATA. Nothing
 * here decides who may see what: the page only draws what the server returns, so a
 * saved view or a hand-edited URL cannot widen access.
 *
 * Filter controls update their input a tick AFTER set_value() is called, and the list
 * reads the inputs. Every path that sets filters and then reloads therefore waits for
 * the set to finish, or the list loads with the previous values.
 */

// var, not const: desk pages are re-evaluated on navigation and a re-declared const
// blanks the page.
var IDQ_ROUTE = 'invoice-download-queue';
var IDQ_PAGE_LENGTH = 50;
// Same user-settings key the page used before the rewrite, so a user last-used filters
// carry over.
var IDQ_SETTINGS_KEY = 'invoice_download_queue';
var IDQ_GROUP_ORDER = ['Report', 'Sales Order', 'Pick List', 'Delivery Note', 'Post Dispatch'];

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
	if (wrapper.idq && wrapper.idq._ready) wrapper.idq.load_list();
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
		this._settings = {};
		// Ticked orders, by name. Kept across pages and sorts, because the queue is paged
		// and a selection used to span every row; cleared when the filters change.
		this._picked = new Set();
		this._load_seq = 0;
		this._ready = false;

		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.page.add_inner_button(__('Columns'), () => this.open_column_picker());
		this.page.add_inner_button(__('Export'), () => this.export_view());
		this.page.add_inner_button(__('Save View'), () => this.save_view(), __('Views'));
		this.page.add_inner_button(__('Manage Views'), () => this.open_view_manager(), __('Views'));

		// ---- download entry points ----
		this.btn_dl_selected = this.page.add_inner_button(__('Download Selected'), () => this.download_selected());
		this.page.add_inner_button(__('Download All'), () => this.download_all());
		this.page.add_inner_button(__('SO + Invoice'), () => this.download_bundle('so,invoice'), __('Club Download'));
		this.page.add_inner_button(__('SO + PL + Invoice'), () => this.download_bundle('so,pl,invoice'), __('Club Download'));

		this.bind_events();
		this.bootstrap();
	}

	// ------------------------------------------------------------ bootstrap

	async bootstrap() {
		try {
			const [cols, access, settings, views] = await Promise.all([
				frappe.call({ method: 'alpinos.invoice_queue_api.get_columns' }),
				frappe.call({ method: 'alpinos.invoice_queue_api.get_access' }),
				frappe.model.user_settings.get(IDQ_SETTINGS_KEY).catch(() => ({})),
				frappe.call({ method: 'alpinos.invoice_queue_api.list_views' }),
			]);
			if (!cols.message || !access.message) return;
			(cols.message.available || []).forEach((c) => { this._catalogue[c.key] = c; });
			this._default_columns = cols.message.default.slice();
			this._columns = this._default_columns.slice();
			this._access = access.message;
			this._settings = settings || {};
			frappe.model.user_settings[IDQ_SETTINGS_KEY] = this._settings;
			this._views = views.message || [];

			await this.setup_filters();

			// A default saved view wins; otherwise pick up where the user left off.
			const def = this._views.find((v) => cint(v.is_default));
			this._ready = true;
			if (def) {
				await this._apply_view(def);
			} else if (this._settings.last_state) {
				await this._apply_state(this._settings.last_state);
			} else if (this._settings.last_filters) {
				await this._apply_state({ filters: this._legacy_filters(this._settings.last_filters) });
			} else {
				this.load_list();
			}
		} catch (e) {
			console.error(e);
		}
	}

	/** Filters saved by the page before the rewrite used single dates. */
	_legacy_filters(old) {
		const f = Object.assign({}, old || {});
		if (f.order_date) { f.order_date_from = f.order_date; f.order_date_to = f.order_date; }
		if (f.dispatch_date) { f.dispatch_date_from = f.dispatch_date; f.dispatch_date_to = f.dispatch_date; }
		delete f.order_date;
		delete f.dispatch_date;
		return f;
	}

	// -------------------------------------------------------------- filters

	async setup_filters() {
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
			options: (this._access.locked ? [] : ['']).concat(this._access.selectable || []).join('\n'),
		});
		if (this._access.default_channel) await chan.set_value(this._access.default_channel);
		if (this._access.locked) {
			chan.df.read_only = 1;
			chan.refresh();
			chan.$wrapper.attr(
				'title',
				this._access.default_channel === 'Offline'
					? __('Your role fixes this page to the Offline channel, General Trade included.')
					: __('Your role fixes this page to the {0} channel.', [this._access.default_channel])
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
		mk('.fld-po-date', { fieldtype: 'Date', fieldname: 'po_date', label: __('PO Date') });
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
					filters: { channel: me._filters.channel ? me._filters.channel.get_value() || '' : '' },
				};
			},
		});
		this._customer_ctl = cust;

		await this.refresh_filter_options();
	}

	async refresh_filter_options() {
		const r = await frappe.call({
			method: 'alpinos.invoice_queue_api.get_filter_options',
			args: { channel: this._filters.channel ? this._filters.channel.get_value() || '' : '' },
		});
		if (!r || !r.message) return;
		const set = async (key, values) => {
			const c = this._filters[key];
			if (!c) return;
			const keep = c.get_value();
			c.df.options = [''].concat(values).join('\n');
			c.refresh();
			if (keep && values.indexOf(keep) !== -1) await c.set_value(keep);
		};
		await set('customer_type', r.message.customer_types || []);
		await set('state', r.message.states || []);
	}

	async on_channel_change() {
		const channel = this._filters.channel.get_value() || '';
		const chosen = this._customer_ctl && this._customer_ctl.get_value();
		this._picked.clear();
		this.refresh_filter_options();
		if (chosen) {
			// A customer that does not belong to the newly chosen channel is cleared
			// rather than left filtering the list down to nothing. Wait for the clear to
			// land before reloading, or the reload still sends the old customer.
			const r = await frappe.call({
				method: 'alpinos.invoice_queue_api.customer_in_channel',
				args: { customer: chosen, channel: channel },
			});
			if (r && r.message === false) {
				await this._customer_ctl.set_value('');
				frappe.show_alert({
					message: __('Customer cleared: not in the selected Channel'),
					indicator: 'orange',
				});
			}
		}
		this._start = 0;
		this.load_list();
	}

	_args() {
		const a = {};
		Object.keys(this._filters).forEach((k) => {
			const v = this._filters[k] && this._filters[k].get_value();
			if (v) a[k] = v;
		});
		return a;
	}

	/** Set every filter to `values` (blank where absent) and wait until they have landed. */
	_set_filters(values) {
		const f = values || {};
		return Promise.all(
			Object.keys(this._filters).map((k) => {
				// A locked Channel is the role talking, not a view or a remembered state.
				if (k === 'channel' && this._access.locked) return Promise.resolve();
				const c = this._filters[k];
				return c ? this._set_control(c, f[k] || '') : Promise.resolve();
			})
		);
	}

	/**
	 * set_value() resolves before a Customer box shows anything: a Link fetches the
	 * customer's title and only then writes the input, and the list reads the input.
	 * Waiting for the title too means the next load sends the customer.
	 */
	async _set_control(c, value) {
		await c.set_value(value);
		if (value && c.df.fieldtype === 'Link' && typeof c.set_link_title === 'function') {
			await c.set_link_title(value);
		}
	}

	// ----------------------------------------------------------------- load

	load_list() {
		const me = this;
		if (!this._columns.length) return;
		const seq = ++this._load_seq;
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
				// A slower earlier request must not overwrite a newer one.
				if (seq !== me._load_seq) return;
				if (r.exc || !r.message) return;
				me._rows = r.message.rows || [];
				me._total = cint(r.message.total);
				// The server may have dropped a column this user may not see.
				if (Array.isArray(r.message.columns) && r.message.columns.length) {
					me._columns = r.message.columns;
				}
				me.render_header();
				me.render_rows(me._rows);
				me.update_selection();
				me.render_pager();
				me._remember_state();
			},
		});
	}

	render_pager() {
		const to = Math.min(this._start + IDQ_PAGE_LENGTH, this._total);
		this.wrapper.find('.idq-range').text(
			this._total ? __('Showing {0} to {1} of {2}', [this._start + 1, to, this._total]) : ''
		);
		this.wrapper.find('.btn-idq-prev').prop('disabled', this._start <= 0);
		this.wrapper.find('.btn-idq-next').prop('disabled', this._start + IDQ_PAGE_LENGTH >= this._total);
	}

	/** Last-used filters, columns and sort, restored next time when no default view exists. */
	_remember_state() {
		const state = {
			filters: this._args(),
			columns: this._columns,
			sort_field: this._sort_field,
			sort_dir: this._sort_dir,
		};
		if (this._access.locked) delete state.filters.channel;
		if (JSON.stringify(this._settings.last_state || {}) === JSON.stringify(state)) return;
		// update(), not save(): save() MERGES object values, so a filter the user has
		// since cleared would survive in the stored state.
		this._settings = Object.assign({}, this._settings, { last_state: state });
		delete this._settings.last_filters;
		frappe.model.user_settings.update(IDQ_SETTINGS_KEY, this._settings);
	}

	async _apply_state(state) {
		const s = state || {};
		const cols = (s.columns || []).filter((k) => this._catalogue[k]);
		if (cols.length) this._columns = cols;
		if (s.sort_field && this._catalogue[s.sort_field]) this._sort_field = s.sort_field;
		if (s.sort_dir) this._sort_dir = s.sort_dir === 'asc' ? 'asc' : 'desc';
		await this._set_filters(s.filters || {});
		this._picked.clear();
		this._start = 0;
		this.load_list();
	}

	// -------------------------------------------------------------- columns

	render_header() {
		const tr = this.wrapper.find('.idq-table thead tr').empty();
		tr.append('<th class="idq-check-col"><input type="checkbox" class="idq-select-all" title="' +
			frappe.utils.escape_html(__('Select every invoice matching the filters')) + '"></th>');
		// Download is pinned first and carries no sort: there is nothing in it to order by.
		tr.append(`<th class="idq-dl-col">${__('Download')}</th>`);
		this._columns.forEach((key) => {
			const meta = this._catalogue[key] || { label: key, sortable: true };
			const sortable = meta.sortable !== false;
			const sorted = this._sort_field === key;
			const arrow = sorted ? (this._sort_dir === 'asc' ? '&uarr;' : '&darr;') : '&#8645;';
			const cls = [sortable ? 'idq-sortable' : '', sorted ? 'idq-sorted' : ''].join(' ');
			tr.append(
				`<th class="${cls}" data-key="${frappe.utils.escape_html(key)}"` +
				(sortable ? ` title="${frappe.utils.escape_html(__('Click to sort'))}"` : '') + '>' +
				frappe.utils.escape_html(meta.label) +
				(sortable ? `<span class="idq-sort-arrow">${arrow}</span>` : '') +
				'</th>'
			);
		});
	}

	open_column_picker() {
		const me = this;
		let shown = this._columns.slice();
		const d = new frappe.ui.Dialog({
			title: __('Columns'),
			size: 'extra-large',
			fields: [{ fieldname: 'holder', fieldtype: 'HTML' }],
			primary_action_label: __('Apply'),
			primary_action() {
				const chosen = [];
				d.$wrapper.find('.idq-shown-list .idq-col-item').each(function () {
					chosen.push($(this).data('key'));
				});
				if (!chosen.length) {
					frappe.msgprint(__('Keep at least one column.'));
					return;
				}
				d.hide();
				me._columns = chosen;
				me._start = 0;
				me.load_list();
			},
			secondary_action_label: __('Reset to default'),
			secondary_action() {
				shown = me._default_columns.slice();
				draw();
			},
		});

		const esc = frappe.utils.escape_html;
		const $box = $(`
			<div class="idq-picker">
				<div class="idq-picker-col">
					<div class="idq-picker-title">${__('Shown, in order')}</div>
					<p class="text-muted idq-picker-hint">${__('Drag to reorder. Download is an action, so it always stays first.')}</p>
					<div class="idq-col-item idq-locked"><span class="idq-col-handle">&#8942;&#8942;</span>
						<span class="idq-col-label">${__('Download')}</span>
						<span class="text-muted" style="font-size:11px;">${__('pinned')}</span></div>
					<div class="idq-shown-list"></div>
				</div>
				<div class="idq-picker-col">
					<div class="idq-picker-title">${__('Add a column')}</div>
					<p class="text-muted idq-picker-hint">${__(
						'Fields from the Sales Order, Pick List, Delivery Note and Post Dispatch. An order with several Pick Lists, Delivery Notes or Post Dispatch records shows amounts and quantities added up, the latest date, and each distinct text value.'
					)}</p>
					<input type="text" class="form-control input-sm idq-picker-search" placeholder="${esc(__('Search columns'))}">
					<div class="idq-available"></div>
				</div>
			</div>`);

		const draw = () => {
			const $shown = $box.find('.idq-shown-list').empty();
			shown.forEach((key) => {
				const meta = this._catalogue[key];
				if (!meta) return;
				$shown.append(
					`<div class="idq-col-item" draggable="true" data-key="${esc(key)}">
						<span class="idq-col-handle">&#8942;&#8942;</span>
						<span class="idq-col-label">${esc(meta.label)}</span>
						<a href="#" class="idq-col-remove" title="${esc(__('Remove'))}">&times;</a>
					</div>`
				);
			});
			drawAvailable();
		};

		const drawAvailable = () => {
			const term = ($box.find('.idq-picker-search').val() || '').toLowerCase().trim();
			const $avail = $box.find('.idq-available').empty();
			const groups = {};
			Object.keys(this._catalogue).forEach((key) => {
				if (shown.indexOf(key) !== -1) return;
				const meta = this._catalogue[key];
				if (term && meta.label.toLowerCase().indexOf(term) === -1) return;
				(groups[meta.group || 'Report'] = groups[meta.group || 'Report'] || []).push(key);
			});
			const order = IDQ_GROUP_ORDER.concat(Object.keys(groups).filter((g) => IDQ_GROUP_ORDER.indexOf(g) === -1));
			let any = false;
			order.forEach((g) => {
				const keys = groups[g];
				if (!keys || !keys.length) return;
				any = true;
				$avail.append(`<div class="idq-group-title">${esc(__(g))} <span class="text-muted">(${keys.length})</span></div>`);
				keys.forEach((key) => {
					$avail.append(
						`<div class="idq-add-item" data-key="${esc(key)}"><span class="idq-add-plus">+</span>${esc(this._catalogue[key].label)}</div>`
					);
				});
			});
			if (!any) $avail.append(`<p class="text-muted" style="font-size:12px;">${__('No matching columns.')}</p>`);
		};

		$box.on('input', '.idq-picker-search', drawAvailable);
		$box.on('click', '.idq-add-item', function () {
			shown.push($(this).data('key'));
			draw();
		});
		$box.on('click', '.idq-col-remove', function (e) {
			e.preventDefault();
			const key = $(this).closest('.idq-col-item').data('key');
			shown = shown.filter((k) => k !== key);
			draw();
		});

		// Plain HTML5 drag and drop: no library, and the row order IS the column order.
		let dragged = null;
		$box.on('dragstart', '.idq-shown-list .idq-col-item', function (e) {
			dragged = this;
			e.originalEvent.dataTransfer.effectAllowed = 'move';
		});
		$box.on('dragover', '.idq-shown-list .idq-col-item', function (e) {
			e.preventDefault();
			if (!dragged || dragged === this) return;
			const rect = this.getBoundingClientRect();
			const after = (e.originalEvent.clientY - rect.top) > rect.height / 2;
			this.parentNode.insertBefore(dragged, after ? this.nextSibling : this);
		});
		$box.on('dragend', () => {
			dragged = null;
			shown = [];
			$box.find('.idq-shown-list .idq-col-item').each(function () { shown.push($(this).data('key')); });
		});

		draw();
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
				const num = ['Currency', 'Float', 'Int'].indexOf(meta.type) !== -1;
				return `<td class="${num ? 'idq-num' : ''}">${this.cell(key, d)}</td>`;
			}).join('');
			const ticked = this._picked.has(d.sales_order) ? 'checked' : '';
			tb.append(
				`<tr><td class="idq-check-col"><input type="checkbox" class="idq-row-select" data-so="${esc(d.sales_order)}" ${ticked}></td>` +
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
		if (meta.type === 'Date' || meta.type === 'Datetime') return esc(frappe.datetime.str_to_user(String(v)));
		if (meta.type === 'Currency') return format_currency(v);
		if (meta.type === 'Float') return format_number(v, null, 2);
		if (meta.type === 'Int') return format_number(v, null, 0);
		if (key === 'pdf_ready' || key === 'downloaded') {
			return `<span class="indicator-pill ${v === 'Yes' ? 'green' : 'gray'}">${esc(v)}</span>`;
		}
		return esc(v);
	}

	// ============================ DOWNLOAD COLUMN ============================
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
		w.on('click', '.btn-idq-apply', () => {
			this._picked.clear();
			this._start = 0;
			this.load_list();
		});
		w.on('click', '.btn-idq-clear', async () => {
			await this._set_filters({});
			this._picked.clear();
			this._start = 0;
			this.refresh_filter_options();
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
				this._sort_dir = 'asc';
			}
			this._start = 0;
			this.load_list();
		});

		// ---- selection ----
		// The header box selects every invoice the filters match, on every page, which is
		// what it meant when every row was loaded at once.
		w.on('change', '.idq-select-all', (e) => {
			if (!$(e.target).prop('checked')) {
				this._picked.clear();
				w.find('.idq-row-select').prop('checked', false);
				this.update_selection();
				return;
			}
			this._all_filtered((all) => {
				this._picked = new Set(all);
				w.find('.idq-row-select').prop('checked', true);
				this.update_selection();
			});
		});
		w.on('change', '.idq-row-select', (e) => {
			const so = $(e.target).data('so');
			if ($(e.target).prop('checked')) this._picked.add(so);
			else this._picked.delete(so);
			this.update_selection();
		});
		w.on('click', '.btn-idq-clear-selection', (e) => {
			e.preventDefault();
			this._picked.clear();
			w.find('.idq-row-select').prop('checked', false);
			this.update_selection();
		});
		w.on('click', '.idq-dl', (e) => {
			e.preventDefault();
			const $a = $(e.currentTarget);
			this._download([$a.data('so')], $a.data('parts'));
		});
	}

	_selected() {
		return Array.from(this._picked);
	}

	update_selection() {
		const n = this._picked.size;
		this.wrapper.find('.idq-select-all').prop('checked', this._total > 0 && n >= this._total);
		this.wrapper.find('.idq-count').html(
			// Not "pending": a downloaded row stays in the list now (Changes(HP) #30 MAIN
			// NOTE), so the count describes what is listed, not what is outstanding.
			n
				? frappe.utils.escape_html(__('{0} selected of {1}', [n, this._total])) +
					` <a href="#" class="btn-idq-clear-selection">${__('Clear selection')}</a>`
				: frappe.utils.escape_html(__('{0} invoice(s)', [this._total]))
		);
	}

	// ============================== DOWNLOADS ===============================

	_download(names, parts) {
		if (!names.length) {
			frappe.msgprint(__('No invoices to download.'));
			return;
		}
		// Same two server functions as before; the ZIP now goes through the queue
		// door, which checks the channel before handing over to the shared function.
		const url = parts
			? '/api/method/alpinos.sales_order_api.download_order_bundle?parts=' +
				encodeURIComponent(parts) +
				'&names=' +
				encodeURIComponent(JSON.stringify(names))
			: '/api/method/alpinos.invoice_queue_api.download_invoices_zip?names=' +
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
		// is paged, so that set is fetched rather than read off the screen.
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

	// -------------------------------------------------------------- export

	export_view() {
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
					message: __('Exported {0} row(s)', [r.message.rows.length]),
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
		// A locked Channel is the role talking, not the view: _set_filters skips it, and
		// the server would refuse another channel anyway.
		return this._apply_state({
			columns: v.columns,
			filters: v.filters,
			sort_field: v.sort_field,
			sort_dir: v.sort_dir,
		});
	}
};
