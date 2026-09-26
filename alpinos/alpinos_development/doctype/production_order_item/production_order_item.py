"""A material line copied from the BOM onto a Production Order.

A snapshot, not a link: Task 4 says editing a BOM later must not change orders already
written, so the quantities and the stage are copied in rather than read through.
"""

from frappe.model.document import Document


class ProductionOrderItem(Document):
	pass
