"""Process Inward -- the Mixing & Baking data sheet (FRD 4.8 / 4.9) for one Production Run.

All rules live in alpinos.production.execution_inward so the page and the desk form share them.
"""

from frappe.model.document import Document


class ProcessInward(Document):
	def validate(self):
		from alpinos.production import execution_inward

		execution_inward.validate_inward(self)

	def before_submit(self):
		from alpinos.production import execution_inward

		execution_inward.before_submit_inward(self)

	def on_submit(self):
		from alpinos.production import execution_inward

		execution_inward.on_submit_inward(self)

	def before_cancel(self):
		from alpinos.production import execution_inward

		execution_inward.before_cancel_inward(self)

	def on_cancel(self):
		from alpinos.production import execution_inward

		execution_inward.on_cancel_inward(self)
