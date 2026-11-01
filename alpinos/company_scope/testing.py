"""Shared fixtures for company-wise access tests (TEST sites only).

	A, B, C = companies()                       # default company, then two others
	user = make_user("cs.po@example.com", {A: ["Purchase User"], B: ["Purchase Accounts User"]})
	name = copy_header("Purchase Order", template, "CS-PO-B", B)   # header-only copy in B
	rows = as_user(user, lambda: get_purchase_order_list(...))       # call as that user
	set_active(user, B) / set_active(user, ALL)
	cleanup_user(user); delete_copies("Purchase Order", ["CS-PO-B"])

Copies are written with db_insert (no validation, no child rows): enough for lists, counts,
permission checks and pages that read headers. Tests must remove what they create.
"""

import frappe

from alpinos.company_scope import ALL, access, active, reset_request_cache, sync


def companies():
	"""(default company, two other companies), stable order."""
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	others = [c for c in frappe.get_all("Company", pluck="name", order_by="name") if c != default]
	return default, others[0], others[1]


def ensure_enabled():
	if not frappe.db.get_single_value("Alpino General Settings", "company_scope_enabled"):
		settings = frappe.get_single("Alpino General Settings")
		settings.company_scope_enabled = 1
		settings.save(ignore_permissions=True)
	fresh()


def fresh():
	"""Forget everything memoised for the request (call between users)."""
	reset_request_cache()
	frappe.local.role_permissions = {}
	if hasattr(frappe.local, "alpinos_cs_authorized"):
		delattr(frappe.local, "alpinos_cs_authorized")
	frappe.local.flags.alpinos_cs_listing = None


def make_user(email, memberships, active_company=None, global_roles=()):
	"""A desk user holding `memberships` = {company: [company-wise roles]} (+ global roles)."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			 "roles": [{"role": r} for r in global_roles]}
		).insert(ignore_permissions=True)
	for name in frappe.get_all("Company Membership", {"user": email}, pluck="name"):
		frappe.delete_doc("Company Membership", name, ignore_permissions=True, flags={"alpinos_skip_user_sync": True})
	first = None
	for company, roles in memberships.items():
		first = first or company
		sync.ensure_membership(email, company, list(roles), is_default=(company == first))
	sync.sync_user(email)
	active.set_active(email, active_company or first)
	frappe.db.commit()
	fresh()
	return email


def set_active(user, company_or_all):
	active.set_active(user, company_or_all)
	frappe.db.commit()
	fresh()


def as_user(user, fn):
	"""Run fn() as `user` (with fresh caches), back to the previous user after."""
	previous = frappe.session.user
	frappe.set_user(user)
	fresh()
	try:
		return fn()
	finally:
		frappe.set_user(previous)
		fresh()


def copy_header(doctype, template, name, company, **overrides):
	"""A header-only copy of `template` in another company (db_insert, no validation)."""
	if frappe.db.exists(doctype, name):
		frappe.db.delete(doctype, {"name": name})
	data = frappe.get_doc(doctype, template).as_dict()
	for key in list(data.keys()):
		if isinstance(data[key], list):
			data.pop(key)
	field = "company"
	data.update({"name": name, field: company, "owner": "Administrator", "docstatus": data.get("docstatus") or 0})
	data.update(overrides)
	frappe.get_doc(data).db_insert()
	return name


def delete_copies(doctype, names):
	for name in names:
		frappe.db.delete(doctype, {"name": name})


def cleanup_user(email):
	for name in frappe.get_all("Company Membership", {"user": email}, pluck="name"):
		frappe.delete_doc("Company Membership", name, ignore_permissions=True, flags={"alpinos_skip_user_sync": True})
	frappe.db.delete("User Permission", {"user": email})
	frappe.db.delete("DefaultValue", {"parent": email})
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	access.clear_cache(email)


__all__ = ["ALL", "as_user", "cleanup_user", "companies", "copy_header", "delete_copies", "ensure_enabled",
	"fresh", "make_user", "set_active"]
