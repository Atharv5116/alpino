// Buyer Master list (Offline Sales, "Opportunity to Sales Order v1.0.0" Sections 1 and 4).
//
//   * status badge (doc Section 8: Pending Approval orange, Approved green, On Hold yellow,
//     Inactive gray, Cancelled red); newest first;
//   * "+ Create New Buyer" opens the creation modal; for a Sales Officer it IS the Add button;
//   * a Sales Admin, with manager scoping switched on, opens on the buyers they are Secondary
//     POC of, and Show All lifts that. List scope only: their permissions are unchanged.

frappe.listview_settings["Buyer Master"] = {
	add_fields: ["buyer_status", "buyer_catalog_status", "channel"],

	get_indicator(doc) {
		if ((doc.channel || "") === "E-com") return null;
		const status = doc.buyer_status || "Approved";
		const colors = { "Pending Approval": "orange", Approved: "green", "On Hold": "yellow", Inactive: "gray", Cancelled: "red" };
		return [__(status), colors[status] || "gray", `buyer_status,=,${status}`];
	},

	primary_action() {
		const officer = frappe.user.has_role("Sales Officer")
			&& !["Sales Manager", "Sales Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (officer && window.alpinos_offline) {
			alpinos_offline.create_buyer();
		} else {
			frappe.new_doc("Buyer Master");
		}
	},

	onload(listview) {
		if (window.alpinos_offline && frappe.model.can_create("Buyer Master")) {
			listview.page.add_inner_button(__("Create New Buyer"), () => alpinos_offline.create_buyer());
		}
		frappe.xcall("alpinos.offline_sales.access.list_scope").then((scope) => {
			if (!scope.secondary_poc_default) return;
			let show_all = false;
			const apply = () => {
				listview.filter_area.remove("secondary_poc");
				if (!show_all) listview.filter_area.add([["Buyer Master", "secondary_poc", "=", scope.employee]]);
				btn.text(show_all ? __("My Buyers") : __("Show All"));
			};
			const btn = listview.page.add_inner_button(__("Show All"), () => {
				show_all = !show_all;
				apply();
			});
			apply();
		});
	},
};
