frappe.query_reports["Accounts Format Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: "From Date",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: "To Date",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "customer",
			label: "Customer",
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "channel",
			label: "Channel",
			fieldtype: "Link",
			options: "Channel",
		},
		{
			fieldname: "customer_type",
			label: "Customer Type",
			fieldtype: "Link",
			options: "Alpino Customer Type",
		},
	],
	onload: function (report) {
		// The upload/download + PDF-fetch workflow lives on the "Invoice Sync" page.
		report.page.add_inner_button(__("Invoice Sync Page"), function () {
			frappe.set_route("invoice-sync");
		});
	},
};
