# Copyright (c) 2026, Alpinos and contributors
# License: MIT

from frappe.model.document import Document


class PurchaseApprovalLog(Document):
	"""One approval action, as BRD 3.2 ("Approval Audit Trail") describes it.

	Written by `alpinos.purchase.purchase_order_approval`, which hangs it off the
	Purchase Order as `custom_approval_log`. Every row is engine-owned and read-only:
	the trail records what happened, so nothing in the desk may edit it after the fact.
	"""
