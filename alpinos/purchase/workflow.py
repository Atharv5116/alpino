"""Purchase Inward workflow engine — statuses, transitions, guards, per-role actions.

Task 289. The BRD's workflow tables (2.3 for the inward, 4.7 for QC, 5.3 for
cancellation) are encoded once here as data; the desk form, the list page and the
server-side actions all read their available buttons from `available_actions()`,
so a transition can never be offered in one place and refused in another.

A transition is a row of:  from_status -> (action, to_status, roles, guard)
`roles` gates who may see and invoke it; `guard` is a callable returning an error
string when the transition is not currently legal (None means "allowed").
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from alpinos.purchase import constants as C


# --------------------------------------------------------------------- guards


def _guard_receiving_complete(doc):
	"""Store may hand over to QC only once the receipt is actually recorded."""
	if not doc.get("actual_arrival_datetime"):
		return _("Please enter the Actual Arrival Date & Time before submitting for QC.")
	if not any(flt(l.received_qty) for l in doc.get("items") or []):
		return _("Please enter the Received Quantity for at least one item.")
	for line in doc.get("items") or []:
		if flt(line.received_qty) and not line.target_warehouse:
			return _("Row {0}: please select a Target Location.").format(line.idx)
	if cint(doc.get("vehicle_details_verified")) and not (
		(doc.get("actual_vehicle_no") or "").strip()
		or (doc.get("actual_driver_contact_no") or "").strip()
	):
		return _("Please enter the correct vehicle and driver details.")
	return None




def _guard_qc_exists(doc):
	if not doc.get("purchase_qc"):
		return _("No Purchase QC has been raised for this inward yet.")
	return None


def _guard_grn_exists(doc):
	if not doc.get("purchase_receipt"):
		return _("No GRN has been generated for this inward yet.")
	return None


def _guard_grn_submitted(doc):
	"""BR-GRN-12 / VAL-GRN-10 — invoice only after the Admin finally submits."""
	if not doc.get("purchase_receipt"):
		return _("Purchase Invoice can be created only after the GRN is finally submitted.")
	if frappe.db.get_value("Purchase Receipt", doc.get("purchase_receipt"), "docstatus") != 1:
		return _("Purchase Invoice can be created only after the GRN is finally submitted.")
	return None


# ---------------------------------------------------------------- transitions

# action -> (label, next_status, allowed_roles, guard, hide)
# `hide(doc)` removes the button altogether (rather than greying it out) when the other
# action of a pair is the one that applies -- Submit for QC vs Create Quarantine.
_T = lambda action, label, nxt, roles, guard=None, hide=None: {
	"action": action,
	"label": label,
	"next_status": nxt,
	"roles": tuple(roles),
	"guard": guard,
	"hide": hide,
}

PURCHASE = C.PURCHASE_ROLES + C.ADMIN_ROLES
STORE = C.STORE_ROLES + C.ADMIN_ROLES
QC = C.QC_ROLES + C.ADMIN_ROLES
ACCOUNTS = C.ACCOUNTS_ROLES + C.ADMIN_ROLES

# BRD 2.3 "Workflow Action" plus the list-screen actions from BRD 1.3 / 1.4.
INWARD_TRANSITIONS = {
	C.PI_DRAFT: [
		_T("submit", _("Submit"), C.PI_PENDING_RECEIPT, PURCHASE),
	],
	C.PI_PENDING_RECEIPT: [
		# Every received item goes to QC; quarantine is decided on the Purchase QC.
		_T("submit_for_qc", _("Submit for QC"), C.PI_PENDING_QC, STORE, _guard_receiving_complete),
	],
	# Older flow only: an inward whose every item was quarantined before QC. Releasing
	# them from its Quarantine document moves it on to Pending QC.
	C.PI_QUARANTINED: [],
	C.PI_PENDING_QC: [
		_T("start_qc", _("Start QC"), C.PI_QC_IN_PROGRESS, QC, _guard_qc_exists),
	],
	C.PI_QC_IN_PROGRESS: [
		_T("complete_qc", _("Complete QC"), C.PI_QC_COMPLETED, QC, _guard_qc_exists),
	],
	C.PI_QC_COMPLETED: [
		_T("generate_grn", _("Generate GRN"), C.PI_GRN_GENERATED, PURCHASE),
	],
	C.PI_GRN_GENERATED: [
		_T("create_purchase_invoice", _("Create Purchase Invoice"), C.PI_PAYMENT_PENDING,
		   PURCHASE, _guard_grn_submitted),
	],
	C.PI_PAYMENT_PENDING: [
		_T("complete_payment", _("Complete Payment"), C.PI_COMPLETED, ACCOUNTS),
	],
	C.PI_COMPLETED: [],
	C.PI_FORCE_CLOSED: [],
	C.PI_CANCELLED: [],
}

# BRD 1.4 "Action Availability by Status" — read-only actions offered alongside
# the transitions above. These never change the status.
INWARD_VIEW_ACTIONS = {
	C.PI_DRAFT: ("edit", "delete", "print"),
	C.PI_PENDING_RECEIPT: ("view", "continue_receiving", "print"),
	# view_quarantine is offered only when the inward has a Quarantine document.
	C.PI_QUARANTINED: ("view", "view_quarantine", "print"),
	C.PI_PENDING_QC: ("view", "view_qc", "view_quarantine", "print"),
	C.PI_QC_IN_PROGRESS: ("view", "view_qc", "view_quarantine", "print"),
	C.PI_QC_COMPLETED: ("view", "view_qc_report", "view_quarantine", "print"),
	# BRD 5.2.3 offers "View Debit Note" only "If Rejected Qty > 0 and Debit Note
	# generated"; the button is routed off doc.debit_note, so it stays hidden until
	# BR-GRN-09 has actually raised one.
	C.PI_GRN_GENERATED: ("view", "view_qc_report", "view_grn", "view_debit_note", "view_quarantine", "print"),
	C.PI_PAYMENT_PENDING: ("view", "view_grn", "view_debit_note", "view_invoice", "view_quarantine", "print"),
	C.PI_COMPLETED: ("view", "view_grn", "view_debit_note", "view_invoice", "view_quarantine", "print"),
	C.PI_FORCE_CLOSED: ("view", "view_qc_report", "view_grn", "view_debit_note", "view_invoice", "view_quarantine", "print"),
	C.PI_CANCELLED: ("view", "print"),
}

# Transitions QC performs on its own screen (Purchase QC Entry / the QC list). The engine
# still owns them -- purchase_qc.start_qc / complete_qc assert them against the inward -- but
# the inward screens offer "Go to QC" instead of running them against a QC nobody is looking at.
QC_SCREEN_ACTIONS = ("start_qc", "complete_qc")

VIEW_ACTION_LABELS = {
	"edit": _("Edit"),
	"delete": _("Delete"),
	"view": _("View"),
	"print": _("Print"),
	"continue_receiving": _("Continue Receiving"),
	"view_qc": _("Go to QC"),
	"view_qc_report": _("View QC Report"),
	"view_grn": _("View GRN"),
	"view_debit_note": _("View Debit Note"),
	"view_invoice": _("View Purchase Invoice"),
	"view_quarantine": _("View Quarantine"),
}

# Roles that may see each read-only action; anything unlisted is open to all
# roles that can read the document.
VIEW_ACTION_ROLES = {
	"edit": PURCHASE,
	"delete": PURCHASE,
	"continue_receiving": STORE,
}


# ------------------------------------------------------------------ resolution


def user_roles(user=None):
	return set(frappe.get_roles(user or frappe.session.user))


def _may(roles, user_role_set):
	return bool(set(roles) & user_role_set) if roles else True


# Transitions the engine declares but that this phase does not implement. The BRD's
# Purchase Invoice and Payment module is section 6, outside the Purchase Inward -> QC ->
# GRN scope built here. They stay visible (BRD 1.4 wants the next step on screen) but
# greyed out with an honest reason, rather than presented as enabled buttons whose only
# outcome is a traceback. start_qc / complete_qc are deliberately NOT listed: they are
# implemented on the Purchase QC document and the QC list page reads `enabled` off them.
ACTION_UNAVAILABLE = {
	# Not a button: the inward reaches Completed on its own once the Purchase Invoice's
	# supplier and logistics payments are fully recorded (purchase_invoice._sync_inward).
	"complete_payment": _(
		"Completes automatically once the Purchase Invoice's payments are fully recorded."
	),
}


# ---------------------------------------------------------------- purchase QC
#
# BRD 4.7's workflow table, encoded. The module remodels the BRD's QC Approved /
# Partially Approved / QC Rejected as `qc_result`, and its GRN Draft / GRN Completed as
# `grn_status`, so what remains here is the inspection's own status machine. Without a
# table there was nothing to refuse an illegal move -- qc_status was only ever derived,
# so a write could put an inspection straight from Pending QC to QC Completed.
#
# from-status -> statuses it may move to.
QC_TRANSITIONS = {
	C.QC_PENDING: {C.QC_IN_PROGRESS, C.QC_SLA_BREACHED, C.QC_CANCELLED},
	# BR-QC-05: inspections run in parallel, so QC In Progress legitimately re-enters
	# itself as each section is worked, and may fall back when a section is reopened.
	C.QC_IN_PROGRESS: {
		C.QC_IN_PROGRESS,
		C.QC_READY_FOR_DECISION,
		C.QC_SLA_BREACHED,
		C.QC_COMPLETED,
		C.QC_CANCELLED,
	},
	C.QC_READY_FOR_DECISION: {
		C.QC_IN_PROGRESS,
		C.QC_READY_FOR_DECISION,
		C.QC_COMPLETED,
		C.QC_SLA_BREACHED,
		C.QC_CANCELLED,
	},
	# The SLA breach is a flag laid over an unfinished inspection, so it returns to the
	# working statuses once the QC team picks it up again.
	C.QC_SLA_BREACHED: {
		C.QC_IN_PROGRESS,
		C.QC_READY_FOR_DECISION,
		C.QC_SLA_BREACHED,
		C.QC_COMPLETED,
		C.QC_CANCELLED,
	},
	C.QC_COMPLETED: {C.QC_CANCELLED},
	C.QC_CANCELLED: set(),
}


def assert_qc_transition(old_status, new_status):
	"""Refuse a QC status move BRD 4.7 does not allow. No-op when nothing changes."""
	old_status = old_status or C.QC_PENDING
	if not new_status or new_status == old_status:
		return
	if new_status not in C.QC_STATUSES:
		frappe.throw(_("Unknown Purchase QC status: {0}").format(new_status))
	if new_status not in QC_TRANSITIONS.get(old_status, set()):
		frappe.throw(
			_("A Purchase QC cannot move from {0} to {1}.").format(
				frappe.bold(old_status), frappe.bold(new_status)
			),
			title=_("BRD 4.7"),
		)


def available_actions(doc, user=None):
	"""Every action `user` may take on `doc` right now.

	Returns a list of dicts: {action, label, next_status, kind, enabled, reason}.
	`kind` is "transition" or "view". A transition whose guard fails is still
	returned, with enabled=False and the guard's message as `reason`, so the UI can
	explain why a button is greyed out rather than silently hiding it.
	"""
	if isinstance(doc, str):
		doc = frappe.get_doc("Purchase Inward", doc)

	roles = user_roles(user)
	status = doc.get("inward_status") or C.PI_DRAFT
	out = []

	for t in INWARD_TRANSITIONS.get(status, []):
		if not _may(t["roles"], roles):
			continue
		if t.get("hide") and t["hide"](doc):
			continue
		reason = t["guard"](doc) if t["guard"] else None
		if reason is None:
			reason = ACTION_UNAVAILABLE.get(t["action"])
		out.append(
			{
				"action": t["action"],
				"label": t["label"],
				"next_status": t["next_status"],
				"kind": "transition",
				"enabled": reason is None,
				"reason": reason,
			}
		)

	for action in INWARD_VIEW_ACTIONS.get(status, ()):
		if not _may(VIEW_ACTION_ROLES.get(action, ()), roles):
			continue
		if action == "view_quarantine" and not doc.get("purchase_quarantine"):
			continue
		out.append(
			{
				"action": action,
				"label": VIEW_ACTION_LABELS.get(action, action.replace("_", " ").title()),
				"next_status": None,
				"kind": "view",
				"enabled": True,
				"reason": None,
			}
		)

	# Admin overrides: a submitted inward can be Force Closed, or moved to any status, at any
	# point. `kind` is "admin" -- neither a workflow transition nor a plain view -- so the
	# screens draw them separately (with a reason prompt) and the list rows leave them out.
	if cint(doc.get("docstatus")) == 1 and may_override_status(user):
		already = status == C.PI_FORCE_CLOSED
		out.append(
			{
				"action": "force_close",
				"label": _("Force Close"),
				"next_status": C.PI_FORCE_CLOSED,
				"kind": "admin",
				"enabled": not already,
				"reason": _("This inward is already Force Closed.") if already else None,
			}
		)
		out.append(
			{
				"action": "change_status",
				"label": _("Change Status"),
				"next_status": None,
				"kind": "admin",
				"enabled": True,
				"reason": None,
				"statuses": [s for s in C.PI_ADMIN_CHOICES if s != status],
			}
		)
	return out


def may_override_status(user=None):
	"""Admin: the Purchase Inward Admin role, System Manager, or the Administrator."""
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(C.ADMIN_ROLES) & user_roles(user))


def override_status(doc, status, reason, user=None):
	"""An Admin moves a submitted inward to `status`, whatever it is now.

	It changes the STATUS only. No document is created, cancelled or reversed -- the QC, GRN,
	invoice and stock stay exactly as they are -- so this is for closing an inward that will
	not follow the normal flow, or for putting a stuck one back to the step it should be at.
	The reason is required and is written on the inward's timeline with who and when.
	"""
	if isinstance(doc, str):
		doc = frappe.get_doc("Purchase Inward", doc)
	if not may_override_status(user):
		frappe.throw(_("Only an Admin may change the status of a Purchase Inward."), frappe.PermissionError)
	if cint(doc.get("docstatus")) != 1:
		frappe.throw(
			_(
				"Only a submitted Purchase Inward can have its status changed. A draft is "
				"discarded, and a cancelled one stays cancelled."
			)
		)
	if status not in C.PI_ADMIN_CHOICES:
		frappe.throw(_("{0} is not a status an Admin can set here.").format(frappe.bold(status or "")))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Please give a reason for changing the status."))
	old = doc.get("inward_status") or C.PI_DRAFT
	if old == status:
		frappe.throw(_("The Purchase Inward is already {0}.").format(frappe.bold(status)))

	set_status(doc, status)
	doc.add_comment(
		"Info",
		_("{0} changed the status from {1} to {2}. Reason: {3}").format(
			frappe.bold(frappe.utils.get_fullname(user or frappe.session.user)),
			frappe.bold(old),
			frappe.bold(status),
			frappe.utils.escape_html(reason),
		),
	)
	return old


def assert_transition(doc, action, user=None):
	"""Raise unless `user` may run `action` on `doc` in its current status."""
	status = doc.get("inward_status") or C.PI_DRAFT
	for t in INWARD_TRANSITIONS.get(status, []):
		if t["action"] != action:
			continue
		if not _may(t["roles"], user_roles(user)):
			frappe.throw(
				_("You do not have permission to perform this action."),
				frappe.PermissionError,
			)
		reason = t["guard"](doc) if t["guard"] else None
		if reason:
			frappe.throw(reason)
		return t
	frappe.throw(
		_("{0} is not available while the Purchase Inward is {1}.").format(
			action.replace("_", " ").title(), status
		)
	)


def set_status(doc, status, commit=False):
	"""Move an inward to `status`, tolerating both saved and in-memory docs."""
	if status not in C.PI_STATUSES:
		frappe.throw(_("Unknown Purchase Inward status: {0}").format(status))
	if isinstance(doc, str):
		doc = frappe.get_doc("Purchase Inward", doc)
	if doc.get("inward_status") == status:
		return doc
	if doc.get("docstatus") == 1 and not doc.get("__islocal"):
		doc.db_set("inward_status", status, update_modified=False)
		# db_set writes straight past the save path, so PurchaseInward's
		# on_update_after_submit -- the only other caller of the rollup -- never fires for
		# a transition. Without this the Purchase Order's Inward Status stays frozen at
		# whatever it was when the inward was last *saved*, so filtering the order list by
		# Inward Status returns the wrong orders for the whole rest of the chain.
		_refresh_order_rollup(doc)
	else:
		doc.inward_status = status
	if commit:
		frappe.db.commit()
	return doc


def _refresh_order_rollup(doc):
	"""Push the new status onto the parent Purchase Order, best effort.

	Imported lazily so a migrate that loads this module before the Purchase Order custom
	fields exist still works. A rollup failure must never strand a legitimate transition,
	so it is logged rather than raised.
	"""
	order = doc.get("purchase_order")
	if not order:
		return
	try:
		from alpinos.purchase.purchase_order_fields import refresh_inward_progress

		refresh_inward_progress(order)
	except Exception:
		frappe.log_error(
			title="Purchase Inward: order rollup failed",
			message=f"{doc.get('name')} -> {order}\n{frappe.get_traceback()}",
		)


@frappe.whitelist()
def get_actions(name):
	"""Whitelisted wrapper so the desk form and list page share one source of truth."""
	doc = frappe.get_doc("Purchase Inward", name)
	doc.check_permission("read")
	return available_actions(doc)
