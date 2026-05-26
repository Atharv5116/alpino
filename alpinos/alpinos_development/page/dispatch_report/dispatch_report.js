frappe.pages['dispatch-report'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Dispatch Report',
		single_column: true,
	});

	// ── CSS ──────────────────────────────────────────────────────────────────
	frappe.dom.set_style(`
		.dr-wrap { overflow-x: auto; padding: 10px 0; font-size: 12px; font-family: 'Inter', sans-serif; }

		.dr-table { border-collapse: collapse; min-width: 100%; }
		.dr-table td, .dr-table th {
			border: 1px solid #d0d0d0;
			padding: 4px 6px;
			text-align: center;
			vertical-align: middle;
		}

		/* ── Left column headers ── */
		.dr-hdr-dispatch { background: #1565c0; color: #fff; font-weight: 700; font-size: 10px; min-width: 64px; }
		.dr-hdr-pending  { background: #f9a825; color: #fff; font-weight: 700; font-size: 10px; min-width: 64px; }
		.dr-hdr-stock    { background: #e65100; color: #fff; font-weight: 700; font-size: 10px; min-width: 64px; }
		.dr-hdr-net      { background: #2e7d32; color: #fff; font-weight: 700; font-size: 10px; min-width: 64px; }
		.dr-hdr-inward   { background: #546e7a; color: #fff; font-weight: 700; font-size: 10px; min-width: 80px; }
		.dr-hdr-item     { background: #37474f; color: #fff; font-weight: 700; font-size: 10px; min-width: 100px; }

		/* ── Left column data cells ── */
		.dr-d  { background: #e3f2fd; }
		.dr-p  { background: #fff9c4; }
		.dr-s  { background: #fff3e0; }
		.dr-n  { background: #e8f5e9; }
		.dr-i  { background: #fafafa; min-width: 80px; }
		.dr-item-cell { background: #fff; text-align: left; font-weight: 600; font-size: 11px; min-width: 100px; }

		/* ── Summary totals row ── */
		.dr-sum-dispatch { background: #1565c0; color: #fff; font-weight: 700; font-size: 15px; }
		.dr-sum-pending  { background: #f9a825; color: #fff; font-weight: 700; font-size: 10px; }
		.dr-sum-stock    { background: #e65100; color: #fff; font-weight: 700; font-size: 15px; }
		.dr-sum-net      { background: #2e7d32; color: #fff; font-weight: 700; font-size: 15px; }
		.dr-sum-label    { background: #eceff1; color: #37474f; font-weight: 700; font-size: 10px; text-align: right; }
		.dr-sum-val      { background: #eceff1; color: #37474f; font-weight: 700; }

		/* ── Green section (Today's Dispatch by CT) ── */
		.dr-green-merged  { background: #1b5e20; color: #fff; font-weight: 700; font-size: 15px; }
		.dr-green-date-hdr{ background: #2e7d32; color: #fff; font-weight: 700; font-size: 10px; }
		.dr-green-ct-hdr  {
			background: #388e3c; color: #fff; font-weight: 700;
			writing-mode: vertical-rl; text-orientation: mixed;
			transform: rotate(180deg);
			height: 60px; min-width: 28px; max-width: 34px;
			font-size: 9px; white-space: nowrap;
		}
		.dr-green-sum  { background: #c8e6c9; color: #1b5e20; font-weight: 600; }
		.dr-green-val  { background: #f1f8e9; color: #33691e; font-weight: 700; }
		.dr-green-zero { background: #f9fbe7; color: #bdbdbd; }

		/* ── Red section (Pending by CT) ── */
		.dr-red-merged  { background: #b71c1c; color: #fff; font-weight: 700; font-size: 15px; }
		.dr-red-date-hdr{ background: #c62828; color: #fff; font-weight: 700; font-size: 10px; }
		.dr-red-ct-hdr  {
			background: #e53935; color: #fff; font-weight: 700;
			writing-mode: vertical-rl; text-orientation: mixed;
			transform: rotate(180deg);
			height: 60px; min-width: 28px; max-width: 34px;
			font-size: 9px; white-space: nowrap;
		}
		.dr-red-sum  { background: #ffcdd2; color: #b71c1c; font-weight: 600; }
		.dr-red-val  { background: #fff5f5; color: #c62828; font-weight: 700; }
		.dr-red-zero { background: #fff8f8; color: #bdbdbd; }

		/* ── Row states ── */
		.dr-row-neg .dr-d,
		.dr-row-neg .dr-p,
		.dr-row-neg .dr-s,
		.dr-row-neg .dr-n { background: #ffebee !important; }
		.dr-row-neg .dr-item-cell { background: #ffebee !important; }
		.dr-neg-val { color: #c62828; font-weight: 700; }

		/* ── Inward past ── */
		.dr-inward-past { background: #ff6f00 !important; color: #fff !important; font-weight: 700; }

		/* ── Box/GW label rows ── */
		.dr-subhdr td { background: #f5f5f5; font-size: 10px; color: #555; }

		/* ── Spacer ── */
		.dr-spacer td { border: none; background: #fff; height: 8px; }

		/* ── Non-zero highlight ── */
		.dr-d-nz { background: #1565c0; color: #fff; font-weight: 700; }
		.dr-p-nz { background: #f9a825; color: #fff; font-weight: 700; }
		.dr-s-nz { background: #e65100; color: #fff; font-weight: 700; }
	`);

	// ── Filters ──────────────────────────────────────────────────────────────
	let date_field = page.add_field({
		fieldtype: 'Date', fieldname: 'date', label: 'Date',
		default: frappe.datetime.get_today(),
		change() { load_data(); },
	});
	let wh_field = page.add_field({
		fieldtype: 'Link', fieldname: 'warehouse', label: 'Warehouse',
		options: 'Warehouse',
		change() { load_data(); },
	});
	page.add_button(__('Refresh'), () => load_data(), { icon: 'refresh' });

	// ── Container ─────────────────────────────────────────────────────────────
	let $wrap = $('<div class="dr-wrap"><div class="dr-content"></div></div>');
	$(wrapper).find('.page-content').append($wrap);
	let $content = $wrap.find('.dr-content');

	// ── Load ──────────────────────────────────────────────────────────────────
	function load_data() {
		let date = date_field.get_value();
		let wh   = wh_field.get_value();
		$content.html('<p style="padding:30px;color:#888;">Loading…</p>');
		frappe.call({
			method: 'alpinos.dispatch_report_api.get_dispatch_report_data',
			args: { date, warehouse: wh },
			callback(r) {
				$content.html(r.message ? build_table(r.message)
					: '<p style="padding:30px;color:#888;">No data found.</p>');
			},
		});
	}

	// ── Abbreviate CT name: "NUTRITIONAL TRADE" → "NT" ───────────────────────
	function abbr(name) {
		if (!name) return '?';
		return name.split(/\s+/).map(w => w[0].toUpperCase()).join('');
	}

	// ── Table builder ──────────────────────────────────────────────────────────
	function build_table(data) {
		let { items, customer_types, summary, date } = data;
		let N    = customer_types.length;
		let today = frappe.datetime.get_today();
		let rows  = [];

		// ── S1: Big section totals row ────────────────────────────────────────
		rows.push(`<tr>
			<td rowspan="2" class="dr-sum-dispatch">${fmt(summary.dispatch_total)}</td>
			<td rowspan="2" class="dr-sum-pending"></td>
			<td rowspan="2" class="dr-sum-stock">${fmt(summary.stock_total || 0)}</td>
			<td rowspan="2" class="dr-sum-net">${fmt(summary.net_total || 0)}</td>
			<td class="dr-sum-label">TOTAL BOX</td>
			<td class="dr-sum-val">${fmt2(summary.total_box)}</td>
			<td colspan="${N}" class="dr-green-merged">${fmt(summary.dispatch_total)}</td>
			<td colspan="${N}" class="dr-red-merged">${fmt(summary.pending_total)}</td>
		</tr>`);

		// ── S2: Per-CT unit totals ─────────────────────────────────────────────
		rows.push(`<tr>
			<td class="dr-sum-label">TOTAL GW</td>
			<td class="dr-sum-val">${fmt2(summary.total_gw)}</td>
			${customer_types.map(ct => `<td class="dr-green-sum">${fmt(summary.dispatch_by_ct[ct]||0)}</td>`).join('')}
			${customer_types.map(ct => `<td class="dr-red-sum">${fmt(summary.pending_by_ct[ct]||0)}</td>`).join('')}
		</tr>`);

		// ── Spacer ─────────────────────────────────────────────────────────────
		rows.push(`<tr class="dr-spacer"><td colspan="${6+N+N}"></td></tr>`);

		// ── H1: Section date headers ───────────────────────────────────────────
		let fmt_date = frappe.datetime.str_to_user(date) || date;
		rows.push(`<tr>
			<td rowspan="2" class="dr-hdr-dispatch">TODAY'S<br>DISPATCH</td>
			<td rowspan="2" class="dr-hdr-pending">PENDING<br>DISPATCH</td>
			<td rowspan="2" class="dr-hdr-stock">TODAY'S<br>STOCK</td>
			<td rowspan="2" class="dr-hdr-net">NET<br>UNIT</td>
			<td rowspan="2" class="dr-hdr-inward">INWARD DATE<br>APPROX</td>
			<td rowspan="2" class="dr-hdr-item">ITEM</td>
			<td colspan="${N}" class="dr-green-date-hdr">TODAY'S DATE &nbsp; ${fmt_date}</td>
			<td colspan="${N}" class="dr-red-date-hdr">PENDING DISPATCH</td>
		</tr>`);

		// ── H2: CT column names (abbreviated, full name on hover) ─────────────
		rows.push(`<tr>
			${customer_types.map(ct => `<td class="dr-green-ct-hdr" title="${ct}">${abbr(ct)}</td>`).join('')}
			${customer_types.map(ct => `<td class="dr-red-ct-hdr"   title="${ct}-P">${abbr(ct)}-P</td>`).join('')}
		</tr>`);

		// ── H3: TOTAL BOX per CT ──────────────────────────────────────────────
		rows.push(`<tr class="dr-subhdr">
			<td colspan="5"></td>
			<td style="font-weight:700;text-align:right;">BOX</td>
			${customer_types.map(ct => `<td class="dr-green-sum">${fmt2(summary.box_by_ct[ct]||0)}</td>`).join('')}
			${customer_types.map(ct => `<td class="dr-red-sum">${fmt2(summary.pending_box_by_ct[ct]||0)}</td>`).join('')}
		</tr>`);

		// ── H4: TOTAL GW per CT ───────────────────────────────────────────────
		rows.push(`<tr class="dr-subhdr">
			<td colspan="5"></td>
			<td style="font-weight:700;text-align:right;">GW</td>
			${customer_types.map(ct => `<td class="dr-green-sum">${fmt2(summary.gw_by_ct[ct]||0)}</td>`).join('')}
			${customer_types.map(() => `<td class="dr-red-zero"></td>`).join('')}
		</tr>`);

		// ── Data rows ─────────────────────────────────────────────────────────
		if (items.length === 0) {
			rows.push(`<tr><td colspan="${6+N+N}" style="padding:20px;color:#888;text-align:center;">
				No sequenced items found for ${fmt_date}.
			</td></tr>`);
		}

		for (let item of items) {
			let is_neg  = item.net_unit < 0;
			let row_cls = is_neg ? 'dr-row-neg' : '';

			// Inward date
			let inward_cell;
			if (item.inward_date) {
				let past = item.inward_date < today;
				let fmt_inward = frappe.datetime.str_to_user(item.inward_date) || item.inward_date;
				inward_cell = `<td class="dr-i${past ? ' dr-inward-past' : ''}">${fmt_inward}</td>`;
			} else {
				inward_cell = `<td class="dr-i"></td>`;
			}

			// Main column cells — highlight non-zero
			let d_cls = item.today_dispatch > 0 ? 'dr-d-nz' : 'dr-d';
			let p_cls = item.pending_dispatch > 0 ? 'dr-p-nz' : 'dr-p';
			let s_cls = item.today_stock > 0 ? 'dr-s-nz' : 'dr-s';
			let net_extra = is_neg ? ' dr-neg-val' : '';

			// CT dispatch cells
			let green_cells = customer_types.map(ct => {
				let v = item.dispatch_by_ct[ct] || 0;
				return `<td class="${v > 0 ? 'dr-green-val' : 'dr-green-zero'}">${v > 0 ? fmt(v) : '0'}</td>`;
			}).join('');

			// CT pending cells
			let red_cells = customer_types.map(ct => {
				let v = item.pending_by_ct[ct] || 0;
				return `<td class="${v > 0 ? 'dr-red-val' : 'dr-red-zero'}">${v > 0 ? fmt(v) : '0'}</td>`;
			}).join('');

			rows.push(`<tr class="${row_cls}">
				<td class="${d_cls}">${fmt(item.today_dispatch)}</td>
				<td class="${p_cls}">${fmt(item.pending_dispatch)}</td>
				<td class="${s_cls}">${fmt(item.today_stock)}</td>
				<td class="dr-n${net_extra}">${fmt(item.net_unit)}</td>
				${inward_cell}
				<td class="dr-item-cell" title="${item.item_name}">${item.item_code}</td>
				${green_cells}
				${red_cells}
			</tr>`);
		}

		return `<table class="dr-table">${rows.join('')}</table>`;
	}

	// ── Formatters ─────────────────────────────────────────────────────────────
	function fmt(v)  { let n=parseFloat(v); return isNaN(n)?'0':(n%1===0?n.toString():n.toFixed(2)); }
	function fmt2(v) { let n=parseFloat(v); return (!n||isNaN(n))?'':( n%1===0?n.toString():n.toFixed(2) ); }

	setTimeout(() => load_data(), 200);
};
