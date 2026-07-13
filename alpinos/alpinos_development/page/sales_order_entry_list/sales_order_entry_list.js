frappe.pages['sales-order-entry-list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Alpino Sales Orders'),
		single_column: true,
	});
	page.main.html(frappe.render_template('sales_order_entry_list'));
	new SalesOrderEntryListPage(page);
};

const SO_STATUS_OPTIONS =
	'\nDraft\nOn Hold\nTo Deliver and Bill\nTo Bill\nTo Deliver\nCompleted\nCancelled\nClosed';

const SO_WORKFLOW_STATUS_OPTIONS =
	'\nDraft\nWarehouse Approval Pending\nFuture Dispatch\nToday\'s Dispatch\nWarehouse Approved' +
	'\nPicking In Progress\nSubmission Pending\nReady For Dispatch' +
	'\nDelivery Note Created\nDispatched\nCompleted\nCancelled';

const SO_WF_COLORS = {
	Draft: 'gray',
	'Warehouse Approval Pending': 'orange',
	'Future Dispatch': 'yellow',
	"Today's Dispatch": 'purple',
	'Warehouse Approved': 'blue',
	'Picking In Progress': 'blue',
	'Submission Pending': 'orange',
	'Ready For Dispatch': 'blue',
	'Delivery Note Created': 'blue',
	Dispatched: 'green',
	Completed: 'green',
	Cancelled: 'red',
};

// Role-based column layouts. Warehouse staff (without a sales role) get the
// warehouse layout; everyone else — sales roles, System Manager — gets sales.
// E-Com layout is specced but deferred (see project memory) — add here later.
const SO_LIST_LAYOUTS = {
	sales: [
		{ label: 'ID', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
		{ label: 'Customer Name', render: (d, h) => h.esc(d.customer_name) },
		{ label: 'Order Date', render: (d, h) => h.date(d.transaction_date) },
		{ label: 'PO No', render: (d, h) => h.esc(d.po_no || '—') },
		{ label: 'Workflow Status', render: (d, h) => h.wf(d) },
		{ label: 'Links', cls: 'text-center', render: (d, h) => h.links(d) },
		{ label: 'Created By', render: (d, h) => h.esc(d.owner_full_name || d.owner) },
		{ label: 'Grand Total', cls: 'text-right', render: (d, h) => h.money(d) },
	],
	warehouse: [
		{ label: 'Customer Type', render: (d, h) => h.esc(d.order_type || '—') },
		{ label: 'ID', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
		{ label: 'PO No', render: (d, h) => h.esc(d.po_no || '—') },
		{ label: 'Customer Name', render: (d, h) => h.esc(d.customer_name) },
		{ label: 'Dispatch Date', render: (d, h) => h.date(d.custom_dispatch_date) },
		{ label: 'PO Exp Date', render: (d, h) => h.date(d.custom_po_expiry_date) },
		{ label: 'Delivery Date', render: (d, h) => h.date(d.delivery_date) },
		{ label: 'Workflow Status', render: (d, h) => h.wf(d) },
		{ label: 'Links', cls: 'text-center', render: (d, h) => h.links(d) },
		{ label: 'Created By', render: (d, h) => h.esc(d.owner_full_name || d.owner) },
		{ label: 'Grand Total', cls: 'text-right', render: (d, h) => h.money(d) },
	],
};

function so_list_layout_for_user() {
	const roles = frappe.user_roles || [];
	const WAREHOUSE_ROLES = [
		'Warehouse Admin', 'Warehouse Manager', 'Warehouse User',
		'PL User', 'PL Manager', 'DN User', 'DN Manager',
	];
	const SALES_ROLES = ['Sales Admin', 'Sales Manager', 'Sales User'];
	const isWarehouse = WAREHOUSE_ROLES.some((r) => roles.includes(r));
	const isSales = SALES_ROLES.some((r) => roles.includes(r));
	return isWarehouse && !isSales ? 'warehouse' : 'sales';
}

class SalesOrderEntryListPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._last_meta = { has_more: 0 };
		this._filter_fields = {};
		this._columns = SO_LIST_LAYOUTS[so_list_layout_for_user()];
		this.render_header();
		this.setup_toolbar();
		this.setup_filters();
		this.bind_events();
		this.wrapper.find('.so-list-filters-title').text(__('Filters'));
		this.wrapper.find('.btn-so-list-apply').text(__('Apply'));
		this.wrapper.find('.btn-so-list-clear').text(__('Clear'));
		this.wrapper.find('.btn-so-list-prev').text(__('Previous'));
		this.wrapper.find('.btn-so-list-next').text(__('Next'));
		this.load_list();
	}

	setup_toolbar() {
		if (frappe.model.can_create('Sales Order')) {
			this.page.set_primary_action(
				__('New Sales Order'),
				() => frappe.set_route('sales-order-entry'),
				'fa fa-plus'
			);
		}
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.btn_download_pdf = this.page.add_inner_button(__('Download PDFs'), () =>
			this.download_selected_pdfs()
		);
		if (this.btn_download_pdf) this.btn_download_pdf.hide();
	}

	_selected_names() {
		const names = [];
		this.wrapper.find('.so-list-row-select:checked').each((i, el) => {
			names.push($(el).data('name'));
		});
		return names;
	}

	update_selection() {
		const all_boxes = this.wrapper.find('.so-list-row-select');
		const checked = this.wrapper.find('.so-list-row-select:checked');
		this.wrapper
			.find('.so-list-select-all')
			.prop('checked', all_boxes.length > 0 && checked.length === all_boxes.length);

		if (checked.length > 0) {
			if (this.btn_download_pdf) this.btn_download_pdf.show();
			if (this.page.set_indicator) {
				this.page.set_indicator(__('{0} selected', [checked.length]), 'orange');
			}
		} else {
			if (this.btn_download_pdf) this.btn_download_pdf.hide();
			if (this.page.clear_indicator) this.page.clear_indicator();
		}
	}

	download_selected_pdfs() {
		const names = this._selected_names();
		if (!names.length) {
			frappe.msgprint(__('Please select at least one Sales Order.'));
			return;
		}
		// One PDF per order, bundled into a single ZIP download.
		const url =
			'/api/method/alpinos.sales_order_api.download_sales_orders_zip?names=' +
			encodeURIComponent(JSON.stringify(names));
		const w = window.open(frappe.urllib.get_full_url(url), '_blank');
		if (!w) frappe.msgprint(__('Please allow pop-ups to download the PDFs.'));
	}

	setup_filters() {
		const w = this.wrapper;
		this._filter_fields.search = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Data',
				fieldname: 'search',
				label: __('Search (ID, customer)'),
			},
			parent: w.find('.fld-search'),
			render_input: true,
		});
		this._filter_fields.status = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Select',
				fieldname: 'status',
				label: __('Status'),
				options: SO_STATUS_OPTIONS,
			},
			parent: w.find('.fld-status'),
			render_input: true,
		});
		this._filter_fields.workflow_status = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Select',
				fieldname: 'workflow_status',
				label: __('Workflow Status'),
				options: SO_WORKFLOW_STATUS_OPTIONS,
			},
			parent: w.find('.fld-workflow-status'),
			render_input: true,
		});
		this._filter_fields.company = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Link',
				fieldname: 'company',
				label: __('Company'),
				options: 'Company',
			},
			parent: w.find('.fld-company'),
			render_input: true,
		});
		this._filter_fields.customer = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Link',
				fieldname: 'customer',
				label: __('Customer'),
				options: 'Customer',
			},
			parent: w.find('.fld-customer'),
			render_input: true,
		});
		this._filter_fields.from_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'from_date', label: __('From date') },
			parent: w.find('.fld-from-date'),
			render_input: true,
		});
		this._filter_fields.to_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'to_date', label: __('To date') },
			parent: w.find('.fld-to-date'),
			render_input: true,
		});
		this._filter_fields.additional_units_damage_filter = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Select',
				fieldname: 'additional_units_damage_filter',
				label: __('Add. units damage'),
				options: '\n\nYes\nNo',
			},
			parent: w.find('.fld-au-damage-filter'),
			render_input: true,
		});
	}

	bind_events() {
		this.wrapper.find('.btn-so-list-apply').on('click', () => {
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-so-list-clear').on('click', () => {
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-so-list-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-so-list-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});
		this.wrapper.on('click', '.so-list-row', (e) => {
			if ($(e.target).closest('a,button,input[type="checkbox"]').length) return;
			const name = $(e.currentTarget).data('name');
			if (!name) return;
			frappe.set_route('sales-order-entry-view', name);
		});
		this.wrapper.on('click', '.so-list-link-btn', (e) => {
			e.stopPropagation();
			const route = $(e.currentTarget).data('route');
			if (Array.isArray(route)) frappe.set_route(...route);
		});
		this.wrapper.on('change', '.so-list-select-all', (e) => {
			const checked = $(e.target).prop('checked');
			this.wrapper.find('.so-list-row-select').prop('checked', checked);
			this.update_selection();
		});
		this.wrapper.on('change', '.so-list-row-select', () => this.update_selection());
	}

	_args() {
		const f = this._filter_fields;
		const aug = f.additional_units_damage_filter.get_value();
		let additional_units_damage_filter = '';
		if (aug === 'Yes') additional_units_damage_filter = 'yes';
		else if (aug === 'No') additional_units_damage_filter = 'no';
		return {
			start: this.start,
			page_length: this.page_length,
			channel: 'Offline',
			search: f.search.get_value() || '',
			status: f.status.get_value() || '',
			workflow_status: f.workflow_status.get_value() || '',
			company: f.company.get_value() || '',
			customer: f.customer.get_value() || '',
			from_date: f.from_date.get_value() || '',
			to_date: f.to_date.get_value() || '',
			additional_units_damage_filter,
		};
	}

	load_list() {
		const me = this;
		me.wrapper.find('.so-list-select-all').prop('checked', false);
		if (me.btn_download_pdf) me.btn_download_pdf.hide();
		if (me.page.clear_indicator) me.page.clear_indicator();
		frappe.call({
			method: 'alpinos.sales_order_api.get_sales_order_entry_list',
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
				};
				me.render_rows(msg.data || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		const tr = this.wrapper.find('.so-list-table thead tr').empty();
		tr.append(
			'<th style="text-align: center;"><input type="checkbox" class="so-list-select-all"></th>'
		);
		this._columns.forEach((c) =>
			tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`)
		);
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.so-list-table tbody').empty();
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="${this._columns.length + 1}" class="text-muted text-center">${__('No Sales Orders found')}</td></tr>`
			);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			date: (v) => (v && frappe.datetime.str_to_user(String(v))) || '—',
			money: (d) => format_currency(d.grand_total || 0, d.currency),
			wf: (d) => {
				const wf = d.custom_workflow_status || '';
				const c = SO_WF_COLORS[wf] || 'gray';
				return wf ? `<span class="indicator-pill ${c}">${esc(wf)}</span>` : '—';
			},
			// Redirect buttons to the latest linked Pick List / Delivery Note /
			// Sales Invoice — shown only when the doc exists AND the user's role
			// can read that doctype.
			links: (d) => {
				const btns = [];
				const mk = (label, route, title) =>
					`<button type="button" class="btn btn-xs btn-default so-list-link-btn"
						data-route='${esc(JSON.stringify(route))}' title="${esc(title)}">${label}</button>`;
				if (d.pick_list && frappe.model.can_read('Pick List')) {
					btns.push(mk('PL', ['pick_list_entry', d.pick_list], d.pick_list));
				}
				if (d.delivery_note && frappe.model.can_read('Delivery Note')) {
					btns.push(mk('DN', ['delivery_note_entry', d.delivery_note], d.delivery_note));
				}
				if (d.sales_invoice && frappe.model.can_read('Sales Invoice')) {
					btns.push(mk('INV', ['Form', 'Sales Invoice', d.sales_invoice], d.sales_invoice));
				}
				return btns.join(' ') || '—';
			},
		};
		rows.forEach((d) => {
			const cells = this._columns
				.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`)
				.join('');
			tb.append(`<tr class="so-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">
				<td style="text-align: center;"><input type="checkbox" class="so-list-row-select" data-name="${esc(d.name)}"></td>
				${cells}
			</tr>`);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.so-list-table tbody tr.so-list-row').length;
		if (!n) {
			this.wrapper.find('.so-list-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.so-list-count').text(__('Showing {0}–{1}', [from, to]));
		}
		this.wrapper.find('.btn-so-list-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-so-list-next').prop('disabled', !this._last_meta.has_more);
	}
}
