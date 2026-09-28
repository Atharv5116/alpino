/**
 * Material Issues — list screen (Material Management).
 *
 * Stock Entries marked Material Issue: Main store to WIP, always against a Material Request.
 * + New starts from the MR picker; a submitted issue offers Create Return.
 */

frappe.pages['material_issue_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Material Issues'),
		single_column: true,
	});
	wrapper.material_issue_list = new MaterialEntryList(page, {
		method: 'alpinos.production.material_issue.get_mi_list',
		entry_page: 'material_issue_entry',
		link_label: __('Linked MR'),
		link_field: 'custom_material_request',
		link_filter: { fieldname: 'material_request', label: __('Material Request'), options: 'Material Request' },
		date_label: __('Issue Date'),
		by_label: __('Issued By'),
		empty: __('No Material Issues match these filters.'),
		row_action(row) {
			return cint(row.docstatus) === 1
				? { label: __('Create Return'), handler() {
					frappe.route_options = { material_issue: row.name };
					frappe.set_route('material_return_entry', 'new');
				} }
				: null;
		},
		nav: [[__('Material Requests'), 'material_request_list'], [__('Material Returns'), 'material_return_list']],
	});
};

frappe.pages['material_issue_list'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	if (wrapper.material_issue_list) wrapper.material_issue_list.refresh();
};

/**
 * Shared by the Material Issue and Material Return lists (the Return list page defines its
 * own copy under the same guard, so either page works when opened first).
 */
if (!window.MaterialEntryList) {
	window.MaterialEntryList = class {
		constructor(page, opts) {
			this.page = page;
			this.opts = opts;
			this.wrapper = $(page.main);
			this.rows = [];
			this.meta = {};
			this.filters = {
				search: '', status: '', sub_order: '', parent: '', fg_item: '',
				date_from: '', date_to: '', start: 0, page_length: 50,
			};
			this.filters[opts.link_filter.fieldname] = '';
			this.render_shell();
			this.make_filters();
			this.make_actions();
			this.bind_pager();
			this.bind_row_actions();
		}

		render_shell() {
			const o = this.opts;
			this.wrapper.html(`
				<div class="prod-list">
					<style>
						.prod-list .prod-filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
						.prod-list .prod-filters > div { min-width: 160px; }
						.prod-list table { width: 100%; }
						.prod-list tbody tr:hover { background: var(--bg-light-gray, #f4f5f6); }
						.prod-list .prod-empty { padding: 40px; text-align: center; color: var(--text-muted); }
						.prod-list .prod-pager { display: flex; align-items: center; justify-content: space-between;
							margin-top: 12px; gap: 12px; flex-wrap: wrap; }
						.prod-list .mm-id { cursor: pointer; font-weight: 600; }
						.prod-list .mm-id:hover { text-decoration: underline; }
						.prod-list .mm-actions { white-space: nowrap; }
						.prod-list .mm-actions .btn { margin-left: 4px; }
					</style>
					<div class="prod-filters">
						<div class="filter-search"></div>
						<div class="filter-status"></div>
						<div class="filter-link"></div>
						<div class="filter-sub"></div>
						<div class="filter-parent"></div>
						<div class="filter-fg"></div>
						<div class="filter-from"></div>
						<div class="filter-to"></div>
					</div>
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:140px;">${__('ID')}</th>
								<th style="width:140px;">${o.link_label}</th>
								<th style="width:120px;">${__('Sub PO')}</th>
								<th>${__('Target FG')}</th>
								<th style="width:110px;">${o.date_label}</th>
								<th style="width:150px;">${o.by_label}</th>
								<th style="width:100px;">${__('Status')}</th>
								<th style="width:170px;">${__('Actions')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${o.empty}</div>
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
			const reload = frappe.utils.debounce(() => { me.filters.start = 0; me.refresh(); }, 300);
			const set = (key) => function () { me.filters[key] = this.get_value(); reload(); };
			const lf = this.opts.link_filter;
			this._ctl('.filter-search', { fieldname: 'search', label: __('Search') }, '', set('search'));
			this._ctl('.filter-status', {
				fieldname: 'status', label: __('Status'), fieldtype: 'Select',
				options: [{ label: __('All'), value: '' }, 'Draft', 'Submitted', 'Cancelled'],
			}, '', set('status'));
			this._ctl('.filter-link', { fieldname: lf.fieldname, label: lf.label, fieldtype: 'Link', options: lf.options }, '', set(lf.fieldname));
			this._ctl('.filter-sub', { fieldname: 'sub_order', label: __('Sub PO'), fieldtype: 'Link', options: 'Work Order' }, '', set('sub_order'));
			this._ctl('.filter-parent', { fieldname: 'parent', label: __('Parent PO'), fieldtype: 'Link', options: 'Production Order' }, '', set('parent'));
			this._ctl('.filter-fg', { fieldname: 'fg_item', label: __('Target FG'), fieldtype: 'Link', options: 'Item' }, '', set('fg_item'));
			this._ctl('.filter-from', { fieldname: 'date_from', label: __('From'), fieldtype: 'Date' }, '', set('date_from'));
			this._ctl('.filter-to', { fieldname: 'date_to', label: __('To'), fieldtype: 'Date' }, '', set('date_to'));
		}

		make_actions() {
			const o = this.opts;
			this.page.set_primary_action(__('+ New'), () => frappe.set_route(o.entry_page, 'new'));
			(o.nav || []).forEach(([label, route]) => this.page.add_inner_button(label, () => frappe.set_route(route)));
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
			this._ctl('.filter-page-length', {
				fieldname: 'page_length', label: '', fieldtype: 'Select',
				options: [50, 100, 200].map((n) => ({ label: __('{0} per page', [n]), value: String(n) })),
			}, '50', function () {
				me.filters.page_length = cint(this.get_value()) || 50;
				me.filters.start = 0;
				me.refresh();
			});
		}

		refresh() {
			const me = this;
			frappe.call({
				method: this.opts.method,
				args: this.filters,
				callback(r) {
					const m = r.message || {};
					me.meta = m;
					me.rows = m.data || [];
					me.page.btn_primary.toggle(!!cint(m.can_create));
					me.render_rows();
					me.render_pager();
				},
			});
		}

		render_rows() {
			const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
			const o = this.opts;
			const $body = this.wrapper.find('tbody').empty();
			this.wrapper.find('.prod-empty').toggle(!this.rows.length);
			const pill = { 'Draft': 'gray', 'Submitted': 'green', 'Cancelled': 'red' };
			this.actions = {};
			this.rows.forEach((row, idx) => {
				const action = o.row_action ? o.row_action(row) : null;
				if (action) this.actions[idx] = action;
				$body.append(`
					<tr>
						<td><span class="mm-id" data-name="${esc(row.name)}">${esc(row.name)}</span></td>
						<td>${esc(row[o.link_field] || '')}</td>
						<td>${esc(row.custom_sub_production_order || '')}</td>
						<td>${esc(row.custom_target_fg_item || '')}</td>
						<td>${esc(frappe.datetime.str_to_user(row.posting_date))}</td>
						<td>${esc(row.by || '')}</td>
						<td><span class="indicator-pill ${pill[row.status] || 'gray'}">${esc(row.status)}</span></td>
						<td class="mm-actions">
							<button class="btn btn-xs btn-default mm-view" data-name="${esc(row.name)}">${__('View')}</button>
							${action ? `<button class="btn btn-xs btn-primary mm-act" data-idx="${idx}">${esc(action.label)}</button>` : ''}
						</td>
					</tr>
				`);
			});
		}

		render_pager() {
			const m = this.meta || {};
			const start = cint(m.start);
			const shown = (this.rows || []).length;
			const total = cint(m.total);
			this.wrapper.find('.prod-count').text(total ? __('{0} to {1} of {2}', [start + 1, start + shown, total]) : '');
			this.wrapper.find('.prod-prev').prop('disabled', start <= 0);
			this.wrapper.find('.prod-next').prop('disabled', !cint(m.has_more));
		}

		bind_row_actions() {
			const me = this;
			this.wrapper.on('click', '.mm-id, .mm-view', function () {
				frappe.set_route(me.opts.entry_page, $(this).attr('data-name'));
			});
			this.wrapper.on('click', '.mm-act', function () {
				const action = (me.actions || {})[cint($(this).attr('data-idx'))];
				if (action) action.handler();
			});
		}
	};
}
