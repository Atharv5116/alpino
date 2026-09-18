// The Purchase Inward module's documents have list screens of their own. The desk's plain
// list view for them is reached by accident -- the "Purchase Inward" breadcrumb on the print
// screen, the breadcrumb on a desk form, "View Purchase Inward" on a Purchase Order -- and
// users landed on a bare grid that looks nothing like the module. Send those to the module's
// list pages instead.
//
// frappe.re_route is the router's own redirect table: the redirect happens before the desk
// list renders, and Back from the module page returns to where the user came from (the
// router steps over the redirected entry) instead of bouncing between the two. Route
// options set by the caller, e.g. a purchase_order filter, ride along to the module page.
// The report view (/app/purchase-inward/view/report) is left reachable.

(function () {
	const redirects = {
		'purchase-inward': 'purchase_inward_list',
		'purchase-qc': 'purchase_qc_list',
		'purchase-quarantine': 'purchase_quarantine_list',
	};
	frappe.re_route = frappe.re_route || {};
	Object.keys(redirects).forEach((from) => {
		if (frappe.re_route[from] === undefined) frappe.re_route[from] = redirects[from];
	});
})();
