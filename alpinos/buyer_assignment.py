"""Buyer Master internal sales assignment: Sales Officer(s), Primary POC(s), Secondary POC.

Buyer Master & Sales Order - Required Changes (03-10-2026), sections 1-5.

These three fields are access control, not labels: they decide which Buyers, Quotations and
Sales Orders a person sees, who gets notified, and who may act. So each one picks from a
defined population:

    Sales Officer(s)  multiple   employees holding the Sales Officer role
    Primary POC(s)    multiple   employees holding Sales Manager or Sales Admin
    Secondary POC     single     employees holding Sales Admin

An employee is identified by the roles on their linked User, so someone with no User account
cannot be assigned -- which is correct, since the assignment exists to grant them access.

The legacy single `primary_poc` Data field already holds an Employee ID (not a typed name),
so migrate_legacy_pocs() carries those values into the new table rather than reinterpreting
them. `secondary_poc` needed no migration: it changed from Data to Link in place and the
column keeps its values.
"""

import frappe
from frappe import _

SALES_OFFICER_ROLE = "Sales Officer"
SALES_MANAGER_ROLE = "Sales Manager"
SALES_ADMIN_ROLE = "Sales Admin"

#: Who may be picked in each field.
PRIMARY_POC_ROLES = (SALES_MANAGER_ROLE, SALES_ADMIN_ROLE)
SECONDARY_POC_ROLES = (SALES_ADMIN_ROLE,)


#: What the Sales Officer role may do, before assignment narrows WHICH records it sees.
#: Only reads here: the create / write / submit matrix belongs to sections 6-11 of the
#: document and is set where that rule is implemented.
_SALES_OFFICER_PERMS = {
	"Buyer Master": {"read": 1, "report": 1},
	"Sales Order": {"read": 1, "report": 1},
}


def setup_assignment_roles():
	"""Create the Sales Officer role and give it the reads the assignment rule needs.

	Without a DocPerm row the role cannot open a list at all, so the assignment conditions
	never get a say -- the user is refused before they apply.
	"""
	if not frappe.db.exists("Role", SALES_OFFICER_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": SALES_OFFICER_ROLE,
				"desk_access": 1,
				"is_custom": 1,
				"description": (
					"Field sales representative. Assigned to Buyers through Buyer Master > "
					"Sales Officer(s); may create and edit Draft Sales Orders but not submit them."
				),
			}
		).insert(ignore_permissions=True)

	from frappe.permissions import add_permission, update_permission_property

	for doctype, perms in _SALES_OFFICER_PERMS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": doctype, "role": SALES_OFFICER_ROLE, "permlevel": 0}
		):
			add_permission(doctype, SALES_OFFICER_ROLE, 0)
		for ptype, value in perms.items():
			update_permission_property(
				doctype, SALES_OFFICER_ROLE, 0, ptype, value, validate=False
			)
	frappe.db.commit()


def employees_with_roles(roles, txt="", start=0, page_len=20):
	"""Active employees whose linked User holds any of `roles`, as (name, employee_name) rows."""
	if not roles:
		return []
	return frappe.db.sql(
		"""
		SELECT DISTINCT e.name, e.employee_name
		FROM `tabEmployee` e
		INNER JOIN `tabUser` u ON u.name = e.user_id AND IFNULL(u.enabled, 0) = 1
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
		WHERE hr.role IN %(roles)s
			AND IFNULL(e.status, 'Active') = 'Active'
			AND (e.name LIKE %(txt)s OR IFNULL(e.employee_name, '') LIKE %(txt)s)
		ORDER BY e.employee_name ASC
		LIMIT %(page_len)s OFFSET %(start)s
		""",
		{
			"roles": tuple(roles),
			"txt": f"%{txt or ''}%",
			"start": int(start or 0),
			"page_len": int(page_len or 20),
		},
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def sales_officer_query(doctype, txt, searchfield, start, page_len, filters):
	return employees_with_roles((SALES_OFFICER_ROLE,), txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def primary_poc_query(doctype, txt, searchfield, start, page_len, filters):
	return employees_with_roles(PRIMARY_POC_ROLES, txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def secondary_poc_query(doctype, txt, searchfield, start, page_len, filters):
	return employees_with_roles(SECONDARY_POC_ROLES, txt, start, page_len)


def employee_for_user(user=None):
	"""The active Employee record for a user, if there is one."""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return None
	return frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, "name"
	)


def _rows(doc, fieldname):
	return [r.employee for r in (doc.get(fieldname) or []) if r.employee]


def dedupe_assignments(doc):
	"""Drop repeated employees from the multi-select tables, keeping the first of each."""
	for fieldname in ("sales_officers", "primary_pocs"):
		rows = doc.get(fieldname) or []
		seen, kept = set(), []
		for row in rows:
			if not row.employee or row.employee in seen:
				continue
			seen.add(row.employee)
			kept.append(row)
		if len(kept) != len(rows):
			doc.set(fieldname, kept)


def add_creating_sales_officer(doc):
	"""A Sales Officer who creates a Buyer is assigned to it, or they lose sight of it at once.

	Only on creation, and only for a real Sales Officer: this must not quietly assign a
	manager or an admin who happens to be creating the record on someone else's behalf.
	"""
	if not doc.is_new():
		return
	if SALES_OFFICER_ROLE not in frappe.get_roles(frappe.session.user):
		return
	employee = employee_for_user()
	if not employee or employee in _rows(doc, "sales_officers"):
		return
	doc.append("sales_officers", {"employee": employee})


def validate_assignments(doc):
	"""Keep the assignment fields to the populations the specification defines."""
	dedupe_assignments(doc)
	add_creating_sales_officer(doc)

	for fieldname, roles, label in (
		("sales_officers", (SALES_OFFICER_ROLE,), _("Sales Officer(s)")),
		("primary_pocs", PRIMARY_POC_ROLES, _("Primary POC(s)")),
	):
		for employee in _rows(doc, fieldname):
			_validate_employee_role(employee, roles, label)

	if doc.get("secondary_poc"):
		_validate_employee_role(doc.secondary_poc, SECONDARY_POC_ROLES, _("Secondary POC"))


def _validate_employee_role(employee, roles, label):
	"""Reject an employee whose user does not hold one of the roles the field requires.

	A record imported or written before the role was granted is reported rather than
	silently accepted, because the assignment would hand out access the person's roles do
	not back.
	"""
	user = frappe.db.get_value("Employee", employee, "user_id")
	if not user:
		frappe.throw(
			_("{0}: {1} has no linked User, so they cannot be assigned.").format(
				label, frappe.bold(employee)
			),
			title=_("Assignment Not Allowed"),
		)
	if not set(roles) & set(frappe.get_roles(user)):
		frappe.throw(
			_("{0}: {1} does not hold the {2} role.").format(
				label, frappe.bold(employee), " or ".join(roles)
			),
			title=_("Assignment Not Allowed"),
		)


@frappe.whitelist()
def migrate_legacy_pocs(apply=0, sample=15):
	"""Carry the legacy single `primary_poc` Employee ID into the Primary POC(s) table.

	`secondary_poc` is not touched: it changed from Data to Link in place, so its values
	are already where they belong. Dry run by default.

	  bench --site SITE execute alpinos.buyer_assignment.migrate_legacy_pocs
	  bench --site SITE execute alpinos.buyer_assignment.migrate_legacy_pocs --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	rows = frappe.db.sql(
		"""
		SELECT bm.name, bm.primary_poc
		FROM `tabBuyer Master` bm
		LEFT JOIN `tabBuyer Primary POC` p
			ON p.parent = bm.name AND p.parenttype = 'Buyer Master'
		WHERE IFNULL(bm.primary_poc, '') <> '' AND p.name IS NULL
		ORDER BY bm.name
		""",
		as_dict=True,
	)

	missing = [r for r in rows if not frappe.db.exists("Employee", r.primary_poc)]
	movable = [r for r in rows if frappe.db.exists("Employee", r.primary_poc)]

	result = {
		"mode": "APPLY" if apply else "DRY-RUN",
		"buyers_with_legacy_poc": len(rows),
		"movable": len(movable),
		"employee_not_found": len(missing),
		"sample": [
			{"buyer": r.name, "primary_poc": r.primary_poc} for r in movable[: int(sample)]
		],
		"not_found_sample": [
			{"buyer": r.name, "primary_poc": r.primary_poc} for r in missing[: int(sample)]
		],
	}
	if not apply:
		return result

	moved = 0
	for row in movable:
		# The child row is written directly: a Buyer Master save would re-run validation and
		# the mapping engine over 900-odd records that this migration has no business touching.
		child = frappe.get_doc(
			{
				"doctype": "Buyer Primary POC",
				"parent": row.name,
				"parenttype": "Buyer Master",
				"parentfield": "primary_pocs",
				"employee": row.primary_poc,
				"idx": 1,
			}
		)
		child.db_insert()
		moved += 1
	frappe.db.commit()
	result["moved"] = moved
	return result
