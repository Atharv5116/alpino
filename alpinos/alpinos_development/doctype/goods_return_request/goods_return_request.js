// Goods Return Request (FSD Document 1, sections 1 and 2).
//
// The channel follows the user's roles (2.3.3): one channel is filled in and locked, two can
// be chosen, none means a request cannot be raised. The server checks the same rule on every
// save, submit and cancel (alpinos.goods_return.access), so this only shapes the form.

const GRR_ACCESS = "alpinos.goods_return.access";

frappe.ui.form.on("Goods Return Request", {
	setup(frm) {
		frm.set_query("channel", () => ({
			filters: { name: ["in", (frm._grr_access && frm._grr_access.channels) || [frm.doc.channel || ""]] },
		}));
		frm.set_query("customer", () => ({
			query: `${GRR_ACCESS}.customer_query`,
			filters: { channel: frm.doc.channel || "" },
		}));
		frm.set_query("destination_customer", () => ({
			query: `${GRR_ACCESS}.customer_query`,
			filters: { any_channel: 1 },
		}));
		frm.set_query("sales_order", () => ({
			filters: { customer: frm.doc.customer || "", company: frm.doc.company || "", docstatus: 1 },
		}));
		frm.set_query("delivery_note", () => {
			const filters = { customer: frm.doc.customer || "", company: frm.doc.company || "", docstatus: 1, is_return: 0 };
			if (frm.doc.sales_order) filters.custom_sales_order_id = frm.doc.sales_order;
			return { filters };
		});
		frm.set_query("return_reason", "items", () => ({ filters: { enabled: 1 } }));
	},

	onload(frm) {
		if (frm.doc.docstatus === 0) grr_load_access(frm);
	},

	refresh(frm) {
		grr_channel_state(frm);
		if (frm.doc.docstatus === 0 && frm.doc.delivery_note) {
			frm.add_custom_button(__("Get Items from Delivery Note"), () => grr_get_dn_items(frm));
		}
	},

	company(frm) {
		if (frm.is_new()) grr_load_access(frm);
	},

	channel(frm) {
		// another channel means another pool of buyers: the party and its orders go
		["customer", "sales_order", "delivery_note"].forEach((f) => frm.doc[f] && frm.set_value(f, null));
	},

	customer(frm) {
		["sales_order", "delivery_note"].forEach((f) => frm.doc[f] && frm.set_value(f, null));
	},

	return_handling_type(frm) {
		if (frm.doc.return_handling_type !== "Customer-to-Customer Redistribution" && frm.doc.destination_customer) {
			frm.set_value("destination_customer", null);
		}
	},
});

function grr_load_access(frm) {
	// onload and the company default can both ask at once: one question per company
	const key = frm.doc.company || "";
	if (frm._grr_loading && frm._grr_loading.key === key) return frm._grr_loading.promise;
	const promise = frappe
		.xcall(`${GRR_ACCESS}.get_request_access`, { company: frm.doc.company || null })
		.then((access) => {
			frm._grr_access = access;
			if (!frm.is_new()) {
				// an existing draft: only lock or free the channel; Executives and managers may
				// open drafts they cannot raise themselves
				grr_channel_state(frm);
				return;
			}
			if (!access.channels.length) {
				if (frm._grr_blocked) return;
				frm._grr_blocked = true;
				frappe.msgprint({
					title: __("Not Permitted"),
					indicator: "red",
					message: __(
						"To raise a goods return you need the Goods Return Coordinator role and a Sales or E-Commerce role."
					),
				});
				frappe.set_route("List", "Goods Return Request");
				return;
			}
			if (frm.doc.channel && !access.channels.includes(frm.doc.channel)) {
				frm.set_value("channel", null);
			}
			if (!frm.doc.channel && access.default) frm.set_value("channel", access.default);
			grr_channel_state(frm);
		});
	frm._grr_loading = { key, promise };
	return promise;
}

function grr_channel_state(frm) {
	const access = frm._grr_access;
	const locked = frm.doc.docstatus !== 0 || (access && access.locked);
	frm.set_df_property("channel", "read_only", locked ? 1 : 0);
}

function grr_get_dn_items(frm) {
	const fill = () =>
		frappe.xcall(`${GRR_ACCESS}.get_delivery_note_items`, { delivery_note: frm.doc.delivery_note }).then((r) => {
			frm.clear_table("items");
			(r.rows || []).forEach((row) => {
				const d = frm.add_child("items");
				Object.assign(d, row);
			});
			if (!frm.doc.sales_order && r.sales_order) frm.doc.sales_order = r.sales_order;
			frm.refresh_fields();
			const n = (r.rows || []).length;
			frappe.show_alert({
				message:
					(n === 1 ? __("1 item added.") : __("{0} items added.", [n])) +
					" " +
					__("Set the return reason and lower each quantity to what comes back."),
				indicator: "green",
			});
		});
	const has_rows = (frm.doc.items || []).some((d) => d.item_code);
	if (has_rows) {
		frappe.confirm(__("Replace the items already on this request?"), fill);
	} else {
		fill();
	}
}
