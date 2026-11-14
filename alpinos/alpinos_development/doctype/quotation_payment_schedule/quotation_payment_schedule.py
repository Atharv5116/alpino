from frappe.model.document import Document


class QuotationPaymentSchedule(Document):
	"""One row of a Partial Quotation's Payment Schedule (doc Section 5, 13): an Advance or Credit
	amount expected on a date. Received / Pending / Status are the sums of the Quotation Payment
	Receipt rows that point at this row (row_key), kept by alpinos.offline_sales.quotation_payments."""

	pass
