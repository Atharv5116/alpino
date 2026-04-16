frappe.ui.form.on("Alpino Product Sale", {
	refresh(frm) {
		toggle_payment_screenshot(frm);
	},

	payment_mode(frm) {
		toggle_payment_screenshot(frm);
	},
});

function toggle_payment_screenshot(frm) {
	const is_qr = frm.doc.payment_mode === "QR";
	frm.toggle_display("payment_screenshot", is_qr);
	frm.toggle_reqd("payment_screenshot", is_qr);
	if (!is_qr && frm.doc.payment_screenshot) {
		frm.set_value("payment_screenshot", null);
	}
}
