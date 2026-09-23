frappe.query_reports["Purchase QC Stock"] = {
	filters: [
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "supplier", label: __("Vendor"), fieldtype: "Link", options: "Supplier" },
		{
			fieldname: "qc_status",
			label: __("QC Status"),
			fieldtype: "Select",
			options: ["", "Pending QC", "QC In Progress"].join("\n"),
		},
	],
};
