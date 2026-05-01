frappe.ui.form.on("Offline Buyer Master", {
	refresh(frm) {
		toggle_tax_fields(frm);
		set_city_state_queries(frm);
		set_margin_queries(frm);
		toggle_shipping_editability(frm);
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

	address(frm) {
		if (frm.doc.shipping_same_as_profile) {
			copy_shipping_address(frm);
		}
	},

	state(frm) {
		if (frm.doc.shipping_same_as_profile) {
			frm.set_value("shipping_state", frm.doc.state || "");
		}
	},

	city(frm) {
		if (frm.doc.shipping_same_as_profile) {
			frm.set_value("shipping_city", frm.doc.city || "");
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

function copy_shipping_address(frm) {
	if (frm.doc.shipping_same_as_profile) {
		frm.set_value("shipping_address", frm.doc.address || "");
		frm.set_value("shipping_state", frm.doc.state || "");
		frm.set_value("shipping_city", frm.doc.city || "");
	}
	toggle_shipping_editability(frm);
}

function set_city_state_queries(frm) {
	frm.set_query("city", () => ({
		filters: { state: frm.doc.state || "" }
	}));
	frm.set_query("shipping_city", () => ({
		filters: { state: frm.doc.shipping_state || frm.doc.state || "" }
	}));
}

function toggle_shipping_editability(frm) {
	const lock = !!frm.doc.shipping_same_as_profile;
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

	// Only variants should be selectable in SKU.
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

				// Keep table clean: remove pure item-group helper row after expansion.
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
