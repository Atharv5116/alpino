// Quotation: "Create Sales Order" (doc Section 6). For Sales Manager / Sales Admin (and System
// Manager) when the Quotation is Finalized, SO Eligibility is Allowed and it has no active
// Sales Order; it opens the Sales Order entry page filled from the Quotation. When it cannot be
// used the button says why. A Sales Officer gets no button (the server refuses them too).
//
// ERPNext's own Create > Sales Order, Update Items and Set as Lost are taken off a Quotation of
// this workflow (Finalize / Cancel Quotation and Create Sales Order replace them; the server
// refuses them anyway). ERPNext adds them at the end of its own refresh, after the form scripts
// have run, so they are removed from its controller's refresh, every time it runs.
(function () {
	function strip(frm) {
		if (!frm || frm.doctype !== "Quotation" || !frm.doc || !frm.doc.custom_quotation_status) return;
		frm.remove_custom_button(__("Sales Order"), __("Create"));
		frm.remove_custom_button(__("Update Items"));
		frm.remove_custom_button(__("Set as Lost"));
	}

	function patch() {
		const C = window.erpnext && erpnext.selling && erpnext.selling.QuotationController;
		if (typeof C !== "function") return false;
		if (C.prototype.refresh.__alpinos_strip) return true;
		const original = C.prototype.refresh;
		C.prototype.refresh = function () {
			const out = original.apply(this, arguments);
			strip(this.frm);
			if (out && typeof out.then === "function") out.then(() => strip(this.frm));
			setTimeout(() => strip(this.frm), 0);
			return out;
		};
		C.prototype.refresh.__alpinos_strip = true;
		return true;
	}

	if (!patch()) {
		let tries = 0;
		const iv = setInterval(() => {
			if (patch() || tries++ > 50) clearInterval(iv);
		}, 200);
	}

	frappe.ui.form.on("Quotation", {
		refresh(frm) {
			strip(frm);
			setTimeout(() => strip(frm), 0);
			if (frm.is_new() || frm.doc.docstatus !== 1) return;
			const manager = ["Sales Manager", "Sales Admin", "System Manager"].some((r) => frappe.user.has_role(r));
			if (!manager) return;
			frappe
				.xcall("alpinos.offline_sales.so_handoff.can_create_sales_order", { quotation: frm.doc.name })
				.then((r) => {
					if (!r) return;
					strip(frm);
					if (r.allowed) {
						const btn = frm.add_custom_button(__("Create Sales Order"), () => {
							frappe.route_options = { from_quotation: frm.doc.name };
							frappe.set_route("sales-order-entry");
						});
						btn.addClass("btn-primary");
					} else if (["Finalized", "Sales Order Created"].includes(frm.doc.custom_quotation_status)) {
						frm.add_custom_button(__("Create Sales Order"), () =>
							frappe.msgprint({ title: __("Create Sales Order"), message: r.reason, indicator: "orange" })
						);
					}
				});
		},
	});
})();
