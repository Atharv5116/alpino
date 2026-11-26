"""Supplier Catalog: the items one supplier supplies (one catalog per supplier).

A Purchase Order for the supplier offers only these items in its item list
(alpinos.purchase.inward_api.po_type_item_query); a supplier with no catalog offers none.
Edited on the Supplier Catalog page (alpinos.purchase.supplier_catalog).
"""

import frappe
from frappe import _
from frappe.model.document import Document


class SupplierCatalog(Document):
	def validate(self):
		seen = set()
		for row in self.get("items"):
			if row.item_code in seen:
				frappe.throw(
					_("Row {0}: {1} is already in this catalog.").format(row.idx, row.item_code),
					title=_("Duplicate Item"),
				)
			seen.add(row.item_code)
			if not row.item_name or not row.item_group:
				name, group = frappe.db.get_value("Item", row.item_code, ["item_name", "item_group"]) or (None, None)
				row.item_name = row.item_name or name
				row.item_group = row.item_group or group
		self.item_count = len(self.get("items"))
