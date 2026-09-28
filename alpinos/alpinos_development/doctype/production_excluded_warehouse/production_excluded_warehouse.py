"""One warehouse Production Settings never counts as available. Rows only."""

from frappe.model.document import Document


class ProductionExcludedWarehouse(Document):
	pass
