// Quotation list, Offline Sales ("Opportunity to Sales Order v1.0.0", Section 1, 3.3): with
// manager scoping switched on, a Sales Admin's list opens on the Quotations of the buyers they
// are Secondary POC of; Show All lifts it. List scope only, never permission. Extends whatever
// listview settings ERPNext already registered for Quotation.
(function () {
	const settings = (frappe.listview_settings["Quotation"] = frappe.listview_settings["Quotation"] || {});
	const previous = settings.onload;
	settings.onload = function (listview) {
		if (previous) previous.call(this, listview);
		frappe.xcall("alpinos.offline_sales.access.list_scope").then((scope) => {
			if (!scope.secondary_poc_default) return;
			let show_all = false;
			const btn = listview.page.add_inner_button(__("Show All"), () => {
				show_all = !show_all;
				apply();
			});
			const apply = () => {
				listview.filter_area.remove("custom_secondary_poc");
				if (!show_all) listview.filter_area.add([["Quotation", "custom_secondary_poc", "=", scope.employee]]);
				btn.text(show_all ? __("My Buyers") : __("Show All"));
			};
			apply();
		});
	};
})();
