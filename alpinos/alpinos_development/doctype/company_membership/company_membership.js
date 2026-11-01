// Company Membership: the company-wise roles one user holds in one company.
frappe.ui.form.on("Company Membership", {
	setup(frm) {
		// Only company-wise roles belong here; the rest are given on the User form.
		frm.set_query("role", "roles", () => ({ filters: { custom_company_scoped: 1, disabled: 0 } }));
	},
	refresh(frm) {
		frm.add_custom_button(__("Company Access Manager"), () =>
			frappe.set_route("company-access-manager", { user: frm.doc.user })
		);
	},
});
