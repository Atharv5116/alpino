"""Goods Return Reason: the standard return reasons, picked on every request item (FSD 1.4.1).

The reason says why the customer returns the goods; it does not decide their physical
condition (INT-BR-11), which the Return GRN records after receipt.
"""

from frappe.model.document import Document


class GoodsReturnReason(Document):
	pass
