/**
 * Sub Production Orders — list screen (Tasks 30 and 31).
 *
 * No New button, deliberately: a sub order is created by approving its Parent (SPO-02), and
 * the server refuses a manual one. A button that always fails is worse than no button.
 *
 * The row actions are the whole point of the screen — Split, Assign Process, Print Job Card
 * — so they sit on the row rather than behind a selection, and each says why it is
 * unavailable rather than being silently missing.
 */

frappe.pages['sub_order_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Sub Production Orders'),
		single_column: true,
	});
	wrapper.sub_order_list = new SubOrderList(page);
};

frappe.pages['sub_order_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.sub_order_list) wrapper.sub_order_list.handle_route();
};

var SubOrderList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.meta = {};
		this.filters = {
			search: '', parent: '', batch: '', item: '', process: '', machine: '',
			execution_status: '', production_type: '', planned_from: '', planned_to: '',
			start: 0, page_length: 50,
		};
		this.render_shell();
		this.make_filters();
		this.make_actions();
		this.bind_pager();
		this.bind_row_actions();
		this.refresh();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="prod-list">
				<style>
					.prod-list .prod-filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
					.prod-list .prod-filters > div { min-width: 160px; }
					.prod-list table { width: 100%; }
					.prod-list tbody tr:hover { background: var(--bg-light-gray, #f4f5f6); }
					.prod-list .prod-empty { padding: 40px; text-align: center; color: var(--text-muted); }
					.prod-list .prod-num { text-align: right; white-space: nowrap; }
					.prod-list .prod-pager { display: flex; align-items: center; justify-content: space-between;
						margin-top: 12px; gap: 12px; flex-wrap: wrap; }
					.prod-list .so-id { cursor: pointer; font-weight: 600; }
					.prod-list .so-id:hover { text-decoration: underline; }
					.prod-list .so-muted { color: var(--text-muted); }
					.prod-list .so-actions { white-space: nowrap; }
					.prod-list .so-actions .btn { margin-left: 4px; }
					.prod-list .so-lock { font-size: 11px; }
				</style>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-parent"></div>
					<div class="filter-batch"></div>
					<div class="filter-item"></div>
					<div class="filter-process"></div>
					<div class="filter-machine"></div>
					<div class="filter-exec"></div>
					<div class="filter-type"></div>
					<div class="filter-from"></div>
					<div class="filter-to"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:110px;">${__('Sub PO')}</th>
								<th style="width:96px;">${__('Parent')}</th>
								<th style="width:110px;">${__('Batch')}</th>
								<th>${__('Item')}</th>
								<th style="width:100px;" class="prod-num">${__('Qty (KG)')}</th>
								<th style="width:130px;">${__('Process')}</th>
								<th style="width:110px;">${__('Planned Date')}</th>
								<th style="width:140px;">${__('Machine')}</th>
								<th style="width:120px;">${__('Status')}</th>
								<th style="width:56px;">${__('Lock')}</th>
								<th style="width:210px;">${__('Actions')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">
						${__('No sub orders yet. They are created when a Production Order is approved.')}
					</div>
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

	/**
	 * /app/sub_order_list/PO-022 opens the screen already narrowed to that Parent PO.
	 *
	 * That is how the Production Order screen links here, so the button lands on that
	 * order's sub orders rather than on all of them. Routing back to the bare
	 * /app/sub_order_list clears it again, so the filter never outlives the link that set
	 * it -- a list that stays silently narrowed after you navigate away reads as missing
	 * data.
	 */
	handle_route() {
		const parent = (frappe.get_route() || [])[1] || '';
		if (parent === this.filters.parent) {
			this.refresh();
			return;
		}
		this.filters.parent = parent;
		this.filters.start = 0;
		// Setting the control fires the filter change handler, which refreshes on its own
		// debounce -- so this must not also refresh, or the screen loads twice.
		if (this.parent_filter) this.parent_filter.set_value(parent);
		else this.refresh();
	}

	make_filters() {
		const me = this;
		// Back to page 1 on any filter change: page 4 of the old result set is not page 4
		// of the new one, and landing on an empty page reads as "nothing found".
		const reload = frappe.utils.debounce(() => { me.filters.start = 0; me.refresh(); }, 300);
		const set = (key) => function () { me.filters[key] = this.get_value(); reload(); };

		this._ctl('.filter-search', { fieldname: 'search', label: __('Search'), fieldtype: 'Data' }, '', set('search'));
		this.parent_filter = this._ctl('.filter-parent', {
			fieldname: 'parent', label: __('Parent PO'), fieldtype: 'Link',
			options: 'Production Order',
		}, '', set('parent'));
		this._ctl('.filter-batch', { fieldname: 'batch', label: __('Batch'), fieldtype: 'Data' }, '', set('batch'));
		this._ctl('.filter-item', {
			fieldname: 'item', label: __('Item'), fieldtype: 'Link', options: 'Item',
			get_query() { return { query: 'alpinos.production.bom_api.fg_item_query' }; },
		}, '', set('item'));
		this._ctl('.filter-process', {
			fieldname: 'process', label: __('Process'), fieldtype: 'Link', options: 'Process Master',
		}, '', set('process'));
		this._ctl('.filter-machine', {
			fieldname: 'machine', label: __('Machine'), fieldtype: 'Link', options: 'Machine',
		}, '', set('machine'));
		this._ctl('.filter-exec', {
			fieldname: 'execution_status', label: __('Status'), fieldtype: 'Select',
			options: [{ label: __('All'), value: '' }, 'Unassigned', 'Assigned', 'In Progress', 'Completed'],
		}, '', set('execution_status'));
		this._ctl('.filter-type', {
			fieldname: 'production_type', label: __('Type'), fieldtype: 'Select',
			options: [{ label: __('All'), value: '' }, 'Own Production', 'Export', 'White Label'],
		}, '', set('production_type'));
		this._ctl('.filter-from', { fieldname: 'planned_from', label: __('Planned From'), fieldtype: 'Date' }, '', set('planned_from'));
		this._ctl('.filter-to', { fieldname: 'planned_to', label: __('Planned To'), fieldtype: 'Date' }, '', set('planned_to'));
	}

	make_actions() {
		// No New button (SPO-02). Export and the navigation links only.
		this.page.add_inner_button(__('Export'), () => this.export_csv());
		this.page.add_inner_button(__('Production Orders'), () => frappe.set_route('production_order_list'));
	}

	bind_pager() {
		const me = this;
		this.wrapper.find('.prod-prev').on('click', () => {
			me.filters.start = Math.max(0, cint(me.filters.start) - cint(me.filters.page_length));
			me.refresh();
		});
		this.wrapper.find('.prod-next').on('click', () => {
			me.filters.start = cint(me.filters.start) + cint(me.filters.page_length);
			me.refresh();
		});
		this.page_length_control = this._ctl('.filter-page-length', {
			fieldname: 'page_length', label: '', fieldtype: 'Select',
			options: [{ label: __('50 per page'), value: '50' }],
		}, '50', function () {
			me.filters.page_length = cint(this.get_value()) || 50;
			me.filters.start = 0;
			me.refresh();
		});
	}

	sync_page_lengths(lengths) {
		if (!lengths || !lengths.length || !this.page_length_control) return;
		const wanted = lengths.map((n) => ({ label: __('{0} per page', [n]), value: String(n) }));
		if (JSON.stringify(this.page_length_control.df.options) === JSON.stringify(wanted)) return;
		this.page_length_control.df.options = wanted;
		this.page_length_control.refresh();
		this.page_length_control.set_value(String(this.filters.page_length));
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.get_sub_order_list',
			args: this.filters,
			callback(r) {
				const m = r.message || {};
				me.meta = m;
				me.rows = m.data || [];
				me.sync_page_lengths(m.page_lengths);
				me.render_rows();
				me.render_pager();
			},
		});
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);
		const canPlan = cint(this.meta.can_plan);
		const pill = {
			'Unassigned': 'gray', 'Assigned': 'blue',
			'In Progress': 'orange', 'Completed': 'green',
		};

		this.rows.forEach((row) => {
			const locked = cint(row.custom_is_locked);
			// Task 30 asks for "Unassigned" and "-" in so many words, rather than blanks,
			// so an empty cell always means the same thing as an empty cell.
			const process = row.custom_assigned_process
				? esc(row.process_label || row.custom_assigned_process)
				: `<span class="so-muted">${__('Unassigned')}</span>`;
			const machine = row.custom_assigned_machine
				? esc(row.custom_assigned_machine)
				: '<span class="so-muted">&mdash;</span>';
			const planned = row.custom_planned_date
				? esc(frappe.datetime.str_to_user(row.custom_planned_date))
				: '<span class="so-muted">&mdash;</span>';
			const status = row.custom_execution_status || 'Unassigned';

			const actions = canPlan
				? `<button class="btn btn-xs btn-default so-assign" data-name="${esc(row.name)}"
						${locked ? 'disabled title="' + __('Locked until the Parent is sent to store') + '"' : ''}>${__('Assign')}</button>
				   <button class="btn btn-xs btn-default so-split" data-name="${esc(row.name)}">${__('Split')}</button>
				   <button class="btn btn-xs btn-default so-print" data-name="${esc(row.name)}">${__('Job Card')}</button>`
				: `<button class="btn btn-xs btn-default so-print" data-name="${esc(row.name)}">${__('Job Card')}</button>`;

			$body.append($(`
				<tr>
					<td><span class="so-id" data-name="${esc(row.name)}">${esc(row.name)}</span></td>
					<td><span class="so-id so-parent" data-parent="${esc(row.custom_parent_production_order)}">${esc(row.custom_parent_production_order)}</span></td>
					<td>${row.custom_batch_number ? esc(row.custom_batch_number) : '<span class="so-muted">&mdash;</span>'}</td>
					<td>${esc(row.production_item)}${row.item_name && row.item_name !== row.production_item
						? ` <span class="so-muted">${esc(row.item_name)}</span>` : ''}</td>
					<td class="prod-num">${esc(format_number(flt(row.qty), null, 3))}</td>
					<td>${process}</td>
					<td>${planned}</td>
					<td>${machine}</td>
					<td><span class="indicator-pill ${pill[status] || 'gray'}">${esc(status)}</span></td>
					<td class="so-lock">${locked
						? `<span class="indicator-pill red" title="${__('Locked')}">&#128274;</span>`
						: `<span class="so-muted" title="${__('Unlocked')}">&#8212;</span>`}</td>
					<td class="so-actions">${actions}</td>
				</tr>
			`));
		});
	}

	render_pager() {
		const m = this.meta || {};
		const start = cint(m.start);
		const shown = (this.rows || []).length;
		const total = cint(m.total);
		this.wrapper.find('.prod-count').text(
			total ? __('{0} to {1} of {2}', [start + 1, start + shown, total]) : '');
		this.wrapper.find('.prod-prev').prop('disabled', start <= 0);
		this.wrapper.find('.prod-next').prop('disabled', !cint(m.has_more));
	}

	bind_row_actions() {
		const me = this;
		this.wrapper.on('click', '.so-id:not(.so-parent)', function () {
			frappe.set_route('Form', 'Work Order', $(this).attr('data-name'));
		});
		this.wrapper.on('click', '.so-parent', function (e) {
			e.stopPropagation();
			frappe.set_route('production_order_entry', $(this).attr('data-parent'));
		});
		this.wrapper.on('click', '.so-assign', function () {
			me.assign_dialog($(this).attr('data-name'));
		});
		this.wrapper.on('click', '.so-split', function () {
			me.split_dialog($(this).attr('data-name'));
		});
		this.wrapper.on('click', '.so-print', function () {
			const name = $(this).attr('data-name');
			window.open(`/printview?doctype=Work%20Order&name=${encodeURIComponent(name)}`
				+ `&format=${encodeURIComponent('Sub PO Job Card')}&no_letterhead=0`, '_blank');
		});
	}

	// ------------------------------------------------------ Assign Process

	assign_dialog(name) {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.assign_process_context',
			args: { sub_order: name },
			freeze: true,
			callback(r) {
				const ctx = r.message;
				if (!ctx) return;
				if (cint(ctx.is_locked)) {
					frappe.msgprint({
						title: __('Sub Order Is Locked'),
						message: __('{0} is locked until {1} is sent to store.', [ctx.sub_order, ctx.parent]),
						indicator: 'orange',
					});
					return;
				}
				me.show_assign_dialog(ctx);
			},
		});
	}

	show_assign_dialog(ctx) {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Assign Process — {0}', [ctx.sub_order]),
			fields: [
				{ fieldtype: 'Data', fieldname: 'sub_order', label: __('Sub PO'), read_only: 1, default: ctx.sub_order },
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'Data', fieldname: 'item', label: __('Target Item'), read_only: 1, default: ctx.item },
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'Float', fieldname: 'qty', label: __('Qty (KG)'), read_only: 1, default: ctx.qty, precision: 3 },
				{ fieldtype: 'Section Break' },
				{
					fieldtype: 'Link', fieldname: 'process', label: __('Assigned Process'),
					options: 'Process Master', reqd: 1, default: ctx.assigned_process || ctx.default_process,
					// PR-03: only Active processes may be assigned.
					get_query() { return { filters: { is_active: 1 } }; },
					onchange() { me.on_process_change(d); },
				},
				{
					fieldtype: 'Link', fieldname: 'machine', label: __('Assigned Machine'),
					options: 'Machine', default: ctx.assigned_machine,
					description: __('Active machines whose type is linked to the process.'),
					get_query() {
						return {
							query: 'alpinos.production.sub_order.machine_query_for_process',
							filters: { process: d.get_value('process') || '' },
						};
					},
				},
				{
					fieldtype: 'Date', fieldname: 'planned_date', label: __('Planned Date'),
					default: ctx.planned_date,
					description: __('Today or later.'),
				},
			],
			primary_action_label: __('Assign'),
			primary_action(values) {
				frappe.call({
					method: 'alpinos.production.sub_order.assign_process',
					args: {
						sub_order: ctx.sub_order,
						process: values.process,
						machine: values.machine || null,
						planned_date: values.planned_date || null,
					},
					freeze: true,
					freeze_message: __('Assigning...'),
					callback(r) {
						if (!r.message) return;
						d.hide();
						frappe.show_alert({ message: __('Assigned to {0}', [r.message.process]), indicator: 'green' }, 5);
						me.refresh();
					},
				});
			},
		});
		d.show();
		me.on_process_change(d);
	}

	on_process_change(d) {
		// The machine is only mandatory when the process says a machine is needed, so the
		// dialog reads that off the process rather than asking for one every time.
		const process = d.get_value('process');
		const field = d.get_field('machine');
		if (!process) {
			field.df.reqd = 0;
			field.refresh();
			return;
		}
		frappe.db.get_value('Process Master', process, 'allow_machine_assignment').then((r) => {
			const needed = cint((r.message || {}).allow_machine_assignment);
			field.df.reqd = needed ? 1 : 0;
			field.df.description = needed
				? __('This process needs a machine before it can start.')
				: __('Optional for this process.');
			field.refresh();
		});
	}

	// ---------------------------------------------------------------- Split

	split_dialog(name) {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.split_context',
			args: { sub_order: name },
			freeze: true,
			callback(r) {
				const ctx = r.message;
				if (!ctx) return;
				if (!ctx.can_split) {
					frappe.msgprint({
						title: __('Cannot Split'),
						message: (ctx.blockers || []).map(frappe.utils.escape_html).join('<br>')
							|| __('You do not have permission to split a sub order.'),
						indicator: 'orange',
					});
					return;
				}
				me.show_split_dialog(ctx);
			},
		});
	}

	show_split_dialog(ctx) {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Split {0}', [ctx.sub_order]),
			fields: [
				{ fieldtype: 'Data', fieldname: 'sub_order', label: __('Current Sub PO'), read_only: 1, default: ctx.sub_order },
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'Float', fieldname: 'current_qty', label: __('Current Qty (KG)'), read_only: 1, default: ctx.qty, precision: 3 },
				{ fieldtype: 'Section Break' },
				{
					fieldtype: 'Float', fieldname: 'split_qty', label: __('Split Qty (KG)'),
					reqd: 1, precision: 3,
					description: __('More than 0 and less than {0}.', [ctx.qty]),
					onchange() {
						const left = flt(ctx.qty) - flt(d.get_value('split_qty'));
						d.set_value('remaining_qty', left > 0 ? left : 0);
					},
				},
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'Float', fieldname: 'remaining_qty', label: __('Remaining Qty (KG)'), read_only: 1, precision: 3, default: ctx.qty },
				{ fieldtype: 'Section Break' },
				{ fieldtype: 'Small Text', fieldname: 'reason', label: __('Reason'), description: __('Optional.') },
			],
			primary_action_label: __('Split'),
			primary_action(values) {
				frappe.call({
					method: 'alpinos.production.sub_order.split_sub_order_action',
					args: {
						sub_order: ctx.sub_order,
						split_qty: values.split_qty,
						reason: values.reason || null,
					},
					freeze: true,
					freeze_message: __('Splitting...'),
					callback(r) {
						if (!r.message) return;
						d.hide();
						frappe.show_alert({
							message: __('{0} created with {1} KG', [r.message.new_sub_order, r.message.split_qty]),
							indicator: 'green',
						}, 6);
						me.refresh();
					},
				});
			},
		});
		d.show();
	}

	// --------------------------------------------------------------- Export

	export_csv() {
		if (!this.rows.length) {
			frappe.msgprint({ message: __('There is nothing on this page to export.'),
				title: __('Nothing To Export'), indicator: 'orange' });
			return;
		}
		const columns = [
			['Sub PO', (r) => r.name],
			['Parent PO', (r) => r.custom_parent_production_order],
			['Batch Number', (r) => r.custom_batch_number],
			['Target Item', (r) => r.production_item],
			['Item Name', (r) => r.item_name],
			['Qty (KG)', (r) => flt(r.qty)],
			['Assigned Process', (r) => r.process_label || r.custom_assigned_process || 'Unassigned'],
			['Planned Date', (r) => r.custom_planned_date || ''],
			['Assigned Machine', (r) => r.custom_assigned_machine || '-'],
			['Execution Status', (r) => r.custom_execution_status],
			['Locked', (r) => (cint(r.custom_is_locked) ? 'Yes' : 'No')],
			['Split From', (r) => r.custom_split_from || ''],
		];
		// Quoted and doubled up, so an item name with a comma cannot shift every column
		// after it.
		const cell = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
		const lines = [columns.map((c) => cell(c[0])).join(',')];
		this.rows.forEach((row) => lines.push(columns.map((c) => cell(c[1](row))).join(',')));
		const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `sub-production-orders-${frappe.datetime.get_today()}.csv`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
		frappe.show_alert({ message: __('Exported {0} row(s)', [this.rows.length]), indicator: 'green' }, 5);
	}
};
