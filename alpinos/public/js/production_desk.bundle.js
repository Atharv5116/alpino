/**
 * Small helpers shared by the Production master screens.
 *
 * They live in one globally-included file because each is needed from several screens,
 * or before any page script has run at all. Anything used by a single screen belongs in
 * that screen instead.
 */

/**
 * Machine and Machine Type have list screens of their own, the same as the Purchase
 * Inward documents do (see purchase_list_redirects.js for why frappe.re_route rather
 * than a redirect inside the list view). The desk grid for them is reached by accident —
 * a breadcrumb, a link from a Machine Type field — and shows raw TYP- ids where the
 * module screens show the type name and what still depends on it.
 *
 * The report view (/app/machine/view/report) stays reachable.
 */
(function () {
	const redirects = {
		'machine': 'machine_list',
		'machine-type': 'machine_type_list',
	};
	frappe.re_route = frappe.re_route || {};
	Object.keys(redirects).forEach((from) => {
		if (frappe.re_route[from] === undefined) frappe.re_route[from] = redirects[from];
	});
})();

/**
 * A capacity written the way a person writes it: "23 KG", never "23.000 KG".
 *
 * format_number pads to float_precision, which defaults to 3, because it is built for
 * money (number_format.js: `decimals = cint(...float_precision) || 3`). A machine
 * capacity is a count of trays or kilos and the padding is noise -- but the thousands
 * separator is not, which is why this still goes through format_number rather than
 * String(v). Returns plain text; the caller escapes it.
 */
window.alpinos_format_capacity = function (value, uom) {
	if (value === null || value === undefined || value === '') return '';
	const n = flt(value);
	// Only the decimals actually present, capped so a float artefact cannot print 15.
	const decimals = Math.min((String(n).split('.')[1] || '').length, 6);
	const number = format_number(n, null, decimals);
	return uom ? `${number} ${uom}` : number;
};

/**
 * Put "Production" in the breadcrumb, optionally followed by one crumb of its own.
 *
 * Frappe derives a page's breadcrumb from its MODULE and picks that module's FIRST
 * workspace (breadcrumbs.js -> set_workspace: module_wise_workspaces[module][0]).
 * Goods Inward and Production are both "Alpinos Development" and Goods Inward comes
 * first, so every Production screen was labelled Goods Inward. breadcrumbs.add() with
 * type "Custom" says it outright. It keys off the current route, so each screen calls
 * this from its own on_page_show.
 *
 * An entry screen passes its list as `label` and `route`, giving the ordinary desk shape
 * of workspace > list > document: coming out of one record you almost always want the
 * other records, and the workspace is still one crumb further left.
 */
window.alpinos_workspace_breadcrumb = function (workspace, label, route) {
	if (!(window.frappe && frappe.breadcrumbs && frappe.breadcrumbs.add)) return;
	const trail = (label && route) ? [{ label: label, route: route }] : [];
	if (trail.length) alpinos_support_breadcrumb_trail();
	frappe.breadcrumbs.add({
		type: 'Custom',
		label: workspace.label,
		route: workspace.route,
		alpinos_trail: trail,
	});
};

window.alpinos_production_breadcrumb = function (label, route) {
	alpinos_workspace_breadcrumb(
		{ label: __('Production'), route: '/app/production' }, label, route
	);
};

/**
 * The same for the Goods Inward screens (Purchase Order, Inward, QC, GRN, Invoice,
 * Quarantine).
 *
 * These never called a helper: their module-derived crumb already reads "Goods Inward",
 * because that workspace happens to be the FIRST one for module Alpinos Development --
 * the same accident that mislabelled every Production screen. Setting it explicitly
 * costs nothing and stops the label depending on workspace ordering, and it is the only
 * way to hang the list crumb after it.
 */
window.alpinos_goods_inward_breadcrumb = function (label, route) {
	alpinos_workspace_breadcrumb(
		{ label: __('Goods Inward'), route: '/app/goods-inward' }, label, route
	);
};

/**
 * Teach frappe.breadcrumbs to draw more than one custom crumb.
 *
 * It cannot be done by appending the extra element after the add() call. container.js
 * change_to() fires the page "show" event -- which is what runs on_page_show, where the
 * helper above is called from -- and only THEN calls breadcrumbs.update(), which clears
 * the bar and redraws it from the single object add() stored. Anything appended by hand
 * is wiped a moment later. So the extra crumb has to travel on that stored object, and
 * set_custom_breadcrumbs has to know to draw it.
 *
 * Patched once, lazily, and only when a screen actually asks for a trail.
 */
function alpinos_support_breadcrumb_trail() {
	const crumbs = frappe.breadcrumbs;
	if (crumbs._alpinos_trail_patched) return;
	if (!(crumbs.set_custom_breadcrumbs && crumbs.append_breadcrumb_element)) return;
	crumbs._alpinos_trail_patched = true;
	const original = crumbs.set_custom_breadcrumbs;
	crumbs.set_custom_breadcrumbs = function (breadcrumbs) {
		original.call(this, breadcrumbs);
		// Array-checked, not just truthy: this runs for every custom breadcrumb on the
		// site, including ones set by code that has never heard of alpinos_trail.
		const trail = breadcrumbs.alpinos_trail;
		if (!Array.isArray(trail)) return;
		trail.forEach((crumb) => {
			if (crumb && crumb.route && crumb.label) {
				this.append_breadcrumb_element(crumb.route, crumb.label);
			}
		});
	};
}
