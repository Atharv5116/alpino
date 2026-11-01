frappe.query_reports["Purchase GRN Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: window.alpinos && alpinos.company ? alpinos.company.current() : frappe.defaults.get_user_default("Company") },
	],
};
