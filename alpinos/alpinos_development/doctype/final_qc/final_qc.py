"""Final QC (FRD Phase 9). Rules live in alpinos.production.final_qc."""

from frappe.model.document import Document


class FinalQC(Document):
	def validate(self):
		from alpinos.production.final_qc import validate_qc
		validate_qc(self)

	def before_submit(self):
		from alpinos.production.final_qc import before_submit_qc
		before_submit_qc(self)

	def on_submit(self):
		from alpinos.production.final_qc import on_submit_qc
		on_submit_qc(self)

	def before_cancel(self):
		from alpinos.production.final_qc import before_cancel_qc
		before_cancel_qc(self)

	def on_cancel(self):
		from alpinos.production.final_qc import on_cancel_qc
		on_cancel_qc(self)
