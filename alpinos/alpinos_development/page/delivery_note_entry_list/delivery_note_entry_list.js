frappe.pages['delivery_note_entry_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Delivery Notes'),
		single_column: true,
	});
	page.main.html(frappe.render_template('delivery_note_entry_list'));
	wrapper.page_instance = new DeliveryNoteListPage(page);
};

class DeliveryNoteListPage {
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
		this.load_list();
	}

	setup_toolbar() {
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
	}

	setup_filters() {
		const w = this.wrapper;
		this._filter_fields.search = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Data',
				fieldname: 'search',
				label: __('Search (ID, Customer)'),
			},
			parent: w.find('.fld-search'),
			render_input: true,
		});
		this._filter_fields.status = frappe.ui.form.make_control({
			df: {
				fieldtype: 'Select',
				fieldname: 'status',
				label: __('Status'),
				options: '\nDraft\nTo Bill\nCompleted\nCancelled\nClosed\nReturn Issued',
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
	}

	bind_events() {
		this.wrapper.find('.btn-dnl-apply').on('click', () => {
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-dnl-clear').on('click', () => {
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-dnl-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-dnl-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});
		this.wrapper.on('click', '.dnl-row', (e) => {
			if ($(e.target).closest('a,button,input').length) return;
			const name = $(e.currentTarget).data('name');
			if (!name) return;
			frappe.set_route('delivery_note_entry', name);
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
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.get_delivery_note_list',
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
		const tb = this.wrapper.find('.dnl-table tbody').empty();
		if (!rows.length) {
			tb.append(`<tr><td colspan="6" class="text-muted text-center">${__('No Delivery Notes found')}</td></tr>`);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		rows.forEach((d) => {
			// Show the workflow-aligned status: Draft -> Dispatched -> Cancelled.
			let wf = 'Draft';
			let status_color = 'red';
			if (d.docstatus === 2) {
				wf = 'Cancelled';
				status_color = 'darkgrey';
			} else if (d.docstatus === 1) {
				wf = 'Dispatched';
				status_color = 'green';
			}
			const customer = d.custom_dn_so_customer_name || d.customer_name || '';
			tb.append(`<tr class="dnl-row" data-name="${esc(d.name)}" style="cursor:pointer;">
				<td><strong>${esc(d.name)}</strong></td>
				<td>${esc(customer)}</td>
				<td>${esc(d.posting_date || '—')}</td>
				<td>${esc(d.custom_dispatch_date || '—')}</td>
				<td>${esc(d.company)}</td>
				<td><span class="indicator-pill ${status_color}">${esc(wf)}</span></td>
			</tr>`);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.dnl-table tbody tr.dnl-row').length;
		if (!n) {
			this.wrapper.find('.dnl-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.dnl-count').text(__('Showing {0}–{1}', [from, to]));
		}
		this.wrapper.find('.btn-dnl-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-dnl-next').prop('disabled', !this._last_meta.has_more);
	}
}

frappe.pages['delivery_note_entry_list'].on_page_show = function (wrapper) {
	if (wrapper.page_instance) {
		wrapper.page_instance.start = 0;
		wrapper.page_instance.load_list();
	}
};
