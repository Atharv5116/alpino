/**
 * Inventory Adjustments (FRD 10.3) -- list. A deduction above the approval threshold sits
 * in Pending Approval until the Plant Head approves it (13.2).
 */

frappe.pages['inventory_adjustment_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Inventory Adjustments'), single_column: true });
	wrapper.list = new AlpInvList(page, {
		method: 'alpinos.production.inventory_api.get_adjustment_list',
		entry_page: 'inventory_adjustment_entry',
		new_label: __('New Adjustment'),
		filters: [
			{ fieldname: 'search', label: __('Search'), fieldtype: 'Data' },
			{ fieldname: 'approval_status', label: __('Status'), fieldtype: 'Select',
				options: ['', 'Draft', 'Pending Approval', 'Posted', 'Rejected', 'Cancelled'] },
			{ fieldname: 'adjustment_type', label: __('Type'), fieldtype: 'Select', options: ['', 'Add Stock', 'Deduct Stock'] },
			{ fieldname: 'warehouse', label: __('Warehouse'), fieldtype: 'Link', options: 'Warehouse' },
			{ fieldname: 'date_from', label: __('From'), fieldtype: 'Date' },
			{ fieldname: 'date_to', label: __('To'), fieldtype: 'Date' },
		],
		defaults: (frappe.route_options && frappe.route_options.approval_status)
			? { approval_status: frappe.route_options.approval_status } : null,
		columns: [
			['name', __('ID'), 'id'], ['posting_date', __('Date'), 'date'], ['adjustment_type', __('Type')],
			['reason_code', __('Reason')], ['warehouse', __('Warehouse')], ['total_kg', __('Total (KG)'), 'num'],
			['by', __('By')], ['approval_status', __('Status'), 'status'],
		],
		nav: [[__('Inventory'), 'production_inventory'], [__('Stock Transfers'), 'production_transfer_list']],
	});
	frappe.route_options = null;
};

frappe.pages['inventory_adjustment_list'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	if (wrapper.list) wrapper.list.refresh();
};

/** Shared by the Stock Transfer and Inventory Adjustment lists (both files define it). */
if (!window.AlpInvList) {
	window.AlpInvList = class {
		constructor(page, opts) {
			this.page = page;
			this.opts = opts;
			this.f = { start: 0, page_length: 50 };
			this.$w = $(page.main);
			this.$w.html(`
				<div class="alp-inv-list">
					<style>
						.alp-inv-list .fl { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px; }
						.alp-inv-list .fl > div { min-width:160px; }
						.alp-inv-list table { width:100%; }
						.alp-inv-list .id { cursor:pointer; font-weight:600; }
						.alp-inv-list .id:hover { text-decoration:underline; }
						.alp-inv-list td.n, .alp-inv-list th.n { text-align:right; }
						.alp-inv-list .pager { display:flex; justify-content:space-between; align-items:center; gap:8px; }
					</style>
					<div class="fl"></div>
					<table class="table table-bordered table-condensed"><thead><tr></tr></thead><tbody></tbody></table>
					<div class="pager"><div class="cnt text-muted"></div>
						<div><button class="btn btn-sm btn-default prev">${__('Previous')}</button>
						<button class="btn btn-sm btn-default next">${__('Next')}</button></div></div>
				</div>`);
			const me = this;
			const reload = frappe.utils.debounce(() => { me.f.start = 0; me.refresh(); }, 300);
			opts.filters.forEach((df) => {
				const $p = $('<div>').appendTo(this.$w.find('.fl'));
				const c = frappe.ui.form.make_control({
					df: Object.assign({ change() { me.f[df.fieldname] = this.get_value(); reload(); } }, df),
					parent: $p, render_input: true,
				});
				c.refresh();
				if (opts.defaults && opts.defaults[df.fieldname]) {
					c.set_value(opts.defaults[df.fieldname]);
					me.f[df.fieldname] = opts.defaults[df.fieldname];
				}
			});
			this.$w.find('thead tr').html(opts.columns.map((c) =>
				`<th class="${c[2] === 'num' ? 'n' : ''}">${c[1]}</th>`).join(''));
			this.$w.find('.prev').on('click', () => { this.f.start = Math.max(this.f.start - this.f.page_length, 0); this.refresh(); });
			this.$w.find('.next').on('click', () => { this.f.start += this.f.page_length; this.refresh(); });
			(opts.nav || []).forEach(([label, route]) => this.page.add_inner_button(label, () => frappe.set_route(route)));
			this.$w.on('click', '.id', (e) => frappe.set_route(opts.entry_page, $(e.currentTarget).attr('data-name')));
		}

		refresh() {
			frappe.call({ method: this.opts.method, args: this.f }).then((r) => this.render(r.message || {}));
		}

		render(d) {
			const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
			if (d.can_create && !this._new) {
				this._new = true;
				this.page.set_primary_action(this.opts.new_label, () => frappe.set_route(this.opts.entry_page, 'new'), 'add');
			}
			const colour = { Draft: 'red', Submitted: 'blue', Cancelled: 'gray', Posted: 'green',
				'Pending Approval': 'orange', Rejected: 'red' };
			const html = (d.rows || []).map((r) => '<tr>' + this.opts.columns.map(([f, , kind]) => {
				const v = r[f];
				if (kind === 'id') return `<td><span class="id" data-name="${esc(v)}">${esc(v)}</span></td>`;
				if (kind === 'date') return `<td>${v ? frappe.datetime.str_to_user(v) : ''}</td>`;
				if (kind === 'num') return `<td class="n">${format_number(flt(v), null, 3)}</td>`;
				if (kind === 'status') return `<td><span class="indicator-pill ${colour[v] || 'gray'}">${esc(v)}</span></td>`;
				return `<td>${esc(v)}</td>`;
			}).join('') + '</tr>').join('')
				|| `<tr><td colspan="${this.opts.columns.length}" class="text-muted text-center">${__('Nothing found.')}</td></tr>`;
			this.$w.find('tbody').html(html);
			const n = (d.rows || []).length;
			this.$w.find('.cnt').text(n ? __('Showing {0} - {1}', [this.f.start + 1, this.f.start + n]) : '');
			this.$w.find('.prev').prop('disabled', !this.f.start);
			this.$w.find('.next').prop('disabled', !d.has_more);
		}
	};
}
