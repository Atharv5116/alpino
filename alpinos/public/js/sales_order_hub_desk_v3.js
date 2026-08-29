/**
 * Send users to the Alpinos entry-list pages instead of the standard ERPNext list views
 * for Sales Order, Pick List and Delivery Note. The Report view stays reachable; every
 * other list-type view (List, Kanban, Dashboard, ...) redirects to the custom page.
 * Desk has no `frappe.ready` (website-only), so register after the app bootstraps.
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
				// defer one tick and re-read the route: opening the Report view can fire an
				// intermediate change without the view suffix, wrongly bouncing to the custom list
				const target = CUSTOM_LIST_PAGE[r[1]];
				setTimeout(function () {
					const cur = frappe.get_route() || [];
					if (cur[0] !== "List" || CUSTOM_LIST_PAGE[cur[1]] !== target) return;
					const view = (cur[2] || "List").toLowerCase();
					if (view !== "report") {
						frappe.set_route(target);
					}
				}, 0);
			} else if (r[0] === "Pick List" && r[1] && r[1] !== "List") {
				frappe.set_route("pick_list_entry", r[1]);
			} else if (r[0] === "Form" && r[1] === "Pick List" && r[2]) {
				frappe.set_route("pick_list_entry", r[2]);
			}
		});
	}

	$(document).on("app_ready", attach);
	// in case app_ready already fired
	setTimeout(attach, 1000);
})();
