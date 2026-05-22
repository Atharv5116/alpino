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
			} else if (r[0] === "List" && r[1] === "Pick List") {
				frappe.set_route("pick-list-list");
			} else if (r[0] === "Pick List" && r[1] && r[1] !== "List") {
				// Intercept standard Pick List form and redirect to custom entry
				frappe.set_route("app", "pick-list-entry", { name: r[1] });
			} else if (r[0] === "Form" && r[1] === "Pick List" && r[2]) {
				frappe.set_route("app", "pick-list-entry", { name: r[2] });
			}
		});
	}

	$(document).on("app_ready", attach);
	// Also try attaching after a short timeout in case app_ready already fired
	setTimeout(attach, 1000);
})();
