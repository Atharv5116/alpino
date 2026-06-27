"""Convert Employee Onboarding `location` from Select to Link -> Branch.

Frappe forbids changing a Custom Field's fieldtype from Select to Link in place
(both via fixture sync and create_custom_fields). This patch deletes the stale
Select definition so the updated fixture / custom-field setup can recreate it as a
Link to Branch. The underlying DB column is preserved (both store text), so any
existing location values that match a Branch name remain valid.

Runs in [post_model_sync], i.e. BEFORE sync_fixtures, so the fixture recreates the
field with the correct type in the same migrate.
"""

import frappe

CUSTOM_FIELD = "Employee Onboarding-location"


def execute():
	if not frappe.db.exists("Custom Field", CUSTOM_FIELD):
		return
	if frappe.db.get_value("Custom Field", CUSTOM_FIELD, "fieldtype") == "Link":
		return
	frappe.delete_doc("Custom Field", CUSTOM_FIELD, force=True, ignore_permissions=True)
	frappe.db.commit()
