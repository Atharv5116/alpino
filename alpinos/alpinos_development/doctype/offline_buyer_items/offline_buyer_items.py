import frappe
from frappe import _
from frappe.model.document import Document


class OfflineBuyerItems(Document):
	def validate(self):
		# Legacy rows stored buyer as Offline Buyer Master name — migrate to Customer.
		if self.buyer and frappe.db.exists("Offline Buyer Master", self.buyer):
			cust = frappe.db.get_value("Offline Buyer Master", self.buyer, "customer")
			if cust:
				self.buyer = cust
			else:
				frappe.throw(
					_("This record points to Offline Buyer Master {0}, which has no Customer set. Set Customer on the master first, then save again.").format(
						frappe.bold(self.buyer)
					)
				)

		if self.buyer and not frappe.db.exists("Offline Buyer Master", {"customer": self.buyer}):
			frappe.throw(
				_("Customer {0} must have an Offline Buyer Master. Create or link the master first.").format(
					frappe.bold(self.buyer)
				),
				title=_("Invalid Customer"),
			)
