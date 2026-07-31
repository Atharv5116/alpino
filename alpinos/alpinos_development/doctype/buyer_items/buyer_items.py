import frappe
from frappe import _
from frappe.model.document import Document


class BuyerItems(Document):
	def validate(self):
		# Legacy rows stored buyer as Buyer Master name — migrate to Customer.
		if self.buyer and frappe.db.exists("Buyer Master", self.buyer):
			cust = frappe.db.get_value("Buyer Master", self.buyer, "customer")
			if cust:
				self.buyer = cust
			else:
				frappe.throw(
					_("This record points to Buyer Master {0}, which has no Customer set. Set Customer on the master first, then save again.").format(
						frappe.bold(self.buyer)
					)
				)

		if self.buyer and not frappe.db.exists("Buyer Master", {"customer": self.buyer}):
			frappe.throw(
				_("Customer {0} must have an Buyer Master. Create or link the master first.").format(
					frappe.bold(self.buyer)
				),
				title=_("Invalid Customer"),
			)

		if self.buyer:
			duplicate = frappe.db.get_value("Buyer Items", {"buyer": self.buyer}, "name")
			if duplicate and duplicate != self.name:
				frappe.throw(
					_(
						"An Buyer Items catalog already exists for {0} ({1}). "
						"Only one catalog per offline buyer is allowed."
					).format(frappe.bold(self.buyer), frappe.bold(duplicate)),
					title=_("Duplicate catalog"),
				)
		
		# Fetch Level from Master
		if self.buyer:
			level = frappe.db.get_value("Buyer Master", {"customer": self.buyer}, "level")
			if level:
				self.level = level
