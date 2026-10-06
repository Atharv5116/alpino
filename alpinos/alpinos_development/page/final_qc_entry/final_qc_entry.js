/**
 * Final QC Inspection (FRD 9.1–9.4). FG Batch Code (FG-Hold only) → batch details; test
 * grid Pass / Fail / Pending; Approved / Rejected / Sample; rejection reason + category
 * (rework form for Chance of Repair / Improvement Required); Approve Batch / Reject Batch /
 * Partial Approval. Save keeps a Pending lab test on hold. QC Manager: Revoke QC Approval.
 */

frappe.pages['final_qc_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Final QC Inspection'), single_column: true });
	wrapper.final_qc_entry = new AlpinosFinalQCEntry(page);
};

frappe.pages['final_qc_entry'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Final QC'), '/app/final_qc_list');
	if (wrapper.final_qc_entry) wrapper.final_qc_entry.handle_route();
};

var AlpinosFinalQCEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.ctx = {};
		this.tests = [];
		this.render_shell();
		this.make_fields();
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fqe">
				<style>
					.fqe .fqe-card { background:var(--card-bg,#fff); border:1px solid var(--border-color,#e2e2e2); border-radius:8px; padding:16px 18px; margin-bottom:16px; }
					.fqe .fqe-card > h5 { margin:0 0 12px; font-size:13px; text-transform:uppercase; letter-spacing:.4px; color:var(--text-muted); }
					.fqe .fqe-tests .frappe-control, .fqe .fqe-tests .form-group { margin-bottom:0; }
					.fqe .fqe-check { font-weight:600; margin-top:6px; }
					.fqe .fqe-bad { color:var(--red-600,#c0392b); }
					.fqe .fqe-ok { color:var(--green-600,#2e9e4f); }
				</style>
				<div class="fqe-banner"></div>
				<div class="fqe-card"><h5>${__('Batch')}</h5>
					<div class="row"><div class="col-md-3 f-name"></div><div class="col-md-3 f-batch"></div><div class="col-md-3 f-status"></div><div class="col-md-3 f-inspector"></div></div>
					<div class="row"><div class="col-md-3 f-sku"></div><div class="col-md-3 f-line"></div><div class="col-md-3 f-date"></div><div class="col-md-3 f-total"></div></div>
					<div class="row"><div class="col-md-3 f-sub"></div><div class="col-md-3 f-parent"></div><div class="col-md-3 f-inward"></div></div>
				</div>
				<div class="fqe-card"><h5>${__('Test Parameters')}</h5>
					<table class="table table-bordered fqe-tests"><thead><tr><th style="width:30%;">${__('Test')}</th><th style="width:20%;">${__('Result')}</th><th>${__('Remarks')}</th></tr></thead><tbody></tbody></table>
				</div>
				<div class="fqe-card"><h5>${__('Quantities & Decision')}</h5>
					<div class="row"><div class="col-md-3 f-approved"></div><div class="col-md-3 f-rejected"></div><div class="col-md-3 f-sample"></div><div class="col-md-3"><div class="fqe-check"></div></div></div>
					<div class="row"><div class="col-md-3 f-reason"></div><div class="col-md-3 f-category"></div><div class="col-md-6 f-remarks"></div></div>
					<div class="row fqe-rework" style="display:none;"><div class="col-md-3 f-rqty"></div><div class="col-md-3 f-rproc"></div><div class="col-md-6 f-rremark"></div></div>
					<div class="row"><div class="col-md-6 f-links"></div></div>
				</div>
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
		const check = () => me.render_check();
		this._ctl('.f-name', { fieldname: 'name', label: __('Final QC'), read_only: 1 });
		this._ctl('.f-batch', {
			fieldname: 'fg_batch', label: __('FG Batch Code'), fieldtype: 'Link', options: 'Batch', reqd: 1,
			description: __('Only FG batches in FG-Hold.'),
			get_query() { return { query: 'alpinos.production.final_qc.hold_batch_query' }; },
			change() { if (!me.loading) me.on_batch(this.get_value()); },
		});
		this._ctl('.f-status', { fieldname: 'qc_status', label: __('QC Status'), read_only: 1 });
		this._ctl('.f-inspector', { fieldname: 'inspector', label: __('Inspector'), read_only: 1 });
		this._ctl('.f-sku', { fieldname: 'sku', label: __('Target SKU'), read_only: 1 });
		this._ctl('.f-line', { fieldname: 'line', label: __('Filling Line'), read_only: 1 });
		this._ctl('.f-date', { fieldname: 'production_date', label: __('Production Date'), read_only: 1 });
		this._ctl('.f-total', { fieldname: 'total_inward_pcs', label: __('Total Inward Qty (Pcs)'), read_only: 1 });
		this._ctl('.f-sub', { fieldname: 'sub_order', label: __('Sub-PO'), read_only: 1 });
		this._ctl('.f-parent', { fieldname: 'parent_po', label: __('Parent PO'), read_only: 1 });
		this._ctl('.f-inward', { fieldname: 'filling_inward', label: __('Filling Inward'), read_only: 1 });
		this._ctl('.f-approved', { fieldname: 'approved_pcs', label: __('Approved Quantity (Pcs)'), fieldtype: 'Int', change: check });
		this._ctl('.f-rejected', { fieldname: 'rejected_pcs', label: __('Rejected Quantity (Pcs)'), fieldtype: 'Int', change: check });
		this._ctl('.f-sample', { fieldname: 'sample_size', label: __('Sample Size Taken'), fieldtype: 'Int', change: check });
		this._ctl('.f-reason', { fieldname: 'rejection_reason', label: __('Rejection Reason'), fieldtype: 'Select', options: [''].concat(['Seal Leak', 'Underweight', 'Damaged Packaging', 'Contamination', 'Other']) });
		this._ctl('.f-category', {
			fieldname: 'rejection_category', label: __('Rejection Category'), fieldtype: 'Select',
			options: ['', 'Direct Reject', 'Chance of Repair', 'Improvement Required'], change: check,
		});
		this._ctl('.f-remarks', { fieldname: 'qc_remarks', label: __('QC Remarks'), fieldtype: 'Small Text', description: __('Mandatory if any parameter is marked Fail.') });
		this._ctl('.f-rqty', { fieldname: 'rework_qty_kg', label: __('Rework Quantity (KG)'), fieldtype: 'Float', precision: 3 });
		this._ctl('.f-rproc', { fieldname: 'rework_process', label: __('Process'), fieldtype: 'Link', options: 'Process Master', get_query() { return { filters: { is_active: 1 } }; } });
		this._ctl('.f-rremark', { fieldname: 'rework_remark', label: __('Remark'), fieldtype: 'Small Text' });
		this._ctl('.f-links', { fieldname: 'links', label: __('Stock / Rework'), fieldtype: 'HTML' });
	}

	handle_route() {
		const route = frappe.get_route() || [];
		this.docname = route[1] && route[1] !== 'new' ? route[1] : null;
		this.load();
	}

	load() {
		const docname = this.docname;
		frappe.call({
			method: 'alpinos.production.final_qc.get_qc_context', args: { final_qc: docname || '' }, freeze: true,
			callback: (r) => {
				if (docname !== this.docname) return;
				this.ctx = r.message || {};
				this.loading = true;
				if (this.ctx.doc) this.fill(this.ctx.doc); else this.reset();
				this.loading = false;
				this.apply_state();
				const opts = frappe.route_options || {};
				frappe.route_options = null;
				if (!this.ctx.doc && opts.fg_batch) { this._set('fg_batch', opts.fg_batch); }
			},
		});
	}

	reset() {
		Object.keys(this.fields).forEach((f) => { if (f !== 'links') this._set(f, ''); });
		this._set('qc_status', 'Draft');
		this.tests = (this.ctx.tests || []).map((t) => ({ test_name: t, test_result: '', test_remarks: '' }));
		this.page.set_title(__('New Final QC'));
	}

	fill(d) {
		['name', 'fg_batch', 'qc_status', 'inspector', 'production_date', 'total_inward_pcs', 'sub_order', 'parent_po', 'filling_inward',
			'approved_pcs', 'rejected_pcs', 'sample_size', 'rejection_reason', 'rejection_category', 'qc_remarks', 'rework_qty_kg',
			'rework_process', 'rework_remark'].forEach((f) => this._set(f, d[f]));
		this._set('sku', `${d.target_sku || ''}${d.sku_name && d.sku_name !== d.target_sku ? ' — ' + d.sku_name : ''}`);
		this._set('line', d.filling_line);
		this.size_kg = flt(d.size_kg);
		this.tests = (d.tests || []).map((t) => ({ test_name: t.test_name, test_result: t.test_result || '', test_remarks: t.test_remarks || '' }));
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const links = [['transfer_entry', 'stock-entry', __('Transfer')], ['sample_entry', 'stock-entry', __('Sample write-off')], ['rework_sub_order', 'work-order', __('Rework Sub-PO')]]
			.filter(([f]) => d[f]).map(([f, route, lbl]) => `${lbl}: <a href="/app/${route}/${esc(d[f])}">${esc(d[f])}</a>`).join('<br>');
		this.fields.links.$wrapper.html(links ? `<div style="margin-top:8px;">${links}</div>` : '');
		this.page.set_title(`${d.name} — ${d.qc_status}`);
	}

	on_batch(batch) {
		if (!batch) return;
		frappe.call({
			method: 'alpinos.production.final_qc.get_batch_info', args: { fg_batch: batch },
			callback: (r) => {
				const m = r.message || {};
				if (m.existing_qc) { frappe.set_route('final_qc_entry', m.existing_qc); return; }
				this._set('sku', `${m.target_sku || ''}${m.sku_name && m.sku_name !== m.target_sku ? ' — ' + m.sku_name : ''}`);
				this._set('line', m.line_label || m.filling_line);
				['production_date', 'total_inward_pcs', 'sub_order', 'parent_po', 'filling_inward'].forEach((f) => this._set(f, m[f]));
				this.size_kg = flt(m.size_kg);
				const $b = this.wrapper.find('.fqe-banner').empty();
				if (m.approval_status === 'Pending') $b.html(`<div class="alert alert-danger">${__('Filling wastage for this batch is awaiting approval; it cannot be released yet.')}</div>`);
				this.render_check();
			},
		});
	}

	editable() { return !!cint(this.ctx.can_write) && (!this.ctx.doc || cint(this.ctx.doc.docstatus) === 0); }

	apply_state() {
		const ed = this.editable();
		this._ro('fg_batch', !(ed && !this.ctx.doc));
		['approved_pcs', 'rejected_pcs', 'sample_size', 'rejection_reason', 'rejection_category', 'qc_remarks', 'rework_qty_kg', 'rework_process', 'rework_remark']
			.forEach((f) => this._ro(f, !ed));
		this.render_tests();
		this.render_check();
		this.page.clear_primary_action();
		this.page.clear_inner_toolbar();
		if (ed) {
			this.page.set_primary_action(__('Save'), () => this.save());
			this.page.add_inner_button(__('Approve Batch'), () => this.decide('Approve Batch'));
			this.page.add_inner_button(__('Partial Approval'), () => this.decide('Partial Approval'));
			this.page.add_inner_button(__('Reject Batch'), () => this.decide('Reject Batch'));
		}
		if (cint(this.ctx.can_revoke)) this.page.add_inner_button(__('Revoke QC Approval'), () => this.revoke());
		const d = this.ctx.doc;
		const $b = this.wrapper.find('.fqe-banner');
		if (d && d.qc_status === 'Pending Lab Test') $b.html(`<div class="alert alert-warning">${__('A lab test is Pending. The batch stays FG-Hold until the result is entered and a decision is made.')}</div>`);
		else if (d && d.qc_status === 'Revoked') $b.html(`<div class="alert alert-warning">${__('This approval was revoked: {0}', [frappe.utils.escape_html(d.revoke_reason || '')])}</div>`);
		else if (!d) $b.empty();
	}

	render_tests() {
		const ed = this.editable();
		const $b = this.wrapper.find('.fqe-tests tbody').empty();
		this.tests.forEach((t, idx) => {
			const $tr = $(`<tr><td>${frappe.utils.escape_html(t.test_name)}</td><td class="c-res"></td><td class="c-rem"></td></tr>`);
			$b.append($tr);
			const res = frappe.ui.form.make_control({
				df: { fieldtype: 'Select', fieldname: 'res_' + idx, options: ['', 'Pass', 'Fail', 'Pending'], read_only: ed ? 0 : 1, change() { t.test_result = this.get_value() || ''; } },
				parent: $tr.find('.c-res'), render_input: true, only_input: true,
			});
			res.refresh(); res.set_value(t.test_result || '');
			const rem = frappe.ui.form.make_control({
				df: { fieldtype: 'Data', fieldname: 'rem_' + idx, read_only: ed ? 0 : 1, change() { t.test_remarks = this.get_value() || ''; } },
				parent: $tr.find('.c-rem'), render_input: true, only_input: true,
			});
			rem.refresh(); rem.set_value(t.test_remarks || '');
		});
	}

	render_check() {
		const a = cint(this._val('approved_pcs')), r = cint(this._val('rejected_pcs')), s = cint(this._val('sample_size'));
		const total = cint(this._val('total_inward_pcs'));
		const ok = a + r + s === total;
		this.wrapper.find('.fqe-check').html(`<span class="${ok ? 'fqe-ok' : 'fqe-bad'}">${a} + ${r} + ${s} = ${a + r + s} / ${total}</span>`);
		const cat = this._val('rejection_category');
		this.wrapper.find('.fqe-rework').toggle(cat === 'Chance of Repair' || cat === 'Improvement Required');
		if ((cat === 'Chance of Repair' || cat === 'Improvement Required') && !flt(this._val('rework_qty_kg')) && r && this.size_kg) {
			this._set('rework_qty_kg', flt(r * this.size_kg, 3));
		}
	}

	payload() {
		const p = { name: this.docname || '', fg_batch: this._val('fg_batch'), tests: this.tests };
		['approved_pcs', 'rejected_pcs', 'sample_size', 'rejection_reason', 'rejection_category', 'qc_remarks', 'rework_qty_kg', 'rework_process', 'rework_remark']
			.forEach((f) => { p[f] = this._val(f); });
		return p;
	}

	save() {
		frappe.call({
			method: 'alpinos.production.final_qc.save_qc', args: { payload: this.payload() }, freeze: true,
			callback: (r) => {
				if (!r.message) return;
				frappe.show_alert({ message: __('Saved {0} ({1})', [r.message.name, r.message.qc_status]), indicator: 'green' });
				if (this.docname !== r.message.name) frappe.set_route('final_qc_entry', r.message.name); else this.load();
			},
		});
	}

	decide(decision) {
		const go = () => frappe.call({
			method: 'alpinos.production.final_qc.decide_qc', args: { payload: this.payload(), decision }, freeze: true,
			callback: (r) => {
				if (!r.message) return;
				let msg = __('{0}: {1}', [r.message.name, r.message.qc_status]);
				if (r.message.rework_sub_order) msg += '<br>' + __('Rework Sub-PO {0} created.', [r.message.rework_sub_order]);
				frappe.msgprint({ title: __('Final QC Recorded'), message: msg, indicator: 'green' });
				if (this.docname !== r.message.name) frappe.set_route('final_qc_entry', r.message.name); else this.load();
			},
		});
		if (decision === 'Partial Approval' && !cint(this._val('rejected_pcs'))) {
			// FRD 9.3 UI pop-up: "How many pieces are Rejected?"
			frappe.prompt([{ fieldname: 'rejected', label: __('How many pieces are Rejected?'), fieldtype: 'Int', reqd: 1 }], (v) => {
				this._set('rejected_pcs', cint(v.rejected));
				const total = cint(this._val('total_inward_pcs')), s = cint(this._val('sample_size'));
				if (!cint(this._val('approved_pcs'))) this._set('approved_pcs', Math.max(total - cint(v.rejected) - s, 0));
				setTimeout(() => frappe.confirm(__('Record Partial Approval?'), go), 300);
			}, __('Partial Approval'));
			return;
		}
		frappe.confirm(__('Record "{0}" for batch {1}? This cannot be edited afterwards.', [decision, this._val('fg_batch')]), go);
	}

	revoke() {
		frappe.prompt([{ fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', reqd: 1 }], (v) => frappe.call({
			method: 'alpinos.production.final_qc.revoke_qc', args: { final_qc: this.docname, reason: v.reason }, freeze: true,
			callback: () => this.load(),
		}), __('Revoke QC Approval'), __('Revoke'));
	}
};
