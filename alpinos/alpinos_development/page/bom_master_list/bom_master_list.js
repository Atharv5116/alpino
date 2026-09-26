/**
 * BOM Master — list screen.
 *
 * Several BOMs may share one finished good, so the variation name and the Default tick
 * are the two columns that actually tell them apart; both are shown prominently.
 */

frappe.pages['bom_master_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('BOM Master'),
		single_column: true,
	});
	wrapper.bom_list = new BomMasterList(page);
};

frappe.pages['bom_master_list'].on_page_show = function (wrapper) {
	alpinos_production_breadcrumb();
	if (wrapper.bom_list) wrapper.bom_list.refresh();
};

var BomMasterList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.rows = [];
		this.filters = { search: '', fg_item: '', is_active: '1', start: 0, page_length: 50 };
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
					.prod-list .prod-pager { display: flex; align-items: center; justify-content: space-between;
						margin-top: 12px; gap: 12px; flex-wrap: wrap; }
				</style>
				<div class="prod-filters">
					<div class="filter-search"></div>
					<div class="filter-fg-item"></div>
					<div class="filter-active"></div>
				</div>
				<div class="prod-table-wrap">
					<table class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th style="width:180px;">${__('BOM ID')}</th>
								<th style="width:180px;">${__('FG Item')}</th>
								<th>${__('BOM Variation Name')}</th>
								<th style="width:90px;">${__('Materials')}</th>
								<th style="width:90px;">${__('Batch Size')}</th>
								<th style="width:80px;">${__('Default')}</th>
								<th style="width:80px;">${__('Active')}</th>
								<th style="width:90px;">${__('Status')}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
					<div class="prod-empty" style="display:none;">${__('No BOMs yet.')}</div>
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
			placeholder: __('BOM, item or variation'),
		}, '', function () { me.filters.search = this.get_value(); reload(); });

		this._ctl('.filter-fg-item', {
			fieldname: 'fg_item', label: __('FG Item'), fieldtype: 'Link', options: 'Item',
		}, '', function () { me.filters.fg_item = this.get_value(); reload(); });

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
		this.page.set_primary_action(__('New BOM'), () => {
			frappe.set_route('bom_master_entry');
		}, 'add');
	}

	refresh() {
		const me = this;
		frappe.call({
			method: 'alpinos.production.bom_api.get_list',
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

		this.rows.forEach((row) => {
			const status = cint(row.docstatus) === 1
				? `<span class="indicator-pill green">${__('Submitted')}</span>`
				: `<span class="indicator-pill orange">${__('Draft')}</span>`;
			const $tr = $(`
				<tr>
					<td>${esc(row.name)}</td>
					<td>${esc(row.item)}</td>
					<td>${row.custom_bom_variation_name
						? esc(row.custom_bom_variation_name)
						: '<span class="text-muted">—</span>'}</td>
					<td>${esc(row.line_count)}</td>
					<td>${esc(row.quantity)} ${esc(row.uom || '')}</td>
					<td>${cint(row.is_default)
						? `<span class="indicator-pill blue">${__('Default')}</span>`
						: '<span class="text-muted">—</span>'}</td>
					<td>${cint(row.is_active) ? __('Yes') : __('No')}</td>
					<td>${status}</td>
				</tr>
			`);
			$tr.on('click', () => frappe.set_route('bom_master_entry', row.name));
			$body.append($tr);
		});
	}
};
