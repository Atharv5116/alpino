frappe.ui.form.on("Offline Buyer Master", {
	refresh(frm) {
		toggle_tax_fields(frm);
		set_city_state_queries(frm);
		set_margin_queries(frm);
		toggle_shipping_editability(frm);
		if (frm.doc.shipping_same_as_profile && (frm.doc.addresses || []).length) {
			copy_shipping_address(frm);
		} else if ((frm.doc.addresses || []).some((r) => cint(r.is_shipping))) {
			sync_shipping_from_table(frm);
		}
		frm.set_query("party_owner", () => ({
			query: "alpinos.offline_buyer_api.party_owner_user_query",
		}));
	},

	payment_term(frm) {
		if (frm.doc.payment_term === "Advance") {
			frm.set_value("payment_term_days", null);
		}
		frm.refresh_field("payment_term_days");
	},

	gst_type(frm) {
		toggle_tax_fields(frm);
	},

	shipping_same_as_profile(frm) {
		copy_shipping_address(frm);
	},
});

function get_primary_address_row(frm) {
	const rows = frm.doc.addresses || [];
	const p = rows.find((r) => cint(r.is_primary));
	return p || rows[0];
}

function copy_shipping_address(frm) {
	if (frm.doc.shipping_same_as_profile) {
		const pr = get_primary_address_row(frm);
		if (pr) {
			frm.set_value("shipping_address", pr.address_line || "");
			frm.set_value("shipping_state", pr.state || "");
			frm.set_value("shipping_city", pr.city || "");
		}
	}
	toggle_shipping_editability(frm);
}

function get_shipping_address_row(frm) {
	const rows = frm.doc.addresses || [];
	return rows.find((r) => cint(r.is_shipping)) || null;
}

function sync_shipping_from_table(frm) {
	if (frm.doc.shipping_same_as_profile) {
		copy_shipping_address(frm);
		return;
	}
	const sh = get_shipping_address_row(frm);
	if (sh) {
		frm.set_value("shipping_address", sh.address_line || "");
		frm.set_value("shipping_state", sh.state || "");
		frm.set_value("shipping_city", sh.city || "");
		toggle_shipping_editability(frm);
	}
}

frappe.ui.form.on("Offline Buyer Address", {
	is_primary(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.is_primary) {
			(frm.doc.addresses || []).forEach((r) => {
				if (r.name && r.name !== row.name && cint(r.is_primary)) {
					frappe.model.set_value(r.doctype, r.name, "is_primary", 0);
				}
			});
		}
		if (frm.doc.shipping_same_as_profile) {
			copy_shipping_address(frm);
		}
	},

	is_shipping(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.is_shipping && !frm.doc.shipping_same_as_profile) {
			sync_shipping_from_table(frm);
		}
	},

	address_line(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (frm.doc.shipping_same_as_profile) {
			copy_shipping_address(frm);
		} else if (cint(row.is_shipping)) {
			sync_shipping_from_table(frm);
		}
	},

	state(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "city", "");
		const row = locals[cdt][cdn];
		if (frm.doc.shipping_same_as_profile) {
			copy_shipping_address(frm);
		} else if (cint(row.is_shipping)) {
			sync_shipping_from_table(frm);
		}
	},

	city(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (frm.doc.shipping_same_as_profile) {
			copy_shipping_address(frm);
		} else if (cint(row.is_shipping)) {
			sync_shipping_from_table(frm);
		}
	},
});

function toggle_tax_fields(frm) {
	const gst_type = frm.doc.gst_type;
	const is_registered = gst_type === "Registered Business";
	const is_unregistered = gst_type === "Unregistered Business";

	frm.toggle_display("gst_no", is_registered);
	frm.toggle_display("gst_certificate", is_registered);
	frm.toggle_reqd("gst_no", is_registered);
	frm.toggle_reqd("gst_certificate", is_registered);

	frm.toggle_display("pan_no", is_unregistered);
	frm.toggle_display("pan_attachment", is_unregistered);
	frm.toggle_reqd("pan_no", is_unregistered);
	frm.toggle_reqd("pan_attachment", is_unregistered);
}

function set_city_state_queries(frm) {
	frm.set_query("city", "addresses", (doc, cdt, cdn) => {
		const row = locals[cdt][cdn];
		return { filters: { state: row.state || "" } };
	});
	frm.set_query("shipping_city", () => {
		const pr = get_primary_address_row(frm);
		const st = frm.doc.shipping_same_as_profile
			? pr?.state || frm.doc.shipping_state
			: frm.doc.shipping_state;
		return { filters: { state: st || "" } };
	});
}

function toggle_shipping_editability(frm) {
	const has_shipping_row = !frm.doc.shipping_same_as_profile &&
		(frm.doc.addresses || []).some((r) => cint(r.is_shipping));
	const lock = !!frm.doc.shipping_same_as_profile || has_shipping_row;
	["shipping_address", "shipping_state", "shipping_city"].forEach((fieldname) => {
		frm.set_df_property(fieldname, "read_only", lock ? 1 : 0);
	});
}

function set_margin_queries(frm) {
	const allowed_groups = [
		"Super Vital",
		"SuperOne",
		"Vinegar",
		"Peanut Crackers",
		"Cornflakes",
		"Protein",
		"Peanut Butter",
		"Oats",
		"Muesli",
		"Bar",
	];

	frm.set_query("item_group", "margins", () => ({
		filters: {
			name: ["in", allowed_groups],
		},
	}));

	frm.set_query("sku", "margins", () => ({
		filters: {
			disabled: 0,
			variant_of: ["!=", ""],
		},
	}));
}

frappe.ui.form.on("Offline Buyer Margin", {
	item_group(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_group) return;

		frappe.call({
			method: "alpinos.offline_buyer_api.get_variant_items_for_group",
			args: {
				item_group: row.item_group,
			},
			callback(r) {
				const items = r.message || [];
				if (!items.length) return;

				const margin = row.margin_percent || 0;
				const existing = new Set((frm.doc.margins || []).map((d) => d.sku).filter(Boolean));

				items.forEach((it) => {
					if (existing.has(it.name)) return;
					const child = frm.add_child("margins");
					child.sku = it.name;
					child.product_name = it.item_name || "";
					child.margin_percent = margin;
				});

				frappe.model.clear_doc(cdt, cdn);
				frm.refresh_field("margins");
			},
		});
	},

	sku(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sku) return;

		frappe.db.get_value("Item", row.sku, ["variant_of", "item_name"], (r) => {
			if (!r) return;
			if (!r.variant_of) {
				frappe.msgprint("Only variant items are allowed in SKU.");
				frappe.model.set_value(cdt, cdn, "sku", "");
				frappe.model.set_value(cdt, cdn, "product_name", "");
				return;
			}

			if (!row.product_name) {
				frappe.model.set_value(cdt, cdn, "product_name", r.item_name || "");
			}
		});
	},
});
