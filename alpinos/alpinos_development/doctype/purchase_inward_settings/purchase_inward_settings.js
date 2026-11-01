// Warehouses by Company: each row's warehouse pickers offer only that company's warehouses.
frappe.ui.form.on("Purchase Inward Settings", {
	setup(frm) {
		["qc_hold_warehouse", "qc_sample_warehouse", "rejected_warehouse", "quarantine_warehouse",
			"control_sample_warehouse"].forEach((field) => {
			frm.set_query(field, "company_warehouses", (doc, cdt, cdn) => ({
				filters: { company: locals[cdt][cdn].company, is_group: 0 },
			}));
			frm.set_query(field, () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		});
	},
});
