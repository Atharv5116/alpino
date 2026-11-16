// Changes(HP) #107: the Daily Report (server: alpinos.daily_report). One block per Customer
// Type: a column per dispatch (Pick List) with its header rows, the SKU rows in Item sequence
// and colour, and Marketing Freebies in their own section. Rows and columns can be frozen
// (how many of each is the user's choice, remembered on this browser); Excel exports the
// template workbook, one sheet per Customer Type.
var DR_PREF_KEY = 'alpinos_daily_report_sticky';

frappe.pages['daily-report'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Daily Report'), single_column: true });
	wrapper.daily_report = new DailyReportPage(page);
};

var DailyReportPage = class {
	constructor(page) {
		this.page = page;
		this.$main = $(page.main);
		this.sticky = this.load_sticky();
		this.add_style();
		this.$main.html(`
			<div class="dr-filters"></div>
			<div class="dr-sticky-bar"></div>
			<div class="dr-blocks"></div>`);
		this.make_filters();
		this.page.set_primary_action(__('Export Excel'), () => this.export());
		this.page.add_inner_button(__('Refresh'), () => this.load());
		this.load();
	}

	add_style() {
		if ($('#dr-style').length) return;
		$(`<style id="dr-style">
			.dr-filters, .dr-sticky-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; margin-bottom: 10px; }
			.dr-filters > div { flex: 0 1 200px; min-width: 160px; }
			.dr-sticky-bar > div { flex: 0 0 150px; }
			.dr-block { margin-bottom: 24px; }
			.dr-block h5 { margin: 6px 0 8px; }
			.dr-scroll { overflow: auto; max-height: 72vh; border: 1px solid var(--border-color, #e2e2e2); border-radius: 6px; }
			.dr-table { border-collapse: separate; border-spacing: 0; font-size: 12px; }
			.dr-table td { border-right: 1px solid var(--border-color, #e2e2e2); border-bottom: 1px solid var(--border-color, #e2e2e2);
				padding: 4px 8px; white-space: nowrap; background: var(--card-bg, #fff); text-align: center; }
			.dr-table td.dr-label { text-align: left; font-weight: 600; }
			.dr-table tr.dr-blue td { background: #4472c4; color: #fff; font-weight: 600; }
			.dr-table tr.dr-yellow td { background: #ffff00; }
			.dr-table td.dr-cancelled { background: #ffc7ce !important; color: #c00000; }
			.dr-table tr.dr-divider td { background: #d9d9d9; font-weight: 700; text-align: left; }
			.dr-table .dr-stuck { position: sticky; z-index: 2; }
			.dr-table .dr-stuck-col { position: sticky; z-index: 1; }
			.dr-table .dr-stuck.dr-stuck-col { z-index: 3; }
		</style>`).appendTo('head');
	}

	load_sticky() {
		try {
			return Object.assign({ on: 1, rows: 11, cols: 3 }, JSON.parse(localStorage.getItem(DR_PREF_KEY) || '{}'));
		} catch (e) {
			return { on: 1, rows: 11, cols: 3 };
		}
	}

	save_sticky() {
		try { localStorage.setItem(DR_PREF_KEY, JSON.stringify(this.sticky)); } catch (e) { /* private window */ }
	}

	make_filters() {
		const mk = (parent, df) => frappe.ui.form.make_control({ df, parent: this.$main.find(parent), render_input: true });
		const $f = this.$main.find('.dr-filters');
		['from', 'to', 'type', 'mm'].forEach((k) => $f.append(`<div class="dr-f-${k}"></div>`));
		const month_start = frappe.datetime.month_start();
		this.f_from = mk('.dr-f-from', { fieldtype: 'Date', fieldname: 'from_date', label: __('Dispatch Date From') });
		this.f_to = mk('.dr-f-to', { fieldtype: 'Date', fieldname: 'to_date', label: __('Dispatch Date To') });
		this.f_type = mk('.dr-f-type', {
			fieldtype: 'Link', fieldname: 'customer_type', label: __('Customer Type'), options: 'Alpino Customer Type',
			description: __('A parent type shows its child types too'),
		});
		this.f_mm = mk('.dr-f-mm', { fieldtype: 'Check', fieldname: 'include_marketing_material', label: __('Include Marketing Freebies') });
		this.f_from.set_input(month_start);
		this.f_to.set_input(frappe.datetime.get_today());
		[this.f_from, this.f_to, this.f_type, this.f_mm].forEach((f) =>
			f.$input.on('change awesomplete-selectcomplete', frappe.utils.debounce(() => this.load(), 300)));

		const $s = this.$main.find('.dr-sticky-bar');
		['on', 'rows', 'cols'].forEach((k) => $s.append(`<div class="dr-s-${k}"></div>`));
		this.s_on = mk('.dr-s-on', { fieldtype: 'Check', fieldname: 'sticky_on', label: __('Freeze rows / columns') });
		this.s_rows = mk('.dr-s-rows', { fieldtype: 'Int', fieldname: 'sticky_rows', label: __('Rows to freeze') });
		this.s_cols = mk('.dr-s-cols', { fieldtype: 'Int', fieldname: 'sticky_cols', label: __('Columns to freeze') });
		this.s_on.set_input(this.sticky.on);
		this.s_rows.set_input(this.sticky.rows);
		this.s_cols.set_input(this.sticky.cols);
		[this.s_on, this.s_rows, this.s_cols].forEach((f) => f.$input.on('change', () => {
			this.sticky = {
				on: cint(this.s_on.get_value()),
				rows: Math.max(0, Math.min(40, cint(this.s_rows.get_value()))),
				cols: Math.max(0, Math.min(10, cint(this.s_cols.get_value()))),
			};
			this.save_sticky();
			this.apply_sticky();
		}));
	}

	args() {
		return {
			from_date: this.f_from.get_value() || frappe.datetime.month_start(),
			to_date: this.f_to.get_value() || frappe.datetime.get_today(),
			customer_type: this.f_type.get_value() || '',
			include_marketing_material: cint(this.f_mm.get_value()),
		};
	}

	load() {
		frappe.xcall('alpinos.daily_report.get_daily_report', this.args()).then((r) => this.render(r));
	}

	render(r) {
		const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
		const num = (v) => (v ? (Math.round(v * 1000) / 1000) : '');
		const $b = this.$main.find('.dr-blocks').empty();
		if (!r.blocks.length) {
			$b.html(`<div class="text-muted">${__('No dispatches with a fetched invoice in this range.')}</div>`);
			return;
		}
		r.blocks.forEach((block) => {
			const cancelled = block.columns.map((c) => c.cancelled);
			const cells = (values) => values.map((v, i) => `<td class="${cancelled[i] ? 'dr-cancelled' : ''}">${v}</td>`).join('');
			let html = '';
			r.headers.forEach((h) => {
				const cls = ['total_box', 'gross_weight', 'total_units'].includes(h.key) ? 'dr-blue' : (h.key === 'date' ? 'dr-yellow' : '');
				const total = h.key in block.totals ? num(block.totals[h.key]) : '';
				html += `<tr class="${cls}"><td></td><td>${total}</td><td class="dr-label">${esc(h.label)}</td>${cells(block.columns.map((c) => esc(c.header[h.key])))}</tr>`;
			});
			const item_row = (it) => `<tr><td>${esc(it.sku_no)}</td><td>${num(it.total)}</td>
				<td class="dr-label" style="${it.color ? `color:${esc(it.color)};` : ''}">${esc(it.item_code)}</td>${cells(it.values.map(num))}</tr>`;
			block.items.forEach((it) => { html += item_row(it); });
			if (block.freebies.length) {
				html += `<tr class="dr-divider"><td colspan="${3 + block.columns.length}">${__('Marketing Freebies')}</td></tr>`;
				block.freebies.forEach((it) => { html += item_row(it); });
			}
			$b.append(`<div class="dr-block">
				<h5>${esc(block.customer_type)} (${esc(block.abbreviation)}) &middot; ${block.columns.length} ${__('dispatches')}</h5>
				<div class="dr-scroll"><table class="dr-table"><tbody>${html}</tbody></table></div>
			</div>`);
		});
		this.apply_sticky();
	}

	/** Freeze the first N rows and M columns of every block, at their measured offsets. */
	apply_sticky() {
		this.$main.find('.dr-table').each((i, table) => {
			$(table).find('td').removeClass('dr-stuck dr-stuck-col').css({ top: '', left: '' });
			if (!this.sticky.on) return;
			const rows = $(table).find('tr').toArray();
			let top = 0;
			rows.slice(0, this.sticky.rows).forEach((tr) => {
				$(tr).children('td').addClass('dr-stuck').css('top', top + 'px');
				top += tr.getBoundingClientRect().height;
			});
			rows.forEach((tr) => {
				let left = 0;
				$(tr).children('td').slice(0, this.sticky.cols).each((j, td) => {
					if (td.colSpan > 1) return;
					$(td).addClass('dr-stuck-col').css('left', left + 'px');
					left += td.getBoundingClientRect().width;
				});
			});
		});
	}

	export() {
		const args = this.args();
		const url = '/api/method/alpinos.daily_report.export_daily_report?' + new URLSearchParams(args).toString();
		window.open(url);
	}
};
