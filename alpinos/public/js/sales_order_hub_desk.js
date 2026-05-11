/**
 * Send users to the Alpinos Sales Order hub list instead of the standard ERPNext
 * Sales Order list (Kanban / List / etc.).
 *
 * Desk does not define `frappe.ready` (that API is website-only). Register after
 * the desk app has bootstrapped so we do not throw on every page load.
 */
(function register_sales_order_hub_redirect() {
	function attach() {
		if (attach._done) return;
		if (!frappe.router || typeof frappe.router.on !== "function") return;
		attach._done = true;
		frappe.router.on("change", function () {
			const r = frappe.get_route() || [];
			if (r[0] === "List" && r[1] === "Sales Order") {
				frappe.set_route("sales-order-entry-list");
			}
		});
	}

	if (typeof frappe.ready === "function") {
		frappe.ready(attach);
	} else {
		$(document).on("app_ready", attach);
	}
})();
