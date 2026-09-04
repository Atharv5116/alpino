# Copyright (c) 2026, Alpinos and contributors
# License: MIT

from frappe.model.document import Document


class PurchaseApprovalLog(Document):
	"""One approval action on a Purchase Inward (BRD 3.2 approval audit trail)."""
