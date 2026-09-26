/**
 * Put "Production" in the breadcrumb on the Machine and Machine Type desk FORMS.
 *
 * The module screens fix this themselves from on_page_show (see production_desk.bundle.js for
 * why the default breadcrumb reads "Goods Inward": both workspaces belong to module
 * Alpinos Development, and breadcrumbs.js takes that module's first workspace). A desk
 * form is not one of those screens, and `frappe.re_route` cannot reach it either -- it
 * redirects a list route, not /app/machine/MAC-004 -- so the form is corrected here.
 *
 * `refresh` rather than `onload`: breadcrumbs are redrawn on every route change, and a
 * form kept in memory is re-shown without loading again.
 */

frappe.ui.form.on('Machine', {
	refresh() {
		if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	},
});

frappe.ui.form.on('Machine Type', {
	refresh() {
		if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	},
});

frappe.ui.form.on('Process Master', {
	refresh() {
		if (window.alpinos_production_breadcrumb) alpinos_production_breadcrumb();
	},
});
