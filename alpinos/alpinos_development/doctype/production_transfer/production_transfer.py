"""Production Transfer (FRD 10.2) -- stock moved between locations.

The rules live in alpinos.production.inventory_api so the screen, the desk form and the API
all go through the same checks. On submit one Stock Entry (Material Transfer,
custom_entry_kind "Production Transfer") is posted; on cancel it is cancelled.
"""

from frappe.model.document import Document


class ProductionTransfer(Document):
	def validate(self):
		from alpinos.production.inventory_api import validate_transfer
		validate_transfer(self)

	def on_submit(self):
		from alpinos.production.inventory_api import post_transfer
		post_transfer(self)

	def on_cancel(self):
		from alpinos.production.inventory_api import cancel_linked_entry
		cancel_linked_entry(self)
