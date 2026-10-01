import frappe
from frappe import _
from frappe.model.document import Document


class AlpinoCustomerType(Document):
	"""A trade customer type, and optionally the type it rolls up into.

	`parent_customer_type` groups several types under one heading — the dispatch report
	reports a child inside its parent's column instead of its own, so one chain reads as
	a single column rather than being spread across every type its sites happen to carry.

	The hierarchy is deliberately ONE level deep. A single hop is all the report needs,
	it keeps the grouping a single LEFT JOIN, and it makes cycles impossible to express
	rather than something that has to be detected.
	"""

	def validate(self):
		self._validate_parent()

	def _validate_parent(self):
		parent = (self.parent_customer_type or "").strip()
		if not parent:
			return

		if parent == self.name:
			frappe.throw(
				_("A Customer Type cannot be its own parent."),
				title=_("Invalid Parent"),
			)

		# One level only, enforced from both ends so neither can be reached by editing
		# the other record first.
		grandparent = frappe.db.get_value(
			"Alpino Customer Type", parent, "parent_customer_type"
		)
		if grandparent:
			frappe.throw(
				_(
					"{0} already rolls up into {1}, so it cannot be a parent itself. "
					"Customer Types are only one level deep."
				).format(frappe.bold(parent), frappe.bold(grandparent)),
				title=_("Invalid Parent"),
			)

		children = frappe.get_all(
			"Alpino Customer Type",
			filters={"parent_customer_type": self.name},
			pluck="name",
			limit=5,
		)
		if children:
			frappe.throw(
				_(
					"{0} is already the parent of {1}, so it cannot roll up into "
					"another type. Customer Types are only one level deep."
				).format(frappe.bold(self.name), ", ".join(frappe.bold(c) for c in children)),
				title=_("Invalid Parent"),
			)


def get_rollup_parent(customer_type):
	"""The column a customer type reports under: its parent, else itself."""
	if not customer_type:
		return None
	return (
		frappe.db.get_value("Alpino Customer Type", customer_type, "parent_customer_type")
		or customer_type
	)
