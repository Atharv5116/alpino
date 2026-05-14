// Copyright (c) 2026, Alpinos and contributors
// License: MIT

frappe.ui.form.on("Sales Order", {
	onload(frm) {
		frm.set_query("customer", () => ({
			query: "alpinos.sales_order_offline_buyer.sales_order_customer_query",
		}));
	},

	refresh(frm) {
		// Align OBM fields when opening / reloading; do not re-apply item rates here.
		sync_offline_buyer_from_customer(frm);
	},

	customer(frm) {
		sync_offline_buyer_from_customer(frm, () => apply_offline_buyer_rates_to_items(frm));
	},
});

function sync_offline_buyer_from_customer(frm, done) {
	if (!frm.fields_dict || !frm.fields_dict.custom_offline_buyer_master) {
		if (typeof done === "function") {
			done();
		}
		return;
	}
	if (!frm.doc.customer) {
		frm.set_value("custom_offline_buyer_master", "");
		frm.set_value("custom_offline_buyer_customer_type", "");
		if (typeof done === "function") {
			done();
		}
		return;
	}

	frappe.call({
		method: "alpinos.sales_order_offline_buyer.get_offline_buyer_for_customer",
		args: { customer: frm.doc.customer },
		callback(r) {
			const m = r.message || {};
			frm.set_value("custom_offline_buyer_master", m.offline_buyer_master || "");
			frm.set_value("custom_offline_buyer_customer_type", m.customer_type || "");
			if (m.customer_type) {
				frm.set_value("order_type", m.customer_type);
			}
			if (typeof done === "function") {
				done();
			}
		},
	});
}

frappe.ui.form.on("Sales Order Item", {
	item_code(frm, cdt, cdn) {
		set_item_rate_from_offline_buyer(frm, cdt, cdn);
	},
});

function set_item_rate_from_offline_buyer(frm, cdt, cdn) {
	if (!frm.doc.customer) {
		return;
	}
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || !row.item_code) {
		return;
	}

	frappe.call({
		method: "alpinos.sales_order_offline_buyer.get_offline_buyer_item_rate",
		args: {
			customer: frm.doc.customer,
			item_code: row.item_code,
		},
		callback(r) {
			const msg = r.message;
			if (msg && typeof msg.rate === "number") {
				frappe.model.set_value(cdt, cdn, "rate", msg.rate);
			}
		},
	});
}

function apply_offline_buyer_rates_to_items(frm) {
	if (!frm.doc.customer || !frm.doc.items || !frm.doc.items.length) {
		return;
	}
	frm.doc.items.forEach((row) => {
		if (row.item_code) {
			set_item_rate_from_offline_buyer(frm, row.doctype, row.name);
		}
	});
}
