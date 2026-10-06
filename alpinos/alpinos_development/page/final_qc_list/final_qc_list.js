/**
 * Final QC — list (FRD Phase 9). Top: FG batches waiting in FG-Hold, with Inspect.
 * Below: every Final QC with its status.
 */

frappe.pages['final_qc_list'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Final QC'), single_column: true });
	wrapper.final_qc_list = new AlpinosFinalQCList(page);
};

frappe.pages['final_qc_list'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb();
	if (wrapper.final_qc_list) wrapper.final_qc_list.refresh();
};

var AlpinosFinalQCList = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.filters = { search: '', qc_status: '', sku: '', start: 0, page_length: 50 };
		this.render_shell();
		this.make_filters();
		this.page.set_primary_action(__('+ New Inspection'), () => frappe.set_route('final_qc_entry', 'new'));
		const me = this;
		this.wrapper.on('click', '.fq-open', function () { frappe.set_route('final_qc_entry', $(this).attr('data-name')); });
		this.wrapper.on('click', '.fq-inspect', function () {
			const draft = $(this).attr('data-draft');
			if (draft) { frappe.set_route('final_qc_entry', draft); return; }
			frappe.route_options = { fg_batch: $(this).attr('data-batch') };
			frappe.set_route('final_qc_entry', 'new');
		});
		this.wrapper.find('.fq-prev').on('click', () => { me.filters.start = Math.max(0, me.filters.start - me.filters.page_length); me.refresh(); });
		this.wrapper.find('.fq-next').on('click', () => { me.filters.start += me.filters.page_length; me.refresh(); });
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fq">
				<style>
					.fq .fq-card { background:var(--card-bg,#fff); border:1px solid var(--border-color,#e2e2e2); border-radius:8px; padding:14px 16px; margin-bottom:16px; }
					.fq .fq-card > h5 { margin:0 0 10px; font-size:13px; text-transform:uppercase; letter-spacing:.4px; color:var(--text-muted); }
					.fq .fq-filters { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:10px; }
					.fq .fq-filters > div { min-width:170px; }
					.fq .fq-open { cursor:pointer; font-weight:600; }
					.fq .fq-num { text-align:right; }
				</style>
				<div class="fq-card"><h5>${__('Awaiting QC (FG-Hold)')}</h5><div class="fq-awaiting"></div></div>
				<div class="fq-card"><h5>${__('Inspections')}</h5>
					<div class="fq-filters"><div class="f-search"></div><div class="f-status"></div><div class="f-sku"></div></div>
					<div class="fq-rows"></div>
					<div style="display:flex;justify-content:flex-end;gap:6px;"><button class="btn btn-sm btn-default fq-prev">${__('Previous')}</button>
					<button class="btn btn-sm btn-default fq-next">${__('Next')}</button></div>
				</div>
			</div>`);
	}

	make_filters() {
		const me = this;
		const reload = frappe.utils.debounce(() => { me.filters.start = 0; me.refresh(); }, 300);
		const mk = (sel, df) => {
			const c = frappe.ui.form.make_control({
				df: Object.assign({ fieldtype: 'Data', change() { me.filters[df.fieldname] = this.get_value() || ''; reload(); } }, df),
				parent: this.wrapper.find(sel), render_input: true,
			});
			c.refresh();
		};
		mk('.f-search', { fieldname: 'search', label: __('Search') });
		mk('.f-status', { fieldname: 'qc_status', label: __('QC Status'), fieldtype: 'Select', options: ['', 'Draft', 'Pending Lab Test', 'Approved', 'Rejected', 'Partially Approved', 'Revoked'] });
		mk('.f-sku', { fieldname: 'sku', label: __('Target SKU'), fieldtype: 'Link', options: 'Item' });
	}

	refresh() {
		frappe.call({ method: 'alpinos.production.final_qc.get_qc_list', args: this.filters, callback: (r) => this.render(r.message || {}) });
	}

	render(m) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		this.page.btn_primary.toggle(!!cint(m.can_create));
		const aw = m.awaiting || [];
		this.wrapper.find('.fq-awaiting').html(aw.length ? `<table class="table table-bordered table-condensed"><thead><tr>
			<th>${__('FG Batch')}</th><th>${__('SKU')}</th><th>${__('MFG Date')}</th><th>${__('Sub-PO')}</th><th class="fq-num">${__('Pcs in Hold')}</th><th></th></tr></thead><tbody>
			${aw.map((b) => `<tr><td>${esc(b.name)}</td><td>${esc(b.sku_name || b.item)}</td><td>${esc(frappe.datetime.str_to_user(b.manufacturing_date))}</td>
				<td>${esc(b.custom_sub_production_order || '')}</td><td class="fq-num">${cint(b.qty)}</td>
				<td>${cint(b.awaiting_approval) ? `<span class="indicator-pill red">${__('Wastage approval pending')}</span>` : ''}
				${cint(m.can_create) ? `<button class="btn btn-xs btn-primary fq-inspect" data-batch="${esc(b.name)}" data-draft="">${b.draft_qc ? __('Continue') : __('Inspect')}</button>` : ''}</td></tr>`).join('')}
			</tbody></table>` : `<p class="text-muted">${__('No batches waiting for QC.')}</p>`);
		const rows = m.data || [];
		const pill = { 'Draft': 'gray', 'Pending Lab Test': 'orange', 'Approved': 'green', 'Rejected': 'red', 'Partially Approved': 'yellow', 'Revoked': 'gray' };
		this.wrapper.find('.fq-rows').html(rows.length ? `<div class="table-responsive"><table class="table table-bordered table-condensed"><thead><tr>
			<th>${__('Final QC')}</th><th>${__('FG Batch')}</th><th>${__('SKU')}</th><th>${__('Production Date')}</th><th class="fq-num">${__('Inward')}</th>
			<th class="fq-num">${__('Approved')}</th><th class="fq-num">${__('Rejected')}</th><th class="fq-num">${__('Sample')}</th><th>${__('Status')}</th><th>${__('Inspector')}</th></tr></thead><tbody>
			${rows.map((r) => `<tr><td><span class="fq-open" data-name="${esc(r.name)}">${esc(r.name)}</span></td><td>${esc(r.fg_batch)}</td>
				<td>${esc(r.sku_name || r.target_sku)}</td><td>${esc(frappe.datetime.str_to_user(r.production_date))}</td><td class="fq-num">${cint(r.total_inward_pcs)}</td>
				<td class="fq-num">${cint(r.approved_pcs)}</td><td class="fq-num">${cint(r.rejected_pcs)}</td><td class="fq-num">${cint(r.sample_size)}</td>
				<td><span class="indicator-pill ${pill[r.qc_status] || 'gray'}">${esc(r.qc_status)}</span></td><td>${esc(r.inspector || '')}</td></tr>`).join('')}
			</tbody></table></div>` : `<p class="text-muted">${__('No inspections match these filters.')}</p>`);
		this.wrapper.find('.fq-prev').prop('disabled', cint(m.start) <= 0);
		this.wrapper.find('.fq-next').prop('disabled', !cint(m.has_more));
	}
};
