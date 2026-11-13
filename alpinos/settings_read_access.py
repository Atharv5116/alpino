"""Read-only access to the settings that standard screens read in the browser.

ERPNext's Stock Entry form reads Stock Settings, and the Chart of Accounts reads Accounts
Settings, from the browser. A role that may open those documents but may not read the
settings got a red "No permission for Stock Settings" (a Warehouse Admin opening a Stock
Entry) or "No permission for Accounts Settings" (an Accounts User opening the Chart of
Accounts). Several roles already had this read-only row, added with their own modules; this
gives it to every role that can read the documents, and nothing wider (read only, level 0).
"""

import frappe

#: settings -> the documents whose screens read it
SETTINGS_READERS = {
	"Stock Settings": (
		"Stock Entry",
		"Stock Reconciliation",
		"Delivery Note",
		"Purchase Receipt",
		"Material Request",
		"Pick List",
	),
	"Accounts Settings": ("Account", "Journal Entry", "Payment Entry", "Sales Invoice", "Purchase Invoice"),
}

_SKIP = {"All", "Guest", "Desk User", "Administrator"}


def _roles_with(doctype, ptype):
	"""Roles holding ptype at level 0 on doctype (its Custom DocPerm rows when it has any)."""
	if not frappe.db.exists("DocType", doctype):
		return set()
	table = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
	return set(frappe.get_all(table, filters={"parent": doctype, "permlevel": 0, ptype: 1}, pluck="role")) - _SKIP


def plan():
	"""{settings: [roles to add]} - what setup() would write."""
	settings = {}
	for name, sources in SETTINGS_READERS.items():
		readers = set()
		for dt in sources:
			readers |= _roles_with(dt, "read")
		settings[name] = sorted(r for r in readers - _roles_with(name, "read") if frappe.db.exists("Role", r))
	return settings


def setup():
	"""after_migrate (inside the perm_seed window: only new rows are written)."""
	from frappe.permissions import setup_custom_perms

	settings = plan()
	for name, roles in settings.items():
		if not roles:
			continue
		setup_custom_perms(name)
		for role in roles:
			key = {"parent": name, "role": role, "permlevel": 0, "if_owner": 0}
			if frappe.db.exists("Custom DocPerm", key):
				continue  # a row of its own (read off): leave it as it is
			frappe.get_doc(
				dict(doctype="Custom DocPerm", parenttype="DocType", parentfield="permissions", read=1, **key)
			).db_insert()
		frappe.clear_cache(doctype=name)
	frappe.clear_cache()
