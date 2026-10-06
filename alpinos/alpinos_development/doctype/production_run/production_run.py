"""Production Run -- one shop-floor run of one process for a Sub PO (or a merged Machine Run).

Created and moved only by alpinos.production.execution (Start / Pause / Resume / Complete).
The controller keeps the one thing that must hold whoever saves it: the minutes add up.
"""

from frappe.model.document import Document


class ProductionRun(Document):
	def validate(self):
		from alpinos.production.execution import compute_minutes

		compute_minutes(self)
