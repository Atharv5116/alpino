frappe.query_reports['Quotation to Sales Order'] = {
	filters: [
		{ fieldname: 'from_date', label: __('From Date'), fieldtype: 'Date',
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: 'to_date', label: __('To Date'), fieldtype: 'Date',
			default: frappe.datetime.get_today() },
		{ fieldname: 'up_id', label: __('Quotation'), fieldtype: 'Link', options: 'Quotation' },
		{ fieldname: 'down_id', label: __('Sales Order'), fieldtype: 'Link', options: 'Sales Order' },
	],
	formatter: function (value, row, column, data, default_formatter) {
		// SO / PL / DN ids open the Alpino page views, not the desk forms.
		const PAGE_ROUTES = {
			'Sales Order': 'sales-order-entry-view',
			'Pick List': 'pick_list_entry',
			'Delivery Note': 'delivery_note_entry',
		};
		if ((column.fieldname === 'up_id' || column.fieldname === 'down_id') && data && data[column.fieldname]) {
			const route = PAGE_ROUTES[column.options];
			if (route) {
				const name = data[column.fieldname];
				return `<a href="/app/${route}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`;
			}
			return default_formatter(value, row, column, data);
		}
		// Quantities always render (zeros included); the LESSER side is
		// highlighted in red whenever the two differ.
		if (data && (column.fieldname === 'up_qty' || column.fieldname === 'down_qty')) {
			let out = format_number(flt(data[column.fieldname]), null, 3);
			const up = flt(data.up_qty), down = flt(data.down_qty);
			if (up !== down) {
				const lesser = up < down ? 'up_qty' : 'down_qty';
				if (column.fieldname === lesser) {
					out = `<span style="color:#c0392b;font-weight:700;background:rgba(231,76,60,.12);padding:1px 6px;border-radius:4px;">${out}</span>`;
				}
			}
			return out;
		}
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === 'difference' && flt(data.difference) < 0) {
			value = `<span style="color:#c0392b;font-weight:600;">${value}</span>`;
		}
		return value;
	},
};
