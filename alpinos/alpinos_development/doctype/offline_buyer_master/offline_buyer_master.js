frappe.ui.form.on("Offline Buyer Master", {
	refresh(frm) {
		toggle_tax_fields(frm);
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
	}
}
