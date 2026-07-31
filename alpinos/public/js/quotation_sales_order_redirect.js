// Alpinos Quotation patches:
//  1. Redirect "Create → Sales Order" on submitted Quotation to the custom Sales Order Entry page.
//  2. Skip erpnext.utils.get_party_details when quotation_to = "Buyer Master"
//     (standard ERPNext party fetch fails with "customer not found" for non-standard party types).

(function () {
	// ── Patch 1: get_party_details guard for Buyer Master ──────────────
	function patch_get_party_details() {
		if (!window.erpnext || !erpnext.utils || !erpnext.utils.get_party_details) {
			return false;
		}
		if (erpnext.utils.get_party_details._alpinos_obm_patched) {
			return true;
		}
		const _orig = erpnext.utils.get_party_details;
		erpnext.utils.get_party_details = function (frm) {
			if (
				frm &&
				frm.doctype === "Quotation" &&
				frm.doc.quotation_to === "Buyer Master"
			) {
				// Skip standard party details fetch — our own sync_obm_quotation_header handles it.
				return;
			}
			return _orig.apply(this, arguments);
		};
		erpnext.utils.get_party_details._alpinos_obm_patched = true;
		return true;
	}

	// ── Patch 2: Sales Order redirect ─────────────────────────────────────────
	function patch_quotation_sales_order_redirect() {
		if (
			!window.erpnext ||
			!erpnext.selling ||
			typeof erpnext.selling.QuotationController !== "function"
		) {
			return false;
		}
		const C = erpnext.selling.QuotationController;
		const existing = C.prototype.make_sales_order;
		if (!existing || existing.__alpinos_redirect_patched) {
			return true;
		}

		const original = existing;
		C.prototype.make_sales_order = function () {
			let me = this;
			let has_alternative_item = this.frm.doc.items.some((item) => item.is_alternative);
			if (has_alternative_item) {
				return original.apply(this, arguments);
			}
			if (this.frm.doc.docstatus !== 1) {
				return original.apply(this, arguments);
			}
			frappe.route_options = frappe.route_options || {};
			frappe.route_options.from_quotation = me.frm.doc.name;
			frappe.set_route("sales-order-entry");
		};
		C.prototype.make_sales_order.__alpinos_redirect_patched = true;
		return true;
	}

	frappe.after_ajax(function () {
		// Apply both patches; retry until the controllers are loaded.
		const done1 = patch_get_party_details();
		const done2 = patch_quotation_sales_order_redirect();
		if (done1 && done2) return;

		let tries = 0;
		const iv = setInterval(function () {
			const d1 = patch_get_party_details();
			const d2 = patch_quotation_sales_order_redirect();
			if ((d1 && d2) || tries++ > 50) clearInterval(iv);
		}, 200);
	});
})();
