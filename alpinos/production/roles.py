"""Roles and permissions for the Production masters.

Permissions are applied as Custom DocPerm rows from the matrix below rather than written
into each doctype's JSON, for the same reason the Purchase module does it (see
alpinos.purchase.roles): the roles are created by THIS app, so a doctype JSON naming them
would have to be synced after the roles exist, and migrate syncs doctypes first.

Nothing here revokes anything. Frappe copies a doctype's standard DocPerms into Custom
DocPerm the first time one is customised, so the System Manager row each doctype ships
with survives untouched.
"""

import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.permissions import add_permission, update_permission_property

from alpinos.production import constants as C

_VIEW = {"select", "read", "print", "email", "report", "export", "share"}

_MANAGED_PTYPES = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"print",
	"email",
	"report",
	"export",
	"share",
	# Only the Production Order is submittable, and frappe simply ignores these three on a
	# doctype that is not -- so listing them here costs the masters nothing.
	"submit",
	"cancel",
	"amend",
)


def _level_ptypes(level):
	if level == "VIEW":
		return set(_VIEW)
	if level == "CREATE_EDIT":
		return _VIEW | {"write", "create"}
	if level == "FULL":
		return _VIEW | {"write", "create", "delete"}
	# The two levels for a submittable doctype. Submitting is recording a document, not
	# approving it -- who may APPROVE is decided by the flow, not by a DocPerm row -- so a
	# User who may raise an order may also submit it.
	if level == "CREATE_EDIT_SUBMIT":
		return _VIEW | {"write", "create", "submit"}
	if level == "FULL_SUBMIT":
		return _VIEW | {"write", "create", "delete", "submit", "cancel", "amend"}
	raise ValueError(f"unknown access level {level!r}")


#: Who may do what to each master.
#:
#: Machine Type is the one deliberate asymmetry: it is the vocabulary every other screen
#: selects from, so only an Admin may extend it (Machine Master 2.1). A Manager who could
#: add types could invent a category no process maps to.
PERMISSION_MATRIX = {
	"Machine Type": {
		C.ROLE_PRODUCTION_ADMIN: "FULL",
		C.ROLE_PRODUCTION_MANAGER: "VIEW",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	# Same asymmetry as Machine Type, and for the same reason: this is the vocabulary the
	# Filling screens read to decide what to draw (FRD 8.1), so only an Admin may extend it.
	"Filling Process Category": {
		C.ROLE_PRODUCTION_ADMIN: "FULL",
		C.ROLE_PRODUCTION_MANAGER: "VIEW",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	"Machine": {
		C.ROLE_PRODUCTION_ADMIN: "FULL",
		C.ROLE_PRODUCTION_MANAGER: "CREATE_EDIT",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	# Task 25 puts a User at the bottom of the approval chain rather than outside it: a
	# User raises an order and a Manager approves it. So a User needs create and write,
	# not VIEW -- what they must NOT have is the approval action, and that is gated by the
	# flow rather than by the DocPerm row. Submit is granted to all three for the same
	# reason: submitting is recording the order, not approving it.
	"Production Order": {
		C.ROLE_PRODUCTION_ADMIN: "FULL_SUBMIT",
		C.ROLE_PRODUCTION_MANAGER: "FULL_SUBMIT",
		C.ROLE_PRODUCTION_USER: "CREATE_EDIT_SUBMIT",
	},
	# A Sub PO IS a Work Order, so without this a Production Manager could approve an order
	# and then not see the sub order it created -- nor split it, assign it or print its Job
	# Card. Added ALONGSIDE ERPNext's own Manufacturing roles; nothing existing loses
	# anything. `create` is granted and then made useless by SPO-02, which refuses a manual
	# sub order on the server: the permission is for the sub orders this module creates on
	# the user's behalf.
	"Work Order": {
		C.ROLE_PRODUCTION_ADMIN: "FULL_SUBMIT",
		C.ROLE_PRODUCTION_MANAGER: "FULL_SUBMIT",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	"Process Master": {
		C.ROLE_PRODUCTION_ADMIN: "FULL",
		C.ROLE_PRODUCTION_MANAGER: "CREATE_EDIT",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	# Item and BOM are ERPNext's own doctypes with their own established roles (Item
	# Manager, Manufacturing Manager, ...). The production roles are ADDED alongside them
	# so the Production screens work; no existing role loses anything.
	"Item": {
		C.ROLE_PRODUCTION_ADMIN: "CREATE_EDIT",
		C.ROLE_PRODUCTION_MANAGER: "CREATE_EDIT",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
	# Submit included, and it has to be: a Work Order -- which is what a Sub PO is -- will
	# not accept a draft BOM, so a Production Order cannot be approved until its recipe is
	# submitted. Without this the whole chain stopped at the BOM, with only ERPNext's own
	# Manufacturing roles able to move it on. Not `delete`: a recipe that has been used is
	# retired by clearing Is Active, not removed.
	"BOM": {
		C.ROLE_PRODUCTION_ADMIN: "CREATE_EDIT_SUBMIT",
		C.ROLE_PRODUCTION_MANAGER: "CREATE_EDIT_SUBMIT",
		C.ROLE_PRODUCTION_USER: "VIEW",
	},
}


def ensure_roles():
	"""Create the three roles if they are not there yet. Never edits an existing one."""
	for role in C.PRODUCTION_ROLES:
		if frappe.db.exists("Role", role):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role
		doc.desk_access = 1
		doc.insert(ignore_permissions=True)


def _grant(doctype, role, level):
	"""Idempotent permlevel-0 Custom DocPerm row for (doctype, role) matching `level`."""
	granted = _level_ptypes(level)
	# add_permission() alerts when the row already exists and update_permission_property()
	# silently no-ops when it does not, so the row is created only when missing. Both key
	# on if_owner=0, so this probe must too.
	if not frappe.db.exists(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	):
		add_permission(doctype, role, 0)
	for ptype in _MANAGED_PTYPES:
		update_permission_property(
			doctype, role, 0, ptype, 1 if ptype in granted else 0, validate=False
		)


def setup_production_roles():
	ensure_roles()
	for doctype, role_levels in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role, level in role_levels.items():
			_grant(doctype, role, level)
		# Validated once the whole matrix for this doctype is in place, not mid-way.
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)
	frappe.db.commit()


def execute():
	setup_production_roles()
