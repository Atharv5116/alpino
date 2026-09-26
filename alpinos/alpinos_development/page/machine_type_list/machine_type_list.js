/**
 * Machine Type Master — list screen (BRD 2.1).
 *
 * The machine and process counts are not decoration: a type is the vocabulary every
 * other screen picks from, so the one question asked of this list is "what still depends
 * on this?" — before anyone renames or retires a category.
 *
 * Add / Edit appear only for a user who actually holds the permission (BRD 2.1.1: only
 * Backend Admin or Super Admin may manage types). The server refuses either way; hiding
 * the button just stops offering an action that will fail.
 */

frappe.pages['machine_type_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Machine Type Master'),
		single_column: true,
	});
	wrapper.machine_type_list = new MachineTypeList(page);
};

frappe.pages['machine_type_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.machine_type_list) wrapper.machine_type_list.refresh();
};

var MachineTypeList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.filters = { search: '', is_active: 'All' };
		this.render_shell();
		this.make_filters();
		this.make_actions();
		this.refresh();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="prod-list">
				<style>
					.prod-list .prod-filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
					.prod-list .prod-filters > div { min-width: 190px; }
					.prod-list table { width: 100%; }
					.prod-list tbody tr { cursor: pointer; }
					.prod-list tbody tr:hover { background: var(--bg-light-gray, #f4f5f6); }
					.prod-list .prod-empty { padding: 40px; text-align: center; color: var(--text-muted); }
					.prod-list .prod-num { text-align: right; }
					.prod-list .prod-warn { display: none; margin-bottom: 14px; padding: 8px 12px;
						border: 1px solid var(--yellow-300, #f5e2a3); border-radius: 6px;
						background: var(--yellow-50, #fffbf0); font-size: 13px; }
				</style>
				<div class="prod-warn"></div>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-active"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:120px;">${__('Type ID')}</th>
								<th>${__('Machine Type Name')}</th>
								<th style="width:150px;" class="prod-num">${__('Machines')}</th>
								<th style="width:110px;" class="prod-num">${__('Processes')}</th>
								<th style="width:90px;">${__('Active')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No machine types yet.')}</div>
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

	make_filters() {
		const me = this;
		const reload = frappe.utils.debounce(() => me.refresh(), 250);

		this._ctl('.filter-search', {
			fieldname: 'search', label: __('Search'), fieldtype: 'Data',
			placeholder: __('ID or name'),
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		this._ctl('.filter-active', {
			fieldname: 'is_active', label: __('Status'), fieldtype: 'Select',
			options: [
				{ label: __('All'), value: 'All' },
				{ label: __('Active'), value: '1' },
				{ label: __('Inactive'), value: '0' },
			],
		}, 'All', function () { me.filters.is_active = this.get_value(); reload(); });
	}

	make_actions() {
		if (frappe.model.can_create('Machine Type')) {
			this.page.set_primary_action(__('Add Machine Type'), () => {
				frappe.set_route('machine_type_entry');
			}, 'add');
		}
		this.page.add_inner_button(__('Machines'), () => frappe.set_route('machine_list'));
		this.page.add_inner_button(__('Processes'), () => frappe.set_route('process_master_list'));
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.machine_api.get_machine_type_list',
			args: this.filters,
			callback(r) {
				me.rows = r.message || [];
				me.render_rows();
			},
		});
	}

	render_warning() {
		// Counted off the rows already fetched, so the banner can never disagree with the
		// column beside it. It follows the filter on purpose: a filtered list is the
		// question the user is actually asking.
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const orphans = this.rows
			.filter((r) => cint(r.is_active) && !cint(r.process_count))
			.map((r) => r.machine_type_name || r.name);
		const $warn = this.wrapper.find('.prod-warn');
		if (!orphans.length) return $warn.hide().empty();
		const shown = orphans.slice(0, 6).map(esc).join(', ');
		const rest = orphans.length > 6 ? ` ${__('and {0} more', [orphans.length - 6])}` : '';
		$warn.html(`${__('Not linked to any process, so nothing can be scheduled on them')}:
			<b>${shown}</b>${rest}.`).show();
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);
		this.render_warning();

		this.rows.forEach((row) => {
			// PR-09 -- an Active type that no process maps to can be chosen for a machine
			// and then never scheduled, so the row says so rather than printing a quiet 0.
			const orphan = cint(row.is_active) && !cint(row.process_count);
			const total = cint(row.machine_count);
			const active = cint(row.active_machine_count);
			// "2 (1 active)" rather than a bare count: a type whose machines are all
			// under maintenance feeds no production, and the bare number hides that.
			// 0, not "None": a count of nothing is still a number, and "None" sorts and
			// reads like missing data rather than like zero.
			let machines = '0';
			if (total) {
				machines = total === active
					? esc(total)
					: `${esc(total)} <span class="text-muted">(${esc(active)} ${__('active')})</span>`;
			}
			const $tr = $(`
				<tr>
					<td>${esc(row.name)}</td>
					<td>${esc(row.machine_type_name)}</td>
					<td class="prod-num">${machines}</td>
					<td class="prod-num">${orphan
						? `<span class="indicator-pill orange" title="${__('No process uses this type')}">0</span>`
						: esc(cint(row.process_count))}</td>
					<td>${cint(row.is_active)
						? `<span class="indicator-pill green">${__('Yes')}</span>`
						: `<span class="indicator-pill red">${__('No')}</span>`}</td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('machine_type_entry', row.name));
			$body.append($tr);
		});
	}
};
