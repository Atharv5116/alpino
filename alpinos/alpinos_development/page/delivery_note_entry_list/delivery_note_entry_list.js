frappe.pages['delivery_note_entry_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Alpino Delivery Notes'),
		single_column: true,
	});
	page.main.html(frappe.render_template('delivery_note_entry_list'));
	wrapper.page_instance = new DeliveryNoteListPage(page);
};

var DeliveryNoteListPage = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._prefs_route = 'delivery_note_entry_list';
		this._last_meta = { has_more: 0 };
		this._filter_fields = {};
		// Opened from a Sales Order's "DN" button -> shows every DN of that SO.
		this.so_filter = (frappe.route_options && frappe.route_options.sales_order) || '';
		if (frappe.route_options) delete frappe.route_options.sales_order;
		this.setup_toolbar();
		this.setup_filters();
		this.bind_events();
		this._restore_view_prefs();
		this._render_so_banner();
		this.load_list();
	}

	_render_so_banner() {
		let $b = this.wrapper.find('.dnl-so-filter-banner');
		if (!this.so_filter) { $b.remove(); return; }
		if (!$b.length) {
			$b = $('<div class="dnl-so-filter-banner" style="margin-bottom:12px; padding:8px 12px; border-radius:6px; background:var(--bg-color,#f4f5f6); border:1px solid var(--border-color,#d1d8dd); display:flex; align-items:center; gap:10px;"></div>');
			this.wrapper.find('.dnl-container').prepend($b);
		}
		$b.html('<span>Showing Delivery Notes for Sales Order <strong>' + frappe.utils.escape_html(this.so_filter) + '</strong></span>');
		$('<button type="button" class="btn btn-xs btn-default">Show all</button>')
			.appendTo($b)
			.on('click', () => { this.so_filter = ''; this.start = 0; this._render_so_banner(); this.load_list(); });
	}

	setup_toolbar() {
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		// Warehouse Admin / Manager only.
		const isWarehouse = ['Warehouse Admin', 'Warehouse Manager', 'System Manager']
			.some((r) => frappe.user.has_role(r));
		if (isWarehouse) {
			this.page.add_inner_button(__('Download LR Excel'), () => this.download_lr_excel(), __('LR'));
			this.page.add_inner_button(__('Upload LR Excel'), () => this.upload_lr_excel(), __('LR'));
		}
	}

	_selected_names() {
		const names = [];
		this.wrapper.find('.dnl-row-select:checked').each((i, el) => {
			names.push($(el).data('name'));
		});
		return names;
	}

	// Ticked rows win; with nothing ticked this stays the old behaviour —
	// every draft Delivery Note dispatching today.
	download_lr_excel() {
		const base =
			'/api/method/alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.download_lr_excel';
		const names = this._selected_names();
		const url = names.length
			? base + '?delivery_notes=' + encodeURIComponent(JSON.stringify(names))
			: base;
		const w = window.open(frappe.urllib.get_full_url(url), '_blank');
		if (!w) frappe.msgprint(__('Please allow pop-ups to download the LR Excel.'));
	}

	upload_lr_excel() {
		const me = this;
		new frappe.ui.FileUploader({
			allow_multiple: false,
			restrictions: { allowed_file_types: ['.xlsx', '.xls'] },
			on_success: (file_doc) => {
				frappe.dom.freeze(__('Updating LR numbers & submitting...'));
				frappe.call({
					method: 'alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry.upload_lr_excel',
					args: { file_url: file_doc.file_url },
					always: () => frappe.dom.unfreeze(),
					callback: (r) => {
						if (r.exc || !r.message) return;
						me._show_lr_result(r.message);
						me.load_list();
					},
				});
			},
		});
	}

	_show_lr_result(m) {
		let html = '<p><b>' + frappe.utils.escape_html(m.message || '') + '</b></p>';
		if ((m.failed || []).length) {
			html += '<table class="table table-bordered" style="font-size:12px;"><thead><tr>' +
				'<th>Row</th><th>Sales Order</th><th>Reason</th></tr></thead><tbody>';
			m.failed.forEach((f) => {
				html += '<tr><td>' + f.row + '</td><td>' +
					frappe.utils.escape_html(f.sales_order || '') + '</td><td>' +
					frappe.utils.escape_html(f.reason || '') + '</td></tr>';
			});
			html += '</tbody></table>';
		}
		frappe.msgprint({
			title: __('LR Update Result'),
			message: html,
			indicator: (m.failed || []).length ? 'orange' : 'green',
		});
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
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-dnl-clear').on('click', () => {
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.dnl-page-size').on('change', (e) => {
			this.page_length = cint($(e.currentTarget).val()) || 20;
			this.start = 0;
			this._save_view_prefs();
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
		this.wrapper.on('change', '.dnl-select-all', (e) => {
			this.wrapper.find('.dnl-row-select').prop('checked', $(e.target).prop('checked'));
			this.update_selection();
		});
		this.wrapper.on('change', '.dnl-row-select', () => this.update_selection());
	}

	// Selection lives on the rows currently rendered, so it clears whenever the
	// list reloads (filter, page size, paging).
	update_selection() {
		const boxes = this.wrapper.find('.dnl-row-select');
		const checked = this.wrapper.find('.dnl-row-select:checked').length;
		this.wrapper.find('.dnl-select-all').prop('checked', !!boxes.length && checked === boxes.length);
		if (checked && this.page.set_indicator) {
			this.page.set_indicator(__('{0} selected', [checked]), 'orange');
		} else if (this.page.clear_indicator) {
			this.page.clear_indicator();
		}
	}

	// Persists filters + page size, never the pagination offset — a fresh visit starts at page 1.
	_save_view_prefs() {
		if (!(window.alpinos && alpinos.list_prefs)) return;
		const f = this._filter_fields;
		alpinos.list_prefs.save(this._prefs_route, {
			search: (f.search && f.search.get_value()) || '',
			status: (f.status && f.status.get_value()) || '',
			company: (f.company && f.company.get_value()) || '',
			page_length: this.page_length,
		});
	}

	// Applies the saved view to instance state + UI controls before the first data load.
	_restore_view_prefs() {
		if (!(window.alpinos && alpinos.list_prefs)) return;
		const saved = alpinos.list_prefs.load(this._prefs_route);
		if (!saved || typeof saved !== 'object') return;
		const f = this._filter_fields;
		['search', 'status', 'company'].forEach((k) => {
			const v = saved[k];
			if (typeof v !== 'string' || !v || !f[k]) return;
			// set_input applies synchronously so the first load_list() reads the restored values.
			if (typeof f[k].set_input === 'function') {
				f[k].set_input(v);
			} else {
				f[k].set_value(v);
			}
		});
		const pl = cint(saved.page_length);
		if ([20, 50, 100].includes(pl)) {
			this.page_length = pl;
			this.wrapper.find('.dnl-page-size').val(String(pl));
		}
	}

	_args() {
		const f = this._filter_fields;
		return {
			start: this.start,
			page_length: this.page_length,
			search: f.search.get_value() || '',
			status: f.status.get_value() || '',
			company: f.company.get_value() || '',
			sales_order: this.so_filter || '',
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
		this.wrapper.find('.dnl-select-all').prop('checked', false);
		if (!rows.length) {
			tb.append(`<tr><td colspan="13" class="text-muted text-center">${__('No Delivery Notes found')}</td></tr>`);
			this.update_selection();
			return;
		}
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const dash = (v) => (v == null || v === '' ? '—' : esc(v));
		const only_date = (v) => (v ? String(v).substring(0, 10) : '—');
		rows.forEach((d) => {
			// Workflow-aligned status: Draft -> Dispatched -> Cancelled.
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
				<td style="text-align:center;"><input type="checkbox" class="dnl-row-select" data-name="${esc(d.name)}"></td>
				<td><strong>${esc(d.name)}</strong></td>
				<td><span class="indicator-pill ${status_color}">${esc(wf)}</span></td>
				<td>${dash(d.custom_sales_order_id)}</td>
				<td>${dash(customer)}</td>
				<td>${only_date(d.posting_date)}</td>
				<td>${only_date(d.custom_dispatch_date)}</td>
				<td>${dash(d.company)}</td>
				<td>${dash(d.custom_transporter_name)}</td>
				<td>${dash(d.custom_lr_gr_no)}</td>
				<td>${dash(d.custom_invoice_no)}</td>
				<td>${dash(d.custom_assigned_to)}</td>
				<td style="text-align:right;">${d.custom_total_boxes == null ? '—' : esc(d.custom_total_boxes)}</td>
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
