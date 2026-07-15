frappe.pages['ecom-sales-order-entry-list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('E-Com Sales Orders'),
		single_column: true,
	});
	page.main.html(frappe.render_template('ecom_sales_order_entry_list'));
	new EcomSalesOrderListPage(page);
};

const ESO_WF_STATUS_OPTIONS =
	'\nDraft\nWarehouse Approval Pending\nFuture Dispatch\nToday\'s Dispatch\nWarehouse Approved' +
	'\nPicking In Progress\nSubmission Pending\nReady For Dispatch\nDelivery Note Created\nDispatched' +
	'\nPartial Ready For Dispatch\nPartial Delivery Note Created\nPartial Dispatched' +
	'\nForced Ready For Dispatch\nForced Delivery Note Created\nForced Dispatched' +
	'\nCompleted\nForced Completed\nCancelled';

const ESO_WF_COLORS = {
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
	'Partial Ready For Dispatch': 'blue',
	'Partial Delivery Note Created': 'blue',
	'Partial Dispatched': 'purple',
	'Forced Ready For Dispatch': 'orange',
	'Forced Delivery Note Created': 'orange',
	'Forced Dispatched': 'red',
	Completed: 'green',
	'Forced Completed': 'red',
	Cancelled: 'red',
};

// E-Com column layout (specced separately from the offline Sales/Warehouse layouts).
const ESO_COLUMNS = [
	{ label: 'ID', render: (d, h) => `<strong>${h.esc(d.name)}</strong>` },
	{ label: 'Customer Name', render: (d, h) => h.esc(d.customer_name) },
	{ label: 'PO Number', render: (d, h) => h.esc(d.custom_po_number || d.po_no || '—') },
	{ label: 'PO Date', render: (d, h) => h.date(d.custom_po_date || d.po_date) },
	{ label: 'Dispatch Date', render: (d, h) => h.date(d.custom_dispatch_date) },
	{ label: 'Workflow Status', render: (d, h) => h.wf(d) },
	{ label: 'Links', cls: 'text-center', render: (d, h) => h.links(d) },
	{ label: 'Created By', render: (d, h) => h.esc(d.owner_full_name || d.owner) },
	{ label: 'Grand Total', cls: 'text-right', render: (d, h) => h.money(d) },
];

class EcomSalesOrderListPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._last_meta = { has_more: 0 };
		this._filters = {};
		this._columns = ESO_COLUMNS;
		this.render_header();
		this.setup_toolbar();
		this.setup_filters();
		this.bind_events();
		this.load_list();
	}

	setup_toolbar() {
		if (frappe.model.can_create('Sales Order')) {
			this.page.set_primary_action(
				__('New E-Com Order'),
				() => frappe.set_route('ecom-sales-order-entry'),
				'fa fa-plus'
			);
		}
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.page.add_inner_button(__('Offline Orders'), () => frappe.set_route('sales-order-entry-list'));
		if (frappe.model.can_create('Sales Order')) {
			this.page.add_inner_button(__('Download Template'), () => {
				window.open('/api/method/alpinos.ecom_sales_order_import.download_ecom_import_template');
			}, __('Import'));
			this.page.add_inner_button(__('Import Excel'), () => this.open_import_dialog(), __('Import'));
		}
	}

	open_import_dialog() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Import E-Com Sales Orders'),
			fields: [
				{
					fieldtype: 'HTML',
					options: `<p class="text-muted">${__(
						'One row per SKU line; rows are grouped into an order by PO Number. Use Download Template for the columns. Each order is validated and created individually — failures are reported and skip only that order.'
					)}</p>`,
				},
				{ fieldtype: 'Attach', fieldname: 'file', label: __('Excel / CSV File'), reqd: 1 },
			],
			primary_action_label: __('Import'),
			primary_action(v) {
				if (!v.file) return;
				frappe.call({
					method: 'alpinos.ecom_sales_order_import.import_ecom_sales_orders',
					args: { file_url: v.file },
					freeze: true,
					freeze_message: __('Importing orders...'),
					callback(r) {
						const m = r.message || {};
						d.hide();
						me.show_import_summary(m);
						me.load_list();
					},
				});
			},
		});
		d.show();
	}

	show_import_summary(m) {
		const created = m.created || [];
		const errors = m.errors || [];
		const esc = (s) => frappe.utils.escape_html(String(s == null ? '' : s));
		let html = `<p><b>${created.length}</b> ${__('order(s) created')}, <b>${errors.length}</b> ${__('failed')} (${__('of')} ${cint(m.total_orders)}).</p>`;
		if (created.length) {
			html += '<ul>' + created.map((c) => `<li>${esc(c.po_number)} → <b>${esc(c.sales_order)}</b></li>`).join('') + '</ul>';
		}
		if (errors.length) {
			html += `<p class="text-danger"><b>${__('Errors')}:</b></p><ul>` +
				errors.map((e) => `<li>${esc(e.po_number)} (${esc(e.customer)}): ${esc(e.error)}</li>`).join('') + '</ul>';
		}
		frappe.msgprint({ title: __('Import Result'), message: html, indicator: errors.length ? 'orange' : 'green' });
	}

	setup_filters() {
		const w = this.wrapper;
		this._filters.search = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', fieldname: 'search', label: __('Search (ID, customer, PO)') },
			parent: w.find('.fld-search'), render_input: true,
		});
		this._filters.workflow_status = frappe.ui.form.make_control({
			df: { fieldtype: 'Select', fieldname: 'workflow_status', label: __('Workflow Status'), options: ESO_WF_STATUS_OPTIONS },
			parent: w.find('.fld-workflow-status'), render_input: true,
		});
		this._filters.customer = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', fieldname: 'customer', label: __('Customer'), options: 'Customer' },
			parent: w.find('.fld-customer'), render_input: true,
		});
		this._filters.from_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'from_date', label: __('From date') },
			parent: w.find('.fld-from-date'), render_input: true,
		});
		this._filters.to_date = frappe.ui.form.make_control({
			df: { fieldtype: 'Date', fieldname: 'to_date', label: __('To date') },
			parent: w.find('.fld-to-date'), render_input: true,
		});
	}

	bind_events() {
		this.wrapper.find('.btn-eso-list-apply').on('click', () => { this.start = 0; this.load_list(); });
		this.wrapper.find('.btn-eso-list-clear').on('click', () => {
			Object.values(this._filters).forEach((f) => f && f.set_value(''));
			this.start = 0; this.load_list();
		});
		this.wrapper.find('.btn-eso-list-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length); this.load_list();
		});
		this.wrapper.find('.btn-eso-list-next').on('click', () => {
			if (this._last_meta.has_more) { this.start += this.page_length; this.load_list(); }
		});
		this.wrapper.on('click', '.eso-list-row', (e) => {
			if ($(e.target).closest('a,button').length) return;
			const name = $(e.currentTarget).data('name');
			if (name) frappe.set_route('ecom-sales-order-entry', { edit_eso: name });
		});
		this.wrapper.on('click', '.eso-list-link-btn', (e) => {
			e.stopPropagation();
			const route = $(e.currentTarget).data('route');
			if (Array.isArray(route)) frappe.set_route(...route);
		});
	}

	_args() {
		const f = this._filters;
		return {
			start: this.start,
			page_length: this.page_length,
			channel: 'E-com',
			search: f.search.get_value() || '',
			workflow_status: f.workflow_status.get_value() || '',
			customer: f.customer.get_value() || '',
			from_date: f.from_date.get_value() || '',
			to_date: f.to_date.get_value() || '',
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.sales_order_api.get_sales_order_entry_list',
			args: me._args(),
			freeze: true, freeze_message: __('Loading...'),
			callback(r) {
				if (r.exc) return;
				const msg = r.message || {};
				me._last_meta = {
					has_more: cint(msg.has_more), start: cint(msg.start), page_length: cint(msg.page_length),
				};
				me.render_rows(msg.data || []);
				me.update_pager();
			},
		});
	}

	render_header() {
		const tr = this.wrapper.find('.eso-list-table thead tr').empty();
		this._columns.forEach((c) => tr.append(`<th class="${c.cls || ''}">${__(c.label)}</th>`));
	}

	render_rows(rows) {
		const tb = this.wrapper.find('.eso-list-table tbody').empty();
		if (!rows.length) {
			tb.append(`<tr><td colspan="${this._columns.length}" class="text-muted text-center">${__('No E-Com Sales Orders found')}</td></tr>`);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const helpers = {
			esc,
			date: (v) => (v && frappe.datetime.str_to_user(String(v))) || '—',
			money: (d) => format_currency(d.grand_total || 0, d.currency),
			wf: (d) => {
				const wf = d.custom_workflow_status || '';
				const c = ESO_WF_COLORS[wf] || 'gray';
				return wf ? `<span class="indicator-pill ${c}">${esc(wf)}</span>` : '—';
			},
			links: (d) => {
				const btns = [];
				const mk = (label, route, title) =>
					`<button type="button" class="btn btn-xs btn-default eso-list-link-btn" data-route='${esc(JSON.stringify(route))}' title="${esc(title)}">${label}</button>`;
				if (d.pick_list && frappe.model.can_read('Pick List')) btns.push(mk('PL', ['pick_list_entry', d.pick_list], d.pick_list));
				if (d.delivery_note && frappe.model.can_read('Delivery Note')) btns.push(mk('DN', ['delivery_note_entry', d.delivery_note], d.delivery_note));
				return btns.join(' ') || '—';
			},
		};
		rows.forEach((d) => {
			const cells = this._columns.map((c) => `<td class="${c.cls || ''}">${c.render(d, helpers)}</td>`).join('');
			tb.append(`<tr class="eso-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">${cells}</tr>`);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.eso-list-table tbody tr.eso-list-row').length;
		if (!n) {
			this.wrapper.find('.eso-list-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.eso-list-count').text(__('Showing {0}–{1}', [from, to]));
		}
		this.wrapper.find('.btn-eso-list-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-eso-list-next').prop('disabled', !this._last_meta.has_more);
	}
}
