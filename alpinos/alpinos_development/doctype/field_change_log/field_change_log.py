# Copyright (c) 2026, Alpinos and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FieldChangeLog(Document):
	pass


#: The roles a change is attributed to, most specific first. The trail records which hat
#: the person was wearing, which is what section 17 of the 03-10-2026 changes asks for.
_ATTRIBUTED_ROLES = (
	"Sales Officer",
	"Sales Admin",
	"Sales Manager",
	"Warehouse Admin",
	"Warehouse Manager",
	"Accounts Manager",
	"Accounts User",
	"System Manager",
)


def acting_role(user=None):
	"""The role to record this change under, or "" when none of the known ones apply."""
	user = user or frappe.session.user
	if user == "Administrator":
		return "Administrator"
	roles = set(frappe.get_roles(user))
	for role in _ATTRIBUTED_ROLES:
		if role in roles:
			return role
	return ""


def log_field_change(reference_doctype, reference_name, field_label, previous_value, new_value,
                     after_submit=1, action=None, item_code=None, reason=None, user_role=None):
	"""Record one change (previous -> new, by whom, under which role, when).

	`action`, `user_role` and `item_code` carry sections 17 and 18 of the 03-10-2026
	changes: what happened, the hat the person was wearing, and the SKU when the change
	belongs to a line rather than the document. A logging failure never breaks the edit
	that triggered it.
	"""
	try:
		frappe.get_doc({
			"doctype": "Field Change Log",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"field_label": field_label,
			"previous_value": ("" if previous_value is None else str(previous_value))[:500],
			"new_value": ("" if new_value is None else str(new_value))[:500],
			"after_submit": 1 if after_submit else 0,
			"action": action or "Edited",
			"user_role": user_role or acting_role(),
			"item_code": item_code or None,
			"reason": reason or None,
			"changed_by": frappe.session.user,
			"changed_on": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Field Change Log write failed")
