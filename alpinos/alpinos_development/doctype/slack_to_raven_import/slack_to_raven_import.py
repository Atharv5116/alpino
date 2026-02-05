import json

import frappe
from frappe.model.document import Document

from alpinos.slack_to_raven_import import import_slack_export


class SlackToRavenImport(Document):
	def before_save(self):
		# Reset status on edit of a new record
		if self.is_new():
			self.status = "Not Started"

	def run_import(self):
		if not self.slack_export:
			frappe.throw("Please upload a Slack export ZIP before running the import.")

		docname = self.name
		# Update status via set_value so we don't trigger timestamp check on save
		# (avoids TimestampMismatchError when the form is left open during long import).
		frappe.db.set_value("Slack To Raven Import", docname, "status", "Running")
		frappe.db.set_value("Slack To Raven Import", docname, "summary", "")
		frappe.db.commit()

		try:
			result = import_slack_export(
				file_url=self.slack_export,
				workspace_name=self.workspace_name or "Slack",
			)
			frappe.db.set_value("Slack To Raven Import", docname, "status", "Completed")
			frappe.db.set_value("Slack To Raven Import", docname, "summary", json.dumps(result, indent=2, default=str))
			frappe.db.commit()
		except Exception:
			frappe.db.set_value("Slack To Raven Import", docname, "status", "Failed")
			frappe.db.set_value("Slack To Raven Import", docname, "summary", frappe.get_traceback())
			frappe.db.commit()
			raise


@frappe.whitelist()
def run_slack_to_raven_import(docname: str):
	doc = frappe.get_doc("Slack To Raven Import", docname)
	doc.run_import()
	# Reload from DB after set_value updates
	frappe.db.commit()
	doc.reload()
	return {
		"status": doc.status,
		"summary": doc.summary,
	}

