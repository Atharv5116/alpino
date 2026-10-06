"""Filling Plan (FRD Phase 6). Rules live in alpinos.production.filling_plan."""

import frappe
from frappe.model.document import Document


class FillingPlan(Document):
	def validate(self):
		from alpinos.production.filling_plan import validate_plan
		validate_plan(self)

	def on_trash(self):
		if not self.flags.get("alpinos_filling") and frappe.get_all(
				"Filling Inward", filters={"filling_plan": self.name}, limit=1):
			frappe.throw(frappe._("This plan has Filling Inwards and cannot be deleted."))
