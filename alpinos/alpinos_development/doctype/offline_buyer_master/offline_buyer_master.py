import frappe
from frappe.model.document import Document


class OfflineBuyerMaster(Document):
	def before_insert(self):
		if not self.customer_id:
			self.customer_id = self.name
