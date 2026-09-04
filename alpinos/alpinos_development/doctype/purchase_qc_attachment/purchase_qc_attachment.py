# Copyright (c) 2026, Alpinos and contributors
# License: MIT

from frappe.model.document import Document


class PurchaseQCAttachment(Document):
	"""One piece of inspection evidence (BRD 4.1.2-4.1.4: one or more images / video).

	The per-row Attach on each inspection line holds the single primary shot; this table is
	what makes "one or more" possible without asking the QC user to add a whole inspection
	row (and re-state the condition) for every extra photo.
	"""
