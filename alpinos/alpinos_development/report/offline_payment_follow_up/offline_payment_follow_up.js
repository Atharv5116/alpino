frappe.query_reports["Offline Payment Follow-up"] = {
	filters: [
		{ fieldname: "queue", label: __("Queue"), fieldtype: "Select", options: "Due Today\nOverdue", default: "Due Today", reqd: 1 },
	],
};
