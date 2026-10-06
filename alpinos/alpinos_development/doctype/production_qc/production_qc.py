"""Production QC -- Phase 5 inspection of a submitted Process Inward.

All rules live in alpinos.production.production_qc.
"""

from frappe.model.document import Document


class ProductionQC(Document):
	def validate(self):
		from alpinos.production import production_qc

		production_qc.validate_qc(self)

	def on_submit(self):
		from alpinos.production import production_qc

		production_qc.on_submit_qc(self)

	def before_cancel(self):
		from alpinos.production import production_qc

		production_qc.before_cancel_qc(self)
