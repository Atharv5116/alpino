"""Operations & Sales workflow — roles, access permissions and status fields.

Code-driven so the whole thing is recreated idempotently on every
`bench migrate` (registered in hooks.after_migrate). Three things are set up:

1. **Roles** — the ten Operations / Offline-Sales roles from the access spec.
2. **Permissions** — a Custom DocPerm matrix on Sales Order / Pick List /
   Delivery Note that mirrors the Roles & Access table. Submit rights are
   granted where the workflow narrative requires them (Sales Manager submits
   Sales Orders; DN User / Warehouse User submit Delivery Notes).
3. **Workflow status fields** — `custom_workflow_status` Select fields on Sales
   Order and Pick List holding the spec's status list. These are tracking
   fields the (later) transition engine will drive; they do NOT touch the
   native `status` field.

NOTE: this pass intentionally sets up the *data* (roles, perms, status
options) only. The transition/validation/notification engine is a separate
build.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import add_permission, update_permission_property


# ---------------------------------------------------------------------------
# 1. Roles
# ---------------------------------------------------------------------------

# role_name -> description. All desk roles. Sales Manager / Sales User already
# ship with ERPNext; we skip those that already exist (creation is idempotent).
ROLES = {
	"Warehouse Admin": "Operations: view Sales Orders; full access to Pick List and Delivery Note.",
	"Warehouse Manager": "Operations: view Sales Orders; full access to Pick List and Delivery Note.",
	"PL Manager": "Operations: full access to Delivery Note.",
	"DN Manager": "Operations: full access to Pick List.",
	"PL User": "Operations: edit assigned Pick Lists (picking).",
	"DN User": "Operations: edit and submit assigned Delivery Notes.",
	"Warehouse User": "Operations: edit Pick Lists; edit and submit Delivery Notes.",
	"Sales Admin": "Offline Sales: full access to Sales Orders; view Pick List / Delivery Note.",
	"Sales Manager": "Offline Sales: create / edit / submit Sales Orders; view Pick List / Delivery Note.",
	"Sales User": "Offline Sales: view Sales Orders / Pick List / Delivery Note.",
	"E-Commerce Coordinator": "E-Com: create / edit / submit E-Com Sales Orders; ASN + GRN entry on Post Delivery; view Pick List / Delivery Note.",
	"E-Commerce Manager": "E-Com: Coordinator access plus cancel Sales Orders and override ASN/GRN on Post Delivery.",
	"E-Commerce Admin": "E-Com: full access to E-Com Sales Orders and Post Delivery.",
}


def _setup_roles():
	for role_name, description in ROLES.items():
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": 1,
					"description": description,
				}
			).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# 2. Permission matrix
# ---------------------------------------------------------------------------

# Base read-only bundle shared by every access level.
_VIEW = {"read", "print", "email", "report", "export"}

# Every ptype this module manages. On each migrate we set each one explicitly
# (granted -> 1, otherwise -> 0) so the row always converges to the matrix.
_MANAGED_PTYPES = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"print",
	"email",
	"report",
	"export",
	"share",
)


def _level_ptypes(level):
	"""Map an access level from the spec to the set of granted ptypes."""
	if level == "FULL":
		# create / edit / submit / cancel / delete / amend everywhere applicable
		return _VIEW | {"write", "create", "delete", "submit", "cancel", "amend", "share"}
	if level == "VIEW":
		return set(_VIEW)
	if level == "EDIT":
		# modify existing records only (no create / submit / cancel / delete)
		return _VIEW | {"write"}
	if level == "EDIT_SUBMIT":
		# EDIT plus submit — DN User / Warehouse User submit Delivery Notes
		return _VIEW | {"write", "submit"}
	if level == "SO_SALES_MANAGER":
		# VIEW / CREATE / EDIT plus submit + cancel per SO workflow + cancellation rules
		return _VIEW | {"write", "create", "submit", "cancel"}
	if level == "SO_CREATE_SUBMIT":
		# VIEW / CREATE / EDIT / submit — no cancel (E-Commerce Coordinator)
		return _VIEW | {"write", "create", "submit"}
	if level == "CREATE_EDIT":
		# masters (non-submittable): view + create + edit
		return _VIEW | {"write", "create"}
	if level == "MASTER_FULL":
		# masters (non-submittable): full control without submit/cancel/amend
		return _VIEW | {"write", "create", "delete", "share"}
	raise ValueError(f"Unknown access level: {level}")


# doctype -> { role -> level }.  Roles omitted for a doctype get N/A (no row).
# PL Manager / DN Manager rows are used exactly as written in the spec table
# (PL Manager -> Delivery Note FULL, DN Manager -> Pick List FULL).
PERMISSION_MATRIX = {
	"Sales Order": {
		"Warehouse Admin": "VIEW",
		"Warehouse Manager": "VIEW",
		"Sales Admin": "FULL",
		"Sales Manager": "SO_SALES_MANAGER",
		"Sales User": "VIEW",
		# E-Com channel (BRD): Coordinator creates/submits, Manager may cancel,
		# Admin has full control. Channel separation is by the entry pages/list
		# filters — docperms are on the shared Sales Order doctype.
		"E-Commerce Coordinator": "SO_CREATE_SUBMIT",
		"E-Commerce Manager": "SO_SALES_MANAGER",
		"E-Commerce Admin": "FULL",
	},
	"Pick List": {
		"Warehouse Admin": "FULL",
		"Warehouse Manager": "FULL",
		"DN Manager": "FULL",
		"PL User": "EDIT",
		"Warehouse User": "EDIT",
		"Sales Admin": "VIEW",
		"Sales Manager": "VIEW",
		"Sales User": "VIEW",
		"E-Commerce Coordinator": "VIEW",
		"E-Commerce Manager": "VIEW",
		"E-Commerce Admin": "VIEW",
	},
	"Delivery Note": {
		"Warehouse Admin": "FULL",
		"Warehouse Manager": "FULL",
		"PL Manager": "FULL",
		"DN User": "EDIT_SUBMIT",
		"Warehouse User": "EDIT_SUBMIT",
		"Sales Admin": "VIEW",
		"Sales Manager": "VIEW",
		"Sales User": "VIEW",
		"E-Commerce Coordinator": "VIEW",
		"E-Commerce Manager": "VIEW",
		"E-Commerce Admin": "VIEW",
	},
	# BRD Module 1: the E-Commerce roles own the (E-Com) Buyer Master.
	# Non-ECOM roles keep their read-only access from the supporting-masters list.
	"Buyer Master": {
		"E-Commerce Coordinator": "CREATE_EDIT",
		"E-Commerce Manager": "CREATE_EDIT",
		"E-Commerce Admin": "MASTER_FULL",
	},
}


def _grant(doctype, role, level):
	"""Ensure a permlevel-0 Custom DocPerm row for (doctype, role) and set every
	managed ptype to match `level`. Idempotent."""
	granted = _level_ptypes(level)
	# Ensure the row exists (no-op + alert if it already does).
	add_permission(doctype, role, 0)
	for ptype in _MANAGED_PTYPES:
		update_permission_property(
			doctype, role, 0, ptype, 1 if ptype in granted else 0, validate=False
		)


def _setup_permissions():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	for doctype, role_levels in PERMISSION_MATRIX.items():
		for role, level in role_levels.items():
			_grant(doctype, role, level)
		# Validate once per doctype after the whole matrix is applied so we
		# never trip on a transient half-configured row.
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)


# Supporting master/transaction doctypes that SO/PL/DN creation and processing
# read behind the scenes (addresses on render, items, stock, batches, taxes,
# the offline-buyer master, etc.). The 10 spec roles are standalone — a user
# holding only e.g. "Warehouse Admin" otherwise hits PermissionError reading an
# Item or Address. We grant READ-ONLY so the frontend flows work without
# widening write access. Read-only on masters is operationally harmless.
SUPPORTING_READ_DOCTYPES = [
	"Item",
	"Item Group",
	"Brand",
	"UOM",
	"Warehouse",
	"Batch",
	"Serial No",
	"Serial and Batch Bundle",
	"Customer",
	"Customer Group",
	"Territory",
	"Address",
	"Contact",
	"Company",
	"Buyer Master",
	"Alpino Customer Type",
	"Sales Taxes and Charges Template",
	"Tax Category",
	"Item Tax Template",
	"Price List",
	"Item Price",
]

# Read access goes to every operational + sales role so all of them can see the
# masters they touch while creating/processing documents.
SUPPORTING_READ_ROLES = [
	"Warehouse Admin",
	"Warehouse Manager",
	"PL Manager",
	"DN Manager",
	"PL User",
	"DN User",
	"Warehouse User",
	"Sales Admin",
	"Sales Manager",
	"Sales User",
	"E-Commerce Coordinator",
	"E-Commerce Manager",
	"E-Commerce Admin",
]

# Read-only ptype bundle for a supporting master.
_READ_ONLY_PTYPES = {"read", "select", "print", "report", "export"}


def _setup_supporting_read_access():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	for doctype in SUPPORTING_READ_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for role in SUPPORTING_READ_ROLES:
			# Don't touch a role that already has its own (possibly wider) perm row.
			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
				continue
			add_permission(doctype, role, 0)
			for ptype in _MANAGED_PTYPES:
				update_permission_property(
					doctype, role, 0, ptype, 1 if ptype in _READ_ONLY_PTYPES else 0, validate=False
				)
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)


# ---------------------------------------------------------------------------
# 3. Workflow status fields
# ---------------------------------------------------------------------------

# Newline-separated Select options, in spec order.
SALES_ORDER_STATUSES = "\n".join(
	[
		"Draft",
		"Warehouse Approval Pending",
		"Future Dispatch",
		"Today's Dispatch",
		"Warehouse Approved",
		"Picking In Progress",
		"Submission Pending",
		"Ready For Dispatch",
		"Delivery Note Created",
		"Dispatched",
		"Partial Ready For Dispatch",
		"Partial Delivery Note Created",
		"Partial Dispatched",
		"Forced Ready For Dispatch",
		"Forced Delivery Note Created",
		"Forced Dispatched",
		"Forced Completed",
		"Completed",
		"Cancelled",
	]
)

PICK_LIST_STATUSES = "\n".join(
	[
		"Draft",
		"Picking Pending",
		"Picking In Progress",
		"Sticker Pending",
		"Submission Pending",
		"Ready To Dispatch",
		"Partial Ready To Dispatch",
		"Forced Ready To Dispatch",
		"Dispatched",
		"Cancelled",
	]
)


def _setup_status_fields():
	custom_fields = {
		"Sales Order": [
			dict(
				fieldname="custom_workflow_status",
				label="Workflow Status",
				fieldtype="Select",
				options=SALES_ORDER_STATUSES,
				insert_after="status",
				default="Draft",
				read_only=1,
				allow_on_submit=1,
				in_standard_filter=1,
				description="Operations workflow stage. Driven by the workflow engine; separate from the native ERPNext status.",
			),
			dict(
				fieldname="custom_expected_dispatch_date",
				label="Expected Dispatch Date",
				fieldtype="Date",
				insert_after="custom_workflow_status",
				read_only=1,
				allow_on_submit=1,
				description="Set when the order is parked as Future Dispatch (stock not yet available).",
			),
			dict(
				fieldname="custom_delivered_on",
				label="Delivered On",
				fieldtype="Date",
				insert_after="custom_expected_dispatch_date",
				read_only=1,
				allow_on_submit=1,
				description="Auto-set to today when Sales marks the order Completed (delivery confirmed).",
			),
		],
		"Pick List": [
			dict(
				fieldname="custom_workflow_status",
				label="Workflow Status",
				fieldtype="Select",
				options=PICK_LIST_STATUSES,
				insert_after="status",
				default="Draft",
				read_only=1,
				allow_on_submit=1,
				in_standard_filter=1,
				description="Operations workflow stage. Driven by the workflow engine; separate from the native ERPNext status.",
			),
			dict(
				fieldname="custom_picking_started",
				label="Picking Started",
				fieldtype="Check",
				insert_after="custom_workflow_status",
				default="0",
				read_only=1,
				hidden=1,
				description="Set when the assigned picker clicks Start Picking. Drives the Picking In Progress stage.",
			),
			dict(
				fieldname="custom_sticker_printed",
				label="Sticker Printed",
				fieldtype="Check",
				insert_after="custom_picking_started",
				default="0",
				read_only=1,
				hidden=1,
				description="Set when stickers are generated for this Pick List. Drives the Submission Pending stage.",
			),
		],
	}
	# ignore_validate=True skips the doctype-wide field re-validation that
	# create_custom_fields triggers on insert. Sales Order's `company` field is
	# intentionally hidden by this app (offline-buyer flow auto-sets it) while
	# remaining mandatory — a state Frappe's check_hidden_and_mandatory rejects.
	# We only add a Select tracking field here, so skipping that unrelated
	# whole-doctype check is safe and avoids breaking migrate.
	create_custom_fields(custom_fields, ignore_validate=True, update=True)


@frappe.whitelist()
def get_workflow_team_users(doctype, include_users=None):
	"""Enabled System Users holding any of the workflow roles defined for the
	doctype in PERMISSION_MATRIX (the warehouse + sales teams). Used by the
	Assign To / QC dropdowns on the Pick List and Delivery Note entry pages so
	they only offer workflow team members instead of every user on the site.

	Names passed in include_users are appended even without a matching role so
	documents with an existing (legacy) assignee still display their value."""
	roles = list(PERMISSION_MATRIX.get(doctype) or {})
	if not roles:
		frappe.throw(f"No workflow roles are defined for {doctype}.")

	role_holders = frappe.get_all(
		"Has Role",
		filters={"role": ["in", roles], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	users = []
	if role_holders:
		users = frappe.get_all(
			"User",
			filters={"name": ["in", role_holders], "enabled": 1, "user_type": "System User"},
			pluck="name",
			order_by="full_name asc",
		)

	if isinstance(include_users, str):
		include_users = frappe.parse_json(include_users) or []
	for extra in include_users or []:
		if extra and extra not in users and frappe.db.exists("User", extra):
			users.append(extra)
	return users


# ---------------------------------------------------------------------------
# Delivery Note "Assigned To" — restricted to DN User / DN Manager
# ---------------------------------------------------------------------------
DN_ASSIGN_ROLES = ["DN User", "DN Manager"]


@frappe.whitelist()
def get_dn_assignable_users(include_users=None):
	"""Enabled System Users holding the DN User or DN Manager role — the only
	users offered in the Delivery Note 'Assigned To' dropdown on the entry page.

	Names in include_users are appended even without a matching role so a DN with
	an existing (legacy) assignee still shows its value."""
	role_holders = frappe.get_all(
		"Has Role",
		filters={"role": ["in", DN_ASSIGN_ROLES], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	users = []
	if role_holders:
		users = frappe.get_all(
			"User",
			filters={"name": ["in", role_holders], "enabled": 1, "user_type": "System User"},
			pluck="name",
			order_by="full_name asc",
		)
	if isinstance(include_users, str):
		include_users = frappe.parse_json(include_users) or []
	for extra in include_users or []:
		if extra and extra not in users and frappe.db.exists("User", extra):
			users.append(extra)
	return users


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def dn_assigned_to_query(doctype, txt, searchfield, start, page_len, filters):
	"""Link-field query for Delivery Note.custom_assigned_to — restricts the
	standard-form picker to DN User / DN Manager holders."""
	txt = txt or ""
	return frappe.db.sql(
		"""
		SELECT DISTINCT u.name, u.full_name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.role IN (%(role1)s, %(role2)s)
		WHERE IFNULL(u.enabled, 0) = 1
			AND u.user_type = 'System User'
			AND u.name NOT IN ('Administrator', 'Guest')
			AND (u.name LIKE %(txt)s OR IFNULL(u.full_name, '') LIKE %(txt)s)
		ORDER BY u.full_name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{
			"role1": "DN User",
			"role2": "DN Manager",
			"txt": f"%{txt}%",
			"start": int(start or 0),
			"page_len": int(page_len or 20),
		},
	)


# ---------------------------------------------------------------------------
# Entry point (hooks.after_migrate)
# ---------------------------------------------------------------------------

def execute():
	_setup_roles()
	_setup_status_fields()
	_setup_permissions()
	_setup_supporting_read_access()
	# Phase 2: bring existing Sales Orders / Pick Lists to a correct workflow
	# status now that the fields exist. Idempotent.
	from alpinos.workflow_engine import backfill_workflow_statuses

	backfill_workflow_statuses()
	# Turn on native stock reservation so Pick List -> reserve, DN -> deduct.
	from alpinos.stock_reservation import enable_stock_reservation

	enable_stock_reservation()
	frappe.db.commit()
