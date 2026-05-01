import frappe
from frappe import _
from frappe.model.document import Document
class OfflineBuyerMaster(Document):
	def validate(self):
		if not self.customer:
			frappe.throw(_("Customer is required on Offline Buyer Master."))

		if self.payment_term in ("Credit", "Partial"):
			if self.payment_term_days is None:
				frappe.throw(
					_("Days is required when Payment Term is Credit or Partial."),
					title=_("Payment Term"),
				)
		else:
			# Advance: do not keep credit/partial days on the document
			self.payment_term_days = None

		filters = {"customer": self.customer}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.count("Offline Buyer Master", filters):
			frappe.throw(
				_("Only one Offline Buyer Master is allowed per Customer. Another record already uses {0}.").format(
					frappe.bold(self.customer)
				),
				title=_("Duplicate Offline Buyer Master"),
			)

	def before_insert(self):
		if not self.customer_id:
			self.customer_id = self.name
