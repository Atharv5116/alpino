# Copyright (c) 2026, Alpinos and contributors
# License: MIT

from frappe.model.document import Document


class PurchaseQuarantineItem(Document):
	"""One quarantined inward line, held until it is released to QC."""
