// Redirect "Create → Sales Order" on submitted Quotation to the custom Sales Order Entry page.

(function () {
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
		if (patch_quotation_sales_order_redirect()) {
			return;
		}
		let tries = 0;
		let iv = setInterval(function () {
			if (patch_quotation_sales_order_redirect() || tries++ > 50) {
				clearInterval(iv);
			}
		}, 200);
	});
})();
