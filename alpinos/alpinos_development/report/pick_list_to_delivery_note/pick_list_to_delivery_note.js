frappe.query_reports['Pick List to Delivery Note'] = {
	filters: [
		{ fieldname: 'from_date', label: __('From Date'), fieldtype: 'Date',
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: 'to_date', label: __('To Date'), fieldtype: 'Date',
			default: frappe.datetime.get_today() },
		{ fieldname: 'up_id', label: __('Pick List'), fieldtype: 'Link', options: 'Pick List' },
		{ fieldname: 'down_id', label: __('Delivery Note'), fieldtype: 'Link', options: 'Delivery Note' },
	],
	// Highlight the LESSER of the two quantities in red.
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && (column.fieldname === 'up_qty' || column.fieldname === 'down_qty')) {
			const up = flt(data.up_qty), down = flt(data.down_qty);
			if (up !== down) {
				const lesser = up < down ? 'up_qty' : 'down_qty';
				if (column.fieldname === lesser) {
					value = `<span style="color:#c0392b;font-weight:700;background:rgba(231,76,60,.12);padding:1px 6px;border-radius:4px;">${value}</span>`;
				}
			}
		}
		if (data && column.fieldname === 'difference' && flt(data.difference) < 0) {
			value = `<span style="color:#c0392b;font-weight:600;">${value}</span>`;
		}
		return value;
	},
};
