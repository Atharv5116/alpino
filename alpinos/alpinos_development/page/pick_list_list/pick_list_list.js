frappe.pages['pick_list_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Alpino Pick Lists'),
		single_column: true,
	});
	page.main.html(frappe.render_template('pick_list_list'));
	wrapper.page_instance = new PickListListPage(page);
};

class PickListListPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.page_length = 20;
		this.start = 0;
		this._prefs_route = 'pick_list_list';
		this._last_meta = { has_more: 0 };
		this._filter_fields = {};
		this.setup_toolbar();
		this.setup_filters();
		this._restore_view_prefs();
		this.bind_events();
		this.load_list();
	}

	setup_toolbar() {
		this.page.add_inner_button(__('Refresh'), () => this.load_list());
		this.btn_bulk_edit = this.page.add_inner_button(__('Edit'), () => this.bulk_edit_fields());
		if (this.btn_bulk_edit) this.btn_bulk_edit.hide();
		this.btn_download_stickers = this.page.add_inner_button(__('Download Stickers'), () =>
			this.download_stickers()
		);
		if (this.btn_download_stickers) this.btn_download_stickers.hide();
	}

	_selected_names() {
		const names = [];
		this.wrapper.find('.pl-list-row-select:checked').each((i, el) => {
			names.push($(el).data('name'));
		});
		return names;
	}

	download_stickers() {
		const pick_lists = this._selected_names();
		if (!pick_lists.length) {
			frappe.msgprint(__('Please select at least one Pick List.'));
			return;
		}
		const url =
			'/api/method/alpinos.pick_list_api.generate_pick_list_stickers_bulk?pick_lists=' +
			encodeURIComponent(JSON.stringify(pick_lists));
		const w = window.open(frappe.urllib.get_full_url(url), '_blank');
		if (!w) frappe.msgprint(__('Please allow pop-ups to download the stickers PDF.'));
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
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.btn-pl-list-clear').on('click', () => {
			Object.values(this._filter_fields).forEach((f) => f && f.set_value(''));
			this.start = 0;
			this._save_view_prefs();
			this.load_list();
		});
		this.wrapper.find('.pl-list-page-size').on('change', (e) => {
			const v = cint($(e.currentTarget).val());
			this.page_length = [20, 50, 100].includes(v) ? v : 20;
			$(e.currentTarget).val(String(this.page_length));
			this.start = 0;
			this._save_view_prefs();
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
			if ($(e.target).closest('a,button,input[type="checkbox"]').length) return;
			const name = $(e.currentTarget).data('name');
			if (!name) return;
			frappe.set_route('pick_list_entry', name);
		});
		this.wrapper.on('change', '.pl-list-select-all', (e) => {
			const checked = $(e.target).prop('checked');
			this.wrapper.find('.pl-list-row-select').prop('checked', checked);
			this.update_selection();
		});
		this.wrapper.on('change', '.pl-list-row-select', () => {
			this.update_selection();
		});
	}

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

	_restore_view_prefs() {
		// Runs before the first load_list(): apply the saved per-user view to
		// the instance AND the visible controls. Every value is validated so a
		// stale/renamed key can never break the page. Pagination offset is
		// intentionally never restored — the list always opens on page 1.
		if (!(window.alpinos && alpinos.list_prefs)) return;
		let saved = {};
		try {
			saved = alpinos.list_prefs.load(this._prefs_route) || {};
		} catch (e) {
			saved = {};
		}
		const f = this._filter_fields;
		// set_input applies synchronously, so the first load_list() sees the
		// restored values via get_value(); set_value is promise-based and can
		// land after the first request.
		const set_sync = (c, v) => {
			if (!c) return;
			if (typeof c.set_input === 'function') c.set_input(v);
			else c.set_value(v);
		};
		try {
			if (typeof saved.search === 'string') {
				set_sync(f.search, saved.search);
			}
			const status_options = ['', 'Draft', 'Open', 'Completed', 'Cancelled', 'Closed', 'Submitted'];
			if (typeof saved.status === 'string' && status_options.includes(saved.status)) {
				set_sync(f.status, saved.status);
			}
			if (typeof saved.company === 'string') {
				set_sync(f.company, saved.company);
			}
			const pl = cint(saved.page_length);
			if ([20, 50, 100].includes(pl)) {
				this.page_length = pl;
			}
		} catch (e) {
			// A malformed saved state must never block the page.
		}
		this.wrapper.find('.pl-list-page-size').val(String(this.page_length));
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
		me.wrapper.find('.pl-list-select-all').prop('checked', false);
		if (me.btn_bulk_edit) me.btn_bulk_edit.hide();
		if (me.btn_download_stickers) me.btn_download_stickers.hide();
		if (me.page && me.page.clear_indicator) me.page.clear_indicator();

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
				`<tr><td colspan="13" class="text-muted text-center">${__('No Pick Lists found')}</td></tr>`
			);
			return;
		}
		const PL_WF_COLORS = {
			'Draft': 'red',
			'Picking Pending': 'orange',
			'Picking In Progress': 'blue',
			'Sticker Pending': 'yellow',
			'Submission Pending': 'orange',
			'Ready To Dispatch': 'blue',
			'Dispatched': 'green',
			'Cancelled': 'red',
		};
		const esc = (s) => frappe.utils.escape_html(s == null ? '' : String(s));
		const dash = (v) => (v == null || v === '' ? '—' : esc(v));
		const only_date = (v) => (v ? String(v).substring(0, 10) : '—');
		rows.forEach((d) => {
			let status_color = 'blue';
			if (d.status === 'Draft') status_color = 'red';
			else if (d.status === 'Completed' || d.status === 'Submitted') status_color = 'green';

			const wf = d.custom_workflow_status || '';
			const wfCell = wf
				? `<span class="indicator-pill ${PL_WF_COLORS[wf] || 'gray'}">${esc(wf)}</span>`
				: '—';

			tb.append(`<tr class="pl-list-row" data-name="${esc(d.name)}" style="cursor:pointer;">
				<td style="text-align: center;"><input type="checkbox" class="pl-list-row-select" data-name="${esc(d.name)}"></td>
				<td><strong>${esc(d.name)}</strong></td>
				<td>${dash(d.custom_sales_order_id)}</td>
				<td>${dash(d.custom_customer_name)}</td>
				<td>${dash(d.custom_po_no)}</td>
				<td>${only_date(d.custom_order_date)}</td>
				<td>${only_date(d.custom_dispatch_date)}</td>
				<td>${dash(d.company)}</td>
				<td>${dash(d.custom_transporter)}</td>
				<td>${dash(d.custom_assigned_to)}</td>
				<td style="text-align:right;">${d.custom_total_box == null ? '—' : esc(d.custom_total_box)}</td>
				<td>${wfCell}</td>
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

	update_selection() {
		const checked_boxes = this.wrapper.find('.pl-list-row-select:checked');
		const checked_count = checked_boxes.length;
		
		const all_boxes = this.wrapper.find('.pl-list-row-select');
		if (all_boxes.length && checked_count === all_boxes.length) {
			this.wrapper.find('.pl-list-select-all').prop('checked', true);
		} else {
			this.wrapper.find('.pl-list-select-all').prop('checked', false);
		}

		if (checked_count > 0) {
			if (this.btn_bulk_edit) this.btn_bulk_edit.show();
			if (this.btn_download_stickers) this.btn_download_stickers.show();
			if (this.page && this.page.set_indicator) {
				this.page.set_indicator(__('{0} selected', [checked_count]), 'orange');
			}
		} else {
			if (this.btn_bulk_edit) this.btn_bulk_edit.hide();
			if (this.btn_download_stickers) this.btn_download_stickers.hide();
			if (this.page && this.page.clear_indicator) this.page.clear_indicator();
		}
	}

	bulk_edit_fields() {
		const checked_boxes = this.wrapper.find('.pl-list-row-select:checked');
		const pick_lists = [];
		checked_boxes.each((i, el) => {
			pick_lists.push($(el).data('name'));
		});

		if (!pick_lists.length) {
			frappe.msgprint(__('Please select at least one Pick List.'));
			return;
		}

		const me = this;
		let dialog = new frappe.ui.Dialog({
			title: __('Bulk Edit Fields'),
			fields: [
				{
					fieldname: 'field',
					fieldtype: 'Select',
					label: __('Select Field'),
					options: [
						{ value: 'custom_transporter', label: __('Transporter') },
						{ value: 'custom_qc_attended_by', label: __('QC Attended By') }
					],
					reqd: 1,
					onchange: function() {
						let val = dialog.get_value('field');
						if (val === 'custom_transporter') {
							dialog.set_df_property('transporter_value', 'hidden', 0);
							dialog.set_df_property('transporter_value', 'reqd', 1);
							dialog.set_df_property('qc_value', 'hidden', 1);
							dialog.set_df_property('qc_value', 'reqd', 0);
						} else {
							dialog.set_df_property('transporter_value', 'hidden', 1);
							dialog.set_df_property('transporter_value', 'reqd', 0);
							dialog.set_df_property('qc_value', 'hidden', 0);
							dialog.set_df_property('qc_value', 'reqd', 1);
						}
					}
				},
				{
					fieldname: 'transporter_value',
					fieldtype: 'Data',
					label: __('New Transporter Value'),
					hidden: 1
				},
				{
					fieldname: 'qc_value',
					fieldtype: 'Link',
					options: 'User',
					label: __('New QC Attended By Value'),
					hidden: 1,
					get_query: function() {
						return {
							filters: {
								enabled: 1,
								user_type: 'System User'
							}
						};
					}
				}
			],
			primary_action_label: __('Update'),
			primary_action: function(values) {
				let fieldname = values.field;
				let val = fieldname === 'custom_transporter' ? values.transporter_value : values.qc_value;
				
				frappe.call({
					method: 'alpinos.pick_list_api.bulk_edit_pick_lists',
					args: {
						pick_lists: pick_lists,
						fieldname: fieldname,
						value: val
					},
					freeze: true,
					freeze_message: __('Updating Pick Lists...'),
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({
								message: __('Updated {0} Pick List(s)', [pick_lists.length]),
								indicator: 'green'
							});
							me.wrapper.find('.pl-list-select-all').prop('checked', false);
							me.load_list();
							dialog.hide();
						}
					}
				});
			}
		});

		dialog.fields_dict.field.df.onchange();
		dialog.show();
	}
}

frappe.pages['pick_list_list'].on_page_show = function (wrapper) {
	if (wrapper.page_instance) {
		wrapper.page_instance.start = 0;
		wrapper.page_instance.load_list();
	}
};