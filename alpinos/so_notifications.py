"""
Sales Order lifecycle notifications (BRD Notification Matrix N01–N23).

Channel = In-App: a Frappe **Notification Log** (bell) per recipient, plus a Raven DM
when the Raven bot is available (continuity with the app's existing DMs). Every send is
best-effort and wrapped so a notification failure never breaks the workflow transition.

Event-driven notifications (N01, N03–N13, N15–N20) are fired from the workflow engine /
action helpers. Sub-status ones (N06/N07/N08) fire from pick_list_on_update. ASN/GRN
rejections (N19/N20) fire from the Post Delivery controller. Time-based reminders
(N02, N14, N21, N22, N23) run from run_daily_so_notifications (scheduler_events.daily).
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

# Role groups (BRD recipients). ECOM role names are the ones seeded by the e-com setup.
WAREHOUSE = ["Warehouse Admin", "Warehouse Manager"]
SALES = ["Sales Admin", "Sales Manager"]
ECOM_COORD = ["E-Commerce Coordinator"]
ECOM_MGR = ["E-Commerce Manager"]
DN_USERS = ["DN User", "Warehouse User"]

# Reminder thresholds (days/hours). Central so they're easy to tune later.
SLA_APPROVAL_HOURS = 4
FUTURE_DISPATCH_LEAD_DAYS = 1
GRN_PENDING_DAYS = 3
PO_EXPIRY_LEAD_DAYS = 3

_PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
_TERMINAL = ("Completed", "Forced Completed", "Cancelled")


# ---------------------------------------------------------------------------
# Low-level send
# ---------------------------------------------------------------------------
def _role_users(roles):
	"""Deduped enabled users holding any of the given role(s)."""
	from alpinos.raven_notifications import _role_users as ru
	out = []
	for r in (roles if isinstance(roles, (list, tuple, set)) else [roles]):
		for u in ru(r) or []:
			if u not in out:
				out.append(u)
	return out


def _send(recipients, subject, doctype=None, docname=None, doc=None, priority="medium"):
	"""Create an in-app Notification Log per recipient (+ Raven DM if available)."""
	users = [u for u in dict.fromkeys(recipients or []) if u and u not in ("Administrator", "Guest")]
	if not users:
		return
	subject = f"{_PRIORITY_ICON.get(priority, '')} {subject}".strip()
	dt = doctype or (doc.doctype if doc else None) or ""
	dn = docname or (doc.name if doc else None) or ""
	for u in users:
		try:
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": u,
				"subject": subject,
				"type": "Alert",
				"document_type": dt,
				"document_name": dn,
			}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="SO notification (bell) failed", message=frappe.get_traceback())
	try:
		from alpinos.raven_notifications import _get_bot, _send_dm
		bot = _get_bot()
		if bot:
			for u in users:
				_send_dm(bot, u, subject, doc)
	except Exception:
		pass


def safe(fn):
	"""Run a notification callable, swallowing/logging any error."""
	try:
		fn()
	except Exception:
		frappe.log_error(title="SO notification failed", message=frappe.get_traceback())


def _so_creator(so_name):
	owner = frappe.db.get_value("Sales Order", so_name, "owner")
	return [owner] if owner else []


# ===========================================================================
# Event-driven notifications
# ===========================================================================
def n01_so_submitted(doc):
	_send(_role_users(WAREHOUSE),
		_("New Sales Order {0} submitted for {1}. Please review and approve.").format(doc.name, doc.get("customer_name") or doc.customer),
		doc=doc, priority="high")


def n03_pl_created(so, pl_name):
	_send(_role_users(SALES),
		_("Sales Order {0} approved. Pick List {1} has been created.").format(so, pl_name),
		doctype="Sales Order", docname=so, priority="medium")


def n04_future_dispatch(so):
	_send(_role_users(SALES),
		_("Sales Order {0} moved to Future Dispatch. Stock not currently available.").format(so),
		doctype="Sales Order", docname=so, priority="high")


def n05_pl_from_future_dispatch(so, pl_name):
	_send(_role_users(SALES),
		_("Stock available! Pick List {1} created for Future Dispatch Order {0}.").format(so, pl_name),
		doctype="Sales Order", docname=so, priority="medium")


def n06_pl_assigned(doc):
	user = doc.get("custom_assigned_to")
	if not user:
		return
	_send([user],
		_("You have been assigned Pick List {0} for {1}. Please start picking.").format(doc.name, doc.get("custom_customer_name") or ""),
		doc=doc, priority="high")


def n07_sticker_pending(doc):
	_send(_role_users(WAREHOUSE),
		_("Pick List {0} is fully picked and awaiting sticker. Please print and apply.").format(doc.name),
		doc=doc, priority="medium")


def n08_submission_pending(doc):
	_send(_role_users(WAREHOUSE),
		_("Sticker applied on Pick List {0}. Ready for your submission.").format(doc.name),
		doc=doc, priority="low")


def n09_pl_submitted(doc, so):
	_send(_role_users(SALES) + _role_users(DN_USERS),
		_("Pick List {0} submitted. Please create the Delivery Note for {1}.").format(doc.name, doc.get("custom_customer_name") or ""),
		doctype="Sales Order", docname=so or "", priority="high")


def n11_dn_dispatched(doc, so):
	lr = doc.get("custom_lr_gr_no") or ""
	transporter = doc.get("custom_transporter_name") or ""
	_send(_role_users(SALES) + _role_users(ECOM_COORD),
		_("Order {0} dispatched via {1}. LR/AWB: {2}.").format(so or doc.name, transporter, lr),
		doctype="Sales Order", docname=so or "", priority="medium")
	# N10: warn the creator if the dispatch date had already passed.
	dd = frappe.db.get_value("Sales Order", so, "custom_dispatch_date") if so else None
	if dd and getdate(dd) < getdate(today()):
		_send(_so_creator(so),
			_("The Dispatch Date for {0} had already passed at dispatch.").format(so),
			doctype="Sales Order", docname=so, priority="high")


def n12_completed(so):
	_send(_role_users(WAREHOUSE),
		_("Sales Order {0} marked as Completed.").format(so),
		doctype="Sales Order", docname=so, priority="low")


def n13_partial_initiated(so, future_date=None):
	extra = _(" Remaining qty scheduled for Future Dispatch on {0}.").format(future_date) if future_date else ""
	_send(_role_users(SALES),
		_("Partial dispatch initiated for {0}.").format(so) + extra,
		doctype="Sales Order", docname=so, priority="high")


def n15_partial_dn_submitted(so):
	_send(_role_users(SALES) + _role_users(ECOM_COORD),
		_("Partial dispatch completed for {0}.").format(so),
		doctype="Sales Order", docname=so, priority="medium")


def n16_auto_completed(so):
	_send(_role_users(SALES) + _role_users(WAREHOUSE),
		_("Sales Order {0} fully fulfilled across all partial terms. Status auto-updated to Completed.").format(so),
		doctype="Sales Order", docname=so, priority="medium")


def n17_forced_close(so, reason):
	_send(_role_users(SALES),
		_("Force Close initiated for {0}. Reason: {1}. Remaining qty abandoned.").format(so, reason or ""),
		doctype="Sales Order", docname=so, priority="high")


def n18_forced_dn_submitted(so):
	_send(_role_users(SALES) + _role_users(ECOM_COORD),
		_("Forced dispatch completed for {0}. Order is now closed.").format(so),
		doctype="Sales Order", docname=so, priority="high")


def n19_asn_rejected(pd):
	_send(_role_users(ECOM_COORD) + _role_users(ECOM_MGR),
		_("ASN for {0} (DN {1}) has been rejected. Please review and re-upload.").format(pd.sales_order, pd.delivery_note),
		doctype="Post Delivery", docname=pd.name, priority="high")


def n20_grn_rejected(pd, rejected_qty):
	_send(_role_users(SALES) + _role_users(ECOM_MGR),
		_("GRN rejection received for {0} (DN {1}). Rejected Qty: {2}. Action required.").format(pd.sales_order, pd.delivery_note, rejected_qty),
		doctype="Post Delivery", docname=pd.name, priority="high")


# ===========================================================================
# Scheduled (daily) reminders — N02, N14, N21, N22, N23
# ===========================================================================
def run_daily_so_notifications():
	safe(_n02_sla_pending_approval)
	safe(_n14_future_dispatch_due)
	safe(_n21_grn_pending)
	safe(_n22_23_po_expiry)


def _n02_sla_pending_approval():
	cutoff = add_to_date(now_datetime(), hours=-SLA_APPROVAL_HOURS)
	rows = frappe.get_all(
		"Sales Order",
		filters={"custom_workflow_status": "Warehouse Approval Pending", "docstatus": 1, "creation": ["<", cutoff]},
		fields=["name", "customer_name"],
	)
	if not rows:
		return
	recipients = _role_users(["Warehouse Manager"]) + _role_users(ECOM_MGR)
	for r in rows:
		_send(recipients,
			_("Reminder: Sales Order {0} has been pending warehouse approval for over {1} hours.").format(r.name, SLA_APPROVAL_HOURS),
			doctype="Sales Order", docname=r.name, priority="medium")


def _n14_future_dispatch_due():
	limit = add_days(today(), FUTURE_DISPATCH_LEAD_DAYS)
	rows = frappe.get_all(
		"Sales Order",
		filters={
			"custom_workflow_status": "Partial Dispatched",
			"custom_force_closed": 0,
			"custom_dispatch_date": ["<=", limit],
		},
		fields=["name", "custom_dispatch_date"],
	)
	if not rows:
		return
	recipients = _role_users(WAREHOUSE)
	for r in rows:
		_send(recipients,
			_("Reminder: remaining qty of {0} is scheduled for dispatch on {1}. Please create the Pick List.").format(r.name, r.custom_dispatch_date),
			doctype="Sales Order", docname=r.name, priority="high")


def _n21_grn_pending():
	if not frappe.db.exists("DocType", "Post Delivery"):
		return
	cutoff = add_days(today(), -GRN_PENDING_DAYS)
	rows = frappe.get_all(
		"Post Delivery",
		filters={"grn_available": 1, "grn_status": "Pending", "dispatch_date": ["<=", cutoff]},
		fields=["name", "sales_order", "dispatch_date"],
	)
	if not rows:
		return
	recipients = _role_users(ECOM_COORD) + _role_users(ECOM_MGR)
	for r in rows:
		_send(recipients,
			_("Reminder: GRN for {0} has been pending since {1}. Please follow up.").format(r.sales_order, r.dispatch_date),
			doctype="Post Delivery", docname=r.name, priority="medium")


def _n22_23_po_expiry():
	limit = add_days(today(), PO_EXPIRY_LEAD_DAYS)
	rows = frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"custom_workflow_status": ["not in", _TERMINAL],
			# NULL expiry dates never satisfy "<=", so this also excludes blank ones.
			"custom_po_expiry_date": ["<=", limit],
		},
		fields=["name", "customer_name", "custom_po_expiry_date", "custom_workflow_status"],
	)
	if not rows:
		return
	recipients = _role_users(SALES)
	td = getdate(today())
	for r in rows:
		# Legacy zero-dates ('0000-00-00') match the SQL filter but read as None.
		if not r.custom_po_expiry_date:
			continue
		expired = getdate(r.custom_po_expiry_date) < td
		if expired:
			msg = _("Expired PO: Sales Order {0} PO expired on {1}. Still in {2}. Immediate action required.").format(
				r.name, r.custom_po_expiry_date, r.custom_workflow_status)
		else:
			msg = _("PO Expiry Alert: Sales Order {0} expires on {1}. Current status: {2}.").format(
				r.name, r.custom_po_expiry_date, r.custom_workflow_status)
		_send(recipients, msg, doctype="Sales Order", docname=r.name, priority="high")
