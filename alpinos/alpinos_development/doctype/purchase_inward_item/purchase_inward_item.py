# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""One ordered line of a Purchase Inward.

All the arithmetic — previously received, pending, excess, expiry — is driven by
the parent (see purchase_inward.py), because every one of those values depends on
sibling rows or on other inwards against the same Purchase Order.
"""

from frappe.model.document import Document


class PurchaseInwardItem(Document):
	pass
