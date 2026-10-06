/**
 * Filling Planning — list of Filling Plans (FRD Phase 6). + New opens the plan screen;
 * a plan with abnormal wastage awaiting approval is flagged red.
 */

frappe.pages['filling_plan_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Filling Planning'), single_column: true });
	wrapper.filling_plan_list = new AlpinosFillingPlanList(page);
};

frappe.pages['filling_plan_list'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb();
	if (wrapper.filling_plan_list) wrapper.filling_plan_list.refresh();
};

var AlpinosFillingPlanList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.filters = { search: '', status: '', parent_po: '', sub_order: '', filling_line: '', date_from: '', date_to: '', start: 0, page_length: 50 };
		this.render_shell();
		this.make_filters();
		this.page.set_primary_action(__('+ New Plan'), () => frappe.set_route('filling_plan_entry', 'new'));
		this.page.add_inner_button(__('Calendar'), () => frappe.set_route('filling_calendar'));
		this.page.add_inner_button(__('Filling Entry'), () => frappe.set_route('filling_entry'));
		this.wrapper.on('click', '.fp-open', function () { frappe.set_route('filling_plan_entry', $(this).attr('data-name')); });
		this.wrapper.find('.fp-prev').on('click', () => { this.filters.start = Math.max(0, this.filters.start - this.filters.page_length); this.refresh(); });
		this.wrapper.find('.fp-next').on('click', () => { this.filters.start += this.filters.page_length; this.refresh(); });
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fp-list">
				<style>
					.fp-list .fp-filters { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
					.fp-list .fp-filters > div { min-width:160px; }
					.fp-list .fp-open { cursor:pointer; font-weight:600; }
					.fp-list .fp-open:hover { text-decoration:underline; }
					.fp-list tr.fp-flag td { background: var(--red-50, #fff1f0); }
					.fp-list .fp-num { text-align:right; }
					.fp-list .fp-empty { padding:40px; text-align:center; color:var(--text-muted); }
				</style>
				<div class="fp-filters">
					<div class="f-search"></div><div class="f-status"></div><div class="f-parent"></div>
					<div class="f-sub"></div><div class="f-line"></div><div class="f-from"></div><div class="f-to"></div>
				</div>
				<div class="table-responsive"><table class="table table-bordered table-condensed">
					<thead><tr>
						<th>${__('Plan')}</th><th>${__('Date')}</th><th>${__('Parent PO')}</th><th>${__('Sub-PO')}</th>
						<th>${__('Filling Line')}</th><th>${__('Target SKUs')}</th><th class="fp-num">${__('Planned')}</th>
						<th class="fp-num">${__('Completed')}</th><th class="fp-num">${__('Pending')}</th><th class="fp-num">${__('KG')}</th><th>${__('Status')}</th>
					</tr></thead><tbody></tbody></table></div>
				<div class="fp-empty" style="display:none;">${__('No Filling Plans match these filters.')}</div>
				<div style="display:flex;justify-content:space-between;align-items:center;">
					<div class="fp-count text-muted"></div>
					<div><button class="btn btn-sm btn-default fp-prev">${__('Previous')}</button>
					<button class="btn btn-sm btn-default fp-next">${__('Next')}</button></div>
				</div>
			</div>`);
	}

	_ctl(sel, df) {
		const me = this;
		const reload = frappe.utils.debounce(() => { me.filters.start = 0; me.refresh(); }, 300);
		const c = frappe.ui.form.make_control({
			df: Object.assign({ fieldtype: 'Data', change() { me.filters[df.fieldname] = this.get_value() || ''; reload(); } }, df),
			parent: this.wrapper.find(sel), render_input: true,
		});
		c.refresh();
		return c;
	}

	make_filters() {
		this._ctl('.f-search', { fieldname: 'search', label: __('Search') });
		this._ctl('.f-status', { fieldname: 'status', label: __('Status'), fieldtype: 'Select', options: ['', 'Planned', 'In Progress', 'Completed', 'Short-Closed', 'Re-Routed'] });
		this._ctl('.f-parent', { fieldname: 'parent_po', label: __('Parent PO'), fieldtype: 'Link', options: 'Production Order' });
		this._ctl('.f-sub', { fieldname: 'sub_order', label: __('Sub-PO'), fieldtype: 'Link', options: 'Work Order' });
		this._ctl('.f-line', { fieldname: 'filling_line', label: __('Filling Line'), fieldtype: 'Link', options: 'Machine' });
		this._ctl('.f-from', { fieldname: 'date_from', label: __('From'), fieldtype: 'Date' });
		this._ctl('.f-to', { fieldname: 'date_to', label: __('To'), fieldtype: 'Date' });
	}

	refresh() {
		frappe.call({
			method: 'alpinos.production.filling_plan.get_plan_list', args: this.filters,
			callback: (r) => this.render(r.message || {}),
		});
	}

	render(m) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const pill = { 'Planned': 'gray', 'In Progress': 'yellow', 'Completed': 'green', 'Short-Closed': 'red', 'Re-Routed': 'red' };
		const rows = m.data || [];
		this.page.btn_primary.toggle(!!cint(m.can_create));
		const $b = this.wrapper.find('tbody').empty();
		this.wrapper.find('.fp-empty').toggle(!rows.length);
		rows.forEach((r) => {
			$b.append(`<tr class="${cint(r.has_pending_approval) ? 'fp-flag' : ''}">
				<td><span class="fp-open" data-name="${esc(r.name)}">${esc(r.name)}</span>
					${cint(r.has_pending_approval) ? `<span class="indicator-pill red" title="${__('Abnormal wastage awaiting approval')}">!</span>` : ''}</td>
				<td>${esc(frappe.datetime.str_to_user(r.plan_date))}</td><td>${esc(r.parent_po)}</td><td>${esc(r.sub_order)}</td>
				<td>${esc(r.line_label)}</td><td>${esc(r.skus)}</td>
				<td class="fp-num">${cint(r.total_planned_pcs)}</td><td class="fp-num">${cint(r.total_completed_pcs)}</td>
				<td class="fp-num">${cint(r.total_pending_pcs)}</td><td class="fp-num">${flt(r.total_planned_kg, 3)}</td>
				<td><span class="indicator-pill ${pill[r.status] || 'gray'}">${esc(r.status)}</span></td></tr>`);
		});
		const start = cint(m.start);
		this.wrapper.find('.fp-count').text(m.total ? __('{0} to {1} of {2}', [start + 1, start + rows.length, m.total]) : '');
		this.wrapper.find('.fp-prev').prop('disabled', start <= 0);
		this.wrapper.find('.fp-next').prop('disabled', !cint(m.has_more));
	}
};
