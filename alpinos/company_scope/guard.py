"""The write guard: doc_events "*" checks that run on every save, submit, cancel and delete.

has_permission covers the normal paths, but alpinos pages insert and save with
ignore_permissions (about 500 places), and ERPNext fills some companies only after the
create check has run. This guard runs inside the save itself, so nothing gets past it:

- a saved document's company cannot change unless the user may write in both companies;
- without ignore_permissions: the user's roles in the company must give the right (or the
  document is shared with them for it);
- with ignore_permissions: the company must be one the user is a member of, or one this
  request already let them act in (so the ledger rows, attendance and leave ledger entries
  that ERPNext / HRMS write while an approver submits another company's document pass);
- every link to a tagged master (Item, Customer, Supplier...) must be tagged for the
  document's company, or untagged;
- a workflow transition needs its role in the document's company.

Skipped for Administrator, migrations / installs / patches, and inside company_scope.bypass().
"""

import frappe
from frappe import _

from alpinos.company_scope import access, bypassed, enabled, exempt_user, registry

#: Ledger rows ERPNext writes from a submitted document; their links were checked on it.
_NO_LINK_CHECK = frozenset(
	{
		"GL Entry",
		"Stock Ledger Entry",
		"Payment Ledger Entry",
		"Bin",
		"Serial and Batch Bundle",
		"Repost Item Valuation",
		"Leave Ledger Entry",
		"Stock Reservation Entry",
	}
)


def _skip(doc):
	user = frappe.session.user
	if not enabled() or exempt_user(user) or bypassed():
		return True
	flags = frappe.flags
	if flags.in_migrate or flags.in_install or flags.in_patch or flags.in_setup_wizard:
		return True
	return not access.is_managed(user)


def _authorized():
	store = getattr(frappe.local, "alpinos_cs_authorized", None)
	if store is None:
		store = frappe.local.alpinos_cs_authorized = set()
	return store


def _shared(doc, ptype):
	if doc.is_new():
		return False
	right = "read" if ptype in ("print", "email") else ptype
	return bool(
		frappe.share.get_shared(
			doc.doctype, frappe.session.user, rights=[right], filters=[["share_name", "=", doc.name]], limit=1
		)
	)


def _deny(message):
	frappe.throw(message, frappe.PermissionError, title=_("Not permitted in this company"))


def _check(doc, ptype):
	if _skip(doc):
		return
	mode, field = registry.mode(doc.doctype)
	if mode != registry.STRICT:
		return
	user = frappe.session.user
	company = doc.get(field)
	before = None if doc.is_new() else doc.get_doc_before_save()
	old = before.get(field) if before else None

	if old and company != old:
		writable = set(access.allowed_companies(doc.doctype, "write", user))
		if old not in writable or (company and company not in writable):
			_deny(
				_("You cannot move {0} {1} from {2} to {3}.").format(
					_(doc.doctype), doc.name, frappe.bold(old), frappe.bold(company or _("no company"))
				)
			)
	if not company:
		return
	authorized = _authorized()
	if doc.flags.ignore_permissions:
		ok = company in authorized or company in access.member_companies(user)
	else:
		allowed = access.allowed_companies(doc.doctype, ptype, user, is_owner=doc.owner == user or doc.is_new())
		ok = company in allowed or _shared(doc, ptype)
	if not ok:
		_deny(
			_("You do not have {0} access to {1} in {2}.").format(
				_(ptype), _(doc.doctype), frappe.bold(company)
			)
		)
	authorized.add(company)
	if ptype in ("create", "write") and doc.doctype not in _NO_LINK_CHECK:
		_check_tagged_links(doc, company)
	if ptype in ("create", "write") and not doc.flags.ignore_permissions:
		_check_workflow(doc, before, company)


# --- doc_events ----------------------------------------------------------------------------


def fill_company(doc, method=None):
	"""before_validate: an alpinos document saved without its company gets it from where it
	belongs (its fetch_from link), else the user's current company. Runs whether or not
	Company-wise access is on: the field is new, and older code does not set it."""
	if doc.meta.module != "Alpinos Development" or not doc.is_new():
		return
	mode, field = registry.mode(doc.doctype)
	if mode != registry.STRICT or doc.get(field):
		return
	df = doc.meta.get_field(field)
	source = (df.fetch_from or "").split(".")
	if len(source) == 2 and doc.get(source[0]):
		link_df = doc.meta.get_field(source[0])
		if link_df and link_df.options:
			value = frappe.db.get_value(link_df.options, doc.get(source[0]), source[1])
			if value:
				doc.set(field, value)
				return
	from alpinos.company_scope.helpers import current_company

	value = current_company()
	if value:
		doc.set(field, value)


def validate(doc, method=None):
	_check(doc, "create" if doc.is_new() else "write")


def before_submit(doc, method=None):
	_check(doc, "submit")


def before_cancel(doc, method=None):
	_check(doc, "cancel")


def on_trash(doc, method=None):
	_check(doc, "delete")


# --- tagged masters ------------------------------------------------------------------------


def _tag_scope(doctype, names):
	"""{name: scope string} for masters, memoised per request."""
	cache = getattr(frappe.local, "alpinos_cs_tag_scope", None)
	if cache is None:
		cache = frappe.local.alpinos_cs_tag_scope = {}
	missing = [n for n in names if (doctype, n) not in cache]
	if missing:
		rows = frappe.get_all(
			doctype, filters={"name": ["in", missing]}, fields=["name", registry.SCOPE_FIELD]
		)
		found = {r.name: r.get(registry.SCOPE_FIELD) or "" for r in rows}
		for n in missing:
			cache[(doctype, n)] = found.get(n, "")
	return {n: cache[(doctype, n)] for n in names}


def _tagged_links(doc):
	"""{tagged doctype: {names}} linked from the document and its child rows."""
	out = {}

	def collect(d, meta):
		for df in meta.get_link_fields():
			target = df.options
			if registry.mode(target)[0] != registry.TAGGED:
				continue
			value = d.get(df.fieldname)
			if value:
				out.setdefault(target, set()).add(value)

	collect(doc, doc.meta)
	for df in doc.meta.get_table_fields():
		child_meta = frappe.get_meta(df.options)
		if not any(registry.mode(l.options)[0] == registry.TAGGED for l in child_meta.get_link_fields()):
			continue
		for row in doc.get(df.fieldname) or []:
			collect(row, child_meta)
	return out


def _check_tagged_links(doc, company):
	needle = f"|{company}|"
	for target, names in _tagged_links(doc).items():
		scopes = _tag_scope(target, sorted(names))
		wrong = [n for n, scope in scopes.items() if scope and needle not in scope]
		if wrong:
			frappe.throw(
				_("{0} {1} {2} not tagged for {3}. Add {3} to its Companies, or pick another.").format(
					_(target),
					", ".join(frappe.bold(n) for n in wrong[:5]) + (" ..." if len(wrong) > 5 else ""),
					_("is") if len(wrong) == 1 else _("are"),
					frappe.bold(company),
				),
				title=_("Not available in this company"),
			)


# --- workflow ------------------------------------------------------------------------------


def _check_workflow(doc, before, company):
	"""A workflow transition must be made by a role the user holds in this company.

	Frappe picks transitions from the user's pooled roles, which would let a Purchase
	approver in company A approve in company B where they only read.
	"""
	from frappe.model.workflow import get_workflow_name

	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		return
	workflow = frappe.get_cached_doc("Workflow", workflow_name)
	state_field = workflow.workflow_state_field
	new_state = doc.get(state_field)
	old_state = before.get(state_field) if before else None
	if not before or not new_state or new_state == old_state:
		return
	roles = access.effective_roles(frappe.session.user, company)
	options = [t for t in workflow.transitions if t.state == old_state and t.next_state == new_state]
	if options and not any(t.allowed in roles for t in options):
		_deny(
			_("Moving {0} from {1} to {2} needs the role {3} in {4}.").format(
				doc.name, old_state, new_state, " / ".join({t.allowed for t in options}), frappe.bold(company)
			)
		)
