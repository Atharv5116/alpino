from frappe.model.document import Document


class QuotationPaymentReceipt(Document):
	"""One submitted payment of a Quotation (doc Section 5, 10 and 19): amount, date and proof as
	recorded by Record Payment. Immutable once added; only a System Manager corrects it, with a
	reason (alpinos.offline_sales.quotation_payments.correct_payment)."""

	pass
