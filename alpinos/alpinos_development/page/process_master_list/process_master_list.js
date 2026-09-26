/**
 * Process Master — list screen (Process Master 3.1).
 *
 * Columns, filters and the New button. Everything it writes goes through the standard
 * client API, so ProcessMaster.validate stays the only place the rules are enforced.
 */

frappe.pages['process_master_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Process Master'),
		single_column: true,
	});
	wrapper.process_list = new ProcessMasterList(page);
};

frappe.pages['process_master_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.process_list) wrapper.process_list.refresh();
};

var ProcessMasterList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.filters = { search: '', machine_type: '', is_active: '1' };
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
					.prod-list .prod-chip { display: inline-block; padding: 1px 8px; margin: 1px 2px 1px 0;
						border-radius: 10px; background: var(--bg-light-gray, #f0f1f2); font-size: 11px; }
				</style>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-machine-type"></div>
					<div class="filter-active"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:120px;">${__('Process Code')}</th>
								<th>${__('Process Name')}</th>
								<th style="width:90px;">${__('Sequence')}</th>
								<th style="width:260px;">${__('Machine Type')}</th>
								<th style="width:100px;">${__('QC Required')}</th>
								<th style="width:110px;">${__('Allow Inward')}</th>
								<th style="width:80px;">${__('Active')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No processes yet.')}</div>
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
			placeholder: __('Code or name'),
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		this._ctl('.filter-machine-type', {
			fieldname: 'machine_type', label: __('Machine Type'), fieldtype: 'Link',
			options: 'Machine Type',
		}, '', function () { me.filters.machine_type = this.get_value(); reload(); });

		this._ctl('.filter-active', {
			fieldname: 'is_active', label: __('Status'), fieldtype: 'Select',
			options: [
				{ label: __('Active'), value: '1' },
				{ label: __('Inactive'), value: '0' },
				{ label: __('All'), value: 'All' },
			],
		}, '1', function () { me.filters.is_active = this.get_value(); reload(); });
	}

	make_actions() {
		const me = this;
		this.page.set_primary_action(__('New Process'), () => {
			frappe.set_route('process_master_entry');
		}, 'add');
		this.page.add_inner_button(__('Machines'), () => frappe.set_route('machine_list'));
		this.page.add_inner_button(__('Machine Types'), () => frappe.set_route('machine_type_list'));
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.process_api.get_list',
			args: this.filters,
			callback(r) {
				me.rows = r.message || [];
				me.render_rows();
			},
		});
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const tick = (v) => (cint(v) ? __('Yes') : __('No'));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);

		this.rows.forEach((row) => {
			const chips = (row.machine_type_labels || [])
				.map((t) => `<span class="prod-chip">${esc(t)}</span>`)
				.join('') || `<span class="text-muted">—</span>`;
			const $tr = $(`
				<tr>
					<td>${esc(row.process_code)}</td>
					<td>${esc(row.process_name)}</td>
					<td>${esc(row.process_sequence)}</td>
					<td>${chips}</td>
					<td>${tick(row.qc_required)}</td>
					<td>${tick(row.allow_inward_entry)}</td>
					<td>${cint(row.is_active)
						? `<span class="indicator-pill green">${__('Yes')}</span>`
						: `<span class="indicator-pill red">${__('No')}</span>`}</td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('process_master_entry', row.name));
			$body.append($tr);
		});
	}
};
