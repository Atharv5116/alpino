# Copyright (c) 2026, Alpinos and contributors
# License: MIT

from frappe.model.document import Document


class PurchaseQCItem(Document):
	"""Per-SKU QC disposition: approved, rejected and the resulting result (BRD 4.6)."""
