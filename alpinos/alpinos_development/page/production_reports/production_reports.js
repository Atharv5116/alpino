/**
 * Production Reports (FRD Phase 12) + Audit Trail (5.6).
 *
 * One page, a report selector on the left, the filters each report supports, and a table in
 * which every document id is a link (12.4 drill-down). Export to CSV, and the end-of-day
 * "Production Summary" print. Access: Production Admin / Manager / Plant Head / System Manager
 * (enforced on the server).
 */

frappe.pages['production_reports'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Production Reports'), single_column: true });
	wrapper.reports = new ProductionReports(page);
};

frappe.pages['production_reports'].on_page_show = function (wrapper) {
	if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
};

class ProductionReports {
	constructor(page) {
		this.page = page;
		this.$w = $(page.main);
		this.f = {};
		this.controls = {};
		this.$w.html(`<div class="prep">
			<style>
				.prep { display:flex; gap:16px; align-items:flex-start; }
				.prep .side { width:230px; flex-shrink:0; border-right:1px solid var(--border-color); padding-right:12px; }
				.prep .side .grp { font-size:11px; text-transform:uppercase; color:var(--text-muted); margin:12px 0 4px; }
				.prep .side a { display:block; padding:4px 8px; border-radius:6px; color:var(--text-color); cursor:pointer; }
				.prep .side a.active { background:var(--bg-gray, #eee); font-weight:600; }
				.prep .main { flex:1; min-width:0; }
				.prep .fl { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:8px; }
				.prep .fl > div { min-width:150px; }
				.prep .tbl { overflow:auto; max-height:70vh; }
				.prep table { width:100%; font-size:12px; }
				.prep th { position:sticky; top:0; background:var(--card-bg, #fff); z-index:1; }
				.prep td.n, .prep th.n { text-align:right; white-space:nowrap; }
				.prep tr.tot td { font-weight:700; background:var(--bg-light-gray, #f6f6f6); }
				.prep .lnk { cursor:pointer; text-decoration:underline; }
				@media (max-width: 768px) { .prep { flex-direction:column; } .prep .side { width:100%; border:0; } }
			</style>
			<div class="side"></div>
			<div class="main"><h4 class="title"></h4><div class="fl"></div><div class="meta text-muted small"></div>
				<div class="tbl"></div></div></div>`);
		this.page.set_primary_action(__('Run'), () => this.run(), 'refresh');
		this.page.add_inner_button(__('Export CSV'), () => this.export());
		this.page.add_inner_button(__('Print Production Summary'), () => this.print_summary());
		frappe.call({ method: 'alpinos.production.production_reports.get_report_index' }).then((r) => {
			this.index = r.message;
			this.render_side();
			this.select(this.index.reports[0].key);
		});
	}

	esc(v) { return frappe.utils.escape_html(v == null ? '' : String(v)); }

	render_side() {
		let html = '', group = null;
		this.index.reports.forEach((r) => {
			if (r.group !== group) { group = r.group; html += `<div class="grp">${this.esc(group)}</div>`; }
			html += `<a data-key="${r.key}">${this.esc(r.label)}</a>`;
		});
		this.$w.find('.side').html(html);
		this.$w.find('.side a').on('click', (e) => this.select($(e.currentTarget).attr('data-key')));
	}

	select(key) {
		this.report = this.index.reports.find((r) => r.key === key);
		this.$w.find('.side a').removeClass('active');
		this.$w.find(`.side a[data-key="${key}"]`).addClass('active');
		this.$w.find('.title').text(this.report.label);
		this.make_filters();
		this.run();
	}

	make_filters() {
		const me = this, $fl = this.$w.find('.fl').empty();
		const statuses = (this.index.statuses || {})[this.report.key];
		const defs = {
			from_date: { label: __('From Date'), fieldtype: 'Date' },
			to_date: { label: __('To Date'), fieldtype: 'Date' },
			parent_po: { label: __('Parent PO'), fieldtype: 'Link', options: 'Production Order' },
			sub_order: { label: __('Sub PO'), fieldtype: 'Link', options: 'Work Order' },
			sku: { label: __('SKU / Item'), fieldtype: 'Link', options: 'Item' },
			batch: { label: __('Batch Number'), fieldtype: 'Link', options: 'Batch' },
			line: { label: __('Filling / Machine Line'), fieldtype: 'Link', options: 'Machine' },
			status: this.report.key === 'audit_trail'
				? { label: __('Document Type'), fieldtype: 'Select', options: [''].concat(this.index.audit_doctypes || []) }
				: statuses ? { label: __('Status'), fieldtype: 'Select', options: [''].concat(statuses) }
					: { label: __('Status'), fieldtype: 'Data' },
			shift: { label: __('Shift'), fieldtype: 'Select', options: [''].concat(this.index.shifts || []) },
		};
		this.controls = {};
		this.report.filters.forEach((fn) => {
			const c = frappe.ui.form.make_control({
				df: Object.assign({ fieldname: fn, change() { me.f[fn] = this.get_value(); } }, defs[fn]),
				parent: $('<div>').appendTo($fl), render_input: true,
			});
			c.refresh();
			if (this.f[fn]) c.set_value(this.f[fn]);
			this.controls[fn] = c;
		});
	}

	args() {
		const out = {};
		(this.report.filters || []).forEach((fn) => { if (this.f[fn]) out[fn] = this.f[fn]; });
		return out;
	}

	run() {
		if (!this.report) return;
		frappe.call({ method: 'alpinos.production.production_reports.run_report',
			args: { report: this.report.key, filters: this.args() }, freeze: true, freeze_message: __('Running report...') })
			.then((r) => { this.data = r.message; this.render(); });
	}

	cell(c, row) {
		const v = row[c.fieldname];
		if (v == null || v === '') return '';
		if (c.fieldtype === 'Link' || c.fieldtype === 'Dynamic Link') {
			const dt = c.fieldtype === 'Link' ? c.options : row[c.options];
			return dt ? `<span class="lnk" data-dt="${this.esc(dt)}" data-name="${this.esc(v)}">${this.esc(v)}</span>` : this.esc(v);
		}
		if (c.fieldtype === 'Float') return format_number(flt(v), null, 3);
		if (c.fieldtype === 'Int') return format_number(cint(v), null, 0);
		if (c.fieldtype === 'Percent') return format_number(flt(v), null, 2) + ' %';
		if (c.fieldtype === 'Currency') return format_currency(flt(v));
		if (c.fieldtype === 'Date') return frappe.datetime.str_to_user(v);
		if (c.fieldtype === 'Datetime') return frappe.datetime.str_to_user(v);
		return this.esc(v);
	}

	render() {
		const d = this.data || {}, cols = d.columns || [], rows = d.rows || [];
		const num = (c) => ['Float', 'Int', 'Percent', 'Currency'].includes(c.fieldtype);
		const head = cols.map((c) => `<th class="${num(c) ? 'n' : ''}" style="min-width:${Math.min(c.width || 100, 260)}px">${this.esc(c.label)}</th>`).join('');
		const body = rows.slice(0, 3000).map((r) => '<tr>' + cols.map((c) =>
			`<td class="${num(c) ? 'n' : ''}">${this.cell(c, r)}</td>`).join('') + '</tr>').join('');
		const tot = Object.keys(d.totals || {}).length
			? '<tr class="tot">' + cols.map((c, i) => `<td class="${num(c) ? 'n' : ''}">${i === 0 ? __('Total')
				: (c.fieldname in d.totals ? format_number(flt(d.totals[c.fieldname]), null, 3) : '')}</td>`).join('') + '</tr>' : '';
		this.$w.find('.meta').text(__('{0} rows', [rows.length]) + (rows.length > 3000 ? ' ' + __('(first 3000 shown; export for all)') : ''));
		this.$w.find('.tbl').html(rows.length
			? `<table class="table table-bordered table-condensed"><thead><tr>${head}</tr></thead><tbody>${body}${tot}</tbody></table>`
			: `<div class="text-muted text-center" style="padding:40px;">${__('No data for these filters.')}</div>`);
		this.$w.find('.lnk').on('click', (e) => this.open($(e.currentTarget).attr('data-dt'), $(e.currentTarget).attr('data-name')));
	}

	open(dt, name) {
		const pages = {
			'Production Order': 'production_order_entry', 'Work Order': 'sub_order_view',
			'Delivery Note': 'delivery_note_entry', 'Production Transfer': 'production_transfer_entry',
			'Inventory Adjustment': 'inventory_adjustment_entry',
		};
		if (pages[dt]) frappe.set_route(pages[dt], name);
		else frappe.set_route('Form', dt, name);
	}

	export() {
		const d = this.data || {};
		if (!(d.rows || []).length) { frappe.msgprint(__('Nothing to export.')); return; }
		const cols = d.columns;
		const q = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
		const lines = [cols.map((c) => q(c.label)).join(',')]
			.concat(d.rows.map((r) => cols.map((c) => q(r[c.fieldname])).join(',')));
		const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = `${this.report.key}_${frappe.datetime.get_today()}.csv`;
		document.body.appendChild(a);
		a.click();
		setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
	}

	print_summary() {
		const f = {};
		['from_date', 'to_date', 'shift'].forEach((k) => { if (this.f[k]) f[k] = this.f[k]; });
		if (!f.from_date && !f.to_date) { f.from_date = f.to_date = frappe.datetime.get_today(); }
		frappe.call({ method: 'alpinos.production.production_reports.production_summary_html', args: { filters: f } })
			.then((r) => {
				const w = window.open('', '_blank');
				if (!w) { frappe.msgprint(__('Allow pop-ups to print.')); return; }
				w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${__('Production Summary')}</title>
					<style>body{font-family:Arial,sans-serif;margin:16px;}</style></head><body>${r.message || ''}</body></html>`);
				w.document.close();
				w.focus();
				setTimeout(() => w.print(), 300);
			});
	}
}
