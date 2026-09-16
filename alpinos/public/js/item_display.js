/**
 * Item Display Configuration (Changes(HP) #39): colour and order Item/SKU rows by the
 * Item Master's Color and Sequence, on exactly the reports and pages a configuration
 * names and nowhere else.
 *
 * The rules and each Item's [color, sequence] arrive in frappe.boot.alpinos_item_display
 * (alpinos.item_display_config), so everything below runs synchronously while a table
 * renders:
 *
 *   Query / Script / Custom Reports  frappe.views.QueryReport: rows sorted after the data
 *                                    is prepared; every column's formatter wrapped.
 *   Report Builder reports           frappe.views.ReportView: rows sorted in place before
 *                                    the table is built (the loaded page only, as its
 *                                    paging is server-side); each cell's format wrapped.
 *   Custom desk pages                the page's <table>s: the SKU column is found by its
 *                                    data-key / data-fieldname or its heading, and the
 *                                    rows are re-applied whenever the page redraws.
 *
 * Items without a sequence keep their normal order after the sequenced ones; items
 * without a colour are not coloured. A page table with inputs in it (an editable grid)
 * is coloured but never reordered, so its row positions stay what the page expects.
 */
(function () {
	const ROW_ALPHA = 0.22;
	const BOTH_ROW_ALPHA = 0.16;
	const CELL_ALPHA = 0.4;

	function config() {
		return (frappe.boot && frappe.boot.alpinos_item_display) || null;
	}

	/**
	 * The boot carries the rules, but a session that started before a configuration was
	 * added or changed has none (or stale ones). Ask the server once per page load, and
	 * redraw if that brings something the screen has not applied yet.
	 */
	function refresh_config(on_change) {
		if (refresh_config.__busy) return;
		refresh_config.__busy = true;
		frappe.call({ method: 'alpinos.item_display_config.get_item_display_payload', type: 'GET' })
			.then((r) => {
				refresh_config.__busy = false;
				const next = (r && r.message) || null;
				const before = JSON.stringify(config() || null);
				if (JSON.stringify(next) === before) return;
				frappe.boot.alpinos_item_display = next;
				if (on_change) on_change();
			})
			.catch(() => {
				refresh_config.__busy = false;
			});
	}

	function rule_for(kind, name) {
		const c = config();
		return (c && name && c.rules && c.rules[kind] && c.rules[kind][name]) || null;
	}

	function item_meta(code) {
		const c = config();
		if (!c || code === null || code === undefined) return null;
		return c.items[String(code).trim()] || null;
	}

	function rgba(hex, alpha) {
		const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || '').trim());
		if (!m) return '';
		const n = parseInt(m[1], 16);
		return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
	}

	function sequence_of(code) {
		const m = item_meta(code);
		return m && m[1] > 0 ? m[1] : 0;
	}

	/** Stable: sequenced items by sequence, then unsequenced items in their original order. */
	function sort_by_sequence(items, get_code, direction) {
		const desc = direction === 'Descending';
		return items
			.map((item, i) => ({ item, i, s: sequence_of(get_code(item)) }))
			.sort((a, b) => {
				if (a.s && b.s) return (desc ? b.s - a.s : a.s - b.s) || a.i - b.i;
				if (a.s) return -1;
				if (b.s) return 1;
				return a.i - b.i;
			})
			.map((d) => d.item);
	}

	/** Background for one cell: [row tint, SKU-cell tint], either may be ''. */
	function tints(rule, code, is_sku_cell) {
		const m = item_meta(code);
		if (!rule || !rule.color || !m || !m[0]) return '';
		if (rule.color_display === 'SKU/Item Code cell only') return is_sku_cell ? rgba(m[0], CELL_ALPHA) : '';
		if (rule.color_display === 'Both') return rgba(m[0], is_sku_cell ? CELL_ALPHA : BOTH_ROW_ALPHA);
		return rgba(m[0], ROW_ALPHA);
	}

	function wrap(html, bg) {
		if (!bg) return html;
		// Bleed over the datatable cell padding so the colour fills the cell.
		return `<div class="alp-idc" style="background:${bg};margin:-8px;padding:8px;">${html == null ? '' : html}</div>`;
	}

	// ------------------------------------------------------------------ reports

	function patch_query_report() {
		const QR = frappe.views && frappe.views.QueryReport && frappe.views.QueryReport.prototype;
		if (!QR || QR.__alp_idc) return;
		QR.__alp_idc = true;

		const orig_prepare = QR.prepare_report_data;
		QR.prepare_report_data = function () {
			const out = orig_prepare.apply(this, arguments);
			const rule = rule_for('reports', this.report_name);
			this.__alp_idc_rule = rule;
			if (rule && rule.sequence && !this.tree_report && Array.isArray(this.data) && this.data.length > 1) {
				const total = this.raw_data && this.raw_data.add_total_row ? this.data.pop() : null;
				const sorted = sort_by_sequence(this.data, (r) => r && r[rule.sku_field], rule.sort_dir);
				this.data.splice(0, this.data.length, ...sorted);
				if (total) this.data.push(total);
			}
			return out;
		};

		const orig_render = QR.render_datatable;
		QR.render_datatable = function () {
			const report = this;
			if (report.__alp_idc_rule && report.__alp_idc_rule.color && Array.isArray(report.columns)) {
				report.columns.forEach((col) => {
					if (!col || col.__alp_idc) return;
					col.__alp_idc = true;
					const base = col.format;
					col.format = function (value, row, column, data, filter) {
						const html = base ? base.call(this, value, row, column, data, filter) : value;
						const rule = report.__alp_idc_rule;
						if (!rule || !rule.color || !data) return html;
						const is_sku = (column && (column.fieldname || column.id)) === rule.sku_field;
						return wrap(html, tints(rule, data[rule.sku_field], is_sku));
					};
				});
			}
			return orig_render.apply(this, arguments);
		};
	}

	function patch_report_view() {
		const RV = frappe.views && frappe.views.ReportView && frappe.views.ReportView.prototype;
		if (!RV || RV.__alp_idc) return;
		RV.__alp_idc = true;

		const orig_render = RV.render;
		RV.render = function () {
			const rule = rule_for('reports', this.report_name);
			this.__alp_idc_rule = rule;
			if (rule && rule.sequence && !this.group_by && Array.isArray(this.data) && this.data.length > 1) {
				// In place, so a row's index still points at its record for inline editing.
				const sorted = sort_by_sequence(this.data, (d) => d && d[rule.sku_field], rule.sort_dir);
				this.data.splice(0, this.data.length, ...sorted);
			}
			return orig_render.apply(this, arguments);
		};

		const orig_get_data = RV.get_data;
		RV.get_data = function (values) {
			const rows = orig_get_data.apply(this, arguments);
			const rule = this.__alp_idc_rule;
			if (!rule || !rule.color || !Array.isArray(rows)) return rows;
			const columns = this.columns || [];
			rows.forEach((cells, i) => {
				const doc = values && values[i];
				if (!doc || !Array.isArray(cells)) return;
				const code = doc[rule.sku_field];
				if (!item_meta(code)) return;
				cells.forEach((cell, j) => {
					if (!cell || typeof cell !== 'object') return;
					const col = columns[j] || {};
					const base = cell.format || col.format;
					const is_sku = col.field === rule.sku_field || (col.docfield && col.docfield.fieldname === rule.sku_field);
					const bg = tints(rule, code, is_sku);
					if (!bg) return;
					cell.format = function (value, row, column, data) {
						return wrap(base ? base(value, row, column, data) : value, bg);
					};
				});
			});
			return rows;
		};
	}

	// -------------------------------------------------------------------- pages

	const norm = (s) => String(s || '').toLowerCase().replace(/[↑↓⇅▲▼]/g, '').replace(/[^a-z0-9]/g, '');

	function sku_column_index(table, sku_field) {
		const head = table.tHead && table.tHead.rows.length ? table.tHead.rows[table.tHead.rows.length - 1] : null;
		const header_row = head || Array.from(table.rows).find((r) => r.querySelector('th'));
		if (!header_row) return -1;
		const wanted = norm(sku_field);
		let col = 0;
		for (const cell of header_row.cells) {
			const keys = [cell.dataset.key, cell.dataset.fieldname, cell.dataset.field, cell.textContent];
			if (keys.some((k) => k && (k === sku_field || norm(k) === wanted))) return col;
			col += cell.colSpan || 1;
		}
		return -1;
	}

	function cell_code(cell) {
		if (!cell) return '';
		const explicit = cell.dataset.sku || cell.dataset.itemCode;
		if (explicit) return explicit.trim();
		const first_line = (cell.innerText || cell.textContent || '').split('\n').map((s) => s.trim()).find(Boolean) || '';
		if (item_meta(first_line)) return first_line;
		return first_line.split(/\s+/)[0] || '';
	}

	function apply_to_table(table, rule) {
		const idx = sku_column_index(table, rule.sku_field);
		if (idx < 0) return;
		const bodies = table.tBodies.length ? Array.from(table.tBodies) : [];
		bodies.forEach((tbody) => {
			const rows = Array.from(tbody.rows);
			const data_rows = rows.filter((tr) => tr.cells.length > idx && !tr.querySelector('th'));
			if (!data_rows.length) return;

			if (rule.color) {
				data_rows.forEach((tr) => {
					const code = cell_code(tr.cells[idx]);
					Array.from(tr.cells).forEach((td, j) => {
						const bg = tints(rule, code, j === idx);
						if (bg) {
							td.style.backgroundColor = bg;
							td.dataset.alpIdc = '1';
						} else if (td.dataset.alpIdc) {
							td.style.backgroundColor = '';
							delete td.dataset.alpIdc;
						}
					});
				});
			}

			// Reorder only a plain read-only table whose every row is a data row: an editable
			// grid tracks rows by position, and a total or group row must not be moved.
			const reorderable = rule.sequence && data_rows.length > 1 && data_rows.length === rows.length
				&& !tbody.querySelector('input, select, textarea, [contenteditable="true"]')
				&& !rows.some((tr) => Array.from(tr.cells).some((td) => td.rowSpan > 1));
			if (reorderable) {
				const sorted = sort_by_sequence(rows, (tr) => cell_code(tr.cells[idx]), rule.sort_dir);
				if (sorted.some((tr, i) => tr !== rows[i])) sorted.forEach((tr) => tbody.appendChild(tr));
			}
		});
	}

	let observer = null;
	let pending = null;

	function watch_page() {
		if (observer) {
			observer.disconnect();
			observer = null;
		}
		const el = frappe.container && frappe.container.page;
		const name = el && el.getAttribute && el.getAttribute('data-page-route');
		const rule = rule_for('pages', name);
		if (!rule) return;

		const run = () => {
			pending = null;
			el.querySelectorAll('table').forEach((t) => apply_to_table(t, rule));
		};
		run();
		// Pages redraw their tables on filters, paging and refresh: re-apply each time.
		// Reordering is itself a DOM change, but a second pass finds the rows already in
		// order and moves nothing, so this settles.
		observer = new MutationObserver(() => {
			if (pending) return;
			pending = setTimeout(run, 120);
		});
		observer.observe(el, { childList: true, subtree: true });
	}

	function redraw() {
		watch_page();
		const qr = frappe.query_report;
		if (qr && qr.refresh && rule_for('reports', qr.report_name)) qr.refresh();
		const rv = typeof cur_list !== 'undefined' && cur_list && cur_list.report_name ? cur_list : null;
		if (rv && rv.refresh && rule_for('reports', rv.report_name)) rv.refresh();
	}

	function attach() {
		if (!frappe.views) return;
		patch_query_report();
		patch_report_view();
		if (!attach.__pages) {
			attach.__pages = true;
			$(document).on('page-change', () => setTimeout(watch_page, 0));
			// Once per page load: pick up a configuration saved after this session started.
			refresh_config(redraw);
		}
		watch_page();
	}

	$(document).on('app_ready', attach);
	setTimeout(attach, 1000);
})();
