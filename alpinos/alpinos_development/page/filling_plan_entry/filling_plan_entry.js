/**
 * Filling Plan — Admin planning screen (FRD 6.1, 6.2, 6.4.3).
 *
 * Header: Date, Parent PO, Sub-PO (only QC-approved baked WIP), Available WIP (KG, the WIP
 * lock), Filling Line (Active filling machines). Grid: Target SKU, Size, Planned Pcs,
 * Equivalent KG (deducted live from Available WIP), Available PM Stock. Every rule is
 * enforced again on the server (alpinos.production.filling_plan).
 */

frappe.pages['filling_plan_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Filling Plan'), single_column: true });
	wrapper.filling_plan_entry = new AlpinosFillingPlanEntry(page);
};

frappe.pages['filling_plan_entry'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Filling Planning'), '/app/filling_plan_list');
	if (wrapper.filling_plan_entry) wrapper.filling_plan_entry.handle_route();
};

var AlpinosFillingPlanEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.rows = [];
		this.ctx = {};
		this.available = 0;
		this.render_shell();
		this.make_fields();
		this.bind_grid();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fpe">
				<style>
					.fpe .fpe-card { background:var(--card-bg,#fff); border:1px solid var(--border-color,#e2e2e2); border-radius:8px; padding:16px 18px; margin-bottom:16px; }
					.fpe .fpe-card > h5 { margin:0 0 12px; font-size:13px; text-transform:uppercase; letter-spacing:.4px; color:var(--text-muted); }
					.fpe table td, .fpe table th { vertical-align:middle; font-size:12.5px; }
					.fpe .fpe-num { text-align:right; white-space:nowrap; }
					.fpe .fpe-grid .frappe-control, .fpe .fpe-grid .form-group { margin-bottom:0; }
					.fpe .fpe-bad { color:var(--red-600,#c0392b); font-weight:600; }
					.fpe .fpe-sum { display:flex; gap:24px; flex-wrap:wrap; margin-top:8px; font-weight:600; }
				</style>
				<div class="fpe-banner"></div>
				<div class="fpe-card"><h5>${__('Plan')}</h5>
					<div class="row"><div class="col-md-3 f-name"></div><div class="col-md-3 f-date"></div><div class="col-md-3 f-parent"></div><div class="col-md-3 f-sub"></div></div>
					<div class="row"><div class="col-md-3 f-avail"></div><div class="col-md-3 f-line"></div><div class="col-md-3 f-cat"></div><div class="col-md-3 f-status"></div></div>
					<div class="row"><div class="col-md-12 f-remarks"></div></div>
				</div>
				<div class="fpe-card"><h5>${__('Split Row Allocation')}</h5>
					<div class="table-responsive"><table class="table table-bordered fpe-grid">
						<thead><tr><th style="width:30px;">#</th><th style="min-width:220px;">${__('Target SKU')}</th><th class="fpe-num">${__('Size (KG)')}</th>
						<th style="width:130px;">${__('Planned Qty (Pcs)')}</th><th class="fpe-num">${__('Equivalent (KG)')}</th><th class="fpe-num">${__('Available PM Stock')}</th>
						<th class="fpe-num">${__('Completed')}</th><th class="fpe-num">${__('Pending')}</th><th>${__('Row')}</th><th></th></tr></thead>
						<tbody></tbody></table></div>
					<button class="btn btn-xs btn-default fpe-add">${__('+ Add Row')}</button>
					<div class="fpe-sum"></div>
				</div>
				<div class="fpe-card fpe-inwards-card" style="display:none;"><h5>${__('Filling Inwards')}</h5><div class="fpe-inwards"></div></div>
			</div>`);
	}

	_ctl(sel, df, value) {
		const c = frappe.ui.form.make_control({ df: Object.assign({ fieldtype: 'Data' }, df), parent: this.wrapper.find(sel), render_input: true });
		c.refresh();
		if (value !== undefined) c.set_value(value);
		this.fields[df.fieldname] = c;
		return c;
	}
	_set(f, v) { if (this.fields[f]) this.fields[f].set_value(v == null ? '' : v); }
	_val(f) { return this.fields[f] ? this.fields[f].get_value() : null; }
	_ro(f, ro) { const c = this.fields[f]; if (c) { c.df.read_only = ro ? 1 : 0; c.refresh(); } }

	make_fields() {
		const me = this;
		this._ctl('.f-name', { fieldname: 'name', label: __('Plan ID'), read_only: 1 });
		this._ctl('.f-date', { fieldname: 'plan_date', label: __('Date'), fieldtype: 'Date', reqd: 1 }, frappe.datetime.get_today());
		this._ctl('.f-parent', {
			fieldname: 'parent_po', label: __('Parent PO'), fieldtype: 'Link', options: 'Production Order', reqd: 1,
			get_query() { return { query: 'alpinos.production.filling_plan.parent_query' }; },
			change() { if (!me.loading) { me._set('sub_order', ''); me.refresh_wip(); } },
		});
		this._ctl('.f-sub', {
			fieldname: 'sub_order', label: __('Sub-PO (Batch)'), fieldtype: 'Link', options: 'Work Order', reqd: 1,
			description: __('Only Sub-POs with QC-approved baked WIP.'),
			get_query() { return { query: 'alpinos.production.filling_plan.sub_order_query', filters: { parent_po: me._val('parent_po') || '' } }; },
			change() { if (!me.loading) me.refresh_wip(); },
		});
		this._ctl('.f-avail', { fieldname: 'available_wip_kg', label: __('Available WIP (KG)'), read_only: 1 });
		this._ctl('.f-line', {
			fieldname: 'filling_line', label: __('Filling Line No.'), fieldtype: 'Link', options: 'Machine', reqd: 1,
			get_query() { return { query: 'alpinos.production.filling_plan.line_query' }; },
			change() { if (!me.loading) me.refresh_all_skus(); },
		});
		this._ctl('.f-cat', { fieldname: 'line_category', label: __('Filling Category'), read_only: 1 });
		this._ctl('.f-status', { fieldname: 'status', label: __('Status'), read_only: 1 }, 'Planned');
		this._ctl('.f-remarks', { fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text' });
	}

	handle_route() {
		const route = frappe.get_route() || [];
		this.docname = route[1] && route[1] !== 'new' ? route[1] : null;
		this.load();
	}

	load() {
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.filling_plan.get_plan_context', args: { plan: docname || '' }, freeze: true,
			callback: (r) => {
				if (docname !== this.docname) return;
				this.ctx = r.message || {};
				this.loading = true;
				if (this.ctx.doc) this.fill(this.ctx.doc); else this.reset();
				this.loading = false;
				this.apply_state();
			},
		});
	}

	reset() {
		['name', 'parent_po', 'sub_order', 'filling_line', 'line_category', 'remarks', 'available_wip_kg'].forEach((f) => this._set(f, ''));
		this._set('plan_date', frappe.datetime.get_today());
		this._set('status', 'Planned');
		this.rows = [{}];
		this.available = 0;
		this.page.set_title(__('New Filling Plan'));
	}

	fill(d) {
		this._set('name', d.name); this._set('plan_date', d.plan_date); this._set('parent_po', d.parent_po);
		this._set('sub_order', d.sub_order); this._set('filling_line', d.filling_line); this._set('line_category', d.line_category);
		this._set('status', d.status); this._set('remarks', d.remarks);
		this.available = flt(d.available_wip_kg);
		this._set('available_wip_kg', this.available);
		this.rows = (d.rows || []).map((r) => Object.assign({}, r));
		this.page.set_title(`${d.name} — ${d.status}`);
	}

	editable() { return !!cint(this.ctx.can_write); }

	apply_state() {
		const ed = this.editable();
		const started = this.ctx.doc && this.ctx.doc.status !== 'Planned';
		['plan_date', 'remarks'].forEach((f) => this._ro(f, !ed));
		['parent_po', 'sub_order', 'filling_line'].forEach((f) => this._ro(f, !ed || started));
		const $b = this.wrapper.find('.fpe-banner').empty();
		const d = this.ctx.doc;
		if (d && cint(d.has_pending_approval)) $b.append(`<div class="alert alert-danger">${__('An inward on this plan has abnormal wastage awaiting approval.')}</div>`);
		if (d && d.rerouted_from) $b.append(`<div class="alert alert-info">${__('Re-routed from {0}.', [frappe.utils.escape_html(d.rerouted_from)])}</div>`);
		if (d && d.rerouted_to) $b.append(`<div class="alert alert-warning">${__('Pending pieces were re-routed to {0}.', [frappe.utils.escape_html(d.rerouted_to)])}</div>`);
		this.wrapper.find('.fpe-add').toggle(ed);
		this.render_rows();
		this.render_inwards();
		this.make_actions();
	}

	make_actions() {
		this.page.clear_primary_action();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		if (this.editable()) this.page.set_primary_action(__('Save'), () => this.save());
		if (cint(this.ctx.can_reroute)) this.page.add_inner_button(__('Re-Route Pending'), () => this.reroute());
		if (cint(this.ctx.can_delete)) this.page.add_menu_item(__('Delete'), () => this.remove());
		this.page.add_inner_button(__('Calendar'), () => frappe.set_route('filling_calendar'));
	}

	refresh_wip() {
		frappe.call({
			method: 'alpinos.production.filling_plan.get_wip_info',
			args: { parent_po: this._val('parent_po') || '', sub_order: this._val('sub_order') || '', plan: this.docname || '' },
			callback: (r) => {
				const m = r.message || {};
				this.available = this._val('sub_order') ? flt(m.available_wip_kg) : flt(m.parent_available_kg);
				this._set('available_wip_kg', this.available);
				this.render_sum();
			},
		});
	}

	refresh_sku(idx) {
		const row = this.rows[idx];
		if (!row || !row.target_sku) return;
		frappe.call({
			method: 'alpinos.production.filling_plan.get_sku_info',
			args: { sku: row.target_sku, filling_line: this._val('filling_line') || '' },
			callback: (r) => {
				const m = r.message || {};
				Object.assign(row, { size_kg: m.size_kg, sku_name: m.sku_name, available_pm_stock: m.available_pm_stock,
					pm_checked: m.pm_checked, compatible: m.compatible, reason: m.reason });
				this.render_rows();
			},
		});
	}

	refresh_all_skus() { this.rows.forEach((r, i) => this.refresh_sku(i)); }

	bind_grid() {
		const me = this;
		this.wrapper.on('click', '.fpe-add', () => { me.rows.push({}); me.render_rows(); });
		this.wrapper.on('click', '.fpe-del', function () { me.rows.splice(cint($(this).attr('data-idx')), 1); me.render_rows(); });
	}

	render_rows() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const me = this;
		const ed = this.editable();
		const $b = this.wrapper.find('.fpe-grid tbody').empty();
		this.rows.forEach((row, idx) => {
			const locked = cint(row.completed_pcs) > 0 || row.row_status === 'Closed';
			const eq = flt(cint(row.planned_pcs) * flt(row.size_kg), 3);
			const pmBad = cint(row.pm_checked) !== 0 && row.available_pm_stock != null && cint(row.planned_pcs) > flt(row.available_pm_stock) && row.row_status !== 'Closed';
			const $tr = $(`<tr>
				<td>${idx + 1}</td><td class="c-sku"></td><td class="fpe-num">${flt(row.size_kg, 3) || ''}</td><td class="c-pcs"></td>
				<td class="fpe-num">${eq || ''}</td>
				<td class="fpe-num ${pmBad ? 'fpe-bad' : ''}">${row.target_sku ? (cint(row.pm_checked) === 0 && row.pm_checked != null ? __('No BOM') : cint(row.available_pm_stock)) : ''}</td>
				<td class="fpe-num">${cint(row.completed_pcs)}</td><td class="fpe-num">${row.pending_pcs != null ? cint(row.pending_pcs) : ''}</td>
				<td>${esc(row.row_status || 'Open')}${row.compatible === 0 ? `<div class="fpe-bad">${esc(row.reason || '')}</div>` : ''}</td>
				<td>${ed && !locked ? `<button class="btn btn-xs btn-default fpe-del" data-idx="${idx}">✕</button>` : ''}</td></tr>`);
			$b.append($tr);
			const sku = frappe.ui.form.make_control({
				df: { fieldtype: 'Link', options: 'Item', fieldname: 'sku_' + idx, read_only: (!ed || locked) ? 1 : 0,
					get_query() { return { query: 'alpinos.production.filling_plan.sku_query', filters: { filling_line: me._val('filling_line') || '' } }; },
					change() { const v = this.get_value(); if (v !== row.target_sku) { row.target_sku = v; me.refresh_sku(idx); } } },
				parent: $tr.find('.c-sku'), render_input: true, only_input: true,
			});
			sku.refresh(); sku.set_value(row.target_sku || '');
			const pcs = frappe.ui.form.make_control({
				df: { fieldtype: 'Int', fieldname: 'pcs_' + idx, read_only: (!ed || row.row_status === 'Closed') ? 1 : 0,
					change() { const v = cint(this.get_value()); if (v !== cint(row.planned_pcs)) { row.planned_pcs = v; me.render_rows(); } } },
				parent: $tr.find('.c-pcs'), render_input: true, only_input: true,
			});
			pcs.refresh(); pcs.set_value(row.planned_pcs || '');
		});
		this.render_sum();
	}

	render_sum() {
		const need = this.rows.reduce((s, r) => {
			if (r.row_status === 'Closed') return s;
			const pending = r.pending_pcs != null && r.name ? cint(r.planned_pcs) - cint(r.completed_pcs) - cint(r.written_off_pcs) - cint(r.rerouted_pcs) : cint(r.planned_pcs);
			return s + Math.max(pending, 0) * flt(r.size_kg);
		}, 0);
		const total = this.rows.reduce((s, r) => s + cint(r.planned_pcs) * flt(r.size_kg), 0);
		const left = flt(this.available - need, 3);
		this.wrapper.find('.fpe-sum').html(`
			<span>${__('Planned')}: ${flt(total, 3)} KG</span>
			<span>${__('Available WIP')}: ${flt(this.available, 3)} KG</span>
			<span class="${left < 0 ? 'fpe-bad' : ''}">${__('Remaining after plan')}: ${left} KG</span>`);
	}

	render_inwards() {
		const list = this.ctx.inwards || [];
		this.wrapper.find('.fpe-inwards-card').toggle(!!list.length);
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		this.wrapper.find('.fpe-inwards').html(`<table class="table table-bordered table-condensed"><thead><tr>
			<th>${__('Inward')}</th><th>${__('Date')}</th><th>${__('SKU')}</th><th class="fpe-num">${__('Pcs')}</th><th class="fpe-num">${__('Filled KG')}</th>
			<th class="fpe-num">${__('Wastage KG')}</th><th class="fpe-num">${__('Loss KG')}</th><th class="fpe-num">${__('Loss %')}</th><th>${__('Type')}</th><th>${__('FG Batch')}</th><th>${__('Approval')}</th></tr></thead><tbody>
			${list.map((r) => `<tr><td><a href="/app/filling-inward/${esc(r.name)}">${esc(r.name)}</a></td><td>${esc(frappe.datetime.str_to_user(r.posting_date))}</td>
				<td>${esc(r.target_sku)}</td><td class="fpe-num">${cint(r.input_pcs)}</td><td class="fpe-num">${flt(r.filled_kg, 3)}</td>
				<td class="fpe-num">${flt(r.wastage_kg, 3)}</td><td class="fpe-num">${flt(r.process_loss_kg, 3)}</td><td class="fpe-num">${flt(r.process_loss_pct, 2)}</td>
				<td>${esc(r.submission_type)}</td><td>${esc(r.fg_batch || '')}</td>
				<td>${r.approval_status === 'Pending' ? `<span class="indicator-pill red">${__('Pending')}</span>` : esc(r.approval_status || '')}</td></tr>`).join('')}
			</tbody></table>`);
	}

	save() {
		const payload = {
			name: this.docname || '', plan_date: this._val('plan_date'), parent_po: this._val('parent_po'),
			sub_order: this._val('sub_order'), filling_line: this._val('filling_line'), remarks: this._val('remarks'),
			rows: this.rows.filter((r) => r.target_sku || cint(r.planned_pcs)).map((r) => ({ name: r.name || '', target_sku: r.target_sku, planned_pcs: cint(r.planned_pcs) })),
		};
		frappe.call({
			method: 'alpinos.production.filling_plan.save_plan', args: { payload }, freeze: true,
			callback: (r) => {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved {0}', [r.message.name]), indicator: 'green' });
				if (this.docname !== r.message.name) frappe.set_route('filling_plan_entry', r.message.name);
				else this.load();
			},
		});
	}

	reroute() {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Re-Route Pending'),
			fields: [
				{ fieldname: 'info', fieldtype: 'HTML', options: `<p class="text-muted">${__('The pending pieces move to a new plan on the chosen line; this plan closes as Re-Routed.')}</p>` },
				{ fieldname: 'filling_line', label: __('New Filling Line'), fieldtype: 'Link', options: 'Machine', reqd: 1,
					get_query() { return { query: 'alpinos.production.filling_plan.line_query', filters: { exclude: me._val('filling_line') || '' } }; } },
				{ fieldname: 'plan_date', label: __('Date'), fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
				{ fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', default: __('Machine breakdown') },
			],
			primary_action_label: __('Re-Route'),
			primary_action(v) {
				frappe.call({
					method: 'alpinos.production.filling_plan.reroute_plan', freeze: true,
					args: { plan: me.docname, filling_line: v.filling_line, plan_date: v.plan_date, reason: v.reason },
					callback(r) { d.hide(); if (r.message) frappe.set_route('filling_plan_entry', r.message.new_plan); },
				});
			},
		});
		d.show();
	}

	remove() {
		frappe.confirm(__('Delete {0}?', [this.docname]), () => frappe.call({
			method: 'alpinos.production.filling_plan.delete_plan', args: { plan: this.docname }, freeze: true,
			callback: () => frappe.set_route('filling_plan_list'),
		}));
	}
};
