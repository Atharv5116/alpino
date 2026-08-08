# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FieldChangeLog(Document):
	pass


def log_field_change(reference_doctype, reference_name, field_label, previous_value, new_value, after_submit=1):
	"""Record one field change (previous -> new, by whom, when). Never let a logging
	failure break the edit that triggered it."""
	try:
		frappe.get_doc({
			"doctype": "Field Change Log",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"field_label": field_label,
			"previous_value": ("" if previous_value is None else str(previous_value))[:500],
			"new_value": ("" if new_value is None else str(new_value))[:500],
			"after_submit": 1 if after_submit else 0,
			"changed_by": frappe.session.user,
			"changed_on": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Field Change Log write failed")
