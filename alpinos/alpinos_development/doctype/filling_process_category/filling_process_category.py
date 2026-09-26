"""Filling Process Category — FRD 4.9 (Phase 8) 8.1.

The master that makes the Filling screens data-driven. A machine carries one category
and an SKU carries the categories it may run on; the Filling Entry screen reads the
machine's category to decide which input component to show. Adding a process later
("Extruded Snacks") must therefore need a new ROW here and nothing else -- no new Select
option in code, no schema change. That is the whole point of the doctype existing, and
the reason nothing downstream may hardcode these names.

Admin-owned, like Machine Type: every other screen picks from this list.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class FillingProcessCategory(Document):
	def validate(self):
		self.category_name = (self.category_name or "").strip()
		self._validate_unique_name()

	def _validate_unique_name(self):
		"""The name IS the record ID, so a repeat is a primary-key clash -- which the
		database reports as "Duplicate entry ... for key 'PRIMARY'". That tells the user
		nothing, so the clash is caught here first."""
		if not self.category_name or not self.is_new():
			return
		if frappe.db.exists("Filling Process Category", self.category_name):
			frappe.throw(
				_("A Filling Process Category called {0} already exists.").format(
					self.category_name
				),
				title=_("Duplicate Category"),
			)

	def on_trash(self):
		"""A category still in use cannot be removed, or the machines and SKUs pointing at
		it would decide nothing. Frappe's own link check covers the Machine link; the SKU
		side is a child table, which that check does not reach."""
		blockers = []

		machines = frappe.get_all(
			"Machine", filters={"filling_process_category": self.name}, pluck="name", limit=5
		) if frappe.get_meta("Machine").has_field("filling_process_category") else []
		if machines:
			blockers.append(_("Machines: {0}").format(", ".join(machines)))

		if frappe.db.table_exists("Item Filling Category"):
			items = frappe.get_all(
				"Item Filling Category",
				filters={"filling_process_category": self.name, "parenttype": "Item"},
				pluck="parent",
				limit=5,
			)
			if items:
				blockers.append(_("Items: {0}").format(", ".join(sorted(set(items)))))

		if blockers:
			frappe.throw(
				_("This Filling Process Category is still in use by {0}.").format(
					"; ".join(blockers)
				),
				title=_("Category In Use"),
			)


@frappe.whitelist()
def active_categories():
	"""The categories any dropdown may offer (8.1: inactive ones are hidden)."""
	frappe.has_permission("Filling Process Category", "read", throw=True)
	return frappe.get_all(
		"Filling Process Category",
		filters={"is_active": 1},
		fields=["name", "category_name", "description"],
		order_by="category_name asc",
	)
