"""Company-wise access: every user works in one company at a time (or "All my companies"),
and holds roles per company.

How it fits together
--------------------
- **Company Membership** (one per user and company) lists the company-wise roles a user has
  in that company. A role is company-wise when Role.custom_company_scoped is ticked; every
  other role is global and applies in every company. The user's own Has Role table holds
  the union of all of it, so Frappe's role-level check passes, and the hooks in
  permissions.py then deny per company. Hooks can only deny, never grant.
- **Company User Permissions** of a managed user are kept equal to the companies they are a
  member of (none when they are a member of every company), so the parts of Frappe and
  ERPNext that already honour User Permissions follow along.
- **The active company** is a per-user default (see active.py) mirrored into the standard
  "company" default, so new documents and ERPNext dashboards pick it up.
- **Every master or transaction** is classified in registry.py: STRICT (has a company),
  TAGGED (a master tagged to companies, blank = all) or GLOBAL.

Nothing here does anything until "Company-wise access is on" is ticked in Alpino General
Settings.
"""

import contextlib

import frappe

ALL = "__all__"
SETTINGS = "Alpino General Settings"
FLAG_FIELD = "company_scope_enabled"


def enabled():
	"""True once Company-wise access is on. Read once per request."""
	local = frappe.local
	cached = getattr(local, "alpinos_cs_enabled", None)
	if cached is not None:
		return cached
	try:
		value = bool(frappe.db.get_single_value(SETTINGS, FLAG_FIELD, cache=True))
	except Exception:
		# Before the field exists (first migrate), or no database (bench commands).
		value = False
	local.alpinos_cs_enabled = value
	return value


def reset_request_cache():
	"""Forget what this request memoised (used by tests and after a switch)."""
	for key in ("alpinos_cs_enabled", "alpinos_cs_rights", "alpinos_cs_modes", "alpinos_cs_members",
		"alpinos_cs_tag_scope", "alpinos_cs_active"):
		if hasattr(frappe.local, key):
			delattr(frappe.local, key)


@contextlib.contextmanager
def bypass(reason=""):
	"""Run system work (imports, repairs, jobs acting for nobody) without the company checks.

	The reason is for whoever reads the call site; nothing records it.
	"""
	depth = frappe.local.flags.get("alpinos_cs_bypass") or 0
	frappe.local.flags.alpinos_cs_bypass = depth + 1
	try:
		yield
	finally:
		frappe.local.flags.alpinos_cs_bypass = depth


def bypassed():
	return bool(frappe.local.flags.get("alpinos_cs_bypass"))


def exempt_user(user):
	"""Users the company checks never apply to."""
	return not user or user in ("Administrator", "Guest")
