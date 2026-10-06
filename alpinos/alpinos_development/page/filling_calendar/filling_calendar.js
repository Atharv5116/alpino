/**
 * Filling Plan Calendar (FRD 6.6). Month / Week / Day views; one card per plan coloured by
 * status (Grey Planned, Yellow In Progress, Green Completed, Red Short-Closed / Re-Routed);
 * filters Filling Line, Target SKU, Status; click a card for its split rows and loss.
 */

frappe.pages['filling_calendar'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Filling Calendar'), single_column: true });
	wrapper.filling_calendar = new AlpinosFillingCalendar(page);
};

frappe.pages['filling_calendar'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb(__('Filling Planning'), '/app/filling_plan_list');
	if (wrapper.filling_calendar) wrapper.filling_calendar.refresh();
};

var AlpinosFillingCalendar = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.mode = 'Month';
		this.anchor = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		this.filters = { filling_line: '', sku: '', status: '' };
		this.plans = {};
		this.render_shell();
		this.make_filters();
		this.page.set_primary_action(__('+ New Plan'), () => frappe.set_route('filling_plan_entry', 'new'));
		this.page.add_inner_button(__('Plan List'), () => frappe.set_route('filling_plan_list'));
		const me = this;
		this.wrapper.on('click', '.fc-mode', function () { me.mode = $(this).attr('data-mode'); me.refresh(); });
		this.wrapper.on('click', '.fc-prev', () => this.shift(-1));
		this.wrapper.on('click', '.fc-next', () => this.shift(1));
		this.wrapper.on('click', '.fc-today', () => { this.anchor = frappe.datetime.str_to_obj(frappe.datetime.get_today()); this.refresh(); });
		this.wrapper.on('click', '.fc-card', function () { me.show_plan($(this).attr('data-name')); });
	}

	render_shell() {
		this.wrapper.html(`
			<div class="fc">
				<style>
					.fc .fc-bar { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px; }
					.fc .fc-bar > div { min-width:160px; }
					.fc .fc-title { font-size:16px; font-weight:600; margin:0 12px; }
					.fc .fc-grid { display:grid; grid-template-columns:repeat(7, minmax(0,1fr)); border-left:1px solid var(--border-color); border-top:1px solid var(--border-color); }
					.fc .fc-grid.fc-day-mode { grid-template-columns:1fr; }
					.fc .fc-head { font-size:11px; text-transform:uppercase; color:var(--text-muted); padding:4px 6px; border-right:1px solid var(--border-color); border-bottom:1px solid var(--border-color); background:var(--subtle-fg,#f7f7f7); }
					.fc .fc-cell { min-height:110px; padding:4px; border-right:1px solid var(--border-color); border-bottom:1px solid var(--border-color); }
					.fc .fc-cell.fc-out { background:var(--subtle-fg,#fafafa); opacity:.6; }
					.fc .fc-cell.fc-now .fc-date { color:var(--primary); font-weight:700; }
					.fc .fc-date { font-size:11px; color:var(--text-muted); margin-bottom:3px; }
					.fc .fc-card { border-radius:5px; padding:4px 6px; margin-bottom:4px; font-size:11px; line-height:1.3; cursor:pointer; border-left:4px solid; }
					.fc .fc-card.st-planned { background:#f0f0f0; border-color:#9e9e9e; }
					.fc .fc-card.st-progress { background:#fff8db; border-color:#e6b800; }
					.fc .fc-card.st-done { background:#e6f6ea; border-color:#2e9e4f; }
					.fc .fc-card.st-red { background:#fdeaea; border-color:#d33; }
					.fc .fc-card .fc-flag { color:#d33; font-weight:700; }
					.fc .fc-legend span { display:inline-block; margin-right:14px; font-size:12px; }
					.fc .fc-legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:middle; }
				</style>
				<div class="fc-bar">
					<div class="btn-group">
						<button class="btn btn-sm btn-default fc-mode" data-mode="Month">${__('Month')}</button>
						<button class="btn btn-sm btn-default fc-mode" data-mode="Week">${__('Week')}</button>
						<button class="btn btn-sm btn-default fc-mode" data-mode="Day">${__('Day')}</button>
					</div>
					<div style="min-width:auto;"><button class="btn btn-sm btn-default fc-prev">‹</button>
					<button class="btn btn-sm btn-default fc-today">${__('Today')}</button>
					<button class="btn btn-sm btn-default fc-next">›</button><span class="fc-title"></span></div>
					<div class="f-line"></div><div class="f-sku"></div><div class="f-status"></div>
				</div>
				<div class="fc-legend" style="margin-bottom:8px;">
					<span><i style="background:#9e9e9e"></i>${__('Planned')}</span><span><i style="background:#e6b800"></i>${__('In Progress')}</span>
					<span><i style="background:#2e9e4f"></i>${__('Completed')}</span><span><i style="background:#d33"></i>${__('Short-Closed / Re-Routed')}</span>
				</div>
				<div class="fc-body"></div>
			</div>`);
	}

	make_filters() {
		const me = this;
		const mk = (sel, df) => {
			const c = frappe.ui.form.make_control({
				df: Object.assign({ change() { me.filters[df.fieldname] = this.get_value() || ''; me.refresh(); } }, df),
				parent: this.wrapper.find(sel), render_input: true,
			});
			c.refresh();
		};
		mk('.f-line', { fieldname: 'filling_line', label: __('Filling Line'), fieldtype: 'Link', options: 'Machine' });
		mk('.f-sku', { fieldname: 'sku', label: __('Target SKU'), fieldtype: 'Link', options: 'Item' });
		mk('.f-status', { fieldname: 'status', label: __('Status'), fieldtype: 'Select', options: ['', 'Planned', 'In Progress', 'Completed', 'Short-Closed', 'Re-Routed'] });
	}

	range() {
		const a = new Date(this.anchor.getTime());
		let from, to;
		if (this.mode === 'Day') { from = to = a; }
		else if (this.mode === 'Week') {
			from = new Date(a); from.setDate(a.getDate() - ((a.getDay() + 6) % 7));
			to = new Date(from); to.setDate(from.getDate() + 6);
		} else {
			const first = new Date(a.getFullYear(), a.getMonth(), 1);
			const last = new Date(a.getFullYear(), a.getMonth() + 1, 0);
			from = new Date(first); from.setDate(first.getDate() - ((first.getDay() + 6) % 7));
			to = new Date(last); to.setDate(last.getDate() + (6 - ((last.getDay() + 6) % 7)));
		}
		return [from, to];
	}

	shift(n) {
		const a = this.anchor;
		if (this.mode === 'Month') this.anchor = new Date(a.getFullYear(), a.getMonth() + n, 1);
		else this.anchor = new Date(a.getFullYear(), a.getMonth(), a.getDate() + n * (this.mode === 'Week' ? 7 : 1));
		this.refresh();
	}

	fmt(d) { return frappe.datetime.obj_to_str(d).slice(0, 10); }

	refresh() {
		this.wrapper.find('.fc-mode').removeClass('btn-primary').addClass('btn-default');
		this.wrapper.find(`.fc-mode[data-mode="${this.mode}"]`).addClass('btn-primary').removeClass('btn-default');
		const [from, to] = this.range();
		frappe.call({
			method: 'alpinos.production.filling_plan.get_calendar',
			args: Object.assign({ date_from: this.fmt(from), date_to: this.fmt(to) }, this.filters),
			callback: (r) => this.render(from, to, (r.message || {}).plans || []),
		});
	}

	cls(status) {
		return { 'Planned': 'st-planned', 'In Progress': 'st-progress', 'Completed': 'st-done' }[status] || 'st-red';
	}

	render(from, to, plans) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		this.plans = {};
		const byDate = {};
		plans.forEach((p) => { this.plans[p.name] = p; (byDate[p.plan_date] = byDate[p.plan_date] || []).push(p); });
		const months = [__('January'), __('February'), __('March'), __('April'), __('May'), __('June'), __('July'), __('August'), __('September'), __('October'), __('November'), __('December')];
		const a = this.anchor;
		const title = this.mode === 'Month' ? `${months[a.getMonth()]} ${a.getFullYear()}`
			: this.mode === 'Week' ? `${frappe.datetime.str_to_user(this.fmt(from))} – ${frappe.datetime.str_to_user(this.fmt(to))}`
			: frappe.datetime.str_to_user(this.fmt(from));
		this.wrapper.find('.fc-title').text(title);
		const today = frappe.datetime.get_today();
		let html = `<div class="fc-grid ${this.mode === 'Day' ? 'fc-day-mode' : ''}">`;
		if (this.mode !== 'Day') [__('Mon'), __('Tue'), __('Wed'), __('Thu'), __('Fri'), __('Sat'), __('Sun')].forEach((d) => { html += `<div class="fc-head">${d}</div>`; });
		for (let d = new Date(from); d <= to; d.setDate(d.getDate() + 1)) {
			const key = this.fmt(d);
			const out = this.mode === 'Month' && d.getMonth() !== a.getMonth();
			html += `<div class="fc-cell ${out ? 'fc-out' : ''} ${key === today ? 'fc-now' : ''}" style="${this.mode !== 'Month' ? 'min-height:300px;' : ''}">
				<div class="fc-date">${d.getDate()}</div>
				${(byDate[key] || []).map((p) => `<div class="fc-card ${this.cls(p.status)}" data-name="${esc(p.name)}">
					<div><b>${esc(p.line_label)}</b> ${cint(p.has_pending_approval) ? '<span class="fc-flag">!</span>' : ''}</div>
					<div>${esc((p.rows || []).map((r) => r.sku_name || r.target_sku).join(', '))}</div>
					<div>${esc(p.sub_order)}</div>
					<div>${__('Done')} ${cint(p.total_completed_pcs)} / ${__('Pending')} ${cint(p.total_pending_pcs)}</div>
				</div>`).join('')}
			</div>`;
		}
		html += '</div>';
		this.wrapper.find('.fc-body').html(html);
	}

	show_plan(name) {
		const p = this.plans[name];
		if (!p) return;
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const d = new frappe.ui.Dialog({
			title: `${p.name} — ${p.status}`, size: 'large',
			fields: [{ fieldname: 'body', fieldtype: 'HTML' }],
			primary_action_label: __('Open Plan'),
			primary_action() { d.hide(); frappe.set_route('filling_plan_entry', p.name); },
		});
		d.fields_dict.body.$wrapper.html(`
			<p>${__('Line')}: <b>${esc(p.line_label)}</b> · ${__('Sub-PO')}: <b>${esc(p.sub_order)}</b> · ${__('Parent PO')}: ${esc(p.parent_po)} · ${__('Date')}: ${esc(frappe.datetime.str_to_user(p.plan_date))}</p>
			<table class="table table-bordered table-condensed"><thead><tr><th>${__('Target SKU')}</th><th>${__('Size')}</th><th>${__('Planned')}</th>
			<th>${__('Completed')}</th><th>${__('Pending')}</th><th>${__('Written Off')}</th><th>${__('Re-Routed')}</th><th>${__('Filled KG')}</th><th>${__('Wastage KG')}</th><th>${__('Row')}</th></tr></thead><tbody>
			${(p.rows || []).map((r) => `<tr><td>${esc(r.sku_name || r.target_sku)}</td><td>${flt(r.size_kg, 3)}</td><td>${cint(r.planned_pcs)}</td><td>${cint(r.completed_pcs)}</td>
				<td>${cint(r.pending_pcs)}</td><td>${cint(r.written_off_pcs)}</td><td>${cint(r.rerouted_pcs)}</td><td>${flt(r.filled_kg, 3)}</td><td>${flt(r.wastage_kg, 3)}</td><td>${esc(r.row_status)}</td></tr>`).join('')}
			</tbody></table>
			<p>${__('Total Wastage')}: <b>${flt(p.total_wastage_kg, 3)} KG</b> · ${__('Process Loss logged')}: <b>${flt(p.loss_kg, 3)} KG</b></p>
			${cint(p.has_pending_approval) ? `<div class="alert alert-danger">${__('Abnormal wastage awaiting approval.')}</div>` : ''}`);
		d.show();
	}
};
