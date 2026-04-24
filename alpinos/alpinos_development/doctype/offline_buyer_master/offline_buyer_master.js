frappe.ui.form.on("Offline Buyer Master", {
	refresh(frm) {
		toggle_tax_fields(frm);
		set_city_state_options(frm);
		toggle_shipping_editability(frm);
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

function set_city_state_options(frm) {
	const state_options = [
		"Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
		"Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
		"Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
		"Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
		"Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "Chandigarh",
		"Dadra and Nagar Haveli and Daman and Diu", "Jammu and Kashmir", "Ladakh",
		"Lakshadweep", "Puducherry", "Andaman and Nicobar Islands"
	];

	const city_seed = [
		"Ahmedabad", "Bengaluru", "Chennai", "Delhi", "Hyderabad", "Jaipur",
		"Kolkata", "Lucknow", "Mumbai", "Nagpur", "Pune", "Surat"
	];

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Offline Buyer Master",
			fields: ["city", "state", "shipping_city", "shipping_state"],
			limit_page_length: 1000,
		},
		callback(r) {
			const rows = r.message || [];
			const city_set = new Set(city_seed);
			const state_set = new Set(state_options);

			rows.forEach((d) => {
				[d.city, d.shipping_city].forEach((c) => c && city_set.add(c));
				[d.state, d.shipping_state].forEach((s) => s && state_set.add(s));
			});

			const city_list = Array.from(city_set).sort().join("\n");
			const state_list = Array.from(state_set).sort().join("\n");

			["city", "shipping_city"].forEach((f) => frm.set_df_property(f, "options", city_list));
			["state", "shipping_state"].forEach((f) => frm.set_df_property(f, "options", state_list));
		},
	});
}

function toggle_shipping_editability(frm) {
	const lock = !!frm.doc.shipping_same_as_profile;
	["shipping_address", "shipping_state", "shipping_city"].forEach((fieldname) => {
		frm.set_df_property(fieldname, "read_only", lock ? 1 : 0);
	});
}

frappe.ui.form.on("Offline Buyer Margin", {
	item_group(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_group) return;

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Item",
				fields: ["name", "item_name"],
				filters: { item_group: row.item_group, disabled: 0, has_variants: 0 },
				limit_page_length: 1000,
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
});
