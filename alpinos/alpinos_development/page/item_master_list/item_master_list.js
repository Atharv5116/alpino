/**
 * Item Master — list screen (Item Master 1.1).
 *
 * The Item doctype is ERPNext's own and already carries almost every field this master
 * needs; only Material Type and Material Category are ours. The list is scoped to the
 * production view of an item rather than trying to be a second Item list.
 */

frappe.pages['item_master_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Item Master'),
		single_column: true,
	});
	wrapper.item_list = new ItemMasterList(page);
};

frappe.pages['item_master_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.item_list) wrapper.item_list.refresh();
};

var ItemMasterList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.filters = { search: '', material_type: '', item_group: '', disabled: '0' };
		this.paging = { start: 0, page_length: 50, total: 0, has_more: 0 };
		this.sort = { field: 'item_code', dir: 'asc' };
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
					.prod-list th.sortable { cursor: pointer; }
					.prod-list th.sortable:hover { background: var(--bg-light-gray, #f0f1f2); }
					.prod-list th .sort-mark { color: var(--text-muted); font-size: 10px; }
					.prod-list .prod-chip { display: inline-block; padding: 1px 8px; border-radius: 10px;
						background: var(--bg-light-gray, #f0f1f2); font-size: 11px; }
				</style>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-material-type"></div>
					<div class="filter-item-group"></div>
					<div class="filter-disabled"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:150px;" class="sortable" data-sort="item_code">${__('SKU Code')}</th>
								<th class="sortable" data-sort="item_name">${__('Item Name')}</th>
								<th style="width:110px;">${__('Material Type')}</th>
								<th style="width:110px;">${__('Category')}</th>
								<th style="width:130px;" class="sortable" data-sort="item_group">${__('Item Group')}</th>
								<th style="width:110px;">${__('HSN Code')}</th>
								<th style="width:80px;">${__('GST %')}</th>
								<th style="width:75px;">${__('Stock UOM')}</th>
								<th style="width:65px;">${__('Batch')}</th>
								<th style="width:80px;">${__('Shelf Life')}</th>
								<th style="width:55px;">${__('QC')}</th>
								<th style="width:80px;">${__('Status')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No items match these filters.')}</div>
					<div class="prod-pager" style="display:flex;align-items:center;gap:12px;margin-top:10px;">
						<span class="prod-count text-muted"></span>
						<span style="flex:1;"></span>
						<button class="btn btn-sm btn-default btn-prev">${__('Previous')}</button>
						<button class="btn btn-sm btn-default btn-next">${__('Next')}</button>
						<div class="filter-page-length" style="min-width:110px;"></div>
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
		// Any filter change returns to the first page: keeping the old offset would show an
		// empty page when the new filter has fewer rows than the old start.
		const reload = frappe.utils.debounce(() => { me.paging.start = 0; me.refresh(); }, 250);

		this._ctl('.filter-search', {
			fieldname: 'search', label: __('Search'), fieldtype: 'Data',
			placeholder: __('SKU code or name'),
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		this._ctl('.filter-material-type', {
			fieldname: 'material_type', label: __('Material Type'), fieldtype: 'Select',
			options: ['', 'RM', 'PM', 'Additive', 'FG'],
		}, '', function () { me.filters.material_type = this.get_value(); reload(); });

		this._ctl('.filter-item-group', {
			fieldname: 'item_group', label: __('Item Group'), fieldtype: 'Link',
			options: 'Item Group',
		}, '', function () { me.filters.item_group = this.get_value(); reload(); });

		this._ctl('.filter-disabled', {
			fieldname: 'disabled', label: __('Status'), fieldtype: 'Select',
			options: [
				{ label: __('Enabled'), value: '0' },
				{ label: __('Disabled'), value: '1' },
				{ label: __('All'), value: 'All' },
			],
		}, '0', function () { me.filters.disabled = this.get_value(); reload(); });

		this._ctl('.filter-page-length', {
			fieldname: 'page_length', label: '', fieldtype: 'Select',
			options: ['50', '100', '200'],
		}, '50', function () {
			me.paging.page_length = cint(this.get_value()) || 50;
			me.paging.start = 0;
			me.refresh();
		});

		this.wrapper.find('.btn-prev').on('click', () => {
			me.paging.start = Math.max(me.paging.start - me.paging.page_length, 0);
			me.refresh();
		});
		this.wrapper.find('.btn-next').on('click', () => {
			if (!me.paging.has_more) return;
			me.paging.start += me.paging.page_length;
			me.refresh();
		});
		this.wrapper.find('thead').on('click', 'th.sortable', function () {
			const field = $(this).data('sort');
			if (!field) return;
			me.sort.dir = me.sort.field === field && me.sort.dir === 'asc' ? 'desc' : 'asc';
			me.sort.field = field;
			me.paging.start = 0;
			me.refresh();
		});
	}

	make_actions() {
		this.page.set_primary_action(__('New Item'), () => {
			frappe.set_route('item_master_entry');
		}, 'add');
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.item_api.get_list',
			args: Object.assign({}, this.filters, {
				start: this.paging.start,
				page_length: this.paging.page_length,
				sort_field: this.sort.field,
				sort_dir: this.sort.dir,
			}),
			callback(r) {
				const res = r.message || {};
				me.rows = res.data || [];
				me.paging.total = cint(res.total);
				me.paging.has_more = cint(res.has_more);
				me.paging.start = cint(res.start);
				me.render_rows();
				me.render_pager();
			},
		});
	}

	render_pager() {
		const p = this.paging;
		const first = p.total ? p.start + 1 : 0;
		const last = p.start + this.rows.length;
		this.wrapper.find('.prod-count').text(
			p.total ? __('Showing {0}-{1} of {2}', [first, last, p.total]) : __('No items')
		);
		this.wrapper.find('.btn-prev').prop('disabled', p.start <= 0);
		this.wrapper.find('.btn-next').prop('disabled', !p.has_more);

		this.wrapper.find('thead th.sortable').each((_, th) => {
			const $th = $(th);
			$th.find('.sort-mark').remove();
			if ($th.data('sort') === this.sort.field) {
				$th.append(` <span class="sort-mark">${this.sort.dir === 'asc' ? '&#9650;' : '&#9660;'}</span>`);
			}
		});
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const tick = (v) => (cint(v) ? __('Yes') : '<span class="text-muted">—</span>');
		const $body = this.wrapper.find('tbody').empty();
		this.wrapper.find('.prod-empty').toggle(!this.rows.length);

		this.rows.forEach((row) => {
			const shelf = cint(row.shelf_life_in_days)
				? `${esc(row.shelf_life_in_days)} ${__('days')}`
				: '<span class="text-muted">—</span>';
			const type = row.custom_material_type
				? `<span class="prod-chip">${esc(row.custom_material_type)}</span>`
				: '<span class="text-muted">—</span>';
			const $tr = $(`
				<tr>
					<td>${esc(row.item_code)}</td>
					<td>${esc(row.item_name)}</td>
					<td>${type}</td>
					<td>${row.custom_material_category ? esc(row.custom_material_category) : '<span class="text-muted">—</span>'}</td>
					<td>${esc(row.item_group)}</td>
					<td>${row.custom_hsn_code ? esc(row.custom_hsn_code) : '<span class="text-muted">—</span>'}</td>
					<td>${flt(row.custom_gst_percent) ? esc(row.custom_gst_percent) + '%' : '<span class="text-muted">—</span>'}</td>
					<td>${esc(row.stock_uom)}</td>
					<td>${tick(row.has_batch_no)}</td>
					<td>${shelf}</td>
					<td>${tick(row.inspection_required_before_purchase)}</td>
					<td>${cint(row.disabled)
						? `<span class="indicator-pill red">${__('Disabled')}</span>`
						: `<span class="indicator-pill green">${__('Enabled')}</span>`}</td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('item_master_entry', row.name));
			$body.append($tr);
		});
	}
};
