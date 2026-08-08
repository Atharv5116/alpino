frappe.query_reports["Accounts Format Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: "Dispatch Date From",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: "Dispatch Date To",
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "sales_order",
			label: "Sales Order ID",
			fieldtype: "Data",
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
		{
			fieldname: "buyer_master_parent",
			label: "Buyer Master (Parent)",
			fieldtype: "Link",
			options: "Buyer Master",
			get_query: () => ({ filters: { is_parent: 1 } }),
		},
		{
			fieldname: "site_name",
			label: "Site Name",
			fieldtype: "Data",
		},
		{
			fieldname: "show_all",
			label: "Show All (incl. fetched invoices)",
			fieldtype: "Check",
			default: 0,
		},
	],
	onload: function (report) {
		// The upload/download + PDF-fetch workflow lives on the "Invoice Sync" page.
		report.page.add_inner_button(__("Invoice Sync Page"), function () {
			frappe.set_route("invoice-sync");
		});
	},
};
