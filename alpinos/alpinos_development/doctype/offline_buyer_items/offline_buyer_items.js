// Copyright (c) 2026, Alpinos and contributors
// License: MIT

frappe.ui.form.on("Offline Buyer Items", {
	refresh(frm) {
		frm.set_query("buyer", () => ({
			query: "alpinos.sales_order_offline_buyer.catalog_customer_query",
		}));
	},
});
