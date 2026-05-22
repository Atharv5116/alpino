frappe.pages['pick_list_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Pick Lists'),
		single_column: true,
	});
	page.main.html(frappe.render_template('pick_list_list'));
	new PickListListPage(page);
};

class PickListListPage {
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
				options: '\nDraft\nOpen\nCompleted\nCancelled\nClosed\nSubmitted',
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
		this.wrapper.find('.btn-pl-list-apply').on('click', () => {
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-pl-list-clear').on('click', () => {
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this.start = 0;
			this.load_list();
		});
		this.wrapper.find('.btn-pl-list-prev').on('click', () => {
			this.start = Math.max(0, this.start - this.page_length);
			this.load_list();
		});
		this.wrapper.find('.btn-pl-list-next').on('click', () => {
			if (this._last_meta.has_more) {
				this.start += this.page_length;
				this.load_list();
			}
		});
		this.wrapper.on('click', '.pl-list-row', (e) => {
			if ($(e.target).closest('a,button').length) return;
			const name = $(e.currentTarget).data('name');
			if (!name) return;
			frappe.set_route('app', 'pick-list-entry', { name: name });
		});
	}

	_args() {
		const f = this._filter_fields;
		return {
			start: this.start,
			page_length: this.page_length,
			search: f.search.get_value() || '',
			status: f.status.get_value() || '',
			company: f.company.get_value() || ''
		};
	}

	load_list() {
		const me = this;
		frappe.call({
			method: 'alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.get_pick_list_entry_list',
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
		const tb = this.wrapper.find('.pl-list-table tbody').empty();
		if (!rows.length) {
			tb.append(
				`<tr><td colspan="5" class="text-muted text-center">${__('No Pick Lists found')}</td></tr>`
			);
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		rows.forEach((d) => {
			const td = d.custom_order_date || '—';
			let status_color = 'blue';
			if (d.status === 'Draft') status_color = 'red';
			else if (d.status === 'Completed' || d.status === 'Submitted') status_color = 'green';
			
			tb.append(`<tr class="pl-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">
				<td><strong>${esc(d.name)}</strong></td>
				<td>${esc(d.custom_customer_name)}</td>
				<td>${esc(td)}</td>
				<td>${esc(d.company)}</td>
				<td><span class="indicator-pill ${status_color}">${esc(d.status)}</span></td>
			</tr>`);
		});
	}

	update_pager() {
		const n = this.wrapper.find('.pl-list-table tbody tr.pl-list-row').length;
		if (!n) {
			this.wrapper.find('.pl-list-count').text(__('No rows on this page'));
		} else {
			const from = this._last_meta.start + 1;
			const to = this._last_meta.start + n;
			this.wrapper.find('.pl-list-count').text(__('Showing {0}–{1}', [from, to]));
		}
		this.wrapper.find('.btn-pl-list-prev').prop('disabled', this.start <= 0);
		this.wrapper.find('.btn-pl-list-next').prop('disabled', !this._last_meta.has_more);
	}
}