/**
 * Send users to the Alpinos Sales Order hub list instead of the standard ERPNext
 * Sales Order list (Kanban / List / etc.).
 */
frappe.ready(function () {
	frappe.router.on("change", function () {
		const r = frappe.get_route() || [];
		if (r[0] === "List" && r[1] === "Sales Order") {
			frappe.set_route("sales-order-entry-list");
		}
	});
});
