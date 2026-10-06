"""Filling Inward (FRD Phase 7). Rules live in alpinos.production.filling_inward."""

from frappe.model.document import Document


class FillingInward(Document):
	def validate(self):
		from alpinos.production.filling_inward import validate_inward
		validate_inward(self)

	def on_submit(self):
		from alpinos.production.filling_inward import on_submit_inward
		on_submit_inward(self)

	def before_cancel(self):
		from alpinos.production.filling_inward import before_cancel_inward
		before_cancel_inward(self)

	def on_cancel(self):
		from alpinos.production.filling_inward import on_cancel_inward
		on_cancel_inward(self)
