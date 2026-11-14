// Quotation list (doc Section 8): the Quotation Status badge (Draft orange, Negotiation blue,
// Finalized green, Sales Order Created purple, Cancelled red) and, in its own column, the
// Payment Status badge (Pending red, Partially Received yellow, Fully Received green). They are
// two separate things and never shown as one status; Force Complete Applied is only a filter.
(function () {
	const settings = (frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {});
	const status_colors = {
		Draft: "orange",
		Negotiation: "blue",
		Finalized: "green",
		"Sales Order Created": "purple",
		Cancelled: "red",
	};
	const payment_colors = { Pending: "red", "Partially Received": "yellow", "Fully Received": "green" };
	settings.add_fields = Array.from(
		new Set([...(settings.add_fields || []), "custom_quotation_status", "custom_payment_status", "custom_force_complete_applied"])
	);
	settings.get_indicator = function (doc) {
		const status = doc.custom_quotation_status;
		if (!status) return null;
		return [__(status), status_colors[status] || "gray", `custom_quotation_status,=,${status}`];
	};
	settings.formatters = Object.assign(settings.formatters || {}, {
		custom_payment_status(value) {
			if (!value) return "";
			return `<span class="indicator-pill ${payment_colors[value] || "gray"}">${__(value)}</span>`;
		},
	});
})();
