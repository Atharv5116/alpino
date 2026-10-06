/**
 * Sub Production Order — read-only view (/app/sub_order_view/<Sub PO>).
 *
 * Nothing on this screen is edited in place. Each action button calls the server function
 * that already owns that rule (Assign Process, Split, Generate MR), and the buttons are
 * only drawn when the server says the action is allowed -- the server still enforces it.
 */

frappe.pages['sub_order_view'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Sub Production Order'),
		single_column: true,
	});
	wrapper.sub_order_view = new SubOrderView(page);
};

frappe.pages['sub_order_view'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb
		&& alpinos_production_breadcrumb(__('Sub Production Orders'), '/app/sub_order_list');
	if (wrapper.sub_order_view) wrapper.sub_order_view.handle_route();
};

var SubOrderView = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.name = null;
		this.data = null;
		this.render_shell();
		this.bind_links();
		this.handle_route();
	}

	esc(v) {
		return frappe.utils.escape_html(v == null ? '' : String(v));
	}

	dash() {
		return '<span class="sov-muted">&mdash;</span>';
	}

	render_shell() {
		this.wrapper.html(`
			<div class="sub-order-view">
				<style>
					.sub-order-view .sov-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e2e2);
						border-radius: 8px; padding: 16px 18px; margin-bottom: 16px; }
					.sub-order-view .sov-card > h5 { margin: 0 0 14px; font-size: 13px; text-transform: uppercase;
						letter-spacing: .4px; color: var(--text-muted); }
					.sub-order-view .sov-actionbar { display: flex; justify-content: flex-end; align-items: center;
						flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
					.sub-order-view .sov-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
						gap: 12px 18px; }
					.sub-order-view .sov-lbl { font-size: 11.5px; color: var(--text-muted); margin-bottom: 2px; }
					.sub-order-view .sov-val { font-size: 13px; font-weight: 500; word-break: break-word; }
					.sub-order-view .sov-muted { color: var(--text-muted); }
					.sub-order-view .sov-link { cursor: pointer; color: var(--text-color); font-weight: 600; }
					.sub-order-view .sov-link:hover { text-decoration: underline; }
					.sub-order-view .sov-locks { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
					.sub-order-view table.sov-table { width: 100%; }
					.sub-order-view table.sov-table th, .sub-order-view table.sov-table td { font-size: 12.5px; vertical-align: middle; }
					.sub-order-view .sov-num { text-align: right; white-space: nowrap; }
					.sub-order-view .sov-docs { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
					.sub-order-view .sov-docs h6 { font-size: 12px; margin: 0 0 8px; font-weight: 600; }
					.sub-order-view .sov-empty { padding: 40px; text-align: center; color: var(--text-muted); }
					.sub-order-view .sov-table-wrap { overflow-x: auto; }
				</style>
				<div class="sov-actionbar"></div>
				<div class="sov-body"></div>
			</div>
		`);
	}

	handle_route() {
		const name = (frappe.get_route() || [])[1] || '';
		if (!name) {
			this.name = null;
			this.wrapper.find('.sov-actionbar').empty();
			this.wrapper.find('.sov-body').html(
				`<div class="sov-empty">${__('No sub order selected.')}</div>`);
			return;
		}
		this.name = name;
		this.refresh();
	}

	refresh() {
		const me = this;
		if (!this.name) return;
		frappe.call({
			method: 'alpinos.production.sub_order_view.get_sub_order_view',
			args: { sub_order: this.name },
			freeze: true,
			callback(r) {
				if (!r.message) return;
				me.data = r.message;
				me.page.set_title(__('Sub Production Order {0}', [r.message.name]));
				me.render();
			},
			error() {
				me.wrapper.find('.sov-actionbar').empty();
				me.wrapper.find('.sov-body').html(
					`<div class="sov-empty">${__('This sub order could not be loaded.')}</div>`);
			},
		});
	}

	// --------------------------------------------------------------- render

	field(label, html) {
		return `<div><div class="sov-lbl">${this.esc(label)}</div><div class="sov-val">${html}</div></div>`;
	}

	text(v) {
		return v || v === 0 ? this.esc(v) : this.dash();
	}

	sub_link(name) {
		return `<span class="sov-link sov-sub" data-name="${this.esc(name)}">${this.esc(name)}</span>`;
	}

	render() {
		const d = this.data;
		const pill = {
			'Unassigned': 'gray', 'Assigned': 'blue', 'In Progress': 'orange', 'Completed': 'green',
			'Pending Store Issue': 'yellow', 'Ready to Run': 'purple',
		};
		const docPill = { 0: 'red', 1: 'blue', 2: 'gray' };
		const status = d.execution_status || 'Unassigned';
		const locks = [];
		if (cint(d.is_locked)) {
			locks.push(`<span class="indicator-pill red">&#128274; ${__('Locked until Sent to Store')}</span>`);
		}
		if (cint(d.plan_locked)) {
			locks.push(`<span class="indicator-pill orange">&#128274; ${__('Plan locked (MR generated)')}</span>`);
		}

		const header = `
			<div class="sov-card">
				<h5>${__('Sub Order')}</h5>
				<div class="sov-grid">
					${this.field(__('Sub PO ID'), `<b>${this.esc(d.name)}</b>`)}
					${this.field(__('Parent PO'), `<span class="sov-link sov-parent" data-name="${this.esc(d.parent)}">${this.esc(d.parent)}</span>`
						+ (d.parent_status ? ` <span class="sov-muted">(${this.esc(d.parent_status)})</span>` : ''))}
					${this.field(__('FG Item'), this.text(d.production_item))}
					${this.field(__('FG Item Name'), this.text(d.item_name))}
					${this.field(__('Qty (KG)'), this.esc(format_number(flt(d.qty), null, 3)))}
					${this.field(__('UOM'), this.text(d.uom))}
					${this.field(__('Batch Number'), this.text(d.batch_number))}
					${this.field(__('Production Type'), this.text(d.production_type))}
					${this.field(__('Client'), this.text(d.client_name))}
					${this.field(__('Execution Status'), `<span class="indicator-pill ${pill[status] || 'gray'}">${this.esc(status)}</span>`)}
					${this.field(__('Split From'), d.split_from ? this.sub_link(d.split_from) : this.dash())}
					${this.field(__('Document Status'), `<span class="indicator-pill ${docPill[cint(d.docstatus)] || 'gray'}">${this.esc(__(d.docstatus_label || ''))}</span>`
						+ (d.wo_status && cint(d.docstatus) === 1 ? ` <span class="sov-muted">${this.esc(d.wo_status)}</span>` : ''))}
				</div>
				${locks.length ? `<div class="sov-locks">${locks.join('')}</div>` : ''}
			</div>`;

		const run = d.machine_run;
		let runHtml = this.dash();
		if (run) {
			runHtml = `${this.esc(run.name)}${run.status ? ` <span class="sov-muted">(${this.esc(run.status)})</span>` : ''}`;
			if ((run.others || []).length) {
				runHtml += `<div class="sov-muted" style="font-weight:400;margin-top:2px;">${__('With')}: `
					+ run.others.map((n) => this.sub_link(n)).join(', ') + '</div>';
			}
		}
		const planning = `
			<div class="sov-card">
				<h5>${__('Planning')}</h5>
				<div class="sov-grid">
					${this.field(__('Assigned Process'), d.process ? this.esc(d.process_label || d.process) : `<span class="sov-muted">${__('Unassigned')}</span>`)}
					${this.field(__('Machine'), d.machine ? this.esc(d.machine_label || d.machine) : this.dash())}
					${this.field(__('Planned Date'), d.planned_date ? this.esc(frappe.datetime.str_to_user(d.planned_date)) : this.dash())}
					${this.field(__('Machine Run'), runHtml)}
				</div>
			</div>`;

		const num = (v) => this.esc(format_number(flt(v), null, 3));
		const rows = (d.materials || []).map((m) => `
			<tr>
				<td>${this.text(m.material_type)}</td>
				<td>${this.esc(m.item_code)}</td>
				<td>${this.text(m.item_name)}</td>
				<td>${this.text(m.uom)}</td>
				<td class="sov-num">${num(m.required_qty)}</td>
				<td class="sov-num">${num(m.issued_qty)}</td>
				<td class="sov-num">${num(m.returned_qty)}</td>
				<td class="sov-num">${flt(m.pending_qty) > 0 ? `<b>${num(m.pending_qty)}</b>` : num(m.pending_qty)}</td>
			</tr>`).join('');
		const materials = `
			<div class="sov-card">
				<h5>${__('Materials')}</h5>
				<div class="sov-table-wrap">
					<table class="table table-bordered table-condensed sov-table">
						<thead><tr>
							<th>${__('Material Type')}</th><th>${__('Item')}</th><th>${__('Item Name')}</th>
							<th>${__('UOM')}</th><th class="sov-num">${__('Required')}</th>
							<th class="sov-num">${__('Issued')}</th><th class="sov-num">${__('Returned')}</th>
							<th class="sov-num">${__('Pending')}</th>
						</tr></thead>
						<tbody>${rows || `<tr><td colspan="8" class="sov-muted text-center">${__('No materials.')}</td></tr>`}</tbody>
					</table>
				</div>
				<div class="sov-muted" style="font-size:12px;">${__('Issued is net of returns, from submitted Material Issues and Material Returns.')}</div>
			</div>`;

		const date = (v) => (v ? this.esc(frappe.datetime.str_to_user(v)) : '');
		const docTable = (title, list, page, cols) => {
			const body = (list || []).map((r) => `
				<tr>
					<td><span class="sov-link sov-doc" data-page="${page}" data-name="${this.esc(r.name)}">${this.esc(r.name)}</span></td>
					${cols.map((c) => `<td>${c(r)}</td>`).join('')}
				</tr>`).join('');
			return `<div><h6>${this.esc(title)} (${(list || []).length})</h6>
				${body ? `<table class="table table-bordered table-condensed sov-table"><tbody>${body}</tbody></table>`
					: `<div class="sov-muted">${__('None')}</div>`}</div>`;
		};
		const children = (d.split_children || []).map((c) => `
			<tr>
				<td>${this.sub_link(c.name)}</td>
				<td class="sov-num">${num(c.qty)}</td>
				<td>${this.esc(c.custom_execution_status || '')}</td>
			</tr>`).join('');
		const docs = `
			<div class="sov-card">
				<h5>${__('Linked Documents')}</h5>
				<div class="sov-docs">
					${docTable(__('Material Requests'), d.material_requests, 'material_request_entry',
						[(r) => this.esc(r.status), (r) => date(r.transaction_date)])}
					${docTable(__('Material Issues'), d.material_issues, 'material_issue_entry',
						[(r) => this.esc(r.status), (r) => date(r.posting_date)])}
					${docTable(__('Material Returns'), d.material_returns, 'material_return_entry',
						[(r) => this.esc(r.status), (r) => date(r.posting_date)])}
					<div><h6>${__('Split Into')} (${(d.split_children || []).length})</h6>
						${children ? `<table class="table table-bordered table-condensed sov-table"><tbody>${children}</tbody></table>`
							: `<div class="sov-muted">${__('None')}</div>`}</div>
				</div>
			</div>`;

		this.wrapper.find('.sov-body').html(header + planning + materials + docs);
		this.make_actions();
	}

	bind_links() {
		this.wrapper.on('click', '.sov-parent', function () {
			frappe.set_route('production_order_entry', $(this).attr('data-name'));
		});
		this.wrapper.on('click', '.sov-sub', function () {
			frappe.set_route('sub_order_view', $(this).attr('data-name'));
		});
		this.wrapper.on('click', '.sov-doc', function () {
			frappe.set_route($(this).attr('data-page'), $(this).attr('data-name'));
		});
	}

	// -------------------------------------------------------------- actions

	make_actions() {
		const me = this;
		const d = this.data;
		const $bar = this.wrapper.find('.sov-actionbar').empty();
		const btn = (label, cls, handler) => {
			const $b = $(`<button class="btn btn-sm ${cls}">${frappe.utils.escape_html(label)}</button>`);
			$b.on('click', handler);
			$bar.append($b);
			return $b;
		};
		if (cint(d.can_assign)) btn(__('Assign Process'), 'btn-primary', () => me.assign_dialog());
		if (cint(d.can_split)) btn(__('Split'), 'btn-default', () => me.split_dialog());
		if (cint(d.can_generate_mr)) btn(__('Generate MR'), 'btn-primary', () => me.generate_mr());
		btn(__('Print Job Card'), 'btn-default', () => {
			window.open(`/printview?doctype=Work%20Order&name=${encodeURIComponent(d.name)}`
				+ `&format=${encodeURIComponent('Sub PO Job Card')}&no_letterhead=0`, '_blank');
		});
		btn(__('Open Planning Board'), 'btn-default', () => frappe.set_route('store_planning_board'));
		btn(__('Shop Floor'), 'btn-default', () => {
			frappe.route_options = { sub_order: d.name };
			frappe.set_route('production_floor');
		});
		if (cint(d.can_open_form)) {
			btn(__('Open Work Order form'), 'btn-default', () => frappe.set_route('Form', 'Work Order', d.name));
		}
		btn(__('Back to List'), 'btn-default', () => frappe.set_route('sub_order_list'));
	}

	generate_mr() {
		const me = this;
		frappe.confirm(
			__('Generate the Material Request for {0}? This submits the sub order and locks its plan.', [this.data.name]),
			() => {
				frappe.call({
					method: 'alpinos.production.material_request.generate_mr',
					args: { sub_order: me.data.name },
					freeze: true,
					freeze_message: __('Generating...'),
					callback(r) {
						if (!r.message) return;
						frappe.show_alert({ message: __('Material Request {0} created', [r.message.material_request]), indicator: 'green' }, 6);
						me.refresh();
					},
				});
			}
		);
	}

	// ------------------------------------------------- Assign Process (as on the list)

	assign_dialog() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.assign_process_context',
			args: { sub_order: this.data.name },
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
					default: ctx.planned_date, description: __('Today or later.'),
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

	// ------------------------------------------------------- Split (as on the list)

	split_dialog() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.split_context',
			args: { sub_order: this.data.name },
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
					args: { sub_order: ctx.sub_order, split_qty: values.split_qty, reason: values.reason || null },
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
};
