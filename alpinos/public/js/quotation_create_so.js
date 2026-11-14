// Quotation: "Create Sales Order" (doc Section 6). For Sales Manager / Sales Admin (and System
// Manager) when the Quotation is Finalized, SO Eligibility is Allowed and it has no active
// Sales Order; it opens the Sales Order entry page filled from the Quotation. When it cannot be
// used the button says why. A Sales Officer gets no button (the server refuses them too).
// ERPNext's own Create > Sales Order is removed so there is one way in.
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		setTimeout(() => frm.remove_custom_button(__("Sales Order"), __("Create")), 0);
		if (frm.is_new() || frm.doc.docstatus !== 1) return;
		const manager = ["Sales Manager", "Sales Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (!manager) return;
		frappe
			.xcall("alpinos.offline_sales.so_handoff.can_create_sales_order", { quotation: frm.doc.name })
			.then((r) => {
				if (!r) return;
				if (r.allowed) {
					const btn = frm.add_custom_button(__("Create Sales Order"), () => {
						frappe.route_options = { from_quotation: frm.doc.name };
						frappe.set_route("sales-order-entry");
					});
					btn.addClass("btn-primary");
				} else if (["Finalized", "Sales Order Created"].includes(frm.doc.custom_quotation_status)) {
					frm.add_custom_button(__("Create Sales Order"), () =>
						frappe.msgprint({ title: __("Create Sales Order"), message: r.reason, indicator: "orange" })
					);
				}
			});
	},
});
