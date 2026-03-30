// Copyright (c) 2026, Alpinos and contributors
// License: MIT

frappe.query_reports["Attendance Summary"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Data",
			reqd: 1,
			default: frappe.datetime.now_date().slice(0, 7), // YYYY-MM format
			description: __("Format: YYYY-MM (e.g., 2026-03)")
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
	
	formatter: function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		
		// Color coding for attendance status in day columns
		if (column.fieldname.startsWith("day_")) {
			if (value && value.includes("ABSENT")) {
				value = `<span style='color:red!important; font-weight:bold'>${value}</span>`;
			} else if (value && value.includes("HOLIDAY")) {
				value = `<span style='color:blue!important'>${value}</span>`;
			} else if (value && value.includes("HALF DAY")) {
				value = `<span style='color:orange!important'>${value}</span>`;
			} else if (value && value.includes("PRESENT")) {
				value = `<span style='color:green!important'>${value}</span>`;
			} else if (value && value.includes("LEAVE")) {
				value = `<span style='color:purple!important'>${value}</span>`;
			} else if (value && value.includes("WORK FROM HOME")) {
				value = `<span style='color:teal!important'>${value}</span>`;
			}
		}
		
		return value;
	},
	
	onload: function(report) {
		// Add month picker helper
		report.page.add_inner_button(__("This Month"), function() {
			frappe.query_report.set_filter_value("month", frappe.datetime.now_date().slice(0, 7));
		});
		
		report.page.add_inner_button(__("Last Month"), function() {
			let last_month = frappe.datetime.add_months(frappe.datetime.now_date(), -1);
			frappe.query_report.set_filter_value("month", last_month.slice(0, 7));
		});
	}
};
