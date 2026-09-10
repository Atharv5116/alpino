"""Quarantine — hold received material out of the flow until QC releases it.

Purchase Inward Item already carried the whole quarantine field surface
(`quarantine`, `quarantine_reason`, `quarantine_status`, `quarantine_date`) and the
module already provisions a Quarantine warehouse. None of it did anything: a
quarantined line went to QC and into stock exactly like any other. This module is
the behaviour.

Three things follow from marking a line:

1. **It cannot go to QC.** `assert_none_open` is composed into the submit-for-QC
   guard, so the hand-off is refused by line number while anything is still held.
2. **It cannot reach usable stock.** `target_for_line` routes a held line to the
   Quarantine warehouse, so on any path where a held line does reach a receipt, the
   quantity lands somewhere it cannot be sold or consumed from.
3. **Only QC may let it out.** Marking is a Store judgement; releasing is a QC one
   (C.ROLE_DESCRIPTIONS has said so all along), so the two actions carry different
   roles.

Releasing sets the status to Released rather than clearing the tick, because the
BRD wants the hold to remain visible on the document after it is lifted.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from alpinos.purchase import constants as C

INWARD = "Purchase Inward"

# Only these roles may lift a hold (ROLE_DESCRIPTIONS: "release from quarantine").
RELEASE_ROLES = C.QC_ROLES + C.ADMIN_ROLES
# Store owns the receipt, so Store marks the hold.
MARK_ROLES = C.STORE_ROLES + C.ADMIN_ROLES


def _held(line):
	"""A line under an OPEN hold: ticked and not yet released."""
	return cint(line.get("quarantine")) and line.get("quarantine_status") != C.QUARANTINE_RELEASED


def open_lines(doc):
	"""Row numbers of every line still held, in order."""
	return [line.idx for line in (doc.get("items") or []) if _held(line)]


# ------------------------------------------------------------------ enforcement


def assert_none_open(doc):
	"""Guard for the submit-for-QC transition. Returns an error string, or None.

	Composed into the transition table rather than raised here, because the workflow
	engine shows a guard message on the button itself instead of only on click.
	"""
	held = open_lines(doc)
	if not held:
		return None
	return _(
		"Row {0} is under quarantine and cannot be sent to QC. "
		"A {1} must release it first."
	).format(", ".join(str(i) for i in held), " / ".join(RELEASE_ROLES[:2]))


def target_for_line(line, fallback):
	"""Where a line's quantity belongs: the Quarantine warehouse while it is held.

	Called from the GRN builder, so a held line that somehow reaches a receipt lands
	out of usable stock rather than in the store it was destined for.
	"""
	if not _held(line):
		return fallback
	return warehouse_name() or fallback


def warehouse_name(company=None):
	"""The provisioned Quarantine warehouse for the document company."""
	from alpinos.purchase.settings import warehouse as settings_warehouse

	try:
		return settings_warehouse(C.WH_QUARANTINE, company)
	except Exception:
		return None


# --------------------------------------------------------------------- actions


def _load(purchase_inward):
	doc = frappe.get_doc(INWARD, purchase_inward)
	doc.check_permission("write")
	return doc


def _assert_role(roles, what):
	if set(frappe.get_roles(frappe.session.user)).intersection(roles):
		return
	frappe.throw(
		_("Only {0} may {1}.").format(" or ".join(roles[:2]), what),
		title=_("Not Allowed"),
	)


def _rows(doc, idx_list):
	"""The lines an action applies to: the named rows, or all of them."""
	if not idx_list:
		return list(doc.get("items") or [])
	wanted = {cint(i) for i in idx_list}
	return [line for line in (doc.get("items") or []) if line.idx in wanted]


@frappe.whitelist()
def mark(purchase_inward, reason, rows=None):
	"""Hold the whole inward, or the named rows, pending QC release."""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Please enter the Quarantine Reason."), title=_("Reason Required"))
	_assert_role(MARK_ROLES, _("place material under quarantine"))

	doc = _load(purchase_inward)
	if cint(doc.docstatus) == 2:
		frappe.throw(_("This Purchase Inward is cancelled."))
	if isinstance(rows, str):
		rows = frappe.parse_json(rows)

	touched = []
	for line in _rows(doc, rows):
		line.quarantine = 1
		line.quarantine_reason = reason
		line.quarantine_status = C.QUARANTINE_HELD
		line.quarantine_date = now_datetime()
		touched.append(line.idx)

	if not touched:
		frappe.throw(_("No item lines to quarantine."))

	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()
	return {"quarantined": touched}


@frappe.whitelist()
def release(purchase_inward, rows=None, remarks=None):
	"""Lift the hold. QC only, and the tick stays so the history is still readable."""
	_assert_role(RELEASE_ROLES, _("release material from quarantine"))

	doc = _load(purchase_inward)
	if isinstance(rows, str):
		rows = frappe.parse_json(rows)

	touched = []
	for line in _rows(doc, rows):
		if not _held(line):
			continue
		line.quarantine_status = C.QUARANTINE_RELEASED
		line.quarantine_date = now_datetime()
		if (remarks or "").strip():
			line.quarantine_reason = (
				f"{line.quarantine_reason or ''}\nReleased: {remarks.strip()}".strip()
			)
		touched.append(line.idx)

	if not touched:
		frappe.throw(_("Nothing is currently under quarantine on this Purchase Inward."))

	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()
	return {"released": touched}


@frappe.whitelist()
def status(purchase_inward):
	"""What the entry screen needs to draw its buttons."""
	doc = frappe.get_doc(INWARD, purchase_inward)
	doc.check_permission("read")
	roles = set(frappe.get_roles(frappe.session.user))
	held = open_lines(doc)
	return {
		"held_rows": held,
		"any_held": bool(held),
		"may_mark": bool(roles.intersection(MARK_ROLES)),
		"may_release": bool(roles.intersection(RELEASE_ROLES)),
		"warehouse": warehouse_name(doc.get("company")),
	}
