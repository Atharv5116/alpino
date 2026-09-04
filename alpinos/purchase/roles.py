"""Purchase Inward roles, DocPerm matrix and role-gated section visibility (data only, re-run on every migrate).

Task 288. Mirrors `alpinos/workflow_role_access.py` — the house pattern for exactly this
job — so the two role systems stay readable side by side.

Three layers, because each one alone is bypassable:

1. **DocPerm matrix** (`PERMISSION_MATRIX`) — who may read / write / create / submit each
   document at all. Derived from the BRD "User Roles" table (Store -> Purchase Inward +
   GRN, QC -> QC Inspection, Purchase -> Purchase Invoice, Accounts -> Payment, Admin ->
   full) *and* from `alpinos.purchase.workflow.INWARD_TRANSITIONS`: a role that owns a
   transition must be able to write the document that transition touches, otherwise the
   button exists but the save throws.
2. **Client Scripts** — hide or read-only whole form sections per role and per status, so
   Store never sees an editable Purchase header and Purchase never sees an editable
   receiving grid.
3. **`assert_can_edit_section` / `assert_section_edits_allowed`** — the server twin of
   layer 2. `depends_on` and every client-side toggle are advisory only; a REST or
   `frappe.client.set_value` call ignores them entirely, so the Purchase Inward controller
   calls these from `validate()` / `on_update_after_submit()`.
4. **permlevel 1 on the Merge & Audit fields** — a section hidden by a Client Script is
   still readable through `/api/resource`, the report view, a list column, an export and
   every print format. permlevel is the only field-level gate Frappe applies server-side.

Two roles hold `submit` for a reason that has nothing to do with submitting: Frappe routes
EVERY save of a docstatus=1 document through `Document.check_docstatus_transition()`, which
checks `submit` permission. Store (on the inward) and Accounts (on the invoice) edit after
submit, so they need it. The real 0 -> 1 transition is fenced off again by
`assert_can_submit_inward()`, which the Purchase Inward controller calls in `before_submit`.

Visibility vs editability: sections are *hidden* only where the BRD asks for it (the Merge
& Audit trail, which is Admin-only per BR-PI-19 / VAL-PI-18). Everything else stays visible
to every role in the chain — Store must read the invoice number, Purchase must read the
received quantity — and is gated on *edit* instead. A section with no `view_roles` is
visible to anyone who can read the document, including core roles outside this module.

Role names deliberately avoid ERPNext's core "Purchase User" / "Purchase Manager", which
already exist with broad Buying permissions; see `alpinos.purchase.constants`.
"""

import json

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.permissions import add_permission, update_permission_property
from frappe.utils import cint, flt

from alpinos.purchase import constants as C


# ---------------------------------------------------------------------- roles

# role_name -> description; a role that already exists is left alone
ROLES = {role: C.ROLE_DESCRIPTIONS.get(role, "") for role in C.ALL_PURCHASE_ROLES}


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


# ---------------------------------------------------------- permission matrix

# Base read-only bundle shared by every access level. `select` is included so these roles
# can resolve Link fields; the house module omits it and its link searches fall back to read.
_VIEW = {"read", "select", "print", "email", "report", "export"}

# Single doctypes: validate_permissions() strips report/import/export and msgprints about it.
_SINGLE_VIEW = {"read", "select", "print", "email"}

# every ptype this module manages; each is set explicitly so the row converges to the matrix
_MANAGED_PTYPES = (
	"select",
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
	if level == "VIEW":
		return set(_VIEW)
	if level == "EDIT":
		# edit existing records only — no create, no submit
		return _VIEW | {"write"}
	if level == "EDIT_AFTER_SUBMIT":
		# `submit` here is not permission to submit a draft: check_docstatus_transition()
		# runs check_permission("submit") for EVERY save of a submitted document, so a role
		# that edits allow_on_submit fields cannot work without it. The draft transition is
		# gated separately by assert_can_submit_inward().
		return _VIEW | {"write", "submit"}
	if level == "CREATE_EDIT":
		# may raise and edit a draft, may never submit it
		return _VIEW | {"write", "create"}
	if level == "CREATE_SUBMIT":
		# raise / edit / submit, but never cancel or delete
		return _VIEW | {"write", "create", "submit"}
	if level == "CREATE_SUBMIT_CANCEL":
		return _VIEW | {"write", "create", "delete", "submit", "cancel", "amend"}
	if level == "FULL":
		return _VIEW | {"write", "create", "delete", "submit", "cancel", "amend", "share"}
	if level == "SETTINGS_VIEW":
		return set(_SINGLE_VIEW)
	if level == "SETTINGS_MANAGE":
		return _SINGLE_VIEW | {"write", "share"}
	raise ValueError(f"Unknown access level: {level}")


# doctype -> {role -> level}; a role omitted for a doctype gets no row from this module
PERMISSION_MATRIX = {
	"Purchase Inward": {
		C.ROLE_PURCHASE_USER: "CREATE_SUBMIT",
		# ROLE_DESCRIPTIONS: "Purchase Inward User access plus cancel and amend"
		C.ROLE_PURCHASE_MANAGER: "CREATE_SUBMIT_CANCEL",
		# Store edits the inward *after* submit through the allow_on_submit receiving
		# fields (workflow: submit_for_qc). Every such save is permission-checked as
		# `submit`, so plain EDIT would kill the whole submit_for_qc flow; creating and
		# submitting a draft stay Purchase-only via assert_can_submit_inward().
		C.ROLE_STORE_USER: "EDIT_AFTER_SUBMIT",
		C.ROLE_STORE_MANAGER: "EDIT_AFTER_SUBMIT",
		C.ROLE_QC_USER: "VIEW",
		C.ROLE_QC_MANAGER: "VIEW",
		C.ROLE_ACCOUNTS: "VIEW",
		C.ROLE_ADMIN: "FULL",
	},
	"Purchase QC": {
		C.ROLE_PURCHASE_USER: "VIEW",
		C.ROLE_PURCHASE_MANAGER: "VIEW",
		C.ROLE_STORE_USER: "VIEW",
		C.ROLE_STORE_MANAGER: "VIEW",
		C.ROLE_QC_USER: "CREATE_SUBMIT",
		C.ROLE_QC_MANAGER: "CREATE_SUBMIT_CANCEL",
		C.ROLE_ACCOUNTS: "VIEW",
		C.ROLE_ADMIN: "FULL",
	},
	# GRN. `generate_grn` is a PURCHASE transition, so Purchase must be able to mint the
	# draft — but only the Admin may finally submit it (BR-GRN-06 / VAL-GRN-04). Core
	# Buying/Stock roles keep whatever they already had: add_permission() first copies the
	# standard DocPerms into Custom DocPerm, so nothing existing is revoked here.
	"Purchase Receipt": {
		C.ROLE_PURCHASE_USER: "CREATE_EDIT",
		C.ROLE_PURCHASE_MANAGER: "CREATE_EDIT",
		C.ROLE_STORE_USER: "VIEW",
		C.ROLE_STORE_MANAGER: "VIEW",
		C.ROLE_QC_USER: "VIEW",
		C.ROLE_QC_MANAGER: "VIEW",
		C.ROLE_ACCOUNTS: "VIEW",
		C.ROLE_ADMIN: "FULL",
	},
	# The PO is upstream of this module; everyone reads it to raise an inward against it.
	"Purchase Order": {
		C.ROLE_PURCHASE_USER: "VIEW",
		C.ROLE_PURCHASE_MANAGER: "VIEW",
		C.ROLE_STORE_USER: "VIEW",
		C.ROLE_STORE_MANAGER: "VIEW",
		C.ROLE_QC_USER: "VIEW",
		C.ROLE_QC_MANAGER: "VIEW",
		C.ROLE_ACCOUNTS: "VIEW",
		C.ROLE_ADMIN: "FULL",
	},
	# BRD: Purchase owns the invoice, Accounts owns the payment recorded against it.
	"Purchase Invoice": {
		# BR-UNF-03 / BRD 6.2.1: the Purchase Team fills the supplier bill and SUBMITS it,
		# which is what pushes the document into the Accounts payment queue. CREATE_EDIT
		# has no submit, so the invoice could never leave Draft and never reached Accounts.
		C.ROLE_PURCHASE_USER: "CREATE_SUBMIT",
		C.ROLE_PURCHASE_MANAGER: "CREATE_SUBMIT",
		C.ROLE_STORE_USER: "VIEW",
		C.ROLE_STORE_MANAGER: "VIEW",
		C.ROLE_QC_USER: "VIEW",
		C.ROLE_QC_MANAGER: "VIEW",
		# Accounts works on the SUBMITTED invoice (payment, remarks), which is the same
		# update_after_submit-needs-`submit` case as Store above.
		C.ROLE_ACCOUNTS: "EDIT_AFTER_SUBMIT",
		C.ROLE_ADMIN: "FULL",
	},
	# BRD User Roles gives Accounts the payment, and workflow.complete_payment is an
	# ACCOUNTS transition — without a row here the role that owns the transition cannot
	# open or raise the document the transition is about.
	"Payment Entry": {
		C.ROLE_PURCHASE_USER: "VIEW",
		C.ROLE_PURCHASE_MANAGER: "VIEW",
		C.ROLE_ACCOUNTS: "CREATE_SUBMIT",
		C.ROLE_ADMIN: "FULL",
	},
	"Purchase Inward Settings": {
		C.ROLE_PURCHASE_USER: "SETTINGS_VIEW",
		C.ROLE_PURCHASE_MANAGER: "SETTINGS_VIEW",
		C.ROLE_STORE_USER: "SETTINGS_VIEW",
		C.ROLE_STORE_MANAGER: "SETTINGS_VIEW",
		C.ROLE_QC_USER: "SETTINGS_VIEW",
		C.ROLE_QC_MANAGER: "SETTINGS_VIEW",
		C.ROLE_ACCOUNTS: "SETTINGS_VIEW",
		C.ROLE_ADMIN: "SETTINGS_MANAGE",
	},
}


def _grant(doctype, role, level):
	"""Ensure a permlevel-0 Custom DocPerm row for (doctype, role) matching level. Idempotent."""
	granted = _level_ptypes(level)
	# add_permission() alerts loudly when the row is already there, and update_permission_
	# property() silently no-ops when it is not — so create it only when it is missing.
	# Both of those key on if_owner=0, so the probe must too: an if_owner=1 row would
	# otherwise skip the insert and leave every update resolving name=None (updating
	# nothing) while the migrate still reports success.
	if not frappe.db.exists(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	):
		add_permission(doctype, role, 0)
	for ptype in _MANAGED_PTYPES:
		update_permission_property(
			doctype, role, 0, ptype, 1 if ptype in granted else 0, validate=False
		)


def _setup_permissions():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	for doctype, role_levels in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		for role, level in role_levels.items():
			if not frappe.db.exists("Role", role):
				continue
			_grant(doctype, role, level)
		# validate once the whole matrix is applied, not mid-way
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)


# Masters the inward / QC / GRN forms read behind the scenes. The module roles are
# standalone, so a user holding only e.g. Store Receiving User would otherwise hit a
# PermissionError reading an Item or a Warehouse.
SUPPORTING_READ_DOCTYPES = (
	"Supplier",
	"Supplier Group",
	"Item",
	"Item Group",
	"Brand",
	"UOM",
	"Warehouse",
	"Batch",
	"Serial No",
	"Serial and Batch Bundle",
	"Company",
	"Address",
	"Contact",
	"Currency",
	"Price List",
	"Item Price",
	"Tax Category",
	"Item Tax Template",
	"Purchase Taxes and Charges Template",
	"Terms and Conditions",
	"Quality Inspection",
	"Quality Inspection Template",
	# link fields on the Payment Entry the Accounts role raises
	"Mode of Payment",
	"Bank Account",
)

# Masters that are NOT open to the whole module. The BRD User Roles table gives Store only
# "Purchase Inward, GRN" and QC only "QC Inspection"; neither has any business with the
# price master or with bank details.
RESTRICTED_READ_DOCTYPES = {
	"Item Price": C.PURCHASE_ROLES + C.ACCOUNTS_ROLES + (C.ROLE_ADMIN,),
	"Price List": C.PURCHASE_ROLES + C.ACCOUNTS_ROLES + (C.ROLE_ADMIN,),
	"Mode of Payment": C.ACCOUNTS_ROLES + (C.ROLE_ADMIN,),
	"Bank Account": C.ACCOUNTS_ROLES + (C.ROLE_ADMIN,),
}

# Reading a master is not a licence to bulk-download it: list views, link searches and the
# form all work on `read` alone, so `report` and `export` stay off.
_READ_ONLY_PTYPES = {"read", "select", "print"}


def _setup_supporting_read_access():
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	for doctype in SUPPORTING_READ_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for role in RESTRICTED_READ_DOCTYPES.get(doctype, C.ALL_PURCHASE_ROLES):
			if not frappe.db.exists("Role", role):
				continue
			# leave a role that already has its own (possibly wider) perm row; if_owner=0
			# matches what add_permission / update_permission_property key on
			if frappe.db.exists(
				"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
			):
				continue
			add_permission(doctype, role, 0)
			for ptype in _MANAGED_PTYPES:
				update_permission_property(
					doctype, role, 0, ptype, 1 if ptype in _READ_ONLY_PTYPES else 0, validate=False
				)
		validate_permissions_for_doctype(doctype)
		frappe.clear_cache(doctype=doctype)


# ------------------------------------------------------ audit field permlevel

# BR-PI-19 / VAL-PI-18. The Merge & Audit trail is Admin-only, and a Client Script that
# hides it is cosmetic: /api/resource, the report view, a list column, an export and every
# print format read straight past it — the same client-only-enforcement trap as depends_on.
# permlevel is the one field-level gate Frappe enforces server-side, so the trail carries
# one and the Client Script is left as decoration.
AUDIT_PERMLEVEL = 1
AUDIT_PERMLEVEL_FIELDS = (
	"audit_section",
	"merged_into",
	"original_invoice_number",
	"invoice_change_log_section",
	"invoice_change_log",
)

# A permlevel > 0 row carries read/write and nothing else — validate_permissions_for_doctype
# strips create/submit/cancel/amend from higher levels anyway.
_AUDIT_PTYPES = {"read", "write"}


def _upsert_docfield_prop(doctype, fieldname, prop, value, property_type="Check"):
	"""One Property Setter per (doctype, field, property); house pattern from
	`alpinos/sales_order_form_layout.py`. Idempotent."""
	existing = frappe.db.exists(
		"Property Setter", {"doc_type": doctype, "field_name": fieldname, "property": prop}
	)
	if existing:
		ps = frappe.get_doc("Property Setter", existing)
		ps.value = str(value)
		ps.property_type = property_type
		ps.save(ignore_permissions=True)
		return
	frappe.get_doc(
		{
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": doctype,
			"field_name": fieldname,
			"property": prop,
			"property_type": property_type,
			"value": str(value),
		}
	).insert(ignore_permissions=True)


def _setup_audit_permlevel():
	"""Move the Merge & Audit fields to permlevel 1 and hand that level to the Admin roles.

	Runs after _setup_permissions(): a permlevel > 0 row is rejected outright unless the
	same role already holds permlevel 0 on the doctype.
	"""
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	doctype = "Purchase Inward"
	if not frappe.db.exists("DocType", doctype):
		return

	meta = frappe.get_meta(doctype)
	for fieldname in AUDIT_PERMLEVEL_FIELDS:
		if meta.get_field(fieldname):
			_upsert_docfield_prop(doctype, fieldname, "permlevel", AUDIT_PERMLEVEL, "Int")

	granted = False
	for role in C.ADMIN_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
		):
			continue
		if not frappe.db.exists(
			"Custom DocPerm",
			{"parent": doctype, "role": role, "permlevel": AUDIT_PERMLEVEL, "if_owner": 0},
		):
			add_permission(doctype, role, AUDIT_PERMLEVEL)
		for ptype in _MANAGED_PTYPES:
			update_permission_property(
				doctype,
				role,
				AUDIT_PERMLEVEL,
				ptype,
				1 if ptype in _AUDIT_PTYPES else 0,
				validate=False,
			)
		granted = True

	if granted:
		validate_permissions_for_doctype(doctype)
	frappe.clear_cache(doctype=doctype)


# ------------------------------------------------------------ section gating

SECTION_HEADER = "header"
SECTION_RECEIVING = "receiving"
SECTION_AUDIT = "audit"
SECTION_QC_INSPECTION = "qc_inspection"
SECTION_QC_DECISION = "qc_decision"

_PURCHASE = C.PURCHASE_ROLES + C.ADMIN_ROLES
_STORE = C.STORE_ROLES + C.ADMIN_ROLES
_QC = C.QC_ROLES + C.ADMIN_ROLES

# QC may still be edited at any status short of a final decision.
QC_OPEN_STATUSES = tuple(s for s in C.QC_STATUSES if s not in (C.QC_COMPLETED, C.QC_CANCELLED))

# Section spec, read by BOTH the Client Script generator and the server guard so the two
# can never disagree about who owns which field.
#
#   section_breaks  Section Break fieldnames — hidden/shown when `view_roles` is set
#   fields          editable-by-design parent fields: hidden/shown AND read-only toggled
#   display_fields  read-only-by-design parent fields: hidden/shown only, never unlocked
#   child_table     grid whose columns this section owns
#   child_fields    editable-by-design columns in that grid
#   view_roles      who may SEE the section; empty = everyone who can read the document
#   edit_roles      who may WRITE its fields
#   open_statuses   statuses at which edits are accepted; empty = any status
#   docstatus       docstatus values at which edits are accepted; empty = any
#   field_roles     per-field role overrides tighter than `edit_roles`
SECTIONS = {
	"Purchase Inward": {
		"status_field": "inward_status",
		"default_status": C.PI_DRAFT,
		"sections": (
			{
				"key": SECTION_HEADER,
				"label": "Purchase Inward Header",
				"section_breaks": ("inward_section", "doc_section", "planned_section"),
				"fields": (
					"purchase_order",
					"inward_type",
					"supplier_order_no",
					"invoice_number",
					"invoice_date",
					"challan_no",
					"gross_weight",
					"inward_datetime",
					"attachment",
					"remarks",
				),
				"display_fields": (
					"supplier",
					"supplier_name",
					"company",
					"po_vehicle_no",
					"po_driver_contact_no",
					"po_estimated_arrival",
					"delivery_location",
				),
				"child_table": "items",
				"child_fields": ("item_code", "description"),
				"view_roles": (),
				"edit_roles": _PURCHASE,
				"open_statuses": C.PI_HEADER_EDITABLE,
				"docstatus": (0,),
				"field_roles": {},
			},
			{
				"key": SECTION_RECEIVING,
				"label": "Store Receiving Details",
				"section_breaks": (
					"receiving_section",
					"receiving_remarks_section",
					"dispute_section",
				),
				"fields": (
					"actual_arrival_datetime",
					"vehicle_details_verified",
					"actual_vehicle_no",
					"actual_driver_contact_no",
					"allow_excess_qty",
					"target_warehouse",
					"receiving_remarks",
					"dispute_attachments",
				),
				"display_fields": ("received_by", "receiving_datetime"),
				"child_table": "items",
				"child_fields": (
					"received_qty",
					"target_warehouse",
					"batch_no",
					"usp",
					"mrp",
					"manufacturing_date",
					"quarantine",
					"quarantine_reason",
					"remarks",
				),
				"view_roles": (),
				"edit_roles": _STORE,
				"open_statuses": C.PI_RECEIVING_OPEN,
				"docstatus": (1,),
				# BR-PI-13: receiving more than the pending quantity is a Store Manager call.
				"field_roles": {"allow_excess_qty": C.EXCESS_OVERRIDE_ROLES},
			},
			{
				# BR-PI-19 / VAL-PI-18 — the invoice-number correction trail is Admin-only,
				# so this is the one section that is genuinely hidden rather than locked.
				"key": SECTION_AUDIT,
				"label": "Merge & Audit",
				"section_breaks": ("audit_section", "invoice_change_log_section"),
				"fields": (),
				"display_fields": ("merged_into", "original_invoice_number", "invoice_change_log"),
				"child_table": None,
				"child_fields": (),
				"view_roles": C.ADMIN_ROLES,
				"edit_roles": C.ADMIN_ROLES,
				"open_statuses": (),
				"docstatus": (),
				"field_roles": {},
			},
		),
	},
	"Purchase QC": {
		"status_field": "qc_status",
		"default_status": C.QC_PENDING,
		"sections": (
			{
				"key": SECTION_QC_INSPECTION,
				"label": "QC Inspection",
				"section_breaks": (
					"vehicle_section",
					"material_section",
					"packaging_section",
					"sample_section",
					"control_sample_section",
				),
				"fields": (
					"inspection_date",
					"inspector",
					"vehicle_inspection_done",
					"vehicle_inspection",
					"material_inspection_done",
					"material_inspection",
					"packaging_inspection_done",
					"packaging_inspection",
					"sample_testing_done",
					"sample_testing",
					"control_sample",
				),
				"display_fields": (),
				"child_table": None,
				"child_fields": (),
				"view_roles": (),
				"edit_roles": _QC,
				"open_statuses": QC_OPEN_STATUSES,
				"docstatus": (0,),
				"field_roles": {},
			},
			{
				"key": SECTION_QC_DECISION,
				"label": "QC Decision",
				"section_breaks": ("decision_section", "remarks_section"),
				"fields": ("rejection_reason", "final_qc_remarks", "overall_remarks"),
				"display_fields": (
					"total_received_qty",
					"total_sample_qty",
					"total_approved_qty",
					"total_rejected_qty",
				),
				"child_table": "items",
				"child_fields": ("approved_qty", "rejected_qty", "rejection_reason", "quarantine"),
				"view_roles": (),
				"edit_roles": _QC,
				"open_statuses": QC_OPEN_STATUSES,
				"docstatus": (0,),
				"field_roles": {},
			},
		),
	},
}


def _spec(doctype):
	return SECTIONS.get(doctype) or {}


def _section(doctype, key):
	for sec in _spec(doctype).get("sections") or ():
		if sec["key"] == key:
			return sec
	frappe.throw(_("Unknown Purchase section: {0}").format(key))


def _roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def _has_any(required, held):
	return bool(set(required) & held) if required else True


def _bypasses_gates(doc, user=None):
	"""Setup code, the Administrator and the module Admin are never section-gated."""
	if frappe.flags.in_migrate or frappe.flags.in_install or frappe.flags.in_patch:
		return True
	if frappe.flags.in_import:
		return True
	if getattr(doc, "flags", None) is not None and doc.flags.get("ignore_permissions"):
		return True
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	# BRD "Admin: Full Access" — and BR-PI-19 needs the Admin to reopen a frozen header.
	return bool(set(C.ADMIN_ROLES) & _roles(user))


def can_edit_section(doc, section, user=None):
	"""(allowed, reason) for `user` editing `section` of `doc` right now.

	`reason` is a translated message when not allowed, None otherwise.
	"""
	if _bypasses_gates(doc, user):
		return True, None

	sec = _section(doc.doctype, section)
	held = _roles(user)

	if sec["view_roles"] and not _has_any(sec["view_roles"], held):
		return False, _("The {0} section is not visible to your role.").format(_(sec["label"]))

	if not _has_any(sec["edit_roles"], held):
		return False, _("Only {0} may edit the {1} section.").format(
			", ".join(sec["edit_roles"]), _(sec["label"])
		)

	if sec["docstatus"] and cint(doc.get("docstatus")) not in sec["docstatus"]:
		return False, _("The {0} section cannot be edited at this stage of the document.").format(
			_(sec["label"])
		)

	spec = _spec(doc.doctype)
	status = doc.get(spec.get("status_field")) or spec.get("default_status")
	if sec["open_statuses"] and status not in sec["open_statuses"]:
		return False, _("The {0} section is closed while the document is {1}.").format(
			_(sec["label"]), status
		)

	return True, None


def assert_can_edit_section(doc, section, user=None):
	"""Raise PermissionError unless `user` may edit `section` of `doc` right now.

	The server twin of the Client Script gating — a REST write, a `frappe.client.set_value`
	call or a bench console edit never sees the client rules, so the controller must call
	this (or `assert_section_edits_allowed`) itself.
	"""
	allowed, reason = can_edit_section(doc, section, user)
	if not allowed:
		frappe.throw(reason, frappe.PermissionError)


def _fieldtype(doctype, fieldname):
	df = frappe.get_meta(doctype).get_field(fieldname)
	return df.fieldtype if df else "Data"


def _norm(fieldtype, value):
	"""Comparable form of a stored value, tolerant of str/datetime/Decimal round trips."""
	if fieldtype in ("Float", "Currency", "Percent", "Int", "Check"):
		return round(flt(value), 6)
	if fieldtype in ("Date", "Datetime", "Time"):
		return str(value or "")[:19]
	if fieldtype in ("Table", "Table MultiSelect"):
		# fallback only: every grid this module tracks is diffed row by row by
		# _table_changed(), because a row count cannot see an edit *inside* a row
		return len(value or [])
	return value if value is not None else ""


def _pre_image(doc):
	"""The document as it was before this save, or None for a brand-new one."""
	if doc.get("__islocal") or not doc.get("name"):
		return None
	before = None
	try:
		before = doc.get_doc_before_save()
	except Exception:
		before = None
	if before is None and frappe.db.exists(doc.doctype, doc.name):
		before = frappe.get_doc(doc.doctype, doc.name)
	return before


def _child_rows(parent, table):
	return {row.name: row for row in (parent.get(table) or []) if row.get("name")}


def _child_doctype(parent_doctype, fieldname):
	df = frappe.get_meta(parent_doctype).get_field(fieldname)
	return df.options if df else None


def _comparable_fields(child_doctype):
	"""Every value-carrying column of a child doctype — what a grid edit can touch."""
	return tuple(
		df.fieldname
		for df in frappe.get_meta(child_doctype).fields
		if df.fieldtype not in no_value_fields
	)


def _row_diff(child_doctype, fieldnames, new_row, old_row):
	"""Tracked fieldnames that differ between two versions of one child row.

	Either side may be None: an added row is diffed against nothing, and a DELETED row is
	diffed the other way round — which is the only way a deletion can register, since the
	incoming document no longer carries the row at all.
	"""
	out = set()
	for fieldname in fieldnames:
		fieldtype = _fieldtype(child_doctype, fieldname)
		new = _norm(fieldtype, new_row.get(fieldname) if new_row else None)
		old = _norm(fieldtype, old_row.get(fieldname) if old_row else None)
		if new != old:
			out.add(fieldname)
	return out


def _table_changed(new_rows, old_rows, child_doctype, fieldnames=None):
	"""True when a grid differs from its pre-image, row by row.

	Row counts are not enough — a one-row edit, or one row added and one removed, is
	exactly what a len() comparison cannot see.
	"""
	fieldnames = _comparable_fields(child_doctype) if fieldnames is None else fieldnames
	old_by_name = {row.get("name"): row for row in (old_rows or []) if row.get("name")}
	seen = set()
	for row in new_rows or []:
		name = row.get("name")
		if not name or name not in old_by_name:
			return True  # a row the pre-image never had
		seen.add(name)
		if _row_diff(child_doctype, fieldnames, row, old_by_name[name]):
			return True
	return bool(set(old_by_name) - seen)  # a row that was deleted


def changed_fields(doc):
	"""(parent fieldnames, {child_table: set(fieldnames)}) that differ from the stored doc.

	A brand-new document counts every non-empty field as changed, so a Store user cannot
	pre-fill the receiving fields on the insert that a Purchase user is supposed to make.

	Only `fields` / `child_fields` are tracked, never `display_fields`: those are derived by
	the controller itself (PO fetch, roll-ups, timestamps) and would fire the gate on the
	document's own housekeeping rather than on a user edit.
	"""
	before = _pre_image(doc)
	parent_changed = set()
	child_changed = {}

	tracked_parent = set()
	tracked_child = {}
	for sec in _spec(doc.doctype).get("sections") or ():
		tracked_parent |= set(sec["fields"])
		if sec["child_table"]:
			tracked_child.setdefault(sec["child_table"], set()).update(sec["child_fields"])

	for fieldname in tracked_parent:
		fieldtype = _fieldtype(doc.doctype, fieldname)
		if fieldtype in ("Table", "Table MultiSelect"):
			# grids declared as plain section fields (dispute_attachments, the QC
			# inspection tables) hold real data, so they get the full row diff too
			child_doctype = _child_doctype(doc.doctype, fieldname)
			if child_doctype and _table_changed(
				doc.get(fieldname), before.get(fieldname) if before else None, child_doctype
			):
				parent_changed.add(fieldname)
			continue
		new = _norm(fieldtype, doc.get(fieldname))
		old = _norm(fieldtype, before.get(fieldname) if before else None)
		if new != old:
			parent_changed.add(fieldname)

	for table, fieldnames in tracked_child.items():
		child_doctype = _child_doctype(doc.doctype, table)
		if not child_doctype:
			continue
		old_rows = _child_rows(before, table) if before else {}
		seen = set()
		for row in doc.get(table) or []:
			if row.get("name"):
				seen.add(row.get("name"))
			touched = _row_diff(child_doctype, fieldnames, row, old_rows.get(row.get("name")))
			if touched:
				child_changed.setdefault(table, set()).update(touched)

		# A row that was in the pre-image and is gone from the incoming document was
		# DELETED — invisible while we only walk the rows that are still here. Deleting a
		# row reads as clearing every field it carried, so it is gated as an edit of exactly
		# those fields: dropping a Purchase-authored line trips the header gate, while
		# Purchase removing its own untouched draft line never trips the receiving gate.
		for name in set(old_rows) - seen:
			touched = _row_diff(child_doctype, fieldnames, None, old_rows[name])
			if touched:
				child_changed.setdefault(table, set()).update(touched)

	return parent_changed, child_changed


def changed_sections(doc):
	"""Section keys touched by the pending save, in spec order."""
	parent_changed, child_changed = changed_fields(doc)
	out = []
	for sec in _spec(doc.doctype).get("sections") or ():
		if set(sec["fields"]) & parent_changed:
			out.append(sec["key"])
			continue
		table = sec["child_table"]
		if table and (set(sec["child_fields"]) & child_changed.get(table, set())):
			out.append(sec["key"])
	return out


def assert_section_edits_allowed(doc, user=None):
	"""Guard every section the pending save actually touches, plus per-field overrides.

	Call this from `validate()` and `on_update_after_submit()`; it is a no-op for a
	document whose owned fields did not change.
	"""
	if _bypasses_gates(doc, user):
		return

	parent_changed, child_changed = changed_fields(doc)
	held = _roles(user)

	for sec in _spec(doc.doctype).get("sections") or ():
		table = sec["child_table"]
		touched = set(sec["fields"]) & parent_changed
		if table:
			touched |= set(sec["child_fields"]) & child_changed.get(table, set())
		if not touched:
			continue

		assert_can_edit_section(doc, sec["key"], user)

		for fieldname, roles in (sec["field_roles"] or {}).items():
			if fieldname in touched and not _has_any(roles, held):
				frappe.throw(
					_("Only {0} may change {1}.").format(", ".join(roles), _(fieldname)),
					frappe.PermissionError,
				)


# Submitting the DRAFT is the Purchase Team's act (INWARD_TRANSITIONS[PI_DRAFT] is
# PURCHASE-only). Store holds `submit` on Purchase Inward for an unrelated reason — every
# update_after_submit save is permission-checked as `submit` — so the 0 -> 1 transition
# needs this guard, or the DocPerm row quietly hands Store the Purchase button.
INWARD_SUBMIT_ROLES = C.PURCHASE_ROLES + C.ADMIN_ROLES


def assert_can_submit_inward(doc, method=None, user=None):
	"""Restrict the Purchase Inward docstatus 0 -> 1 transition to Purchase and Admin.

	Called from `PurchaseInward.before_submit()`. `method` is there so the same function
	can be wired to the `before_submit` doc_event, which invokes a handler as
	`(doc, "before_submit")` — without it the hook would hand the method name to `user`.

	A save of an ALREADY submitted document never reaches before_submit, so the Store
	receiving flow (which is exactly why Store holds `submit`) is untouched.
	"""
	if _bypasses_gates(doc, user):
		return
	if not _has_any(INWARD_SUBMIT_ROLES, _roles(user)):
		frappe.throw(
			_("Only {0} may submit a Purchase Inward.").format(", ".join(INWARD_SUBMIT_ROLES)),
			frappe.PermissionError,
		)


def assert_can_submit_grn(doc, method=None, user=None):
	"""BR-GRN-06 / VAL-GRN-04 — only the Admin roles may finally submit a module GRN.

	The DocPerm matrix already withholds `submit` on Purchase Receipt from every module
	role but `Purchase Inward Admin`; this is the role-level twin, so a user who also
	happens to hold a core Stock/Buying role cannot submit a module GRN by that back door.

	Gated on the module marker first: this is wired to the Purchase Receipt `before_submit`
	doc_event, and an ordinary alpinos stock receipt carries no `custom_purchase_inward` —
	without the short-circuit the hook would block every Purchase Receipt on the site.
	`method` absorbs the hook's second positional argument (the event name).
	"""
	if isinstance(doc, str):
		doc = frappe.get_doc("Purchase Receipt", doc)
	if not (doc and doc.get("custom_purchase_inward")):
		return

	user = user or frappe.session.user
	if user == "Administrator" or frappe.flags.in_migrate or frappe.flags.in_patch:
		return
	if not _has_any(C.GRN_FINAL_SUBMIT_ROLES, _roles(user)):
		frappe.throw(
			_("Only {0} may submit a GRN.").format(", ".join(C.GRN_FINAL_SUBMIT_ROLES)),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_section_access(doctype, name=None):
	"""Per-section {view, edit, reason} for the current user — for desk pages and the SPA.

	Advisory only: every write is still re-checked by `assert_section_edits_allowed`.
	"""
	if doctype not in SECTIONS:
		frappe.throw(_("{0} has no Purchase section spec.").format(doctype))

	if name:
		doc = frappe.get_doc(doctype, name)
		doc.check_permission("read")
	else:
		doc = frappe.new_doc(doctype)

	held = _roles()
	out = {}
	for sec in SECTIONS[doctype]["sections"]:
		allowed, reason = can_edit_section(doc, sec["key"])
		out[sec["key"]] = {
			"label": sec["label"],
			"view": bool(_has_any(sec["view_roles"], held)) or _bypasses_gates(doc),
			"edit": allowed,
			"reason": reason,
		}
	return out


# ------------------------------------------------------------- client scripts

# What the browser needs from SECTIONS. Kept to the same keys so a spec change reaches both
# layers at once.
_CLIENT_KEYS = (
	"key",
	"label",
	"section_breaks",
	"fields",
	"display_fields",
	"child_table",
	"child_fields",
	"view_roles",
	"edit_roles",
	"open_statuses",
	"docstatus",
	"field_roles",
)


def _client_spec(doctype):
	spec = SECTIONS[doctype]
	return {
		"doctype": doctype,
		"status_field": spec["status_field"],
		"default_status": spec["default_status"],
		"admin_roles": list(C.ADMIN_ROLES),
		"sections": [
			{k: (list(sec[k]) if isinstance(sec[k], tuple) else sec[k]) for k in _CLIENT_KEYS}
			for sec in spec["sections"]
		],
	}


# One shared implementation; the per-doctype spec is injected as JSON.
_SECTION_SCRIPT = """
// Role-gated section visibility. Generated from alpinos/purchase/roles.py SECTIONS —
// do not hand-edit; a migrate overwrites it. Cosmetic only: the same rules are enforced
// server-side by alpinos.purchase.roles.assert_section_edits_allowed.

var ALPINOS_PURCHASE_SECTIONS = __SPEC__;

function alpinos_purchase_has_any(roles) {
    if (!roles || !roles.length) return true;
    return !!frappe.user.has_role(roles);
}

function alpinos_purchase_set_grid_readonly(frm, table, fields, editable) {
    var field = frm.fields_dict[table];
    if (!field || !field.grid) return;
    var grid = field.grid;
    (fields || []).forEach(function (fieldname) {
        var known = (grid.docfields || []).some(function (df) {
            return df.fieldname === fieldname;
        });
        // update_docfield_property throws on an unknown column, so check first
        if (known) grid.toggle_enable(fieldname, editable);
    });
}

function alpinos_purchase_apply_section(frm, sec, visible, editable) {
    // hide/show only where the spec asks for it, so a section is never unhidden by accident
    if (sec.view_roles && sec.view_roles.length) {
        (sec.section_breaks || []).forEach(function (sb) {
            if (frm.fields_dict[sb]) frm.set_df_property(sb, 'hidden', visible ? 0 : 1);
        });
        (sec.fields || []).concat(sec.display_fields || []).forEach(function (fieldname) {
            if (frm.fields_dict[fieldname]) {
                frm.set_df_property(fieldname, 'hidden', visible ? 0 : 1);
            }
        });
    }

    var field_roles = sec.field_roles || {};
    (sec.fields || []).forEach(function (fieldname) {
        if (!frm.fields_dict[fieldname]) return;
        var allowed = editable;
        if (allowed && field_roles[fieldname]) {
            allowed = alpinos_purchase_has_any(field_roles[fieldname]);
        }
        frm.set_df_property(fieldname, 'read_only', allowed ? 0 : 1);
    });

    if (sec.child_table) {
        alpinos_purchase_set_grid_readonly(frm, sec.child_table, sec.child_fields, editable);
    }
}

function alpinos_purchase_apply_sections(frm) {
    var spec = ALPINOS_PURCHASE_SECTIONS;
    if (!spec || frm.doc.doctype !== spec.doctype) return;

    var is_admin = alpinos_purchase_has_any(spec.admin_roles) || frappe.session.user === 'Administrator';
    var status = frm.doc[spec.status_field] || spec.default_status;

    (spec.sections || []).forEach(function (sec) {
        // the admin override is VISIBILITY only. Unlocking a section whose fields are not
        // allow_on_submit merely invites a core "Not allowed to change after submission"
        // error on save, so open_statuses and docstatus keep narrowing edit for admins too.
        var visible = is_admin || alpinos_purchase_has_any(sec.view_roles);
        var editable = visible && alpinos_purchase_has_any(sec.edit_roles);
        if (editable && sec.open_statuses && sec.open_statuses.length) {
            editable = sec.open_statuses.indexOf(status) !== -1;
        }
        if (editable && sec.docstatus && sec.docstatus.length) {
            editable = sec.docstatus.indexOf(cint(frm.doc.docstatus)) !== -1;
        }
        alpinos_purchase_apply_section(frm, sec, visible, editable);
    });
}

frappe.ui.form.on('__DOCTYPE__', {
    refresh: function (frm) {
        alpinos_purchase_apply_sections(frm);
    },
    onload_post_render: function (frm) {
        alpinos_purchase_apply_sections(frm);
    },
    __STATUS_FIELD__: function (frm) {
        alpinos_purchase_apply_sections(frm);
    }
});
"""


def _render_section_script(doctype):
	spec = _client_spec(doctype)
	return (
		_SECTION_SCRIPT.replace("__SPEC__", json.dumps(spec, indent=1))
		.replace("__DOCTYPE__", doctype)
		.replace("__STATUS_FIELD__", spec["status_field"])
	)


def _upsert_client_script(script_name, doctype, script):
	"""Idempotent Client Script upsert; re-enables a script somebody switched off."""
	existing = frappe.db.exists("Client Script", {"name": script_name})
	if existing:
		doc = frappe.get_doc("Client Script", existing)
		doc.script = script
		doc.enabled = 1
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": script_name,
				"dt": doctype,
				"view": "Form",
				"enabled": 1,
				"module": "Alpinos Development",
				"script": script,
			}
		).insert(ignore_permissions=True)


def create_purchase_inward_client_script():
	"""Section gating on the Purchase Inward form (Purchase header vs Store receiving)."""
	if not frappe.db.exists("DocType", "Purchase Inward"):
		return
	_upsert_client_script(
		"Purchase Inward - Section Access",
		"Purchase Inward",
		_render_section_script("Purchase Inward"),
	)


def create_purchase_qc_client_script():
	"""Section gating on the Purchase QC form (QC-owned inspection and decision)."""
	if not frappe.db.exists("DocType", "Purchase QC"):
		return
	_upsert_client_script(
		"Purchase QC - Section Access",
		"Purchase QC",
		_render_section_script("Purchase QC"),
	)


# --------------------------------------------- entry point (hooks.after_migrate)


def setup_purchase_roles():
	"""Roles, DocPerm matrix, audit permlevel, supporting read access, Client Scripts.

	Idempotent — safe to re-run on every migrate.
	"""
	_setup_roles()
	_setup_permissions()
	_setup_audit_permlevel()
	_setup_supporting_read_access()
	create_purchase_inward_client_script()
	create_purchase_qc_client_script()
	frappe.db.commit()
