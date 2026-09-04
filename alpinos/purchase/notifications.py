"""QC handoff: the Submit-for-QC transition, the QC team notification and the SLA sweep.

BRD "Purchase Inward Part -1" 4.10:

	BR-QC-01  the inward appears in the QC queue as soon as Store submits the receipt
	BR-QC-02  the QC team is notified on that handoff
	BR-QC-03  a 2-hour QC SLA runs from the handoff timestamp
	BR-QC-04  past the SLA, alert the department every 30 minutes until QC completes

The SLA clock lives on the Purchase QC document (sla_start / sla_due / sla_breached /
last_escalation_on) and its two intervals come from Purchase Inward Settings, so a site can
retune both without a code change.

Notifications follow the house convention: an in-app Notification Log plus a Raven DM via
`alpinos.so_notifications._send`, and an HTML mail built with `escape_html` in the shape
`alpinos.attendance_alerts` uses. Both channels are best-effort — a role with no enabled
users produces no alert and no error, which is why the SLA state is written to the document
before anything is sent.

Registered in alpinos/hooks.py (owned by the orchestrator):

	scheduler_events["cron"]["*/5 * * * *"] -> alpinos.purchase.notifications.run_qc_sla_escalation

Manual run: bench --site <site> execute alpinos.purchase.notifications.run_qc_sla_escalation
"""

import frappe
from frappe import _
from frappe.utils import (
	add_to_date,
	cint,
	escape_html,
	flt,
	get_datetime,
	get_url_to_form,
	now_datetime,
	time_diff_in_seconds,
)

from alpinos.purchase import constants as C
from alpinos.purchase import workflow
from alpinos.purchase.settings import escalation_minutes, get_settings, notification_roles, sla_hours

QC_DOCTYPE = "Purchase QC"

# QC is finished — or was never going to happen — so the SLA stops running.
_SLA_CLOSED = (C.QC_COMPLETED, C.QC_CANCELLED)


# ------------------------------------------------- 302: submit for QC ------


@frappe.whitelist()
def submit_for_qc(purchase_inward):
	"""Hand a received Purchase Inward to QC (BRD 2.3 "Submit for QC", BR-QC-01/02/03).

	Stamps the receipt, raises the Purchase QC in Draft, starts the SLA clock and notifies.
	Re-running is a no-op that returns the same QC: BR-QC-01 gives an inward one QC, and a
	double-clicked button must not raise a second one.
	"""
	inward = frappe.get_doc("Purchase Inward", purchase_inward)
	inward.check_permission("write")
	workflow.assert_transition(inward, "submit_for_qc", frappe.session.user)

	if inward.docstatus != 1:
		frappe.throw(_("Submit the Purchase Inward before handing it over to QC."))

	now = now_datetime()
	inward.db_set(
		{
			"received_by": inward.received_by or frappe.session.user,
			"receiving_datetime": inward.receiving_datetime or now,
		},
		update_modified=False,
	)

	qc, created = _ensure_purchase_qc(inward)

	inward.db_set(
		{"purchase_qc": qc.name, "qc_status": C.QC_PENDING}, update_modified=False
	)
	workflow.set_status(inward, C.PI_PENDING_QC)

	if created and cint(get_settings(inward.company).get("notify_qc_on_submit")):
		notify_qc_team(qc, inward)

	return {
		"purchase_qc": qc.name,
		"inward_status": C.PI_PENDING_QC,
		"qc_status": C.QC_PENDING,
		"sla_start": qc.sla_start,
		"sla_due": qc.sla_due,
	}


def _ensure_purchase_qc(inward):
	"""(Purchase QC, created?) for this inward. A cancelled QC does not count.

	The row lock serialises two concurrent handoffs on the inward; without it both read
	"no QC yet" and both insert, and BR-QC-01's one-QC-per-inward quietly stops holding.
	"""
	frappe.db.get_value("Purchase Inward", inward.name, "name", for_update=True)
	found = frappe.get_all(
		QC_DOCTYPE,
		filters={"purchase_inward": inward.name, "docstatus": ("<", 2)},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	if found:
		return frappe.get_doc(QC_DOCTYPE, found[0]), False

	# BR-QC-03: the clock starts at the handoff, not when a QC user opens the document.
	start = get_datetime(inward.receiving_datetime or now_datetime())
	minutes = int(round(flt(sla_hours(inward.company)) * 60))

	qc = frappe.new_doc(QC_DOCTYPE)
	qc.purchase_inward = inward.name
	qc.supplier = inward.supplier
	qc.supplier_name = inward.supplier_name
	qc.supplier_order_no = inward.supplier_order_no
	qc.invoice_number = inward.invoice_number
	qc.inward_type = inward.inward_type
	qc.company = inward.company
	qc.received_qty = flt(inward.total_received_qty)
	qc.qc_status = C.QC_PENDING
	qc.qc_result = C.QC_RESULT_PENDING
	qc.sla_start = start
	qc.sla_due = add_to_date(start, minutes=minutes)
	qc.sla_breached = 0
	# `inspector` / `inspection_date` default to __user / Now — the Store user handing over
	# and the handoff second, not the QC user or the moment of inspection (BRD 4.1.1). Both
	# stay blank on a Pending QC row (BRD 3.1); purchase_qc.start_qc stamps them when a QC
	# user actually picks the job up. Clearing inspection_date matters too: leaving it set
	# made start_qc's `if not qc.inspection_date` stamp unreachable.
	qc.inspector = None
	qc.inspection_date = None

	for line in inward.get("items") or []:
		if flt(line.received_qty) <= 0:
			continue
		qc.append(
			"items",
			{
				"item_code": line.item_code,
				"item_name": line.item_name,
				"uom": line.uom,
				"received_qty": flt(line.received_qty),
				"manufacturing_date": line.manufacturing_date,
				"expiry_date": line.expiry_date,
				"target_warehouse": line.target_warehouse or inward.target_warehouse,
				"quarantine": cint(line.quarantine),
				"qc_result": C.QC_RESULT_PENDING,
				"po_detail": line.po_detail,
				# Purchase Inward Item autonames by hash, so the row name is the only
				# identity that survives a PO with two rows of the same item.
				"purchase_inward_item": line.name,
			},
		)

	if not qc.get("items"):
		frappe.throw(_("No received quantity to hand over to QC."))

	qc.total_received_qty = flt(inward.total_received_qty)

	# The system raises the QC, not the Store user: the DocPerm matrix gives Store read-only
	# access to Purchase QC on purpose (BRD "User Roles"), and who may trigger this handoff
	# was already decided by assert_transition above.
	qc.insert(ignore_permissions=True)
	return qc, True


# ------------------------------------------------- BR-QC-02 notification ---


def _hours(company=None):
	"""SLA hours rendered for humans — 2 rather than 2.0, 1.5 kept as 1.5."""
	hours = flt(sla_hours(company))
	return int(hours) if hours == int(hours) else hours


def qc_recipients(company=None):
	"""Enabled users holding any of the configured QC notification roles."""
	from alpinos.raven_notifications import _role_users

	out = []
	for role in notification_roles(company):
		for user in _role_users(role) or []:
			if user not in out:
				out.append(user)
	return out


def notify_qc_team(qc, inward=None):
	"""BR-QC-02 — tell QC a new inward is waiting, and by when."""
	subject = _("QC pending: Purchase Inward {0} handed over by Store").format(qc.purchase_inward)
	intro = _(
		"A new Purchase Inward has been handed over for quality inspection. "
		"The {0}-hour QC SLA is running."
	).format(_hours(qc.company))
	_dispatch(qc, subject, intro, inward=inward, priority="high")


def _notify_sla_breach(qc, overdue_minutes, first):
	"""BR-QC-04 — the breach alert and every escalation after it."""
	if first:
		subject = _("QC SLA breached: Purchase Inward {0}").format(qc.purchase_inward)
	else:
		subject = _("QC still pending: Purchase Inward {0} is {1} minutes overdue").format(
			qc.purchase_inward, overdue_minutes
		)
	intro = _(
		"Quality inspection has not been completed within the SLA. This inward is "
		"{0} minutes overdue and will be escalated every {1} minutes until QC is completed."
	).format(overdue_minutes, escalation_minutes(qc.company))
	_dispatch(qc, subject, intro, priority="high")


def _dispatch(qc, subject, intro, inward=None, priority="medium"):
	"""One alert on both house channels. Never raises — a failed alert must not roll back
	the transition or the SLA watermark that produced it."""
	recipients = qc_recipients(qc.company)
	if not recipients:
		return

	try:
		from alpinos.so_notifications import _send

		_send(recipients, subject, doctype=QC_DOCTYPE, docname=qc.name, priority=priority)
	except Exception:
		frappe.log_error(title="Purchase QC alert (bell) failed", message=frappe.get_traceback())

	emails = _emails(recipients)
	if not emails:
		return
	try:
		frappe.sendmail(recipients=emails, subject=subject, message=_message(qc, intro, inward))
	except Exception:
		frappe.log_error(title="Purchase QC alert (email) failed", message=frappe.get_traceback())


def _emails(users):
	"""Enabled, real email addresses for a list of user ids."""
	out, seen = [], set()
	for user in users:
		if not user or user in seen or user in ("Administrator", "Guest"):
			continue
		seen.add(user)
		row = frappe.db.get_value("User", user, ["enabled", "email"], as_dict=True)
		if row and row.enabled and row.email:
			out.append(row.email)
	return out


def _message(qc, intro, inward=None):
	if inward is None and qc.purchase_inward:
		inward = frappe.db.get_value(
			"Purchase Inward",
			qc.purchase_inward,
			["purchase_order", "invoice_number", "supplier_name", "total_received_qty"],
			as_dict=True,
		)
	inward = inward or {}
	link = get_url_to_form(QC_DOCTYPE, qc.name)

	rows = [
		(_("Purchase QC"), qc.name),
		(_("Purchase Inward"), qc.purchase_inward),
		(_("Purchase Order"), inward.get("purchase_order")),
		(_("Vendor"), qc.supplier_name or inward.get("supplier_name")),
		(_("Invoice Number"), qc.invoice_number or inward.get("invoice_number")),
		(_("Received Qty"), flt(qc.received_qty) or flt(inward.get("total_received_qty"))),
		(_("SLA Start"), qc.sla_start),
		(_("SLA Due"), qc.sla_due),
	]

	th = "padding:6px 10px;border:1px solid #e5e7eb;text-align:left;background:#f9fafb;"
	td = "padding:6px 10px;border:1px solid #e5e7eb;"
	body = ""
	for label, value in rows:
		body += (
			"<tr>"
			f"<th style='{th}'>{escape_html(str(label))}</th>"
			f"<td style='{td}'>{escape_html(str(value if value not in (None, '') else '—'))}</td>"
			"</tr>"
		)

	return (
		f"<p>{escape_html(intro)}</p>"
		"<table style='border-collapse:collapse;font-size:13px;'>"
		f"<tbody>{body}</tbody></table>"
		f"<p style='margin-top:12px;'><a href='{escape_html(link)}'>{escape_html(_('Open the Purchase QC'))}</a></p>"
		"<p style='color:#6b7280;font-size:12px;margin-top:12px;'>"
		"Automated Purchase Inward alert from Alpinos.</p>"
	)


# ---------------------------------------- BR-QC-03 / BR-QC-04 SLA sweep ----


def run_qc_sla_escalation():
	"""Scheduler entry: breach every overdue Purchase QC and re-alert on the interval.

	Runs as Administrator, so `get_all` deliberately sees every QC regardless of role.
	Never reuse this from a whitelisted endpoint without re-checking permissions.
	"""
	if not frappe.db.exists("DocType", QC_DOCTYPE):
		return 0

	now = now_datetime()
	rows = frappe.get_all(
		QC_DOCTYPE,
		filters={
			# The QC is still Draft until the decision is submitted; a submitted or
			# cancelled one has nothing left to escalate.
			"docstatus": 0,
			"sla_due": ("<", now),
			"qc_status": ("not in", list(_SLA_CLOSED)),
		},
		fields=["name", "purchase_inward", "sla_due", "sla_breached", "last_escalation_on"],
		limit_page_length=0,
	)

	# Purchase Inward Settings is a Single, so the interval is the same for every row —
	# read it once rather than per document.
	interval = escalation_minutes()

	sent = 0
	for row in rows:
		try:
			if _escalate(row, now, interval):
				sent += 1
		except Exception:
			frappe.log_error(
				title="Purchase QC SLA escalation failed", message=frappe.get_traceback()
			)
	return sent


def _escalate(row, now, interval):
	"""Mark the breach and alert, unless the interval has not elapsed yet."""
	first = not cint(row.sla_breached)
	if not first:
		last = get_datetime(row.last_escalation_on or row.sla_due)
		if now < add_to_date(last, minutes=interval):
			return False

	# Watermark BEFORE the send. This app has no scheduler lock of any kind, so
	# last_escalation_on IS the throttle; writing it after a slow send lets the next tick
	# fire the same alert again. sla_breached / last_escalation_on / qc_status are
	# allow_on_submit, so they are written with db.set_value rather than a save.
	updates = {"last_escalation_on": now}
	if first:
		updates["sla_breached"] = 1
		updates["qc_status"] = C.QC_SLA_BREACHED
	frappe.db.set_value(QC_DOCTYPE, row.name, updates, update_modified=False)
	if first and row.purchase_inward:
		frappe.db.set_value(
			"Purchase Inward",
			row.purchase_inward,
			"qc_status",
			C.QC_SLA_BREACHED,
			update_modified=False,
		)
	frappe.db.commit()

	overdue = int(max(time_diff_in_seconds(now, row.sla_due), 0) // 60)
	_notify_sla_breach(frappe.get_doc(QC_DOCTYPE, row.name), overdue, first)
	return True
