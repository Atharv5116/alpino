"""Inventory Adjustment (FRD 10.3 / 10.4.3 / 13.2) -- stock audit corrections.

Submit posts the Stock Entry at once, unless it deducts more than the approval threshold
(Production Settings > adjustment_approval_kg, default 500 KG): then it waits in Pending
Approval for the Plant Head and NOTHING is deducted until approved. Rules live in
alpinos.production.inventory_api.
"""

from frappe.model.document import Document


class InventoryAdjustment(Document):
	def validate(self):
		from alpinos.production.inventory_api import validate_adjustment
		validate_adjustment(self)

	def on_submit(self):
		from alpinos.production.inventory_api import on_submit_adjustment
		on_submit_adjustment(self)

	def on_cancel(self):
		from alpinos.production.inventory_api import on_cancel_adjustment
		on_cancel_adjustment(self)
