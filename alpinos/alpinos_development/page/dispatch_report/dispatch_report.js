frappe.pages['dispatch-report'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Dispatch Report',
		single_column: true,
	});

	// ── CSS ──────────────────────────────────────────────────────────────────
	frappe.dom.set_style(`
		.dr-wrapper { overflow-x: auto; padding: 12px 4px; font-size: 11px; }
		.dr-table {
			border-collapse: collapse;
			min-width: 100%;
			table-layout: auto;
			white-space: nowrap;
		}
		.dr-table td, .dr-table th {
			border: 1px solid #aaa;
			padding: 3px 5px;
			text-align: center;
			vertical-align: middle;
		}

		/* ── Left section column colors ── */
		.dr-col-dispatch  { background: #ffffff; }
		.dr-col-pending   { background: #ffff00; }
		.dr-col-stock     { background: #ffc000; }
		.dr-col-net       { background: #92d050; }
		.dr-col-inward    { background: #ffffff; min-width: 90px; }
		.dr-col-item      { background: #ffffff; text-align: left; min-width: 110px; font-weight: 600; }

		/* ── Header labels ── */
		.dr-hdr-dispatch  { background: #d9d9d9; font-weight: 700; font-size: 10px; }
		.dr-hdr-pending   { background: #ffff00; font-weight: 700; font-size: 10px; }
		.dr-hdr-stock     { background: #ffc000; font-weight: 700; font-size: 10px; }
		.dr-hdr-net       { background: #92d050; font-weight: 700; font-size: 10px; }
		.dr-hdr-inward    { background: #f2f2f2; font-weight: 700; font-size: 10px; }

		/* ── Green section (Today's Dispatch by CT) ── */
		.dr-green-merged  { background: #375623; color: #fff; font-weight: 700; font-size: 13px; }
		.dr-green-date    { background: #375623; color: #fff; font-weight: 700; font-size: 10px; }
		.dr-green-ct-hdr  {
			background: #00b050; color: #fff; font-weight: 700;
			writing-mode: vertical-rl; text-orientation: mixed;
			transform: rotate(180deg); height: 75px; min-width: 32px; max-width: 40px;
			font-size: 10px;
		}
		.dr-green-sum     { background: #e2efda; }
		.dr-green-cell    { background: #e2efda; }
		.dr-green-zero    { background: #e2efda; color: #4472c4; }

		/* ── Red section (Pending Dispatch by CT) ── */
		.dr-red-merged    { background: #c00000; color: #fff; font-weight: 700; font-size: 13px; }
		.dr-red-date      { background: #c00000; color: #fff; font-weight: 700; font-size: 10px; }
		.dr-red-ct-hdr    {
			background: #ff0000; color: #fff; font-weight: 700;
			writing-mode: vertical-rl; text-orientation: mixed;
			transform: rotate(180deg); height: 75px; min-width: 32px; max-width: 40px;
			font-size: 10px;
		}
		.dr-red-sum       { background: #fce4d6; }
		.dr-red-cell      { background: #fce4d6; }
		.dr-red-zero      { background: #fce4d6; color: #4472c4; }

		/* ── Row states ── */
		.dr-row-negative td.dr-col-dispatch,
		.dr-row-negative td.dr-col-pending,
		.dr-row-negative td.dr-col-stock,
		.dr-row-negative td.dr-col-net { background: #ff9999; }

		.dr-inward-past   { background: #ff0000 !important; color: #fff !important; font-weight: 700; }

		/* ── Summary labels ── */
		.dr-total-label   { background: #f2f2f2; font-weight: 700; text-align: right; font-size: 10px; }
		.dr-total-val     { background: #f2f2f2; font-weight: 700; }

		/* ── Misc ── */
		.dr-spacer td     { border: none; background: #fff; height: 6px; }
		.dr-negative-val  { color: #c00000; font-weight: 700; }
	`);

	// ── Filters ──────────────────────────────────────────────────────────────
	let date_field = page.add_field({
		fieldtype: 'Date',
		fieldname: 'date',
		label: 'Date',
		default: frappe.datetime.get_today(),
		change() { load_data(); },
	});

	let warehouse_field = page.add_field({
		fieldtype: 'Link',
		fieldname: 'warehouse',
		label: 'Warehouse',
		options: 'Warehouse',
		change() { load_data(); },
	});

	page.add_button(__('Refresh'), () => load_data(), { icon: 'refresh' });

	// ── Main container ───────────────────────────────────────────────────────
	let $wrap = $('<div class="dr-wrapper"><div class="dr-content"></div></div>');
	$(wrapper).find('.page-content').append($wrap);
	let $content = $wrap.find('.dr-content');

	// ── Load data ────────────────────────────────────────────────────────────
	function load_data() {
		let date = date_field.get_value();
		let warehouse = warehouse_field.get_value();

		$content.html('<div style="padding:40px;text-align:center;color:#888;">Loading…</div>');

		frappe.call({
			method: 'alpinos.dispatch_report_api.get_dispatch_report_data',
			args: { date, warehouse },
			callback(r) {
				if (r.message) {
					$content.html(build_table(r.message));
				} else {
					$content.html('<div style="padding:40px;text-align:center;color:#888;">No data found.</div>');
				}
			},
		});
	}

	// ── Table builder ─────────────────────────────────────────────────────────
	function build_table(data) {
		let { items, customer_types, summary, date } = data;
		let N = customer_types.length;
		let total_cols = 6 + N + N; // dispatch, pending, stock, net, inward, item + 2×CT

		let fmt_date = frappe.datetime.str_to_user(date) || date;
		let today_str = frappe.datetime.get_today();

		let rows = [];

		// ── ROW S1: Section merged headers + summary totals ──────────────────
		rows.push(`
			<tr>
				<td rowspan="2" class="dr-col-dispatch" style="font-weight:700;font-size:13px;">
					${fmt(summary.dispatch_total)}
				</td>
				<td rowspan="2" class="dr-col-pending"></td>
				<td rowspan="2" class="dr-col-stock" style="font-weight:700;font-size:13px;">
					${fmt(summary.stock_total || 0)}
				</td>
				<td rowspan="2" class="dr-col-net" style="font-weight:700;font-size:13px;">
					${fmt(summary.net_total || 0)}
				</td>
				<td class="dr-total-label">TOTAL BOX</td>
				<td class="dr-total-val">${fmt2(summary.total_box)}</td>
				<td colspan="${N}" class="dr-green-merged">${fmt(summary.dispatch_total)}</td>
				<td colspan="${N}" class="dr-red-merged">${fmt(summary.pending_total)}</td>
			</tr>
		`);

		// ── ROW S2: Per-CT unit totals ────────────────────────────────────────
		let green_ct_totals = customer_types.map(ct =>
			`<td class="dr-green-sum">${fmt(summary.dispatch_by_ct[ct] || 0)}</td>`
		).join('');
		let red_ct_totals = customer_types.map(ct =>
			`<td class="dr-red-sum">${fmt(summary.pending_by_ct[ct] || 0)}</td>`
		).join('');

		rows.push(`
			<tr>
				<td class="dr-total-label">TOTAL GW</td>
				<td class="dr-total-val">${fmt2(summary.total_gw)}</td>
				${green_ct_totals}
				${red_ct_totals}
			</tr>
		`);

		// ── SPACER ────────────────────────────────────────────────────────────
		rows.push(`<tr class="dr-spacer"><td colspan="${total_cols}"></td></tr>`);

		// ── ROW H1: Column section headers ───────────────────────────────────
		rows.push(`
			<tr>
				<td rowspan="2" class="dr-hdr-dispatch">TODAY'S<br>DISPATCH</td>
				<td rowspan="2" class="dr-hdr-pending">PENDING<br>DISPATCH</td>
				<td rowspan="2" class="dr-hdr-stock">TODAY'S<br>STOCK</td>
				<td rowspan="2" class="dr-hdr-net">NET<br>UNIT</td>
				<td rowspan="2" class="dr-hdr-inward">INWARD DATE<br>APPROX</td>
				<td rowspan="2" style="background:#f2f2f2;font-weight:700;font-size:10px;"></td>
				<td colspan="${N}" class="dr-green-date">TODAY'S DATE &nbsp; ${fmt_date}</td>
				<td colspan="${N}" class="dr-red-date">PENDING DISPATCH</td>
			</tr>
		`);

		// ── ROW H2: CT column names (vertical text) ──────────────────────────
		let green_ct_hdrs = customer_types.map(ct =>
			`<td class="dr-green-ct-hdr">${ct}</td>`
		).join('');
		let red_ct_hdrs = customer_types.map(ct =>
			`<td class="dr-red-ct-hdr">${ct}-P</td>`
		).join('');
		rows.push(`<tr>${green_ct_hdrs}${red_ct_hdrs}</tr>`);

		// ── ROW H3: TOTAL BOX per CT ──────────────────────────────────────────
		let green_box = customer_types.map(ct =>
			`<td class="dr-green-sum">${fmt2(summary.box_by_ct[ct] || 0)}</td>`
		).join('');
		let red_box = customer_types.map(ct =>
			`<td class="dr-red-sum">${fmt2(summary.pending_box_by_ct[ct] || 0)}</td>`
		).join('');
		rows.push(`
			<tr>
				<td colspan="5"></td>
				<td class="dr-col-item" style="font-size:10px;font-weight:700;">TOTAL BOX</td>
				${green_box}${red_box}
			</tr>
		`);

		// ── ROW H4: TOTAL GW per CT ───────────────────────────────────────────
		let green_gw = customer_types.map(ct =>
			`<td class="dr-green-sum">${fmt2(summary.gw_by_ct[ct] || 0)}</td>`
		).join('');
		let red_gw_blank = customer_types.map(() => `<td class="dr-red-sum"></td>`).join('');
		rows.push(`
			<tr>
				<td colspan="5"></td>
				<td class="dr-col-item" style="font-size:10px;font-weight:700;">TOTAL GW</td>
				${green_gw}${red_gw_blank}
			</tr>
		`);

		// ── DATA ROWS ─────────────────────────────────────────────────────────
		for (let item of items) {
			let is_negative = item.net_unit < 0;
			let row_class = is_negative ? 'dr-row-negative' : '';

			// Inward date cell
			let inward_cell = '';
			if (item.inward_date) {
				let is_past = item.inward_date < today_str;
				let inward_cls = is_past ? 'dr-col-inward dr-inward-past' : 'dr-col-inward';
				let inward_fmt = frappe.datetime.str_to_user(item.inward_date) || item.inward_date;
				inward_cell = `<td class="${inward_cls}">${inward_fmt}</td>`;
			} else {
				inward_cell = `<td class="dr-col-inward"></td>`;
			}

			// Net unit — highlight negative in red
			let net_display = item.net_unit;
			let net_extra = is_negative ? ' dr-negative-val' : '';

			// Per-CT dispatch cells
			let green_cells = customer_types.map(ct => {
				let v = item.dispatch_by_ct[ct] || 0;
				let cls = v === 0 ? 'dr-green-zero' : 'dr-green-cell';
				return `<td class="${cls}">${fmt(v)}</td>`;
			}).join('');

			// Per-CT pending cells
			let red_cells = customer_types.map(ct => {
				let v = item.pending_by_ct[ct] || 0;
				let cls = v === 0 ? 'dr-red-zero' : 'dr-red-cell';
				return `<td class="${cls}">${fmt(v)}</td>`;
			}).join('');

			rows.push(`
				<tr class="${row_class}">
					<td class="dr-col-dispatch">${fmt(item.today_dispatch)}</td>
					<td class="dr-col-pending">${fmt(item.pending_dispatch)}</td>
					<td class="dr-col-stock">${fmt(item.today_stock)}</td>
					<td class="dr-col-net${net_extra}">${fmt(net_display)}</td>
					${inward_cell}
					<td class="dr-col-item" title="${item.item_name}">${item.item_code}</td>
					${green_cells}
					${red_cells}
				</tr>
			`);
		}

		if (items.length === 0) {
			rows.push(`
				<tr>
					<td colspan="${total_cols}" style="padding:20px;color:#888;text-align:center;">
						No sequenced items found for this date.
					</td>
				</tr>
			`);
		}

		return `<table class="dr-table">${rows.join('')}</table>`;
	}

	// ── Formatters ────────────────────────────────────────────────────────────
	function fmt(v) {
		if (v === null || v === undefined) return '0';
		let n = parseFloat(v);
		if (isNaN(n)) return '0';
		return n % 1 === 0 ? n.toString() : n.toFixed(2);
	}

	function fmt2(v) {
		if (v === null || v === undefined) return '0';
		let n = parseFloat(v);
		if (isNaN(n) || n === 0) return '0';
		return n % 1 === 0 ? n.toString() : n.toFixed(2);
	}

	// ── Auto-load ─────────────────────────────────────────────────────────────
	setTimeout(() => load_data(), 200);
};
