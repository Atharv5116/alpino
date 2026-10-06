/**
 * Filling Entry — operator screen (FRD 6.3, 6.4, 7.1–7.4, 8.4.3).
 *
 * Pick an active plan row; plan details are read-only and inherited from the plan. Enter
 * Today's Input (Pcs), Filling Wastage (KG), Partial / Final Inward and, for an empty hopper
 * with pending pieces, Mark Run Complete. Submit Inward validates and posts on the server
 * (alpinos.production.filling_inward); Generate FG Labels becomes active after a successful
 * submission and prints Today's Input copies of the FG label.
 */

frappe.pages['filling_entry'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Filling Entry'), single_column: true });
	wrapper.filling_entry = new AlpinosFillingEntry(page);
};

frappe.pages['filling_entry'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb();
	if (wrapper.filling_entry) wrapper.filling_entry.load();
};

var AlpinosFillingEntry = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.fields = {};
		this.ctx = {};
		this.current = null;
		this.last = null;
		this.render_shell();
		this.make_fields();
		this.bind();
		this.page.set_primary_action(__('Submit Inward'), () => this.submit());
		this.page.add_inner_button(__('Generate FG Labels'), () => this.labels(this.last));
		this.page.add_inner_button(__('Filling Plans'), () => frappe.set_route('filling_plan_list'));
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fe">
				<style>
					.fe .fe-card { background:var(--card-bg,#fff); border:1px solid var(--border-color,#e2e2e2); border-radius:8px; padding:16px 18px; margin-bottom:16px; }
					.fe .fe-card > h5 { margin:0 0 12px; font-size:13px; text-transform:uppercase; letter-spacing:.4px; color:var(--text-muted); }
					.fe .fe-big { font-size:22px; font-weight:700; }
					.fe .fe-stat { text-align:center; padding:8px; border-radius:6px; background:var(--subtle-fg,#f5f5f5); }
					.fe .fe-stat .lbl { font-size:11px; text-transform:uppercase; color:var(--text-muted); }
					.fe .fe-num { text-align:right; white-space:nowrap; }
					.fe tr.fe-flag td { background:var(--red-50,#fff1f0); }
					.fe .fe-comp { display:none; }
				</style>
				<div class="fe-banner"></div>
				<div class="fe-card"><h5>${__('Active Plan')}</h5>
					<div class="row"><div class="col-md-8 f-pick"></div><div class="col-md-4 f-shift"></div></div>
					<div class="row"><div class="col-md-3 f-date"></div><div class="col-md-3 f-line"></div><div class="col-md-3 f-parent"></div><div class="col-md-3 f-sub"></div></div>
					<div class="row"><div class="col-md-3 f-sku"></div><div class="col-md-3 f-size"></div><div class="col-md-3 f-cat"></div><div class="col-md-3 f-wip"></div></div>
					<div class="row" style="margin-top:6px;">
						<div class="col-md-4"><div class="fe-stat"><div class="lbl">${__('Target Plan (Pcs)')}</div><div class="fe-big s-plan">–</div></div></div>
						<div class="col-md-4"><div class="fe-stat"><div class="lbl">${__('Completed (Pcs)')}</div><div class="fe-big s-done">–</div></div></div>
						<div class="col-md-4"><div class="fe-stat"><div class="lbl">${__('Pending (Pcs)')}</div><div class="fe-big s-pending">–</div></div></div>
					</div>
				</div>
				<div class="fe-card"><h5>${__("Today's Input")}</h5>
					<div class="row"><div class="col-md-3 f-pcs"></div><div class="col-md-3 f-eq"></div><div class="col-md-3 f-wastage"></div><div class="col-md-3 f-loss"></div></div>
					<div class="row"><div class="col-md-3 f-type"></div><div class="col-md-3 f-complete"></div><div class="col-md-6 f-remarks"></div></div>
					<div class="row fe-comp fe-comp-oats"><div class="col-md-3 f-mfg"></div><div class="col-md-3 f-rmb"></div></div>
					<div class="row fe-comp fe-comp-teamb"><div class="col-md-3 f-man"></div><div class="col-md-3 f-premix"></div></div>
				</div>
				<div class="fe-card"><h5>${__('Recent Inwards')}</h5><div class="fe-recent"></div></div>
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

	make_fields() {
		const me = this;
		const preview = frappe.utils.debounce(() => me.preview(), 300);
		this._ctl('.f-pick', { fieldname: 'pick', label: __('Plan Row'), fieldtype: 'Select', options: [], change() { me.select(this.get_value()); } });
		this._ctl('.f-shift', { fieldname: 'shift', label: __('Shift'), read_only: 1 });
		this._ctl('.f-date', { fieldname: 'plan_date', label: __('Plan Date'), read_only: 1 });
		this._ctl('.f-line', { fieldname: 'line', label: __('Filling Line'), read_only: 1 });
		this._ctl('.f-parent', { fieldname: 'parent_po', label: __('Parent PO'), read_only: 1 });
		this._ctl('.f-sub', { fieldname: 'sub_order', label: __('Sub-PO'), read_only: 1 });
		this._ctl('.f-sku', { fieldname: 'sku', label: __('Target SKU'), read_only: 1 });
		this._ctl('.f-size', { fieldname: 'size', label: __('Size (KG)'), read_only: 1 });
		this._ctl('.f-cat', { fieldname: 'category', label: __('Filling Category'), read_only: 1 });
		this._ctl('.f-wip', { fieldname: 'wip', label: __('Available WIP (KG)'), read_only: 1 });
		this._ctl('.f-pcs', { fieldname: 'input_pcs', label: __("Today's Input (Pcs)"), fieldtype: 'Int', change: preview });
		this._ctl('.f-eq', { fieldname: 'equivalent_kg', label: __('Equivalent (KG)'), read_only: 1 });
		this._ctl('.f-wastage', { fieldname: 'wastage_kg', label: __('Filling Wastage (KG)'), fieldtype: 'Float', precision: 3, change: preview });
		this._ctl('.f-loss', { fieldname: 'loss', label: __('Process Loss (%)'), read_only: 1 });
		this._ctl('.f-type', { fieldname: 'submission_type', label: __('Submission Type'), fieldtype: 'Select', options: ['Partial Inward', 'Final Inward'], change: preview }, 'Partial Inward');
		this._ctl('.f-complete', {
			fieldname: 'mark_run_complete', label: __('Mark Run Complete'), fieldtype: 'Check',
			description: __('Hopper empty but pieces still pending: writes off the pending pieces and closes the plan.'), change: preview,
		});
		this._ctl('.f-remarks', { fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text' });
		this._ctl('.f-mfg', { fieldname: 'mfg_date', label: __('MFG Date'), fieldtype: 'Date' }, frappe.datetime.get_today());
		this._ctl('.f-rmb', { fieldname: 'rm_batch_ref', label: __('RM Batch Tracking') });
		this._ctl('.f-man', { fieldname: 'manpower_count', label: __('Manpower'), fieldtype: 'Int' });
		this._ctl('.f-premix', { fieldname: 'premix_code', label: __('Pre-Mix Code') });
	}

	bind() {
		const me = this;
		this.wrapper.on('click', '.fe-label', function () { me.labels({ fg_batch: $(this).attr('data-batch'), input_pcs: cint($(this).attr('data-pcs')) }); });
		this.wrapper.on('click', '.fe-approve', function () { me.approve($(this).attr('data-name')); });
		this.wrapper.on('click', '.fe-reverse', function () { me.reverse($(this).attr('data-name')); });
	}

	load() {
		frappe.call({
			method: 'alpinos.production.filling_inward.get_entry_context',
			callback: (r) => {
				this.ctx = r.message || {};
				const opts = (this.ctx.options || []).map((o) => ({
					value: `${o.plan}::${o.row}`,
					label: `${o.line_label} · ${o.sku_name || o.target_sku} · ${o.sub_order} · ${__('pending')} ${cint(o.pending_pcs)} (${o.plan})`,
				}));
				const pick = this.fields.pick;
				pick.df.options = [{ value: '', label: opts.length ? __('Choose a plan row…') : __('No open plans') }].concat(opts);
				pick.refresh();
				const keep = this.current && opts.find((o) => o.value === `${this.current.plan}::${this.current.row}`);
				pick.set_value(keep ? keep.value : '');
				this.select(keep ? keep.value : '');
				this._set('shift', this.ctx.shift || '');
				this.page.btn_primary.toggle(!!cint(this.ctx.can_submit));
				this.toggle_labels();
				this.render_recent();
			},
		});
	}

	select(value) {
		const o = (this.ctx.options || []).find((x) => `${x.plan}::${x.row}` === value) || null;
		this.current = o;
		const $b = this.wrapper.find('.fe-banner').empty();
		this._set('plan_date', o ? frappe.datetime.str_to_user(o.plan_date) : '');
		this._set('line', o ? o.line_label : '');
		this._set('parent_po', o ? o.parent_po : '');
		this._set('sub_order', o ? `${o.sub_order}${o.batch_number ? ' (' + o.batch_number + ')' : ''}` : '');
		this._set('sku', o ? `${o.target_sku}${o.sku_name && o.sku_name !== o.target_sku ? ' — ' + o.sku_name : ''}` : '');
		this._set('size', o ? flt(o.size_kg, 3) : '');
		this._set('category', o ? o.line_category : '');
		this._set('wip', o ? flt(o.wip_qty, 3) : '');
		this.wrapper.find('.s-plan').text(o ? cint(o.planned_pcs) : '–');
		this.wrapper.find('.s-done').text(o ? cint(o.completed_pcs) : '–');
		this.wrapper.find('.s-pending').text(o ? cint(o.pending_pcs) : '–');
		// FRD 8.4.3 component injection by the machine's Filling Category.
		// default pending BA confirmation: categories named like "Oats" get MFG Date / RM batch,
		// "Team B" gets manpower / pre-mix; any other category shows both.
		const cat = ((o && o.line_category) || '').toLowerCase();
		const oats = cat.includes('oat'), teamb = cat.includes('team b');
		this.wrapper.find('.fe-comp-oats').toggle(!!o && (oats || !teamb));
		this.wrapper.find('.fe-comp-teamb').toggle(!!o && (teamb || !oats));
		if (o && !cint(o.line_active)) $b.html(`<div class="alert alert-danger">${__('This filling line is not Active. Production cannot be recorded on it.')}</div>`);
		['input_pcs', 'wastage_kg', 'equivalent_kg', 'loss'].forEach((f) => this._set(f, ''));
		this._set('submission_type', 'Partial Inward');
		this._set('mark_run_complete', 0);
	}

	payload() {
		const o = this.current || {};
		return {
			filling_plan: o.plan, plan_row: o.row, input_pcs: cint(this._val('input_pcs')), wastage_kg: flt(this._val('wastage_kg')),
			submission_type: this._val('submission_type'), mark_run_complete: cint(this._val('mark_run_complete')),
			mfg_date: this._val('mfg_date'), rm_batch_ref: this._val('rm_batch_ref'), manpower_count: cint(this._val('manpower_count')),
			premix_code: this._val('premix_code'), remarks: this._val('remarks'),
		};
	}

	preview() {
		if (!this.current) return;
		const o = this.current;
		this._set('equivalent_kg', flt(cint(this._val('input_pcs')) * flt(o.size_kg), 3));
		frappe.call({
			method: 'alpinos.production.filling_inward.preview_inward', args: { payload: this.payload() },
			callback: (r) => {
				const m = r.message || {};
				this._set('loss', `${flt(m.process_loss_pct, 2)} % (${flt(m.process_loss_kg, 3)} KG)`);
				const $b = this.wrapper.find('.fe-banner').empty();
				if (cint(this._val('input_pcs')) > cint(o.pending_pcs)) {
					$b.html(`<div class="alert alert-danger">${__('Actual Production Quantity cannot exceed the planned quantity. Please contact the Production Admin to update the plan.')}</div>`);
				} else if (cint(m.empties_hopper)) {
					$b.html(`<div class="alert alert-warning">${__('This Final Inward empties the Sub-PO hopper: any WIP left is written off as process loss.')}</div>`);
				}
			},
		});
	}

	submit() {
		if (!this.current) { frappe.msgprint(__('Choose the plan row you are filling.')); return; }
		const p = this.payload();
		const final = p.submission_type === 'Final Inward' || p.mark_run_complete;
		const msg = final ? __('Submit a FINAL inward of {0} pcs and close this run?', [p.input_pcs]) : __('Submit {0} pcs?', [p.input_pcs]);
		frappe.confirm(msg, () => frappe.call({
			method: 'alpinos.production.filling_inward.submit_inward', args: { payload: p }, freeze: true,
			callback: (r) => {
				const m = r.message;
				if (!m) return;
				this.last = m;
				frappe.msgprint({
					title: __('Inward {0} submitted', [m.name]),
					indicator: cint(m.needs_approval) ? 'orange' : 'green',
					message: (m.fg_batch ? __('FG Batch Code: <b>{0}</b>', [frappe.utils.escape_html(m.fg_batch)]) + '<br>' : '')
						+ __('Process Loss: {0} KG ({1}%)', [flt(m.process_loss_kg, 3), flt(m.process_loss_pct, 2)])
						+ (cint(m.needs_approval) ? '<br>' + __('Wastage is above tolerance; the batch is flagged for approval.') : ''),
				});
				this.load();
			},
		}));
	}

	toggle_labels() {
		const btn = this.page.inner_toolbar && this.page.inner_toolbar.find(`button:contains("${__('Generate FG Labels')}")`);
		if (btn && btn.length) btn.prop('disabled', !(this.last && this.last.fg_batch));
	}

	labels(row) {
		if (!row || !row.fg_batch) { frappe.msgprint(__('Submit an inward first.')); return; }
		const url = `/printview?doctype=Batch&name=${encodeURIComponent(row.fg_batch)}&format=${encodeURIComponent('FG Label')}`
			+ `&no_letterhead=1&trigger_print=1&copies=${Math.max(cint(row.input_pcs), 1)}`;
		window.open(url, '_blank');
	}

	render_recent() {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const list = this.ctx.recent || [];
		const canRev = cint(this.ctx.can_reverse), canApp = cint(this.ctx.can_approve);
		this.wrapper.find('.fe-recent').html(list.length ? `<div class="table-responsive"><table class="table table-bordered table-condensed"><thead><tr>
			<th>${__('Inward')}</th><th>${__('Date')}</th><th>${__('Plan')}</th><th>${__('SKU')}</th><th class="fe-num">${__('Pcs')}</th>
			<th class="fe-num">${__('Wastage KG')}</th><th class="fe-num">${__('Loss %')}</th><th>${__('Type')}</th><th>${__('FG Batch')}</th><th>${__('Approval')}</th><th></th></tr></thead><tbody>
			${list.map((r) => `<tr class="${r.approval_status === 'Pending' ? 'fe-flag' : ''}">
				<td><a href="/app/filling-inward/${esc(r.name)}">${esc(r.name)}</a></td><td>${esc(frappe.datetime.str_to_user(r.posting_date))}</td>
				<td>${esc(r.filling_plan)}</td><td>${esc(r.target_sku)}</td><td class="fe-num">${cint(r.input_pcs)}</td>
				<td class="fe-num">${flt(r.wastage_kg, 3)}</td><td class="fe-num">${flt(r.process_loss_pct, 2)}</td><td>${esc(r.submission_type)}</td>
				<td>${esc(r.fg_batch || '')}</td><td>${r.approval_status === 'Pending' ? `<span class="indicator-pill red">${__('Pending')}</span>` : esc(r.approval_status || '')}</td>
				<td style="white-space:nowrap;">
					${r.fg_batch ? `<button class="btn btn-xs btn-default fe-label" data-batch="${esc(r.fg_batch)}" data-pcs="${cint(r.input_pcs)}">${__('Labels')}</button>` : ''}
					${canApp && r.approval_status === 'Pending' ? `<button class="btn btn-xs btn-primary fe-approve" data-name="${esc(r.name)}">${__('Approve')}</button>` : ''}
					${canRev ? `<button class="btn btn-xs btn-danger fe-reverse" data-name="${esc(r.name)}">${__('Reverse & Adjust')}</button>` : ''}
				</td></tr>`).join('')}</tbody></table></div>` : `<p class="text-muted">${__('No inwards yet.')}</p>`);
	}

	approve(name) {
		frappe.prompt([{ fieldname: 'remarks', label: __('Approval Remarks'), fieldtype: 'Small Text' }], (v) => frappe.call({
			method: 'alpinos.production.filling_inward.approve_wastage', args: { inward: name, remarks: v.remarks }, freeze: true,
			callback: () => this.load(),
		}), __('Approve abnormal wastage on {0}', [name]), __('Approve'));
	}

	reverse(name) {
		frappe.prompt([{ fieldname: 'reason', label: __('Reason'), fieldtype: 'Small Text', reqd: 1 }], (v) => frappe.call({
			method: 'alpinos.production.filling_inward.reverse_inward', args: { inward: name, reason: v.reason }, freeze: true,
			callback: () => { frappe.show_alert({ message: __('{0} reversed. Record the corrected inward.', [name]), indicator: 'orange' }); this.load(); },
		}), __('Reverse & Adjust {0}', [name]), __('Reverse'));
	}
};
