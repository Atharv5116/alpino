/**
 * Send users to the Alpinos entry-list pages instead of the standard ERPNext
 * list views for Sales Order, Pick List and Delivery Note.
 *
 * The Report view (List/<doctype>/Report) stays reachable — e.g. from the
 * awesomebar "Sales Order Report" — but every other list-type view (List,
 * Kanban, Dashboard, ...) redirects to the custom page, so clicking
 * "List View" from inside the report also lands on the custom page.
 *
 * Desk does not define `frappe.ready` (that API is website-only). Register after
 * the desk app has bootstrapped so we do not throw on every page load.
 */
(function register_sales_order_hub_redirect() {
	const CUSTOM_LIST_PAGE = {
		"Sales Order": "sales-order-entry-list",
		"Pick List": "pick_list_list",
		"Delivery Note": "delivery_note_entry_list",
	};

	function attach() {
		if (attach._done) return;
		if (!frappe.router || typeof frappe.router.on !== "function") return;
		attach._done = true;
		frappe.router.on("change", function () {
			const r = frappe.get_route() || [];
			if (r[0] === "List" && CUSTOM_LIST_PAGE[r[1]]) {
				const view = (r[2] || "List").toLowerCase();
				if (view !== "report") {
					frappe.set_route(CUSTOM_LIST_PAGE[r[1]]);
				}
			} else if (r[0] === "Pick List" && r[1] && r[1] !== "List") {
				// Intercept standard Pick List form and redirect to custom entry
				frappe.set_route("pick_list_entry", r[1]);
			} else if (r[0] === "Form" && r[1] === "Pick List" && r[2]) {
				frappe.set_route("pick_list_entry", r[2]);
			}
		});
	}

	$(document).on("app_ready", attach);
	// Also try attaching after a short timeout in case app_ready already fired
	setTimeout(attach, 1000);
})();
