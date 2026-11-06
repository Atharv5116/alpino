"""Goods Return roles and their permissions (FSD 2.2).

  * Goods Return Coordinator raises, edits, submits and cancels requests for the channels
    of their Sales / E-Commerce roles (the channel part is alpinos.goods_return.access).
  * Goods Return Executive handles the operational side: in Phase A that is reading the
    requests of both channels; receiving, verification, disposal, stock and closure come
    with the Return GRN phase.

Both are company-wise roles (Role.custom_company_scoped), so under company-wise access they
are granted per company in Company Access, like the Sales roles they pair with.

Permission rows are written with the purchase module's _grant, inside the after_migrate
window of company_scope.perm_seed: a row written the first time stays as written, and after
that Role Permissions Manager owns it.
"""

import frappe

from alpinos.goods_return import COORDINATOR, EXECUTIVE, REASON, REQUEST

ROLES = {
	COORDINATOR: "Raises and submits customer Goods Return Requests for the channels of their Sales or E-Commerce role.",
	EXECUTIVE: "Handles the operational side of customer goods returns: receiving, verification, disposal, stock and closure.",
}

PERMISSION_MATRIX = {
	REQUEST: {COORDINATOR: "CREATE_SUBMIT_CANCEL", EXECUTIVE: "VIEW"},
	REASON: {COORDINATOR: "VIEW", EXECUTIVE: "VIEW"},
	# what the Executive opens from a request (a Coordinator has these through their Sales role)
	"Customer": {EXECUTIVE: "VIEW"},
	"Item": {EXECUTIVE: "VIEW"},
	"Channel": {COORDINATOR: "VIEW", EXECUTIVE: "VIEW"},
	"Buyer Master": {EXECUTIVE: "VIEW"},
	"Sales Order": {EXECUTIVE: "VIEW"},
	"Delivery Note": {EXECUTIVE: "VIEW"},
}


def setup_roles():
	for role_name, description in ROLES.items():
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role_name, "desk_access": 1, "description": description}
			).insert(ignore_permissions=True)
		if frappe.db.has_column("Role", "custom_company_scoped") and not frappe.db.get_value(
			"Role", role_name, "custom_company_scoped"
		):
			frappe.db.set_value("Role", role_name, "custom_company_scoped", 1, update_modified=False)


def setup_permissions():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	from alpinos.purchase.roles import _grant

	for doctype, role_levels in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role, level in role_levels.items():
			if frappe.db.exists("Role", role):
				_grant(doctype, role, level)
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)
