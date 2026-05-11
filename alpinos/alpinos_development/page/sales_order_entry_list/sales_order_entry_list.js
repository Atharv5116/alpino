frappe.pages['sales-order-entry-list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Sales Orders'),
		single_column: true,
	});
	page.main.html(frappe.render_template('sales_order_entry_list'));
	new SalesOrderEntryListPage(page);
};

const SO_STATUS_OPTIONS =
	'\nDraft\nOn Hold\nTo Deliver and Bill\nTo Bill\nTo Deliver\nCompleted\nCancelled\nClosed';

class SalesOrderEntryListPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._last_meta = { has_more: 0 };
		this._filter_fields = {};
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
			if ($(e.target).closest('a,button').length) return;
			const name = $(e.currentTarget).data('name');
			if (!name) return;
			frappe.route_options = { sales_order: name };
			frappe.set_route('sales-order-entry-view');
		});
	}

	_args() {
		const f = this._filter_fields;
		return {
			start: this.start,
			page_length: this.page_length,
			search: f.search.get_value() || '',
			status: f.status.get_value() || '',
			company: f.company.get_value() || '',
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

	render_rows(rows) {
		const tb = this.wrapper.find('.so-list-table tbody').empty();
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="8" class="text-muted text-center">${__('No Sales Orders found')}</td></tr>`
			);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		rows.forEach((d) => {
			const gt = format_currency(d.grand_total || 0, d.currency);
			const td = (d.transaction_date && frappe.datetime.str_to_user(d.transaction_date)) || '—';
			const dd = (d.delivery_date && frappe.datetime.str_to_user(d.delivery_date)) || '—';
			tb.append(`<tr class="so-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">
				<td><strong>${esc(d.name)}</strong></td>
				<td>${esc(d.customer)}</td>
				<td>${esc(d.customer_name)}</td>
				<td>${esc(td)}</td>
				<td>${esc(dd)}</td>
				<td>${esc(d.company)}</td>
				<td><span class="indicator-pill blue">${esc(d.status)}</span></td>
				<td class="text-right">${gt}</td>
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
