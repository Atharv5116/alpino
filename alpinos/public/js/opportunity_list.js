// Opportunity list status badges (doc Section 8): Pending (Draft) orange, Pending (Submitted)
// blue, Converted to Quotation blue, Won green, Partial yellow, Hold gray, Lost red, Cancelled
// red. The badge filters the list on that status. Columns and filters: offline_sales.list_views.
(function () {
	const settings = (frappe.listview_settings["Opportunity"] = frappe.listview_settings["Opportunity"] || {});
	const colors = {
		"Pending (Draft)": "orange",
		"Pending (Submitted)": "blue",
		"Converted to Quotation": "blue",
		Won: "green",
		Partial: "yellow",
		Hold: "gray",
		Lost: "red",
		Cancelled: "red",
	};
	settings.add_fields = Array.from(new Set([...(settings.add_fields || []), "custom_opportunity_status"]));
	settings.get_indicator = function (doc) {
		const status = doc.custom_opportunity_status;
		if (!status) return null;
		return [__(status), colors[status] || "gray", `custom_opportunity_status,=,${status}`];
	};
})();
