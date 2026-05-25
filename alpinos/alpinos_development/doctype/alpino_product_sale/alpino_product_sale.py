import frappe
from frappe.model.document import Document


class AlpinoProductSale(Document):
	def validate(self):
		if self.payment_mode == "QR" and not self.payment_screenshot:
			frappe.throw("Payment Screenshot is mandatory when Payment Mode is QR.")
