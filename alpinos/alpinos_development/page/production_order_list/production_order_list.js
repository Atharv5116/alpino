/**
 * Parent Production Order — list screen (Task 21).
 *
 * Paged from the start. The Item list had to be fixed after silently truncating at 200 of
 * 231 items, and orders accumulate faster than a catalogue does.
 *
 * Two actions the FRD asks for are NOT here: Merge (task 35) and Send to Store (task D).
 * Both depend on a Sub PO existing, and Sub PO creation timing is one of the decisions still
 * open — so rather than offer buttons that would have to guess, the screen says what it is
 * waiting for.
 */

frappe.pages['production_order_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Production Orders'),
		single_column: true,
	});
	wrapper.production_order_list = new ProductionOrderList(page);
};

frappe.pages['production_order_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.production_order_list) wrapper.production_order_list.refresh();
};

var ProductionOrderList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.meta = {};
		this.filters = {
			search: '', production_type: '', fg_item: '', status: '', client: '',
			start_date_from: '', start_date_to: '',
			start: 0, page_length: 50, sort_field: '', sort_dir: 'desc',
		};
		this.render_shell();
		this.make_filters();
		this.make_actions();
		this.bind_selection();
		this.refresh();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="prod-list">
				<style>
					.prod-list .prod-filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
					.prod-list .prod-filters > div { min-width: 170px; }
					.prod-list table { width: 100%; }
					.prod-list tbody tr { cursor: pointer; }
					.prod-list tbody tr:hover { background: var(--bg-light-gray, #f4f5f6); }
					.prod-list .prod-empty { padding: 40px; text-align: center; color: var(--text-muted); }
					.prod-list .prod-num { text-align: right; white-space: nowrap; }
					.prod-list thead th.sortable { cursor: pointer; }
					.prod-list thead th.sortable:hover { text-decoration: underline; }
					.prod-list .prod-pager { display: flex; align-items: center; justify-content: space-between;
						margin-top: 12px; gap: 12px; flex-wrap: wrap; }
					.prod-list .prod-note { display: flex; gap: 8px; align-items: baseline;
						margin-bottom: 14px; padding: 8px 12px; border-radius: 6px; font-size: 13px;
						border: 1px solid var(--border-color, #e2e2e2); background: var(--bg-light-gray, #f8f8f8); }
				</style>
				<div class="prod-note prod-selection" style="display:none;"></div>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-type"></div>
					<div class="filter-status"></div>
					<div class="filter-fg"></div>
					<div class="filter-client"></div>
					<div class="filter-from"></div>
					<div class="filter-to"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:34px;"><input type="checkbox" class="po-check-all"></th>
								<th style="width:96px;" class="sortable" data-sort="name">${__('PO ID')}</th>
								<th style="width:120px;" class="sortable" data-sort="production_type">${__('Type')}</th>
								<th style="width:150px;" class="sortable" data-sort="client_name">${__('Client')}</th>
								<th class="sortable" data-sort="fg_item">${__('FG Item')}</th>
								<th style="width:110px;" class="prod-num sortable" data-sort="production_qty_kg">${__('Target KG')}</th>
								<th style="width:90px;" class="prod-num">${__('Total Pcs')}</th>
								<th style="width:110px;" class="sortable" data-sort="delivery_date">${__('Delivery')}</th>
								<th style="width:140px;">${__('Sub POs')}</th>
								<th style="width:130px;" class="sortable" data-sort="status">${__('Status')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No production order yet.')}</div>
				</div>
				<div class="prod-pager">
					<div class="prod-count text-muted"></div>
					<div style="display:flex;gap:8px;align-items:center;">
						<div class="filter-page-length" style="min-width:150px;"></div>
						<button class="btn btn-sm btn-default prod-prev">${__('Previous')}</button>
						<button class="btn btn-sm btn-default prod-next">${__('Next')}</button>
					</div>
				</div>
			</div>
		`);

		const me = this;
		this.wrapper.find('thead th.sortable').on('click', function () {
			const field = $(this).attr('data-sort');
			if (me.filters.sort_field === field) {
				me.filters.sort_dir = me.filters.sort_dir === 'asc' ? 'desc' : 'asc';
			} else {
				me.filters.sort_field = field;
				me.filters.sort_dir = 'asc';
			}
			me.filters.start = 0;
			me.refresh();
		});
		this.wrapper.find('.prod-prev').on('click', () => {
			me.filters.start = Math.max(0, cint(me.filters.start) - cint(me.filters.page_length));
			me.refresh();
		});
		this.wrapper.find('.prod-next').on('click', () => {
			me.filters.start = cint(me.filters.start) + cint(me.filters.page_length);
			me.refresh();
		});
	}

	_ctl(selector, df, value, onchange) {
		const parent = this.wrapper.find(selector);
		if (!parent.length) return null;
		parent.empty();
		const control = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data', change: onchange }, df),
			parent: parent,
			render_input: true,
		});
		control.refresh();
		if (value !== undefined) control.set_value(value);
		return control;
	}

	make_filters() {
		const me = this;
		// Any filter change resets to the first page: page 4 of the old result set is not
		// page 4 of the new one, and landing on an empty page reads as "no orders".
		const reload = frappe.utils.debounce(() => { me.filters.start = 0; me.refresh(); }, 300);

		this._ctl('.filter-search', {
			fieldname: 'search', label: __('Search'), fieldtype: 'Data',
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		this._ctl('.filter-type', {
			fieldname: 'production_type', label: __('Type'), fieldtype: 'Select',
			options: [{ label: __('All'), value: '' }, 'Own Production', 'Export', 'White Label'],
		}, '', function () { me.filters.production_type = this.get_value(); reload(); });

		this._ctl('.filter-status', {
			fieldname: 'status', label: __('Status'), fieldtype: 'Select',
			options: [{ label: __('All'), value: '' }, 'Draft', 'Pending Approval', 'Approved',
				'Sent To Store', 'Rejected', 'Cancelled'],
		}, '', function () { me.filters.status = this.get_value(); reload(); });

		this._ctl('.filter-fg', {
			fieldname: 'fg_item', label: __('FG Item'), fieldtype: 'Link', options: 'Item',
			get_query() { return { query: 'alpinos.production.bom_api.fg_item_query' }; },
		}, '', function () { me.filters.fg_item = this.get_value(); reload(); });

		this._ctl('.filter-client', {
			fieldname: 'client', label: __('Client'), fieldtype: 'Link', options: 'Customer',
		}, '', function () { me.filters.client = this.get_value(); reload(); });

		this._ctl('.filter-from', {
			fieldname: 'start_date_from', label: __('Start From'), fieldtype: 'Date',
		}, '', function () { me.filters.start_date_from = this.get_value(); reload(); });

		this._ctl('.filter-to', {
			fieldname: 'start_date_to', label: __('Start To'), fieldtype: 'Date',
		}, '', function () { me.filters.start_date_to = this.get_value(); reload(); });

		this.page_length_control = this._ctl('.filter-page-length', {
			fieldname: 'page_length', label: '', fieldtype: 'Select',
			options: [{ label: __('50 per page'), value: '50' }],
		}, '50', function () {
			me.filters.page_length = cint(this.get_value()) || 50;
			me.filters.start = 0;
			me.refresh();
		});
	}

	make_actions() {
		if (frappe.model.can_create('Production Order')) {
			this.page.set_primary_action(__('New Production Order'), () => {
				frappe.set_route('production_order_entry');
			}, 'add');
		}
		// Task 21: Export. Built from the rows on screen, so what downloads is exactly the
		// filtered page being looked at rather than a second query that could disagree.
		this.page.add_inner_button(__('Export'), () => this.export_csv());
		// Task 35: Merge is on the Parent list only, and needs two or more selected.
		this.page.add_inner_button(__('Merge'), () => this.merge());
		this.page.add_inner_button(__('Sub Orders'), () => frappe.set_route('sub_order_list'));
		this.page.add_inner_button(__('BOM Master'), () => frappe.set_route('bom_master_list'));
		this.page.add_inner_button(__('Item Master'), () => frappe.set_route('item_master_list'));
	}

	// ------------------------------------------------------------- selection

	bind_selection() {
		const me = this;
		this.wrapper.on('change', '.po-check', () => me.render_selection());
		this.wrapper.on('change', '.po-check-all', function () {
			me.wrapper.find('.po-check').prop('checked', $(this).prop('checked'));
			me.render_selection();
		});
	}

	selected() {
		return this.wrapper.find('.po-check:checked').toArray().map((el) => $(el).attr('data-name'));
	}

	render_selection() {
		const names = this.selected();
		const $note = this.wrapper.find('.prod-selection');
		if (!names.length) return $note.hide().empty();
		const rows = this.rows.filter((r) => names.includes(r.name));
		const sendable = rows.filter((r) => r.status === 'Approved').map((r) => r.name);
		const esc = (v) => frappe.utils.escape_html(String(v));
		let html = `<b>${__('{0} selected', [names.length])}:</b> ${esc(names.join(', '))}`;
		if (sendable.length) {
			html += ` &nbsp; <button class="btn btn-xs btn-primary po-send">${
				__('Send {0} to Store', [sendable.length])}</button>`;
		}
		html += ` &nbsp; <button class="btn btn-xs btn-default po-merge">${__('Merge')}</button>`;
		html += ` &nbsp; <button class="btn btn-xs btn-default po-clear">${__('Clear')}</button>`;
		$note.html(html).show();
		const me = this;
		$note.find('.po-send').off('click').on('click', () => me.send_selected_to_store(sendable));
		$note.find('.po-merge').off('click').on('click', () => me.merge());
		$note.find('.po-clear').off('click').on('click', () => {
			me.wrapper.find('.po-check, .po-check-all').prop('checked', false);
			me.render_selection();
		});
	}

	send_selected_to_store(names) {
		const me = this;
		frappe.confirm(
			__('Send {0} to store? Their sub orders are unlocked and the store team is told.',
				[names.join(', ')]),
			async () => {
				const done = [];
				const failed = [];
				for (const name of names) {
					try {
						// One at a time, and a failure on one must not hide the ones that
						// worked -- each order is its own decision.
						const r = await frappe.call({
							method: 'alpinos.production.production_order_api.send_to_store',
							args: { production_order: name },
						});
						if (r.message) done.push(name);
					} catch (e) {
						failed.push(name);
					}
				}
				if (done.length) {
					frappe.show_alert({ message: __('Sent: {0}', [done.join(', ')]), indicator: 'green' }, 6);
				}
				if (failed.length) {
					frappe.msgprint({ title: __('Some Orders Were Not Sent'), indicator: 'orange',
						message: failed.join(', ') });
				}
				me.refresh();
			}
		);
	}

	// ----------------------------------------------------------------- merge

	merge() {
		const names = this.selected();
		if (names.length < 2) {
			frappe.msgprint({ title: __('Cannot Merge'), indicator: 'orange',
				message: __('Select at least two orders.') });
			return;
		}
		const me = this;
		frappe.call({
			method: 'alpinos.production.production_order_api.merge_view',
			args: { production_orders: names },
			freeze: true,
			freeze_message: __('Building the consolidated view...'),
			callback(r) {
				if (!r.message) return;
				me.show_merge_view(r.message);
			},
		});
	}

	show_merge_view(data) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const num = (v, d) => esc(format_number(flt(v), null, d === undefined ? 3 : d));

		let html = `<div class="merge-view">
			<p class="text-muted">${__('A planning view only. Nothing is saved, and the orders stay independent.')}</p>
			<h5>${__('Orders')}</h5>
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('PO')}</th><th>${__('FG Item')}</th>
				<th class="text-right">${__('Qty (KG)')}</th><th class="text-right">${__('PCS')}</th>
				<th>${__('Start')}</th><th>${__('Delivery')}</th><th>${__('Status')}</th>
			</tr></thead><tbody>`;
		data.orders.forEach((o) => {
			html += `<tr><td>${esc(o.name)}</td><td>${esc(o.fg_item)}</td>
				<td class="text-right">${num(o.production_qty_kg)}</td>
				<td class="text-right">${esc(cint(o.production_qty_pcs))}</td>
				<td>${o.production_start_date ? esc(frappe.datetime.str_to_user(o.production_start_date)) : '—'}</td>
				<td>${o.delivery_date ? esc(frappe.datetime.str_to_user(o.delivery_date)) : '—'}</td>
				<td>${esc(o.status)}</td></tr>`;
		});
		html += `</tbody></table>
			<h5>${__('Totals')}</h5>
			<table class="table table-bordered table-condensed"><tbody>
				<tr><td>${__('Orders')}</td><td class="text-right">${esc(cint(data.totals.orders))}</td></tr>
				<tr><td>${__('Total KG')}</td><td class="text-right">${num(data.totals.kg)}</td></tr>
				<tr><td>${__('Total PCS')}</td><td class="text-right">${esc(cint(data.totals.pcs))}</td></tr>
				<tr><td>${__('Total Batches')}</td><td class="text-right">${num(data.totals.batches)}</td></tr>
			</tbody></table>
			<h5>${__('Consolidated Materials')}</h5>
			<table class="table table-bordered table-condensed"><thead><tr>
				<th>${__('Item')}</th><th>${__('Type')}</th><th>${__('UOM')}</th>
				<th class="text-right">${__('Required')}</th>
				<th class="text-right">${__('Available')}</th>
				<th class="text-right">${__('Shortage')}</th><th>${__('Status')}</th>
			</tr></thead><tbody>`;
		data.materials.forEach((m) => {
			html += `<tr><td>${esc(m.item_code)}</td><td>${esc(m.material_type || '')}</td>
				<td>${esc(m.uom || '')}</td>
				<td class="text-right">${num(m.required_qty)}</td>
				<td class="text-right">${num(m.available_qty)}</td>
				<td class="text-right">${m.shortage_qty ? num(m.shortage_qty) : '—'}</td>
				<td>${esc(m.status)}</td></tr>`;
		});
		html += '</tbody></table></div>';

		const d = new frappe.ui.Dialog({
			title: __('Consolidated Planning View'),
			size: 'extra-large',
			fields: [{ fieldtype: 'HTML', fieldname: 'body', options: html }],
			primary_action_label: __('Export'),
			primary_action() { me_export(); },
			secondary_action_label: __('Print'),
			secondary_action() {
				const w = window.open('', '_blank');
				w.document.write(`<html><head><title>${__('Consolidated Planning View')}</title>
					<style>body{font-family:sans-serif;font-size:12px;}
					table{width:100%;border-collapse:collapse;margin-bottom:14px;}
					th,td{border:1px solid #333;padding:4px 6px;}
					.text-right{text-align:right;}</style></head><body>${html}</body></html>`);
				w.document.close();
				w.print();
			},
		});

		function me_export() {
			const cell = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
			const lines = [['Item', 'Material Type', 'UOM', 'Required', 'Available', 'Shortage', 'Status']
				.map(cell).join(',')];
			data.materials.forEach((m) => lines.push([
				m.item_code, m.material_type, m.uom, flt(m.required_qty),
				flt(m.available_qty), flt(m.shortage_qty), m.status].map(cell).join(',')));
			const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `consolidated-materials-${frappe.datetime.get_today()}.csv`;
			document.body.appendChild(a); a.click(); document.body.removeChild(a);
			URL.revokeObjectURL(url);
		}

		d.show();
	}

	export_csv() {
		if (!this.rows.length) {
			frappe.msgprint({ message: __('There is nothing on this page to export.'),
				title: __('Nothing To Export'), indicator: 'orange' });
			return;
		}
		const columns = [
			['PO ID', (r) => r.name],
			['Production Type', (r) => r.production_type],
			['Client', (r) => r.client_name],
			['FG Item', (r) => r.fg_item],
			['FG Item Name', (r) => r.fg_item_name],
			['Batch Number', (r) => r.batch_number],
			['BOM No', (r) => r.bom_no],
			['Target Qty (KG)', (r) => flt(r.production_qty_kg)],
			['Total Pcs', (r) => cint(r.production_qty_pcs)],
			['Start Date', (r) => r.production_start_date],
			['Delivery Date', (r) => r.delivery_date],
			['Sub POs', (r) => (r.sub_orders || []).map((s) => String(s.name).split('-').pop()).join('/')],
			['Status', (r) => r.status],
		];
		// Quoted and doubled up, so a client name with a comma or a quote in it cannot
		// shift every column after it.
		const cell = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
		const lines = [columns.map((c) => cell(c[0])).join(',')];
		this.rows.forEach((row) => lines.push(columns.map((c) => cell(c[1](row))).join(',')));
		// A BOM is a UTF-8 file; without it Excel reads a rupee sign or an accent as
		// mojibake, which is what "it opened wrong in Excel" usually means.
		const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `production-orders-${frappe.datetime.get_today()}.csv`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
		frappe.show_alert({ message: __('Exported {0} row(s)', [this.rows.length]),
			indicator: 'green' }, 5);
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.production_order_api.get_list',
			args: this.filters,
			callback(r) {
				const m = r.message || {};
				me.rows = m.data || [];
				me.meta = m;
				me.sync_page_lengths(m.page_lengths);
				me.render_rows();
				me.render_pager();
			},
		});
	}

	sync_page_lengths(lengths) {
		if (!lengths || !lengths.length || !this.page_length_control) return;
		const wanted = lengths.map((n) => ({ label: __('{0} per page', [n]), value: String(n) }));
		const current = this.page_length_control.df.options;
		// Only rewritten when it actually differs: setting options re-renders the control,
		// which fires change, which reloads the list — an endless round trip otherwise.
		if (JSON.stringify(current) === JSON.stringify(wanted)) return;
		this.page_length_control.df.options = wanted;
		this.page_length_control.refresh();
		this.page_length_control.set_value(String(this.filters.page_length));
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);
		const pill = {
			'Draft': 'gray', 'Pending Approval': 'orange', 'Approved': 'blue',
			'Sent To Store': 'green', 'Rejected': 'red', 'Cancelled': 'red',
		};

		this.rows.forEach((row) => {
			// The FRD asks for the sub orders listed as A/B/C, which is what the suffix of a
			// Sub PO name already is — so the letters are read off the names rather than
			// counted, and a gap left by a cancelled split shows up honestly.
			const subs = (row.sub_orders || []).map((s) => String(s.name).split('-').pop());
			const subText = subs.length
				? `${esc(subs.length)} <span class="text-muted">(${esc(subs.join('/'))})</span>`
				: '<span class="text-muted">—</span>';
			const $tr = $(`
				<tr>
					<td class="po-check-cell"><input type="checkbox" class="po-check" data-name="${esc(row.name)}"></td>
					<td>${esc(row.name)}</td>
					<td>${esc(row.production_type || '')}</td>
					<td>${row.client_name ? esc(row.client_name) : '<span class="text-muted">—</span>'}</td>
					<td>${esc(row.fg_item || '')}${row.fg_item_name && row.fg_item_name !== row.fg_item
						? ` <span class="text-muted">${esc(row.fg_item_name)}</span>` : ''}</td>
					<td class="prod-num">${esc(format_number(flt(row.production_qty_kg), null, 3))}</td>
					<td class="prod-num">${row.production_qty_pcs
						? esc(cint(row.production_qty_pcs)) : '<span class="text-muted">—</span>'}</td>
					<td>${row.delivery_date
						? esc(frappe.datetime.str_to_user(row.delivery_date)) : '<span class="text-muted">—</span>'}</td>
					<td>${subText}</td>
					<td><span class="indicator-pill ${pill[row.status] || 'gray'}">${esc(row.status || '')}</span></td>
				</tr>
			`);
			// The checkbox is for selecting, not for opening -- clicking it must not
			// navigate away from the list the user is building a selection on.
			$tr.on('click', (e) => {
				if ($(e.target).closest('.po-check-cell').length) return;
				frappe.set_route('production_order_entry', row.name);
			});
			$body.append($tr);
		});
		this.render_selection();
	}

	render_pager() {
		const m = this.meta || {};
		const start = cint(m.start);
		const shown = (this.rows || []).length;
		const total = cint(m.total);
		const $count = this.wrapper.find('.prod-count');
		if (!total) {
			$count.text('');
		} else {
			$count.text(__('{0} to {1} of {2}', [start + 1, start + shown, total]));
		}
		this.wrapper.find('.prod-prev').prop('disabled', start <= 0);
		this.wrapper.find('.prod-next').prop('disabled', !cint(m.has_more));
	}
};
