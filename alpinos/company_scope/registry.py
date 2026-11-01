"""Which doctypes are company-wise, and how.

STRICT  the document belongs to one company, held in a Link to Company (normally `company`).
        Any parent doctype with a `company` Link is STRICT unless listed in GLOBAL_DOCTYPES,
        so a new company-bearing doctype is locked by default.
TAGGED  a master tagged to one or more companies (custom_companies); blank = all companies.
SELF    Company itself: the document's name is the company.
GLOBAL  everything else (settings, logs, shared masters such as UOM or Designation).

Child tables follow their parent: Frappe checks a child row through its parent.
"""

import frappe

STRICT = "strict"
TAGGED = "tagged"
SELF = "self"
GLOBAL = "global"

TAG_FIELD = "custom_companies"
TAG_DOCTYPE = "Alpinos Company Tag"
#: Hidden mirror of the tags, "|AHFPL company|HH company|", kept by tags.sync_scope, so SQL
#: and get_all can filter without joining the child table.
SCOPE_FIELD = "custom_company_scope"

#: Masters that carry company tags (decided 1 Nov 2026). Old records were tagged to Alpino
#: Health Foods on go-live; blank means every company.
TAGGED_DOCTYPES = (
	"Item",
	"Customer",
	"Supplier",
	"Buyer Master",
	"Price List",
	"Machine",
	"Process Master",
)

#: Doctypes that have a company field but are not scoped by it.
GLOBAL_DOCTYPES = frozenset(
	{
		# Who may work where: managed by System Managers across every company.
		"Company Membership",
		# Settings, logs and system queues.
		"Prepared Report",
		"Error Log",
		"Scheduled Job Log",
		"Data Import",
		"Data Export",
		"Session Default",
		"Global Defaults",
		"Accounting Dimension",
		"Accounting Dimension Filter",
		"Email Account",
		"Number Card",
		"Dashboard Chart",
		"Workspace",
		"Report",
	}
)

#: STRICT doctypes whose company lives in another field.
COMPANY_FIELD = {}


def _company_link(meta):
	field = COMPANY_FIELD.get(meta.name, "company")
	df = meta.get_field(field)
	if df and df.fieldtype == "Link" and df.options == "Company":
		return field
	return None


def mode(doctype):
	"""(mode, company fieldname or None) for a doctype. Memoised per request."""
	cache = getattr(frappe.local, "alpinos_cs_modes", None)
	if cache is None:
		cache = frappe.local.alpinos_cs_modes = {}
	if doctype in cache:
		return cache[doctype]
	cache[doctype] = result = _mode(doctype)
	return result


def _mode(doctype):
	if not doctype:
		return GLOBAL, None
	if doctype == "Company":
		return SELF, "name"
	if doctype in GLOBAL_DOCTYPES:
		return GLOBAL, None
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return GLOBAL, None
	if meta.istable or meta.issingle or meta.is_virtual:
		return GLOBAL, None
	if meta.get_field(SCOPE_FIELD) and meta.get_field(TAG_FIELD):
		return TAGGED, SCOPE_FIELD
	field = _company_link(meta)
	if field:
		return STRICT, field
	return GLOBAL, None


def is_scoped(doctype):
	return mode(doctype)[0] != GLOBAL
