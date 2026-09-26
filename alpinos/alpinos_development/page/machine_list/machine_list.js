/**
 * Machine Master — list screen (BRD 2.2).
 *
 * The five columns and the two filters the BRD names, and nothing else. Built on the
 * same shell as the Process Master list so the Production screens read as one module.
 */

frappe.pages['machine_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Machine Master'),
		single_column: true,
	});
	wrapper.machine_list = new MachineList(page);
};

frappe.pages['machine_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.machine_list) wrapper.machine_list.refresh();
};

var MachineList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.filters = { search: '', machine_type: '', status: 'All', filling_category: '', start: 0, page_length: 50 };
		this.render_shell();
		this.make_filters();
		this.make_actions();
		this.bind_pager();
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
					.prod-list .prod-pager { display: flex; align-items: center; justify-content: space-between;
						margin-top: 12px; gap: 12px; flex-wrap: wrap; }
				</style>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-machine-type"></div>
					<div class="filter-status"></div>
					<div class="filter-filling-category"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:120px;">${__('Machine ID')}</th>
								<th>${__('Machine Name')}</th>
								<th style="width:240px;">${__('Machine Type')}</th>
								<th style="width:160px;" class="prod-num">${__('Max Capacity')}</th>
								<th style="width:170px;">${__('Filling Category')}</th>
								<th style="width:150px;">${__('Status')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No machines yet.')}</div>
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

	make_filters() {
		const me = this;
		const reload = frappe.utils.debounce(() => me.refresh(), 250);

		this._ctl('.filter-search', {
			fieldname: 'search', label: __('Search'), fieldtype: 'Data',
			placeholder: __('ID or name'),
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		// BRD 2.2.1 filter 1.
		this._ctl('.filter-machine-type', {
			fieldname: 'machine_type', label: __('Machine Type'), fieldtype: 'Link',
			options: 'Machine Type',
		}, '', function () { me.filters.machine_type = this.get_value(); reload(); });

		// BRD 2.2.1 filter 2. Defaults to All rather than Active: this is the master
		// list, and a machine under maintenance is exactly what someone comes here to
		// find. The Active-only rule belongs on the screens that ASSIGN a machine.
		this._ctl('.filter-status', {
			fieldname: 'status', label: __('Current Status'), fieldtype: 'Select',
			options: [
				{ label: __('All'), value: 'All' },
				{ label: __('Active'), value: 'Active' },
				{ label: __('Under Maintenance'), value: 'Under Maintenance' },
				{ label: __('Inactive'), value: 'Inactive' },
			],
		}, 'All', function () { me.filters.status = this.get_value(); reload(); });

		this._ctl('.filter-filling-category', {
			fieldname: 'filling_category', label: __('Filling Category'),
			fieldtype: 'Link', options: 'Filling Process Category',
		}, '', function () { me.filters.filling_category = this.get_value(); reload(); });
	}

	apply_create_permission(can_create) {
		// Hidden rather than never built: the answer arrives with the first list call, which
		// lands after make_actions() has already run.
		const $btn = this.page.btn_primary;
		if ($btn && $btn.length) $btn.toggle(!!can_create);
	}

	make_actions() {
		// BRD 2.2.2: Add Machine and Edit Machine. Edit is the row click.
		this.page.set_primary_action(__('Add Machine'), () => {
			frappe.set_route('machine_entry');
		}, 'add');
		// Hidden until the server says otherwise, so a user who cannot create never sees it
		// flash up and then disappear.
		this.apply_create_permission(false);
		this.page.add_inner_button(__('Machine Types'), () => frappe.set_route('machine_type_list'));
		this.page.add_inner_button(__('Processes'), () => frappe.set_route('process_master_list'));
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.machine_api.get_machine_list',
			args: this.filters,
			callback(r) {
				const m = r.message || {};
				me.meta = m;
				me.rows = m.data || [];
				me.sync_page_lengths(m.page_lengths);
				me.render_rows();
				me.render_pager();
				// BRD 2.2.2 gives Add Machine to whoever may create one. The server says
				// who that is, so the button is not offered to a user whose save it would
				// refuse.
				me.apply_create_permission(cint(m.can_create));
			},
		});
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
		// Only rewritten when it actually differs: setting options re-renders the control,
		// which fires change, which reloads the list -- an endless round trip otherwise.
		if (JSON.stringify(this.page_length_control.df.options) === JSON.stringify(wanted)) return;
		this.page_length_control.df.options = wanted;
		this.page_length_control.refresh();
		this.page_length_control.set_value(String(this.filters.page_length));
	}

	render_pager() {
		const m = this.meta || {};
		const start = cint(m.start);
		const shown = (this.rows || []).length;
		const total = cint(m.total);
		const $count = this.wrapper.find('.prod-count');
		$count.text(total ? __('{0} to {1} of {2}', [start + 1, start + shown, total]) : '');
		this.wrapper.find('.prod-prev').prop('disabled', start <= 0);
		this.wrapper.find('.prod-next').prop('disabled', !cint(m.has_more));
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);

		// The colour says at a glance whether the machine can take work: green only for
		// Active, because only Active may be assigned (BRD 4.2 rules 2 and 3).
		const pill = {
			'Active': 'green',
			'Under Maintenance': 'orange',
			'Inactive': 'red',
		};

		this.rows.forEach((row) => {
			const cap = row.max_capacity
				? esc(alpinos_format_capacity(row.max_capacity, row.capacity_uom))
				: '<span class="text-muted">—</span>';
			const $tr = $(`
				<tr>
					<td>${esc(row.name)}</td>
					<td>${esc(row.machine_name)}</td>
					<td>${esc(row.machine_type_label || '')}</td>
					<td class="prod-num">${cap}</td>
					<td>${row.filling_process_category
						? esc(row.filling_process_category)
						: '<span class="text-muted">&mdash;</span>'}</td>
					<td><span class="indicator-pill ${pill[row.status] || 'gray'}">${esc(row.status)}</span></td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('machine_entry', row.name));
			$body.append($tr);
		});
	}
};
