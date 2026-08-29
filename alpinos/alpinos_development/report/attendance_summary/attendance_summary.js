// Copyright (c) 2026, Alpinos and contributors
// License: MIT

// section colour grouping mirrors the Final Format Excel bands
var ATT_SECTION = {
	// Basic Information
	employee_name: "basic", employee: "basic", status: "basic", date_of_joining: "basic",
	aging: "basic", department: "basic", company: "basic",
	// Days Calculation
	month_working_days: "days", final_paid_days: "days", final_payable_days: "days",
	present_working_days: "days", clock_in_days: "days",
	// Deduction
	absent_days: "ded", late_entries: "ded", late_half_days: "ded", late_full_days: "ded",
	working_hours_shortage: "ded",
	// Leave
	paid_leave: "leave", unpaid_leave: "leave", wfh: "leave", od: "leave",
	// Other
	public_holiday: "other", weekend: "other", missing_attendance: "other", avg_working_hours: "other",
	verify: "verify",
};
var ATT_CELL_BG = { basic: "#eef2ff", days: "#e8f6ee", ded: "#fdecea", leave: "#fff8e1", other: "#f4e9fd", verify: "#eceff1" };
var ATT_HEAD_BG = { basic: "#c7d2fe", days: "#b7e4c7", ded: "#f6bdb6", leave: "#ffe39a", other: "#e0c3fb", verify: "#cfd8dc" };

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
		if (column.fieldname.startsWith("day_")) {
			var raw = (value == null) ? "" : String(value);
			if (raw === "" || raw === "-") return raw;
			var esc = raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
			if (esc.indexOf("In:") !== -1) {
				var isAbsent = /(^|\n)ABSENT\b/.test(raw);
				var html = esc
					.replace(/^(WFH|OD)(?=\n)/, '<span style="color:#C00000;font-weight:bold">$1</span>')
					.replace(/(Late Time :\s*)([^\n]+)/, function (m, p1, p2) {
						return p2.trim() ? p1 + '<span style="color:#C00000;font-weight:bold">' + p2 + '</span>' : m;
					})
					.replace(/(Early Out :\s*)([^\n]+)/, function (m, p1, p2) {
						return p2.trim() ? p1 + '<span style="color:#C00000;font-weight:bold">' + p2 + '</span>' : m;
					})
					.replace(/\n/g, "<br>");
				return isAbsent ? '<span style="color:#C00000;font-weight:bold">' + html + '</span>' : html;
			}
			if (raw.indexOf("WEEKEND") !== -1) {
				return '<span style="color:#607d8b;font-weight:bold">' + esc + '</span>';
			}
			if (raw.indexOf("HOLIDAY") !== -1) {
				return '<span style="color:#1976d2">' + esc.replace(/\n/g, "<br>") + '</span>';
			}
			// leave day (leave type / "HALF DAY - ...") -> shaded cell
			return '<div style="background:#fff3cd;margin:-4px -8px;padding:4px 8px;">' + esc.replace(/\n/g, "<br>") + '</div>';
		}

		value = default_formatter(value, row, column, data);

		var _bg = ATT_CELL_BG[ATT_SECTION[column.fieldname]];
		if (_bg) {
			value = '<div style="background:' + _bg + '; margin:-4px -8px; padding:4px 8px;">' + (value == null ? "" : value) + '</div>';
		}

		return value;
	},

	onload: function(report) {
		// rebuilds the two-sheet Summary+Details workbook to the client spec — rich day cells,
		// colours, banners — which the built-in export can't produce
		report.page.add_inner_button(__("Download Final Format"), function() {
			var f = frappe.query_report.get_filter_values();
			if (!f || !f.month) {
				frappe.msgprint(__("Set the Month filter first."));
				return;
			}
			var p = { month: f.month };
			if (f.employee) p.employee = f.employee;
			if (f.company) p.company = f.company;
			var url = "/api/method/alpinos.alpinos_development.report.attendance_summary.attendance_summary_export.download_final_format?"
				+ $.param(p);
			window.open(url, "_blank");
		}).addClass("btn-primary");

		report.page.add_inner_button(__("This Month"), function() {
			frappe.query_report.set_filter_value("month", frappe.datetime.now_date().slice(0, 7));
		});

		report.page.add_inner_button(__("Last Month"), function() {
			let last_month = frappe.datetime.add_months(frappe.datetime.now_date(), -1);
			frappe.query_report.set_filter_value("month", last_month.slice(0, 7));
		});

		// frappe reports don't band headers natively; re-applied whenever the datatable re-renders
		function paint_headers() {
			try {
				var dt = report.datatable;
				if (!dt || !dt.datamanager || !dt.datamanager.columns) return;
				dt.datamanager.columns.forEach(function(c) {
					var sec = ATT_SECTION[c.id] || ATT_SECTION[c.fieldname] || ATT_SECTION[c.field];
					if (!sec) return;
					$(report.wrapper)
						.find('.dt-header .dt-cell[data-col-index="' + c.colIndex + '"]')
						.css("background-color", ATT_HEAD_BG[sec]);
				});
			} catch (e) { /* cosmetic — never block the report */ }
		}
		setTimeout(paint_headers, 600);
		try {
			var host = report.wrapper && report.wrapper.get(0);
			if (host && window.MutationObserver) {
				var _t = null;
				new MutationObserver(function() {
					clearTimeout(_t);
					_t = setTimeout(paint_headers, 150);
				}).observe(host, { childList: true, subtree: true });
			}
		} catch (e) { /* noop */ }
	}
};
