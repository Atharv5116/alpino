/**
 * Store Planning — the planning board (tasks 1-16).
 *
 * Left: the Sub POs waiting to be planned, and the current shortages.
 * Right: a Mon-Sun month calendar. Drag a Sub PO onto a day to plan it, drag a card to
 * another day to reschedule it, click a card for its summary.
 *
 * Native HTML5 drag and drop, no library. Every rule is checked again on the server
 * (alpinos.production.store_planning); the checks here only save a round trip and make
 * the reason visible before anything is sent.
 */

frappe.pages['store_planning_board'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Store Planning'),
		single_column: true,
	});
	wrapper.store_planning_board = new StorePlanningBoard(page);
};

frappe.pages['store_planning_board'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	if (wrapper.store_planning_board) wrapper.store_planning_board.refresh();
};

var StorePlanningBoard = class {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.main);
		const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
		this.year = today.getFullYear();
		this.month = today.getMonth() + 1;
		this.filters = { process: '', machine: '' };
		this.search = '';
		this.data = null;
		this.selected = new Set();
		this.render_shell();
		this.make_filters();
		this.make_actions();
		this.bind_events();
	}

	// ------------------------------------------------------------ helpers

	esc(v) {
		return frappe.utils.escape_html(v == null ? '' : String(v));
	}

	qty(v) {
		return window.alpinos_format_capacity
			? alpinos_format_capacity(v)
			: format_number(flt(v), null, 0);
	}

	date_user(v) {
		return v ? frappe.datetime.str_to_user(v) : '—';
	}

	is_past(date_str) {
		return date_str < frappe.datetime.get_today();
	}

	call(method, args, opts) {
		return new Promise((resolve, reject) => {
			frappe.call(Object.assign({
				method: 'alpinos.production.store_planning.' + method,
				args: args || {},
				callback: (r) => resolve(r.message),
				error: reject,
			}, opts || {}));
		});
	}

	// -------------------------------------------------------------- shell

	render_shell() {
		this.wrapper.html(`
			<div class="spb">
				<style>
					.spb { --spb-border: var(--border-color, #d1d8dd); --spb-muted: var(--text-muted, #6c7680); }
					.spb .spb-top { display:flex; flex-wrap:wrap; align-items:flex-end; gap:12px; margin-bottom:12px; }
					.spb .spb-month { font-size:18px; font-weight:600; min-width:170px; }
					.spb .spb-nav .btn { margin-right:4px; }
					.spb .spb-top .spb-filter { min-width:170px; }
					.spb .spb-top .frappe-control { margin-bottom:0; }
					.spb .spb-legend { display:flex; flex-wrap:wrap; gap:10px; font-size:12px; margin-bottom:10px; }
					.spb .spb-legend span.dot { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:middle; }
					.spb .spb-body { display:flex; gap:14px; align-items:flex-start; }
					.spb .spb-left { width:340px; flex:0 0 340px; }
					.spb .spb-right { flex:1 1 auto; min-width:0; }
					.spb .spb-panel { border:1px solid var(--spb-border); border-radius:6px; margin-bottom:14px; background:var(--card-bg, #fff); }
					.spb .spb-panel-head { padding:8px 10px; border-bottom:1px solid var(--spb-border); font-weight:600; display:flex; justify-content:space-between; align-items:center; }
					.spb .spb-panel-body { padding:8px; max-height:520px; overflow:auto; }
					.spb .spb-un { border:1px solid var(--spb-border); border-radius:6px; padding:6px 8px; margin-bottom:6px; cursor:grab; background:var(--bg-color, #fff); }
					.spb .spb-un:hover { border-color:var(--primary, #2490ef); }
					.spb .spb-un .spb-un-head { display:flex; justify-content:space-between; gap:6px; }
					.spb .spb-un .spb-un-name { font-weight:600; }
					.spb .spb-un .spb-sub { font-size:11px; color:var(--spb-muted); }
					.spb .spb-un .spb-un-actions { margin-top:4px; display:flex; gap:4px; }
					.spb .spb-mini { margin-top:6px; font-size:11px; width:100%; }
					.spb .spb-mini td, .spb .spb-mini th { padding:2px 4px; border-bottom:1px solid var(--spb-border); }
					.spb .spb-ok { color:#27AE60; font-weight:700; }
					.spb .spb-warn { color:#EB5757; font-weight:700; cursor:pointer; }
					.spb .spb-cal { width:100%; border-collapse:collapse; table-layout:fixed; }
					.spb .spb-cal th { text-align:center; font-size:12px; padding:6px; border:1px solid var(--spb-border); background:var(--subtle-fg, #f4f5f6); }
					.spb .spb-cal td { vertical-align:top; border:1px solid var(--spb-border); height:120px; padding:3px; cursor:pointer; }
					.spb .spb-cal td.spb-out { background:var(--subtle-fg, #fafbfc); opacity:.7; }
					.spb .spb-cal td.spb-past { background:repeating-linear-gradient(45deg, transparent, transparent 6px, rgba(0,0,0,.03) 6px, rgba(0,0,0,.03) 12px); cursor:not-allowed; }
					.spb .spb-cal td.spb-today .spb-daynum { background:var(--primary, #2490ef); color:#fff; border-radius:10px; padding:0 6px; }
					.spb .spb-cal td.spb-over { outline:2px dashed var(--primary, #2490ef); outline-offset:-3px; }
					.spb .spb-daynum { font-size:12px; font-weight:600; display:inline-block; margin-bottom:2px; }
					.spb .spb-card { border:1px solid var(--spb-border); border-left:5px solid #828282; border-radius:4px; padding:3px 5px; margin-bottom:3px; font-size:11px; line-height:1.3; background:var(--bg-color, #fff); cursor:pointer; overflow:hidden; }
					.spb .spb-card.spb-short { border-color:#EB5757; border-width:2px; }
					.spb .spb-card .spb-c1 { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
					.spb .spb-card .spb-c2, .spb .spb-card .spb-c3 { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--spb-muted); }
					.spb .spb-card .spb-badge { font-size:10px; background:#9B51E0; color:#fff; border-radius:8px; padding:0 5px; margin-left:3px; }
					.spb .spb-card .spb-sel { margin:0 3px 0 0; vertical-align:middle; }
					.spb .spb-more { font-size:11px; color:var(--primary, #2490ef); cursor:pointer; }
					.spb .spb-empty { color:var(--spb-muted); padding:12px; text-align:center; font-size:12px; }
					.spb .spb-alerts td, .spb .spb-alerts th { font-size:11px; padding:3px 4px; }
					@media (max-width: 991px) { .spb .spb-body { flex-direction:column; } .spb .spb-left { width:100%; flex-basis:auto; } }
				</style>
				<div class="spb-top">
					<div class="spb-nav">
						<button class="btn btn-sm btn-default spb-prev" title="${__('Previous month')}">&#9664;</button>
						<button class="btn btn-sm btn-default spb-next" title="${__('Next month')}">&#9654;</button>
						<button class="btn btn-sm btn-default spb-today">${__('Today')}</button>
					</div>
					<div class="spb-month"></div>
					<div class="spb-filter spb-filter-process"></div>
					<div class="spb-filter spb-filter-machine"></div>
				</div>
				<div class="spb-legend"></div>
				<div class="spb-body">
					<div class="spb-left">
						<div class="spb-panel">
							<div class="spb-panel-head">
								<span>${__('Unplanned Sub POs')} <span class="spb-un-count text-muted"></span></span>
							</div>
							<div style="padding:8px 8px 0;">
								<input type="text" class="form-control input-sm spb-search" placeholder="${__('Search Sub PO, item, parent...')}">
							</div>
							<div class="spb-panel-body spb-unplanned"></div>
						</div>
						<div class="spb-panel">
							<div class="spb-panel-head">
								<span>${__('Shortage Alerts')} <span class="spb-al-count text-muted"></span></span>
								<button class="btn btn-xs btn-default spb-notify">${__('Notify Purchase')}</button>
							</div>
							<div class="spb-panel-body spb-alerts"></div>
						</div>
					</div>
					<div class="spb-right">
						<table class="spb-cal">
							<thead><tr>
								${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => `<th>${__(d)}</th>`).join('')}
							</tr></thead>
							<tbody></tbody>
						</table>
					</div>
				</div>
			</div>
		`);
	}

	_ctl(selector, df, onchange) {
		const parent = this.wrapper.find(selector).empty();
		const control = frappe.ui.form.make_control({
			df: Object.assign({ change: onchange }, df),
			parent: parent,
			render_input: true,
		});
		control.refresh();
		return control;
	}

	make_filters() {
		const me = this;
		const reload = frappe.utils.debounce(() => me.refresh(), 300);
		this._ctl('.spb-filter-process', {
			fieldname: 'process', label: __('Process'), fieldtype: 'Link', options: 'Process Master',
			get_query() { return { filters: { is_active: 1 } }; },
		}, function () { me.filters.process = this.get_value() || ''; reload(); });
		this._ctl('.spb-filter-machine', {
			fieldname: 'machine', label: __('Machine'), fieldtype: 'Link', options: 'Machine',
		}, function () { me.filters.machine = this.get_value() || ''; reload(); });
	}

	make_actions() {
		this.page.set_primary_action(__('Generate MR'), () => this.bulk_generate_mr(), 'file');
		this.page.add_inner_button(__('Refresh'), () => this.refresh());
		this.page.add_inner_button(__('Sub Production Orders'), () => frappe.set_route('sub_order_list'));
	}

	// ------------------------------------------------------------- data

	refresh() {
		const me = this;
		return this.call('get_board', {
			year: this.year, month: this.month,
			process: this.filters.process || null, machine: this.filters.machine || null,
		}).then((data) => {
			me.data = data || {};
			// Selection only survives for cards that are still selectable.
			const keep = new Set((me.data.cards || [])
				.filter((c) => c.execution_status === 'Assigned' && !cint(c.plan_locked))
				.map((c) => c.name));
			me.selected = new Set([...me.selected].filter((n) => keep.has(n)));
			me.render();
		});
	}

	render() {
		const d = this.data || {};
		const first = frappe.datetime.str_to_obj(d.first || frappe.datetime.get_today());
		this.wrapper.find('.spb-month').text(
			first.toLocaleString(frappe.boot.lang || undefined, { month: 'long', year: 'numeric' }));
		this.page.btn_primary && this.page.btn_primary.toggle(!!cint(d.can_plan));
		this.render_legend();
		this.render_unplanned();
		this.render_alerts();
		this.render_calendar();
	}

	render_legend() {
		const items = (this.data.processes || []).map((p) =>
			`<span><span class="dot" style="background:${this.esc(p.color)}"></span>${this.esc(p.process_name || p.name)}</span>`);
		items.push(`<span><span class="spb-ok">&#10003;</span> ${__('Stock OK')}</span>`);
		items.push(`<span><span class="spb-warn">&#9888;</span> ${__('Shortage')}</span>`);
		items.push(`<span>&#128274; ${__('MR generated (locked)')}</span>`);
		this.wrapper.find('.spb-legend').html(items.join(''));
	}

	stock_icon(row) {
		if (!cint(row.has_stock_rows)) return `<span class="text-muted" title="${__('No materials')}">&mdash;</span>`;
		return cint(row.stock_ok)
			? `<span class="spb-ok" title="${__('Stock OK')}">&#10003;</span>`
			: `<span class="spb-warn spb-short-icon" data-name="${this.esc(row.name)}" title="${__('Shortage')}">&#9888;</span>`;
	}

	render_unplanned() {
		const $box = this.wrapper.find('.spb-unplanned').empty();
		const q = (this.search || '').toLowerCase();
		const rows = (this.data.unplanned || []).filter((r) => !q || [r.name, r.production_item,
			r.item_name, r.parent, r.batch, r.production_type].join(' ').toLowerCase().includes(q));
		this.wrapper.find('.spb-un-count').text(`(${rows.length})`);
		if (!rows.length) {
			$box.html(`<div class="spb-empty">${__('Nothing waiting to be planned.')}</div>`);
			return;
		}
		const canPlan = cint(this.data.can_plan);
		const canSplit = cint(this.data.can_split);
		rows.forEach((r) => {
			$box.append(`
				<div class="spb-un" draggable="${canPlan ? 'true' : 'false'}" data-name="${this.esc(r.name)}">
					<div class="spb-un-head">
						<span class="spb-un-name">${this.esc(r.name)} &middot; ${this.esc(this.qty(r.qty))} KG</span>
						<span>${this.stock_icon(r)}
							<a class="spb-eye" data-name="${this.esc(r.name)}" title="${__('Stock')}" style="margin-left:4px;cursor:pointer;">&#128065;</a></span>
					</div>
					<div>${this.esc(r.item_name || r.production_item)}</div>
					${cint(r.next_stage) ? `<div><span class="indicator-pill blue">${__('Next')}: ${this.esc(r.next_process_label || r.next_process || '')}</span></div>` : ''}
					<div class="spb-sub">${this.esc(r.parent)}${r.production_type ? ' &middot; ' + this.esc(r.production_type) : ''}</div>
					<div class="spb-sub">${__('Start')}: ${this.esc(this.date_user(r.planned_start_date))}
						&middot; ${__('Delivery')}: ${this.esc(this.date_user(r.expected_delivery_date))}</div>
					<div class="spb-mini-wrap" style="display:none;"></div>
					<div class="spb-un-actions">
						${canPlan ? `<button class="btn btn-xs btn-default spb-plan" data-name="${this.esc(r.name)}">${__('Plan')}</button>` : ''}
						${canSplit && !cint(r.next_stage) ? `<button class="btn btn-xs btn-default spb-split" data-name="${this.esc(r.name)}">${__('Split')}</button>` : ''}
						<button class="btn btn-xs btn-default spb-open" data-name="${this.esc(r.name)}">${__('Open')}</button>
					</div>
				</div>`);
		});
	}

	render_alerts() {
		const $box = this.wrapper.find('.spb-alerts').empty();
		const alerts = this.data.alerts || [];
		this.wrapper.find('.spb-al-count').text(`(${alerts.length})`);
		this.wrapper.find('.spb-notify').toggle(!!alerts.length && !!cint(this.data.can_plan));
		if (!alerts.length) {
			$box.html(`<div class="spb-empty">${__('No shortages.')}</div>`);
			return;
		}
		$box.html(`
			<table class="table table-condensed" style="margin:0;">
				<thead><tr><th>${__('Item')}</th><th class="text-right">${__('Short')}</th><th>${__('Sub PO')}</th><th>${__('Planned')}</th></tr></thead>
				<tbody>${alerts.map((a) => `
					<tr>
						<td title="${this.esc(a.item)}">${this.esc(a.item_name || a.item)}</td>
						<td class="text-right" style="color:#EB5757;white-space:nowrap;">${this.esc(this.qty(a.deficit))} ${this.esc(a.uom)}</td>
						<td><a class="spb-open-summary" data-name="${this.esc(a.sub_order)}">${this.esc(a.sub_order)}</a></td>
						<td style="white-space:nowrap;">${a.planned_date ? this.esc(this.date_user(a.planned_date)) : `<span class="text-muted">${__('Unplanned')}</span>`}</td>
					</tr>`).join('')}
				</tbody>
			</table>`);
	}

	render_calendar() {
		const d = this.data;
		const $body = this.wrapper.find('.spb-cal tbody').empty();
		const byDay = {};
		(d.cards || []).forEach((c) => { (byDay[c.planned_date] = byDay[c.planned_date] || []).push(c); });
		const today = d.today || frappe.datetime.get_today();
		const month = cint(d.month);
		let cursor = d.grid_start;
		const MAX = 3;
		while (cursor <= d.grid_end) {
			const $tr = $('<tr></tr>');
			for (let i = 0; i < 7; i++) {
				const obj = frappe.datetime.str_to_obj(cursor);
				const cls = [];
				if (obj.getMonth() + 1 !== month) cls.push('spb-out');
				if (cursor < today) cls.push('spb-past');
				if (cursor === today) cls.push('spb-today');
				const cards = byDay[cursor] || [];
				const shown = cards.slice(0, MAX).map((c) => this.card_html(c)).join('');
				const more = cards.length > MAX
					? `<div class="spb-more" data-date="${cursor}">${__('+{0} more', [cards.length - MAX])}</div>` : '';
				$tr.append(`<td class="spb-day ${cls.join(' ')}" data-date="${cursor}">
					<span class="spb-daynum">${obj.getDate()}</span>${shown}${more}</td>`);
				cursor = frappe.datetime.add_days(cursor, 1);
			}
			$body.append($tr);
		}
	}

	card_html(c) {
		const locked = cint(c.plan_locked);
		const short = cint(c.has_stock_rows) && !cint(c.stock_ok);
		const selectable = cint(this.data.can_plan) && c.execution_status === 'Assigned' && !locked && !c.material_request;
		const nextStage = c.execution_status === 'Ready for Next Stage';
		const draggable = cint(this.data.can_plan) && ((c.execution_status === 'Assigned' && !locked) || nextStage);
		const icons = [];
		if (cint(c.has_stock_rows)) {
			icons.push(short
				? `<span class="spb-warn spb-short-icon" data-name="${this.esc(c.name)}" title="${__('Shortage')}">&#9888;</span>`
				: `<span class="spb-ok" title="${__('Stock OK')}">&#10003;</span>`);
		}
		if (locked) icons.push(`<span title="${__('Plan locked: MR generated')}">&#128274;</span>`);
		const merged = c.machine_run && cint(c.merged_count) > 1
			? `<span class="spb-badge" title="${this.esc(c.machine_run)}">${__('Merged ×{0}', [c.merged_count])}</span>` : '';
		const title = [c.name, c.item_name || c.production_item, c.process_label, c.machine_label,
			c.execution_status].filter(Boolean).join(' · ');
		return `
			<div class="spb-card ${short ? 'spb-short' : ''}" draggable="${draggable ? 'true' : 'false'}"
				data-name="${this.esc(c.name)}" style="border-left-color:${this.esc(c.color)};" title="${this.esc(title)}">
				<div class="spb-c1">${selectable ? `<input type="checkbox" class="spb-sel" data-name="${this.esc(c.name)}" ${this.selected.has(c.name) ? 'checked' : ''}>` : ''}${this.esc(c.name)} &middot; ${this.esc(this.qty(c.qty))} KG ${icons.join(' ')}${merged}</div>
				<div class="spb-c2">${this.esc(c.item_name || c.production_item)}</div>
				<div class="spb-c3">${this.esc(c.process_label || '')}${c.machine_label ? ' &middot; ' + this.esc(c.machine_label) : ''}</div>
			</div>`;
	}

	card(name) {
		return (this.data.cards || []).find((c) => c.name === name)
			|| (this.data.unplanned || []).find((c) => c.name === name);
	}

	// ------------------------------------------------------------ events

	bind_events() {
		const me = this;
		const w = this.wrapper;

		w.on('click', '.spb-prev', () => this.shift_month(-1));
		w.on('click', '.spb-next', () => this.shift_month(1));
		w.on('click', '.spb-today', () => {
			const t = frappe.datetime.str_to_obj(frappe.datetime.get_today());
			this.year = t.getFullYear();
			this.month = t.getMonth() + 1;
			this.refresh();
		});
		w.on('input', '.spb-search', frappe.utils.debounce(function () {
			me.search = $(this).val() || '';
			me.render_unplanned();
		}, 200));
		w.on('click', '.spb-notify', () => this.notify_purchase());

		// Left panel
		w.on('click', '.spb-eye', function (e) {
			e.stopPropagation();
			me.toggle_mini($(this).closest('.spb-un'), $(this).attr('data-name'));
		});
		w.on('click', '.spb-plan', function (e) {
			e.stopPropagation();
			me.open_planning($(this).attr('data-name'), null);
		});
		w.on('click', '.spb-split', function (e) {
			e.stopPropagation();
			me.split_dialog($(this).attr('data-name'));
		});
		w.on('click', '.spb-open', function (e) {
			e.stopPropagation();
			frappe.set_route('sub_order_view', $(this).attr('data-name'));
		});
		w.on('click', '.spb-open-summary', function (e) {
			e.stopPropagation();
			const name = $(this).attr('data-name');
			const c = me.card(name);
			if (c && c.planned_date) me.show_summary(name);
			else me.show_shortage(name);
		});
		w.on('click', '.spb-short-icon', function (e) {
			e.stopPropagation();
			me.show_shortage($(this).attr('data-name'));
		});

		// Calendar
		w.on('click', '.spb-sel', function (e) {
			e.stopPropagation();
			const name = $(this).attr('data-name');
			if (this.checked) me.selected.add(name); else me.selected.delete(name);
		});
		w.on('click', '.spb-card', function (e) {
			e.stopPropagation();
			me.show_summary($(this).attr('data-name'));
		});
		w.on('click', '.spb-more', function (e) {
			e.stopPropagation();
			me.show_day($(this).attr('data-date'));
		});
		w.on('click', '.spb-day', function () {
			me.click_day($(this).attr('data-date'));
		});

		// Drag and drop (native HTML5)
		w.on('dragstart', '.spb-un[draggable="true"], .spb-card[draggable="true"]', function (e) {
			const $el = $(this);
			const payload = { kind: $el.hasClass('spb-card') ? 'card' : 'unplanned', name: $el.attr('data-name') };
			const dt = e.originalEvent.dataTransfer;
			dt.effectAllowed = 'move';
			dt.setData('text/plain', JSON.stringify(payload));
			me.dragging = payload;
		});
		w.on('dragend', '.spb-un, .spb-card', () => {
			me.dragging = null;
			w.find('.spb-over').removeClass('spb-over');
		});
		w.on('dragover', '.spb-day', function (e) {
			if (!me.dragging) return;
			e.preventDefault();
			e.originalEvent.dataTransfer.dropEffect = me.is_past($(this).attr('data-date')) ? 'none' : 'move';
			$(this).addClass('spb-over');
		});
		w.on('dragleave', '.spb-day', function (e) {
			if (!this.contains(e.originalEvent.relatedTarget)) $(this).removeClass('spb-over');
		});
		w.on('drop', '.spb-day', function (e) {
			e.preventDefault();
			$(this).removeClass('spb-over');
			let payload = me.dragging;
			try {
				payload = JSON.parse(e.originalEvent.dataTransfer.getData('text/plain')) || payload;
			} catch (err) { /* keep the in-memory payload */ }
			me.dragging = null;
			if (payload) me.drop(payload, $(this).attr('data-date'));
		});
	}

	shift_month(delta) {
		let m = this.month + delta;
		let y = this.year;
		if (m < 1) { m = 12; y -= 1; }
		if (m > 12) { m = 1; y += 1; }
		this.month = m;
		this.year = y;
		this.refresh();
	}

	warn(message, title) {
		frappe.msgprint({ title: title || __('Not Allowed'), message: message, indicator: 'orange' });
	}

	drop(payload, date) {
		if (this.is_past(date)) {
			this.warn(__("You can't plan on a past date."));
			return;
		}
		if (payload.kind === 'unplanned') {
			this.open_planning(payload.name, date);
			return;
		}
		const c = this.card(payload.name);
		if (!c) return;
		if (c.planned_date === date) return;
		if (c.execution_status !== 'Ready for Next Stage' && (cint(c.plan_locked) || c.material_request || c.execution_status !== 'Assigned')) {
			this.warn(__('An MR exists for this sub order; cancel it before re-planning.'), __('Planning Is Locked'));
			return;
		}
		const me = this;
		const go = () => me.call('reschedule_planning', { sub_order: c.name, planned_date: date },
			{ freeze: true, freeze_message: __('Rescheduling...') })
			.then((r) => me.after_save(r, __('{0} moved to {1}', [c.name, frappe.datetime.str_to_user(date)])));
		if (c.machine_run && cint(c.merged_count) > 1) {
			frappe.confirm(__('{0} is merged with {1} other Sub PO(s) in {2}. Move the whole run to {3}?',
				[c.name, cint(c.merged_count) - 1, c.machine_run, frappe.datetime.str_to_user(date)]), go);
		} else {
			go();
		}
	}

	after_save(r, message) {
		if (!r) return;
		frappe.show_alert({ message: message, indicator: 'green' }, 5);
		const short = r.shortages || [];
		if (short.length) {
			// VAL-STK-01: a warning, the planning is saved.
			frappe.msgprint({
				title: __('Planned With A Stock Shortage'),
				indicator: 'orange',
				message: __('The planning was saved, but stock is short:') + '<br>' + short.map((s) =>
					`${this.esc(s.sub_order)}: ${__('Shortage: {0} {1} {2}', [this.esc(this.qty(s.deficit)),
						this.esc(s.uom), this.esc(s.item_name || s.item)])}`).join('<br>'),
			});
		}
		this.refresh();
	}

	click_day(date) {
		if (!cint(this.data.can_plan)) return;
		if (this.is_past(date)) {
			this.warn(__("You can't plan on a past date."));
			return;
		}
		this.open_planning(null, date);
	}

	show_day(date) {
		const cards = (this.data.cards || []).filter((c) => c.planned_date === date);
		const d = new frappe.ui.Dialog({
			title: __('Planned on {0}', [frappe.datetime.str_to_user(date)]),
			fields: [{ fieldtype: 'HTML', fieldname: 'list' }],
		});
		const $list = d.get_field('list').$wrapper;
		$list.addClass('spb').html(cards.map((c) => this.card_html(c)).join(''));
		$list.on('click', '.spb-card', (e) => {
			d.hide();
			this.show_summary($(e.currentTarget).attr('data-name'));
		});
		$list.on('click', '.spb-short-icon', (e) => {
			e.stopPropagation();
			this.show_shortage($(e.currentTarget).attr('data-name'));
		});
		d.show();
	}

	// -------------------------------------------------------------- stock

	stock_table(rows) {
		if (!rows || !rows.length) return `<div class="text-muted">${__('No materials on this Sub PO.')}</div>`;
		return `
			<table class="table table-condensed table-bordered spb-mini" style="margin:0;">
				<thead><tr><th>${__('Item')}</th><th>${__('UOM')}</th><th class="text-right">${__('Required')}</th>
					<th class="text-right">${__('Available')}</th><th>${__('Status')}</th><th class="text-right">${__('Deficit')}</th></tr></thead>
				<tbody>${rows.map((r) => `
					<tr>
						<td title="${this.esc(r.item)}">${this.esc(r.item_name || r.item)}</td>
						<td>${this.esc(r.uom)}</td>
						<td class="text-right">${this.esc(this.qty(r.required))}</td>
						<td class="text-right">${this.esc(this.qty(r.available))}</td>
						<td>${r.status === 'Shortage' ? `<span class="spb-warn">${__('Shortage')}</span>` : `<span class="spb-ok">${__('OK')}</span>`}</td>
						<td class="text-right">${flt(r.deficit) ? this.esc(this.qty(r.deficit)) : '—'}</td>
					</tr>`).join('')}
				</tbody>
			</table>`;
	}

	toggle_mini($row, name) {
		const $wrap = $row.find('.spb-mini-wrap');
		if ($wrap.is(':visible')) { $wrap.hide(); return; }
		$wrap.html(`<div class="text-muted" style="font-size:11px;">${__('Loading...')}</div>`).show();
		this.call('get_sub_order_stock', { sub_order: name }).then((rows) => $wrap.html(this.stock_table(rows)));
	}

	show_shortage(name) {
		const c = this.card(name);
		const done = (rows) => {
			const short = (rows || []).filter((r) => r.status === 'Shortage');
			frappe.msgprint({
				title: __('Stock Shortage — {0}', [name]),
				indicator: 'red',
				message: (short.length
					? short.map((r) => `<div><b>${__('Shortage: {0} {1} {2}', [this.esc(this.qty(r.deficit)),
						this.esc(r.uom), this.esc(r.item_name || r.item)])}</b></div>`).join('')
					: `<div>${__('No shortage.')}</div>`)
					+ '<hr>' + this.stock_table(rows),
			});
		};
		this.call('get_sub_order_stock', { sub_order: name, planned_date: (c && c.planned_date) || null }).then(done);
	}

	// ---------------------------------------------------- planning popup

	open_planning(sub_order, date) {
		const me = this;
		if (!cint(this.data.can_plan)) {
			this.warn(__('Only a Store Planner, Production Manager or Production Admin may change the planning.'));
			return;
		}
		if (!sub_order) {
			this.call('unplanned_options', { planned_date: date }).then((options) => {
				if (!(options || []).length) {
					me.warn(__('There are no unplanned Sub POs to plan.'), __('Nothing To Plan'));
					return;
				}
				me.show_planning_dialog(null, date, options);
			});
			return;
		}
		this.call('get_planning_context', { sub_order: sub_order, planned_date: date || null },
			{ freeze: true }).then((ctx) => {
			if (!ctx) return;
			if (cint(ctx.plan_locked)) {
				me.warn(__('An MR exists for this sub order; cancel it before re-planning.'), __('Planning Is Locked'));
				return;
			}
			me.show_planning_dialog(ctx, date || ctx.planned_date, null);
		});
	}

	show_planning_dialog(ctx, date, options) {
		const me = this;
		const choosing = !ctx;
		const processOptions = ((ctx && ctx.processes) || []).map((p) => ({
			label: p.process_name || p.name, value: p.name,
		}));
		const fields = [];
		if (choosing) {
			fields.push({
				fieldtype: 'Select', fieldname: 'sub_order', label: __('Sub PO'), reqd: 1,
				options: [{ label: __('Select a Sub PO...'), value: '' }].concat(options.map((o) => ({
					label: `${o.name} · ${me.qty(o.qty)} KG · ${o.item_name || o.production_item}`, value: o.name,
				}))),
				onchange() {
					const name = d.get_value('sub_order');
					if (!name) return;
					const when = d.get_value('planned_date') || date;
					d.hide();
					me.open_planning(name, when);
				},
			});
		} else {
			fields.push({ fieldtype: 'Data', fieldname: 'sub_order', label: __('Sub PO'), read_only: 1, default: ctx.sub_order });
		}
		fields.push(
			{ fieldtype: 'Column Break' },
			{ fieldtype: 'Data', fieldname: 'item', label: __('Target Item'), read_only: 1,
				default: ctx ? `${ctx.item}${ctx.item_name && ctx.item_name !== ctx.item ? ' — ' + ctx.item_name : ''}` : '' },
			{ fieldtype: 'Column Break' },
			{ fieldtype: 'Float', fieldname: 'qty', label: __('Target Qty (KG)'), read_only: 1, precision: 3,
				default: ctx ? ctx.qty : 0 },
			{ fieldtype: 'Section Break' },
			{ fieldtype: 'Date', fieldname: 'planned_date', label: __('Planned Date'), reqd: 1, default: date || '',
				description: __('Today or later.'),
				onchange() { if (!choosing) me.refresh_dialog_stock(d, ctx); } },
			{ fieldtype: 'Column Break' },
			{ fieldtype: 'Select', fieldname: 'process', label: __('Assigned Process'), reqd: 1,
				options: processOptions, default: ctx ? ctx.default_process : '',
				read_only: choosing ? 1 : 0,
				onchange() { if (!choosing) me.on_dialog_process(d, ctx); } },
			{ fieldtype: 'Column Break' },
			{ fieldtype: 'Select', fieldname: 'machine', label: __('Select Machine'), options: [] },
			{ fieldtype: 'Section Break' },
			{ fieldtype: 'Data', fieldname: 'completed', label: __('Completed Processes'), read_only: 1,
				default: ctx ? ((ctx.completed_processes || []).join(', ') || __('None')) : '' },
			{ fieldtype: 'Section Break', label: __('Stock Status') },
			{ fieldtype: 'HTML', fieldname: 'stock_html' },
			{ fieldtype: 'Section Break', label: __('Merge Center') },
			{ fieldtype: 'HTML', fieldname: 'merge_html' },
		);

		const canCancel = ctx && (ctx.execution_status === 'Assigned' || (ctx.execution_status === 'Ready for Next Stage' && ctx.default_process && ctx.planned_date));
		const d = new frappe.ui.Dialog({
			title: ctx ? __('Process Assignment — {0}', [ctx.sub_order]) : __('Process Assignment'),
			size: 'large',
			fields: fields,
			primary_action_label: __('Save Planning'),
			primary_action(values) {
				if (choosing) return;
				me.save_dialog(d, ctx, values);
			},
			secondary_action_label: canCancel ? __('Cancel Planning') : __('Close'),
			secondary_action() {
				if (canCancel) me.cancel_planning(ctx.sub_order, () => d.hide());
				else d.hide();
			},
		});
		d.show();
		if (choosing) {
			d.get_primary_btn().prop('disabled', true);
			d.get_field('stock_html').$wrapper.html(`<div class="text-muted">${__('Choose a Sub PO first.')}</div>`);
			return;
		}
		d.spb_machines = ctx.machines || [];
		d.spb_candidates = ctx.merge_candidates || [];
		me.set_machine_options(d, ctx, ctx.assigned_machine);
		me.render_dialog_stock(d, ctx.stock);
		me.render_merge(d, ctx);
	}

	process_row(ctx, name) {
		return (ctx.processes || []).find((p) => p.name === name) || {};
	}

	set_machine_options(d, ctx, value) {
		const field = d.get_field('machine');
		const needed = cint(this.process_row(ctx, d.get_value('process')).allow_machine_assignment);
		field.df.options = [{ label: needed ? __('Select a machine...') : __('No machine'), value: '' }].concat(
			(d.spb_machines || []).map((m) => ({
				label: `${m.machine_name || m.name}${flt(m.max_capacity) ? ` (${__('max')} ${this.qty(m.max_capacity)} ${m.capacity_uom || ''})` : ''}`,
				value: m.name,
			})));
		field.df.reqd = needed ? 1 : 0;
		field.df.description = needed
			? __('This process needs a machine. Active machines linked to the process only.')
			: __('Optional for this process.');
		field.refresh();
		const allowed = (d.spb_machines || []).some((m) => m.name === value);
		field.set_value(allowed ? value : '');
		field.$input && field.$input.off('change.spb').on('change.spb', () => this.render_merge(d, ctx));
	}

	on_dialog_process(d, ctx) {
		const process = d.get_value('process');
		Promise.all([
			this.call('machines_with_capacity', { process: process }),
			this.call('get_merge_candidates', { sub_order: ctx.sub_order, process: process }),
		]).then(([machines, candidates]) => {
			d.spb_machines = machines || [];
			d.spb_candidates = candidates || [];
			this.set_machine_options(d, ctx, d.get_value('machine'));
			this.render_merge(d, ctx);
		});
	}

	refresh_dialog_stock(d, ctx) {
		const date = d.get_value('planned_date');
		if (date && this.is_past(date)) {
			frappe.show_alert({ message: __("You can't plan on a past date."), indicator: 'orange' }, 5);
		}
		this.call('get_sub_order_stock', { sub_order: ctx.sub_order, planned_date: date || null })
			.then((rows) => this.render_dialog_stock(d, rows));
	}

	render_dialog_stock(d, rows) {
		const short = (rows || []).filter((r) => r.status === 'Shortage');
		const head = !(rows || []).length ? ''
			: short.length
				? `<div class="spb-warn" style="margin-bottom:6px;">&#9888; ${__('{0} item(s) short. You can still save; the card will be marked.', [short.length])}</div>`
				: `<div class="spb-ok" style="margin-bottom:6px;">&#10003; ${__('All materials available.')}</div>`;
		d.get_field('stock_html').$wrapper.addClass('spb').html(head + this.stock_table(rows));
	}

	render_merge(d, ctx) {
		const $w = d.get_field('merge_html').$wrapper.addClass('spb');
		const checked = new Set($w.find('.spb-merge:checked').map(function () { return $(this).attr('data-name'); }).get());
		const cands = d.spb_candidates || [];
		const members = ctx.run_members || [];
		let html = '';
		if (members.length) {
			html += `<div style="margin-bottom:6px;">${__('Already merged in {0}', [this.esc(ctx.machine_run)])}: ${
				members.map((m) => `${this.esc(m.name)} (${this.esc(this.qty(m.qty))} KG)`).join(', ')}</div>`;
		}
		if (!cands.length) {
			html += `<div class="text-muted">${__('No other unplanned Sub PO has the same FG item and the same next process.')}</div>`;
		} else {
			html += `
				<table class="table table-condensed table-bordered" style="margin:0;">
					<thead><tr><th style="width:30px;"></th><th>${__('Sub PO')}</th><th class="text-right">${__('Qty (KG)')}</th><th>${__('Parent')}</th><th>${__('Start')}</th></tr></thead>
					<tbody>${cands.map((c) => `
						<tr>
							<td><input type="checkbox" class="spb-merge" data-name="${this.esc(c.name)}" data-qty="${flt(c.qty)}" ${checked.has(c.name) ? 'checked' : ''}></td>
							<td>${this.esc(c.name)}</td>
							<td class="text-right">${this.esc(this.qty(c.qty))}</td>
							<td>${this.esc(c.parent)}</td>
							<td>${this.esc(this.date_user(c.planned_start_date))}</td>
						</tr>`).join('')}
					</tbody>
				</table>`;
		}
		html += '<div class="spb-merge-total" style="margin-top:6px;"></div>';
		$w.html(html);
		$w.off('change.spb').on('change.spb', '.spb-merge', () => this.update_merge_total(d, ctx));
		this.update_merge_total(d, ctx);
	}

	update_merge_total(d, ctx) {
		const $w = d.get_field('merge_html').$wrapper;
		let total = flt(ctx.qty) + (ctx.run_members || []).reduce((s, m) => s + flt(m.qty), 0);
		$w.find('.spb-merge:checked').each(function () { total += flt($(this).attr('data-qty')); });
		const machine = (d.spb_machines || []).find((m) => m.name === d.get_value('machine'));
		const max = machine ? flt(machine.max_capacity) : 0;
		const over = max && total > max;
		let text = `${__('Total')}: <b>${this.esc(this.qty(total))} KG</b>`;
		if (max) {
			text += ` / ${__('Machine max capacity')}: <b>${this.esc(this.qty(max))} ${this.esc(machine.capacity_uom || '')}</b>`;
		}
		if (over) {
			text += cint(ctx.capacity_check)
				? ` <span class="spb-warn">${__('Over capacity — merging will be refused.')}</span>`
				: ` <span class="spb-warn">${__('Over capacity.')}</span>`;
		}
		$w.find('.spb-merge-total').html(text);
	}

	save_dialog(d, ctx, values) {
		const me = this;
		if (!values.planned_date || this.is_past(values.planned_date)) {
			this.warn(__("You can't plan on a past date."));
			return;
		}
		const merge = d.get_field('merge_html').$wrapper.find('.spb-merge:checked')
			.map(function () { return $(this).attr('data-name'); }).get();
		this.call('save_planning', {
			sub_order: ctx.sub_order,
			process: values.process,
			machine: values.machine || null,
			planned_date: values.planned_date,
			merge_with: JSON.stringify(merge),
		}, { freeze: true, freeze_message: __('Saving planning...') }).then((r) => {
			if (!r) return;
			d.hide();
			me.after_save(r, r.machine_run
				? __('{0} Sub POs planned together in {1}', [r.sub_orders.length, r.machine_run])
				: __('{0} planned on {1}', [ctx.sub_order, frappe.datetime.str_to_user(r.planned_date)]));
		});
	}

	cancel_planning(sub_order, done) {
		const me = this;
		const d = new frappe.ui.Dialog({
			title: __('Cancel Planning — {0}', [sub_order]),
			fields: [{
				fieldtype: 'Small Text', fieldname: 'reason', label: __('Cancellation Reason'), reqd: 1,
				description: __('Recorded as a comment on the Sub PO.'),
			}],
			primary_action_label: __('Cancel Planning'),
			primary_action(values) {
				if (!(values.reason || '').trim()) {
					me.warn(__('Please enter a cancellation reason before cancelling the planning.'), __('Reason Required'));
					return;
				}
				me.call('cancel_planning', { sub_order: sub_order, reason: values.reason },
					{ freeze: true, freeze_message: __('Cancelling...') }).then((r) => {
					if (!r) return;
					d.hide();
					if (done) done();
					frappe.show_alert({ message: __('Planning of {0} cancelled', [sub_order]), indicator: 'orange' }, 5);
					me.refresh();
				});
			},
		});
		d.show();
	}

	// ------------------------------------------------------ summary modal

	show_summary(name) {
		const me = this;
		this.call('get_sub_order_summary', { sub_order: name }, { freeze: true }).then((s) => {
			if (!s) return;
			const row = (label, value) => `<tr><th style="width:170px;">${label}</th><td>${value}</td></tr>`;
			const history = (s.merge_history || []).length
				? s.merge_history.map((h) => `<div>${me.esc(h.name)} — ${me.esc(h.status)} — ${me.esc(me.date_user(h.planned_date))}
					— ${me.esc(h.machine || '')} — ${me.esc(me.qty(h.total_qty))} KG — ${(h.members || []).map((m) => me.esc(m)).join(', ')}
					${h.cancel_reason ? `<span class="text-muted">(${me.esc(h.cancel_reason)})</span>` : ''}</div>`).join('')
				: `<span class="text-muted">${__('Never merged.')}</span>`;
			const status = `${me.esc(s.execution_status)}${cint(s.plan_locked) ? ' &#128274;' : ''}`;
			const buttons = [];
			if (cint(s.can_edit)) buttons.push(`<button class="btn btn-sm btn-default spb-s-edit">${__('Edit Planning')}</button>`);
			if (cint(s.can_cancel)) buttons.push(`<button class="btn btn-sm btn-default spb-s-cancel">${__('Cancel Planning')}</button>`);
			if (cint(s.can_generate_mr)) buttons.push(`<button class="btn btn-sm btn-primary spb-s-mr">${__('Generate MR')}</button>`);
			buttons.push(`<button class="btn btn-sm btn-default spb-s-print">${__('Print Job Card')}</button>`);
			buttons.push(`<button class="btn btn-sm btn-default spb-s-open">${__('Open Sub PO')}</button>`);

			const d = new frappe.ui.Dialog({
				title: __('Sub PO {0}', [s.sub_order]),
				size: 'large',
				fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
			});
			const $b = d.get_field('body').$wrapper.addClass('spb');
			$b.html(`
				<table class="table table-condensed table-bordered">
					${row(__('Parent PO'), `${me.esc(s.parent)} <span class="text-muted">(${me.esc(s.parent_status || '')})</span>`)}
					${row(__('Sub PO'), me.esc(s.sub_order) + (s.split_from ? ` <span class="text-muted">(${__('split from {0}', [me.esc(s.split_from)])})</span>` : ''))}
					${row(__('FG Item'), `${me.esc(s.item)} — ${me.esc(s.item_name || '')}`)}
					${row(__('Qty'), `${me.esc(me.qty(s.qty))} KG`)}
					${row(__('Process'), me.esc(s.process_label || s.process || '—'))}
					${row(__('Machine'), me.esc(s.machine_label || s.machine || '—'))}
					${row(__('Planned Date'), me.esc(me.date_user(s.planned_date)))}
					${row(__('Status'), status)}
					${row(__('Material Request'), s.material_request ? `<a href="/app/material-request/${encodeURIComponent(s.material_request)}">${me.esc(s.material_request)}</a>` : '—')}
					${row(__('Merge History'), history)}
				</table>
				<div style="font-weight:600;margin:6px 0;">${__('Stock Status')}</div>
				${me.stock_table(s.stock)}
				<div style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap;">${buttons.join('')}</div>
			`);
			$b.on('click', '.spb-s-edit', () => { d.hide(); me.open_planning(s.sub_order, s.planned_date); });
			$b.on('click', '.spb-s-cancel', () => me.cancel_planning(s.sub_order, () => d.hide()));
			$b.on('click', '.spb-s-mr', () => me.generate_mr(s.sub_order, () => d.hide()));
			$b.on('click', '.spb-s-print', () => {
				window.open(`/printview?doctype=Work%20Order&name=${encodeURIComponent(s.sub_order)}`
					+ `&format=${encodeURIComponent('Sub PO Job Card')}&no_letterhead=0`, '_blank');
			});
			$b.on('click', '.spb-s-open', () => { d.hide(); frappe.set_route('sub_order_view', s.sub_order); });
			d.show();
		});
	}

	// ------------------------------------------------------------- MR

	generate_mr(sub_order, done) {
		const me = this;
		frappe.confirm(__('Generate the Material Request for {0}? Its planning will be locked.', [sub_order]), () => {
			me.call('generate_mr', { sub_order: sub_order },
				{ freeze: true, freeze_message: __('Generating MR...') }).then((r) => {
				if (!r) return;
				if (done) done();
				frappe.show_alert({ message: __('{0} created', [r.material_request || __('Material Request')]), indicator: 'green' }, 6);
				me.refresh();
			});
		});
	}

	bulk_generate_mr() {
		const me = this;
		const run = (names, label) => {
			if (!names.length) {
				me.warn(__('There are no planned, unlocked Sub POs to generate an MR for.'), __('Nothing To Generate'));
				return;
			}
			frappe.confirm(__('Generate Material Requests for {0} Sub PO(s) {1}? Their planning will be locked.',
				[names.length, label]) + '<br><small>' + names.map((n) => me.esc(n)).join(', ') + '</small>', () => {
				me.call('generate_mr_bulk', { sub_orders: JSON.stringify(names) },
					{ freeze: true, freeze_message: __('Generating MRs...') }).then((r) => {
					me.selected.clear();
					me.show_bulk_result(r);
					me.refresh();
				});
			});
		};
		if (this.selected.size) {
			run([...this.selected], __('(selected)'));
			return;
		}
		this.call('week_mr_candidates', {}).then((r) => {
			run((r && r.sub_orders) || [], __('planned this week ({0} – {1})',
				[frappe.datetime.str_to_user(r.from), frappe.datetime.str_to_user(r.to)]));
		});
	}

	show_bulk_result(r) {
		// Material Management owns the shape; render whatever rows come back.
		let rows = r;
		if (r && !Array.isArray(r)) rows = r.results || r.rows || r.data || [];
		if (!Array.isArray(rows) || !rows.length) {
			frappe.show_alert({ message: __('Done'), indicator: 'green' }, 5);
			return;
		}
		const html = rows.map((x) => {
			if (typeof x !== 'object' || x === null) return `<div>${this.esc(x)}</div>`;
			const name = x.sub_order || x.name || '';
			const ok = x.material_request && !x.error;
			const msg = x.material_request || x.error || x.message || x.status || '';
			return `<div>${ok ? '<span class="spb-ok">&#10003;</span>' : '<span class="spb-warn">&#9888;</span>'}
				<b>${this.esc(name)}</b>: ${this.esc(msg)}</div>`;
		}).join('');
		frappe.msgprint({ title: __('Generate MR — Results'), message: `<div class="spb">${html}</div>`, indicator: 'blue' });
	}

	notify_purchase() {
		const me = this;
		frappe.confirm(__('Send the current shortage list to the Purchase team?'), () => {
			me.call('notify_purchase', {}, { freeze: true }).then((r) => {
				if (!r) return;
				frappe.show_alert({
					message: __('{0} user(s) notified about {1} item(s)', [(r.notified || []).length, r.items]),
					indicator: 'green',
				}, 6);
			});
		});
	}

	// ------------------------------------------------------------ Split

	split_dialog(name) {
		const me = this;
		frappe.call({
			method: 'alpinos.production.sub_order.split_context',
			args: { sub_order: name },
			freeze: true,
			callback(r) {
				const ctx = r.message;
				if (!ctx) return;
				if (!ctx.can_split) {
					me.warn((ctx.blockers || []).map(frappe.utils.escape_html).join('<br>')
						|| __('You do not have permission to split a sub order.'), __('Cannot Split'));
					return;
				}
				const d = new frappe.ui.Dialog({
					title: __('Split {0}', [ctx.sub_order]),
					fields: [
						{ fieldtype: 'Data', fieldname: 'sub_order', label: __('Current Sub PO'), read_only: 1, default: ctx.sub_order },
						{ fieldtype: 'Column Break' },
						{ fieldtype: 'Float', fieldname: 'current_qty', label: __('Current Qty (KG)'), read_only: 1, default: ctx.qty, precision: 3 },
						{ fieldtype: 'Section Break' },
						{
							fieldtype: 'Float', fieldname: 'split_qty', label: __('Split Qty (KG)'), reqd: 1, precision: 3,
							description: __('More than 0 and less than {0}.', [ctx.qty]),
							onchange() {
								const left = flt(ctx.qty) - flt(d.get_value('split_qty'));
								d.set_value('remaining_qty', left > 0 ? left : 0);
							},
						},
						{ fieldtype: 'Column Break' },
						{ fieldtype: 'Float', fieldname: 'remaining_qty', label: __('Remaining Qty (KG)'), read_only: 1, precision: 3, default: ctx.qty },
						{ fieldtype: 'Section Break' },
						{ fieldtype: 'Small Text', fieldname: 'reason', label: __('Reason'), description: __('Optional.') },
					],
					primary_action_label: __('Split'),
					primary_action(values) {
						frappe.call({
							method: 'alpinos.production.sub_order.split_sub_order_action',
							args: { sub_order: ctx.sub_order, split_qty: values.split_qty, reason: values.reason || null },
							freeze: true,
							freeze_message: __('Splitting...'),
							callback(res) {
								if (!res.message) return;
								d.hide();
								frappe.show_alert({
									message: __('{0} created with {1} KG', [res.message.new_sub_order, res.message.split_qty]),
									indicator: 'green',
								}, 6);
								me.refresh();
							},
						});
					},
				});
				d.show();
			},
		});
	}
};
