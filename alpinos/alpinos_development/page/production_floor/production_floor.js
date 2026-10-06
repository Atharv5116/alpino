/**
 * Shop Floor (/app/production_floor) -- FRD Phase 4.
 *
 * One card per Sub PO, or per Machine Run when Sub POs were merged (BR-MRG-02: the run is
 * what the operator works on). The gate (VAL-GATE-01/02/03), Start / Pause / Resume /
 * Complete Production and Create Inward Entry. Every button only calls the server, which
 * enforces the rule again; the buttons are drawn only when the server says they apply.
 */

frappe.pages['production_floor'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Shop Floor'), single_column: true });
	wrapper.production_floor = new ProductionFloor(page);
};

frappe.pages['production_floor'].on_page_show = function (wrapper) {
	window.alpinos_production_breadcrumb && alpinos_production_breadcrumb();
	if (wrapper.production_floor) wrapper.production_floor.on_show();
};

var ProductionFloor = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		this.data = null;
		this.offset = 0;
		this.make_filters();
		this.render_shell();
		this.page.set_primary_action(__('Refresh'), () => this.refresh(), 'refresh');
		this.page.add_inner_button(__('Production QC'), () => frappe.set_route('production_qc_list'));
		this.tick = setInterval(() => this.update_timers(), 1000);
		this.poll = setInterval(() => { if (!document.hidden && this.is_visible()) this.refresh(true); }, 60000);
	}

	is_visible() {
		return (frappe.get_route() || [])[0] === 'production_floor';
	}

	on_show() {
		if (frappe.route_options && frappe.route_options.sub_order) {
			this.f.search.set_value(frappe.route_options.sub_order);
			frappe.route_options = null;
		}
		this.refresh();
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	make_filters() {
		const p = this.page;
		const go = () => this.refresh();
		this.f = {
			search: p.add_field({ fieldname: 'search', label: __('Sub PO / Batch / Item'), fieldtype: 'Data', change: go }),
			process: p.add_field({ fieldname: 'process', label: __('Process'), fieldtype: 'Select', options: [''], change: go }),
			machine: p.add_field({ fieldname: 'machine', label: __('Machine'), fieldtype: 'Select', options: [''], change: go }),
			date_from: p.add_field({ fieldname: 'date_from', label: __('Planned From'), fieldtype: 'Date', change: go }),
			date_to: p.add_field({ fieldname: 'date_to', label: __('Planned To'), fieldtype: 'Date', change: go }),
			status: p.add_field({ fieldname: 'status', label: __('Status'), fieldtype: 'Select', options: [''], change: go }),
		};
	}

	render_shell() {
		this.wrapper.html(`
			<div class="pf">
				<style>
					.pf .pf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
					.pf .pf-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e2e2);
						border-radius: 8px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
					.pf .pf-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
					.pf .pf-title { font-weight: 600; font-size: 14px; }
					.pf .pf-sub { font-size: 12px; color: var(--text-muted); }
					.pf .pf-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; font-size: 12.5px; }
					.pf .pf-meta span { color: var(--text-muted); }
					.pf .pf-badge { font-size: 11.5px; padding: 3px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; }
					.pf .b-green { background: #e4f5e9; color: #1e7a3c; }
					.pf .b-blue { background: #e3effd; color: #1c5fb8; }
					.pf .b-red { background: #fde8e8; color: #b42318; }
					.pf .b-orange { background: #fff1e0; color: #b25e09; }
					.pf .b-grey { background: #eef0f2; color: #555; }
					.pf .b-purple { background: #f0e8fd; color: #6b3fb8; }
					.pf .pf-gate { font-size: 12px; color: #b42318; }
					.pf .pf-timer { font-family: var(--font-family-monospace, monospace); font-size: 20px; font-weight: 600; }
					.pf .pf-timer-lbl { font-size: 11px; color: var(--text-muted); }
					.pf .pf-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
					.pf .pf-members { font-size: 12px; }
					.pf .pf-link { cursor: pointer; font-weight: 600; }
					.pf .pf-link:hover { text-decoration: underline; }
					.pf .pf-empty { padding: 50px; text-align: center; color: var(--text-muted); }
				</style>
				<div class="pf-body"><div class="pf-empty">${__('Loading...')}</div></div>
			</div>`);
		const me = this;
		this.wrapper.on('click', '.pf-sub-link', function () {
			frappe.set_route('sub_order_view', $(this).attr('data-name'));
		});
		this.wrapper.on('click', '.pf-act', function () {
			const card = me.cards[$(this).attr('data-key')];
			me.act($(this).attr('data-act'), card);
		});
	}

	args() {
		const v = (k) => this.f[k].get_value() || null;
		return { search: v('search'), process: v('process'), machine: v('machine'),
			date_from: v('date_from'), date_to: v('date_to'), status: v('status') };
	}

	refresh(silent) {
		frappe.call({
			method: 'alpinos.production.execution.get_floor',
			args: this.args(),
			freeze: !silent,
			callback: (r) => {
				this.data = r.message || {};
				this.offset = moment(this.data.server_time).diff(moment());
				this.fill_selects();
				this.render();
			},
		});
	}

	fill_selects() {
		const d = this.data;
		const set = (field, opts) => {
			const current = field.get_value();
			field.df.options = [{ label: '', value: '' }].concat(opts);
			field.refresh();
			if (current) field.set_value(current);
		};
		if (!this._selects_done) {
			set(this.f.process, (d.processes || []).map((p) => ({ label: p.label, value: p.name })));
			set(this.f.status, (d.statuses || []).map((s) => ({ label: __(s), value: s })));
			this._selects_done = true;
		}
		set(this.f.machine, (d.machines || []).map((m) => ({ label: m.label, value: m.name })));
	}

	badge(status) {
		const map = {
			'Ready to Run': 'b-green', 'Running': 'b-blue', 'Paused': 'b-red', 'Process Completed': 'b-purple',
			'Inward Logged': 'b-purple', 'Pending QC': 'b-orange', 'Ready for Next Stage': 'b-green',
		};
		return `<span class="pf-badge ${map[status] || 'b-grey'}">${this.esc(__(status))}</span>`;
	}

	render() {
		const cards = this.data.cards || [];
		this.cards = {};
		const $body = this.wrapper.find('.pf-body');
		if (!cards.length) {
			$body.html(`<div class="pf-empty">${__('No sub orders on the floor for these filters.')}</div>`);
			return;
		}
		$body.html(`<div class="pf-grid">${cards.map((c) => this.card_html(c)).join('')}</div>`);
		this.update_timers();
	}

	card_html(c) {
		this.cards[c.key] = c;
		const e = (v) => this.esc(v);
		const btn = (act, label, cls) =>
			`<button class="btn btn-sm ${cls} pf-act" data-act="${act}" data-key="${e(c.key)}">${e(label)}</button>`;
		const actions = [];
		if (c.can_start) actions.push(btn('start', __('Start Production'), 'btn-primary'));
		if (c.can_pause) actions.push(btn('pause', __('Pause'), 'btn-danger'));
		if (c.can_resume) actions.push(btn('resume', __('Resume'), 'btn-primary'));
		if (c.can_complete) actions.push(btn('complete', __('Complete Production'), 'btn-success'));
		if (c.can_inward) actions.push(btn('inward', __('Create Inward Entry'), 'btn-primary'));
		if (c.open_inward) actions.push(btn('open_inward', __('Open Inward Entry'), 'btn-default'));
		if (c.run) actions.push(btn('log', __('Audit Log'), 'btn-default'));
		const title = c.machine_run
			? `${__('Machine Run')} ${e(c.machine_run)}`
			: `<span class="pf-link pf-sub-link" data-name="${e(c.members[0])}">${e(c.members[0])}</span>`;
		const members = c.machine_run
			? `<div class="pf-members">${__('Merged Sub POs')}: ${c.rows.map((r) =>
				`<span class="pf-link pf-sub-link" data-name="${e(r.name)}">${e(r.name)}</span> (${format_number(r.qty, null, 3)})`).join(', ')}</div>`
			: '';
		const gate = (c.gate || []).length
			? `<div class="pf-gate">${c.gate.map((g) => `&#9888; ${e(g.message)}`).join('<br>')}</div>` : '';
		const timer = c.run && c.run.started_on
			? `<div><div class="pf-timer-lbl">${__('Net run time')}${c.run.status === 'Paused'
				? ` &middot; ${__('Paused')}: ${e(c.run.pause_reason || '')}` : ''}</div>
				<div class="pf-timer" data-key="${e(c.key)}">--:--:--</div></div>` : '';
		return `
			<div class="pf-card">
				<div class="pf-head">
					<div><div class="pf-title">${title}</div>
						<div class="pf-sub">${e(c.production_item)}${c.item_name && c.item_name !== c.production_item ? ' &middot; ' + e(c.item_name) : ''}</div></div>
					${this.badge(c.display_status)}
				</div>
				${members}
				<div class="pf-meta">
					<div><span>${__('Process')}:</span> ${e(c.process_label || '-')}</div>
					<div><span>${__('Machine')}:</span> ${e(c.machine_label || c.machine || '-')}</div>
					<div><span>${__('Planned')}:</span> ${c.planned_date ? frappe.datetime.str_to_user(c.planned_date) : '-'}</div>
					<div><span>${__('Qty (KG)')}:</span> ${format_number(c.qty, null, 3)}</div>
					<div><span>${__('Batch')}:</span> ${e(c.batch || '-')}</div>
					<div><span>${__('Run')}:</span> ${e(c.run ? c.run.name : '-')}</div>
				</div>
				${gate}${timer}
				<div class="pf-actions">${actions.join('')}</div>
			</div>`;
	}

	net_seconds(run) {
		if (!run || !run.started_on) return 0;
		const now = moment().add(this.offset, 'ms');
		const end = run.completed_on ? moment(run.completed_on) : now;
		let secs = end.diff(moment(run.started_on), 'seconds');
		secs -= Math.round(flt(run.downtime_logged) * 60);
		if (run.status === 'Paused' && run.paused_since) secs -= now.diff(moment(run.paused_since), 'seconds');
		return Math.max(secs, 0);
	}

	update_timers() {
		if (!this.cards) return;
		const pad = (n) => String(n).padStart(2, '0');
		this.wrapper.find('.pf-timer').each((_, el) => {
			const c = this.cards[$(el).attr('data-key')];
			const s = this.net_seconds(c && c.run);
			$(el).text(`${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`);
		});
	}

	call(method, args, msg) {
		frappe.call({
			method: `alpinos.production.execution.${method}`, args, freeze: true,
			callback: (r) => {
				if (msg) frappe.show_alert({ message: msg, indicator: 'green' });
				this.refresh(true);
				if (r.message && r.message.inward_allowed === 0) {
					frappe.show_alert({ message: __('No inward sheet for this process: it is ready for the next stage.'), indicator: 'blue' });
				}
			},
		});
	}

	act(action, c) {
		if (!c) return;
		const run = c.run && c.run.name;
		if (action === 'start') {
			frappe.confirm(__('Start production for {0}?', [c.machine_run || c.members[0]]),
				() => this.call('start_production', { sub_order: c.members[0] }, __('Production started')));
		} else if (action === 'pause') {
			this.pause_dialog(c);
		} else if (action === 'resume') {
			this.call('resume_production', { production_run: run }, __('Production resumed'));
		} else if (action === 'complete') {
			frappe.confirm(__('Complete production on {0}? The timer stops and the process cannot be restarted.', [run]),
				() => this.call('complete_production', { production_run: run }, __('Production completed')));
		} else if (action === 'inward') {
			frappe.set_route('process_inward_entry', run);
		} else if (action === 'open_inward') {
			frappe.set_route('process_inward_entry', c.open_inward);
		} else if (action === 'log') {
			this.show_log(c);
		}
	}

	pause_dialog(c) {
		const d = new frappe.ui.Dialog({
			title: __('Pause Production'),
			fields: [
				{ fieldname: 'reason', label: __('Reason'), fieldtype: 'Select', reqd: 1,
					options: [''].concat(this.data.pause_reasons || []) },
				{ fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text',
					description: __('Mandatory when the reason is Other.') },
			],
			primary_action_label: __('Pause'),
			primary_action: (v) => {
				if (v.reason === 'Other' && !(v.remarks || '').trim()) {
					frappe.msgprint(__('Please enter the reason in the Remarks field.'));
					return;
				}
				d.hide();
				this.call('pause_production', { production_run: c.run.name, reason: v.reason, remarks: v.remarks },
					__('Production paused'));
			},
		});
		d.show();
	}

	show_log(c) {
		const rows = (c.run.logs || []).map((l) => `<tr><td>${this.esc(l.event)}</td>
			<td>${l.at ? frappe.datetime.str_to_user(l.at) : ''}</td><td>${this.esc(l.user)}</td>
			<td>${this.esc(l.reason || '')}${l.remarks ? ' - ' + this.esc(l.remarks) : ''}</td>
			<td class="text-right">${l.duration_minutes ? format_number(l.duration_minutes, null, 2) : ''}</td></tr>`).join('');
		const r = c.run;
		frappe.msgprint({
			title: __('Production Audit Log: {0}', [r.name]),
			wide: true,
			message: `<p>${__('Gross')}: <b>${format_number(r.gross_minutes, null, 2)}</b> min &middot;
				${__('Downtime')}: <b>${format_number(r.downtime_minutes, null, 2)}</b> min &middot;
				${__('Net')}: <b>${format_number(r.net_minutes, null, 2)}</b> min</p>
				<table class="table table-bordered table-sm"><thead><tr><th>${__('Event')}</th><th>${__('At')}</th>
				<th>${__('User')}</th><th>${__('Reason')}</th><th class="text-right">${__('Pause (min)')}</th></tr></thead>
				<tbody>${rows}</tbody></table>`,
		});
	}
};
