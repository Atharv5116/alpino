// Warehouses by Company: each row's warehouse pickers offer only that company's warehouses.
frappe.ui.form.on("Production Settings", {
	setup(frm) {
		["main_warehouse", "wip_warehouse", "baked_wip_warehouse", "fg_warehouse", "fg_hold_warehouse",
			"rejected_warehouse"].forEach((field) => {
			frm.set_query(field, "company_warehouses", (doc, cdt, cdn) => ({
				filters: { company: locals[cdt][cdn].company, is_group: 0 },
			}));
		});
	},
});
