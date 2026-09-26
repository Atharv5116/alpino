/**
 * Filling Process Category — list screen (FRD 4.9 Phase 8, 8.2 and 8.5).
 *
 * This master is the trigger the whole filling handshake turns on: a Machine carries one
 * category, an FG item carries the categories it may run on, and 8.4 compares the two. So
 * the question this list has to answer is not "what categories exist" but "what depends on
 * each one" — which is why the Machines and SKUs counts are columns and not a detail you
 * have to open a record to find.
 *
 * 8.5 says a new filling process must need no code change. Nothing here names a category.
 */

frappe.pages['filling_category_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Filling Process Category'),
		single_column: true,
	});
	wrapper.filling_category_list = new FillingCategoryList(page);
};

frappe.pages['filling_category_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.filling_category_list) wrapper.filling_category_list.refresh();
};

var FillingCategoryList = class {
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
								<th>${__('Category')}</th>
								<th style="width:150px;" class="prod-num">${__('Machines')}</th>
								<th style="width:110px;" class="prod-num">${__('SKUs')}</th>
								<th>${__('Description')}</th>
								<th style="width:90px;">${__('Active')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">
						${__('No filling process category yet. Add one, then set it on a filling machine and on the SKUs it may run.')}
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
		const reload = frappe.utils.debounce(() => me.refresh(), 300);
		this._ctl('.filter-search', {
			fieldname: 'search', label: __('Search'), fieldtype: 'Data',
		}, '', function () { me.filters.search = this.get_value(); reload(); });
		this._ctl('.filter-active', {
			fieldname: 'is_active', label: __('Active'), fieldtype: 'Select',
			options: [
				{ label: __('All'), value: 'All' },
				{ label: __('Active'), value: '1' },
				{ label: __('Inactive'), value: '0' },
			],
		}, 'All', function () { me.filters.is_active = this.get_value(); reload(); });
	}

	make_actions() {
		if (frappe.model.can_create('Filling Process Category')) {
			this.page.set_primary_action(__('Add Category'), () => {
				frappe.set_route('filling_category_entry');
			}, 'add');
		}
		this.page.add_inner_button(__('Machines'), () => frappe.set_route('machine_list'));
		this.page.add_inner_button(__('Items'), () => frappe.set_route('item_master_list'));
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.filling.get_category_list',
			args: this.filters,
			callback(r) {
				me.rows = r.message || [];
				me.render_rows();
			},
		});
	}

	render_warning() {
		// A category nothing points at yet is the normal state of a brand new one, so this
		// is a note and not an alarm. It earns its place because the handshake in 8.4 fails
		// silently on a half-wired category: the machine matches nothing, or the SKU has no
		// line it may run on, and neither screen says which side is missing.
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const half = this.rows
			.filter((r) => cint(r.is_active) && (!cint(r.machine_count) || !cint(r.sku_count)))
			.map((r) => r.category_name || r.name);
		const $warn = this.wrapper.find('.prod-warn');
		if (!half.length) return $warn.hide().empty();
		const shown = half.slice(0, 6).map(esc).join(', ');
		const rest = half.length > 6 ? ` ${__('and {0} more', [half.length - 6])}` : '';
		$warn.html(`${__('Not yet wired to both a machine and an SKU, so nothing can be filled on them')}:
			<b>${shown}</b>${rest}.`).show();
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);
		this.render_warning();

		this.rows.forEach((row) => {
			const total = cint(row.machine_count);
			const active = cint(row.active_machine_count);
			// "2 (1 active)" rather than a bare count: a category whose machines are all
			// under maintenance can be planned against and then not run.
			let machines = '0';
			if (total) {
				machines = total === active
					? esc(total)
					: `${esc(total)} <span class="text-muted">(${esc(active)} ${__('active')})</span>`;
			}
			const skus = cint(row.sku_count);
			const $tr = $(`
				<tr>
					<td>${esc(row.category_name || row.name)}</td>
					<td class="prod-num">${machines}</td>
					<td class="prod-num">${skus
						? esc(skus)
						: `<span class="indicator-pill orange" title="${__('No item allows this category')}">0</span>`}</td>
					<td class="text-muted">${esc(row.description || '')}</td>
					<td>${cint(row.is_active)
						? `<span class="indicator-pill green">${__('Yes')}</span>`
						: `<span class="indicator-pill red">${__('No')}</span>`}</td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('filling_category_entry', row.name));
			$body.append($tr);
		});
	}
};
