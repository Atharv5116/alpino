"""Quarantine — hold received items out of QC and usable stock until they are released.

On the Purchase Inward, Store ticks "Quarantine Items" and then either "Quarantine Entire
Inward" or the individual lines, with one reason and one reminder interval for the lot.

At the hand-over the held lines go into a separate Purchase Quarantine document:

    some items held   Submit for QC -> Purchase Quarantine (held lines) + Purchase QC (the rest)
    every item held   Create Quarantine (replaces Submit for QC) -> Purchase Quarantine only;
                      the inward sits at Quarantined

While held, a line cannot reach QC and never reaches a receipt, so it is never in usable
stock. Store, QC or an Admin releases lines from the Quarantine document whenever they
choose, or when the reminder prompts them. A release raises a Purchase QC for exactly the
released lines, and from there they follow the normal QC -> GRN -> Purchase Invoice path:

    * the inward has no live QC yet (everything was quarantined) -> it becomes the inward's
      QC, and the inward moves on to Pending QC as usual;
    * otherwise it is a QC of its own, with its own GRN and invoice, and leaves the inward's
      first QC / GRN untouched.

Releasing marks the line Released rather than clearing the tick, so the hold stays visible
on the inward after it is lifted.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, flt, get_url_to_form, getdate, now_datetime

from alpinos.purchase import constants as C

INWARD = "Purchase Inward"
INWARD_ITEM = "Purchase Inward Item"
QUARANTINE = "Purchase Quarantine"
QC = "Purchase QC"

#: Store quarantines at receipt; Store, QC or an Admin may release.
MARK_ROLES = C.STORE_ROLES + C.ADMIN_ROLES
RELEASE_ROLES = C.STORE_ROLES + C.QC_ROLES + C.ADMIN_ROLES


# ------------------------------------------------------------------ line state


def _held(line):
	"""A line under an OPEN hold: ticked and not yet released."""
	return bool(cint(line.get("quarantine"))) and line.get("quarantine_status") != C.QUARANTINE_RELEASED


def held_lines(doc):
	"""Received lines currently held."""
	return [
		line for line in (doc.get("items") or []) if flt(line.get("received_qty")) > 0 and _held(line)
	]


def open_lines(doc):
	"""Row numbers of every line still held, in order."""
	return [line.idx for line in held_lines(doc)]


def all_received_held(doc):
	"""True when there is something received and every received line is held."""
	received = [line for line in (doc.get("items") or []) if flt(line.get("received_qty")) > 0]
	return bool(received) and all(_held(line) for line in received)


def setup_error(doc):
	"""What is still missing before a quarantine can be raised, or None."""
	if doc.get("purchase_quarantine"):
		return None
	if not cint(doc.get("quarantine_items")):
		return None
	if not held_lines(doc):
		return _("Select the items to quarantine, or tick Quarantine Entire Inward.")
	if cint(doc.get("quarantine_reminder_days")) <= 0:
		return _("Enter after how many days you want to be reminded about the quarantined items.")
	return None


def target_for_line(line, fallback):
	"""Where a line's quantity belongs: the Quarantine warehouse while it is held.

	A held line is kept off every receipt, so this is a backstop for any path that still
	reaches the GRN builder with one.
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


def apply_selection(doc):
	"""Normalise the quarantine picks on a Store Receiving save. Runs on the inward.

	Untick "Quarantine Items" and every pick is cleared; tick "Quarantine Entire Inward"
	and every received line is picked. The header reason is copied onto picked lines that
	have none. Once the Quarantine document exists the picks are history and are left alone.
	"""
	if doc.get("purchase_quarantine") or cint(doc.get("docstatus")) != 1:
		return
	if doc.get("inward_status") not in C.PI_RECEIVING_OPEN:
		return
	items = doc.get("items") or []
	if not cint(doc.get("quarantine_items")):
		doc.quarantine_entire_inward = 0
		for line in items:
			if not line.get("quarantine_status"):
				line.quarantine = 0
		return
	if cint(doc.get("quarantine_entire_inward")):
		for line in items:
			line.quarantine = 1 if flt(line.received_qty) > 0 else 0
	reason = (doc.get("quarantine_reason") or "").strip()
	for line in items:
		if cint(line.quarantine) and reason and not (line.get("quarantine_reason") or "").strip():
			line.quarantine_reason = reason


# ------------------------------------------------------------------ the document


def create_quarantine_document(inward, lines):
	"""Raise the Purchase Quarantine for `lines` and mark them held on the inward."""
	if inward.get("purchase_quarantine") and frappe.db.exists(QUARANTINE, inward.purchase_quarantine):
		return frappe.get_doc(QUARANTINE, inward.purchase_quarantine)
	if not lines:
		frappe.throw(_("No received item is marked for quarantine."))

	now = now_datetime()
	q = frappe.new_doc(QUARANTINE)
	q.purchase_inward = inward.name
	q.purchase_order = inward.get("purchase_order")
	q.supplier = inward.get("supplier")
	q.supplier_name = inward.get("supplier_name")
	q.company = inward.get("company")
	q.quarantine_date = now
	q.quarantined_by = frappe.session.user
	q.entire_inward = 1 if all_received_held(inward) else 0
	q.reason = inward.get("quarantine_reason")
	q.reminder_days = cint(inward.get("quarantine_reminder_days"))
	for line in lines:
		q.append(
			"items",
			{
				"purchase_inward_item": line.name,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"uom": line.uom,
				"qty": flt(line.received_qty),
				"batch_no": line.get("batch_no"),
				"target_warehouse": line.get("target_warehouse") or inward.get("target_warehouse"),
				"status": C.QUARANTINE_HELD,
			},
		)
	# The system raises it on the Store user's hand-over; who may do that was decided by
	# the workflow transition that called this.
	q.insert(ignore_permissions=True)

	for line in lines:
		values = {
			"quarantine": 1,
			"quarantine_status": C.QUARANTINE_HELD,
			"quarantine_date": now,
			"quarantine_reason": line.get("quarantine_reason") or inward.get("quarantine_reason"),
		}
		frappe.db.set_value(INWARD_ITEM, line.name, values, update_modified=False)
		for key, value in values.items():
			line.set(key, value)
	inward.db_set("purchase_quarantine", q.name, update_modified=False)
	return q


def _stamp_receipt(inward):
	now = now_datetime()
	inward.db_set(
		{
			"received_by": inward.get("received_by") or frappe.session.user,
			"receiving_datetime": inward.get("receiving_datetime") or now,
		},
		update_modified=False,
	)


@frappe.whitelist()
def create_quarantine(purchase_inward):
	"""Every item is quarantined: hand the inward over to quarantine instead of QC."""
	from alpinos.purchase import workflow

	inward = frappe.get_doc(INWARD, purchase_inward)
	inward.check_permission("write")
	workflow.assert_transition(inward, "create_quarantine", frappe.session.user)
	if cint(inward.docstatus) != 1:
		frappe.throw(_("Submit the Purchase Inward first."))

	frappe.db.get_value(INWARD, inward.name, "name", for_update=True)
	_stamp_receipt(inward)
	q = create_quarantine_document(inward, held_lines(inward))
	workflow.set_status(inward, C.PI_QUARANTINED)
	return {"purchase_quarantine": q.name, "inward_status": C.PI_QUARANTINED}


# ---------------------------------------------------------------------- release


def _assert_role(roles, what):
	if set(frappe.get_roles(frappe.session.user)).intersection(roles):
		return
	frappe.throw(
		_("Only the Store, QC or Admin team may {0}.").format(what),
		frappe.PermissionError,
		title=_("Not Allowed"),
	)


def _parse_rows(rows):
	if isinstance(rows, str):
		rows = json.loads(rows or "[]")
	return [r for r in (rows or []) if r]


@frappe.whitelist()
def release_items(purchase_quarantine, rows=None, remarks=None):
	"""Release the selected quarantined lines and raise their Purchase QC."""
	from alpinos.purchase import notifications, workflow
	from alpinos.purchase.settings import get_settings

	_assert_role(RELEASE_ROLES, _("release quarantined items"))
	q = frappe.get_doc(QUARANTINE, purchase_quarantine)
	q.check_permission("read")

	wanted = set(_parse_rows(rows))
	if not wanted:
		frappe.throw(_("Select the items to release."))

	inward = frappe.get_doc(INWARD, q.purchase_inward)
	if cint(inward.docstatus) != 1:
		frappe.throw(_("Purchase Inward {0} is not submitted.").format(inward.name))

	frappe.db.get_value(QUARANTINE, q.name, "name", for_update=True)
	targets = [r for r in q.get("items") or [] if r.name in wanted and r.status == C.QUARANTINE_HELD]
	if not targets:
		frappe.throw(_("None of the selected items is still quarantined."))

	inward_lines = {line.name: line for line in inward.get("items") or []}
	lines = []
	for row in targets:
		line = inward_lines.get(row.purchase_inward_item)
		if not line:
			frappe.throw(
				_("Row {0}: its Purchase Inward line no longer exists.").format(row.idx)
			)
		lines.append(line)

	main_qc = inward.get("purchase_qc")
	main_live = bool(main_qc) and frappe.db.get_value(QC, main_qc, "docstatus") != 2

	now = now_datetime()
	# Release the lines on the inward before the QC is built, so the QC sees them as
	# ordinary lines rather than held ones.
	for line in lines:
		frappe.db.set_value(
			INWARD_ITEM,
			line.name,
			{"quarantine_status": C.QUARANTINE_RELEASED, "quarantine_date": now},
			update_modified=False,
		)
		line.quarantine_status = C.QUARANTINE_RELEASED

	qc = notifications.build_purchase_qc(
		inward, lines, sla_start=now, purchase_quarantine=q.name
	)

	remarks = (remarks or "").strip() or None
	for row in targets:
		row.status = C.QUARANTINE_RELEASED
		row.released_on = now
		row.released_by = frappe.session.user
		row.release_remarks = remarks
		row.purchase_qc = qc.name
	q.flags.ignore_permissions = True
	q.save()

	if not main_live:
		# Everything had been quarantined, so this QC is the inward's own: the inward picks up
		# the ordinary QC -> GRN -> Invoice path from here.
		inward.db_set({"purchase_qc": qc.name, "qc_status": C.QC_PENDING}, update_modified=False)
		if inward.inward_status in (C.PI_QUARANTINED, C.PI_PENDING_RECEIPT):
			workflow.set_status(inward, C.PI_PENDING_QC)

	if cint(get_settings(inward.company).get("notify_qc_on_submit")):
		notifications.notify_qc_team(qc, inward)

	return {
		"purchase_qc": qc.name,
		"released": [row.name for row in targets],
		"status": q.status,
		"inward_qc": not main_live,
	}


def revert_release(qc):
	"""A cancelled release-QC puts its lines back under quarantine, so they can be released again."""
	if not qc.get("purchase_quarantine") or not frappe.db.exists(QUARANTINE, qc.purchase_quarantine):
		return
	q = frappe.get_doc(QUARANTINE, qc.purchase_quarantine)
	now = now_datetime()
	touched = []
	for row in q.get("items") or []:
		if row.purchase_qc != qc.name:
			continue
		row.status = C.QUARANTINE_HELD
		row.purchase_qc = None
		row.released_on = None
		row.released_by = None
		row.release_remarks = None
		touched.append(row.purchase_inward_item)
	if not touched:
		return
	q.flags.ignore_permissions = True
	q.save()
	for name in touched:
		if name and frappe.db.exists(INWARD_ITEM, name):
			frappe.db.set_value(
				INWARD_ITEM,
				name,
				{"quarantine_status": C.QUARANTINE_HELD, "quarantine_date": now},
				update_modified=False,
			)


# ----------------------------------------------------------------- screen helpers


@frappe.whitelist()
def update_reminder(purchase_quarantine, reminder_days):
	"""Change after how many days the Quarantine document reminds the teams."""
	_assert_role(RELEASE_ROLES, _("change the quarantine reminder"))
	q = frappe.get_doc(QUARANTINE, purchase_quarantine)
	q.check_permission("read")
	q.reminder_days = cint(reminder_days)
	q.flags.ignore_permissions = True
	q.save()
	return {"reminder_days": q.reminder_days, "next_reminder_on": q.next_reminder_on}


@frappe.whitelist()
def get_quarantine_context(purchase_quarantine):
	"""What the Quarantine screen may offer."""
	q = frappe.get_doc(QUARANTINE, purchase_quarantine)
	q.check_permission("read")
	may = bool(set(frappe.get_roles()).intersection(RELEASE_ROLES))
	held = [r.name for r in q.get("items") or [] if r.status == C.QUARANTINE_HELD]
	# "Go to QC" offers every QC these goods touch: the QC each release raised, and the
	# inward's own QC that took the items which were never quarantined.
	qcs = {}
	for row in q.get("items") or []:
		if row.purchase_qc and row.purchase_qc not in qcs:
			qcs[row.purchase_qc] = "released"
	main_qc = frappe.db.get_value(INWARD, q.purchase_inward, "purchase_qc")
	if main_qc and main_qc not in qcs:
		qcs[main_qc] = "inward"
	return {
		"can_release": may and bool(held),
		"can_edit_reminder": may and q.status != C.QRN_RELEASED,
		"held_rows": held,
		"purchase_qcs": [
			{
				"name": name,
				"source": source,
				"qc_status": frappe.db.get_value(QC, name, "qc_status"),
				"purchase_receipt": frappe.db.get_value(QC, name, "purchase_receipt"),
			}
			for name, source in qcs.items()
			if frappe.db.exists(QC, name)
		],
		"inward_status": frappe.db.get_value(INWARD, q.purchase_inward, "inward_status"),
	}


@frappe.whitelist()
def status(purchase_inward):
	"""Quarantine state of an inward, for its screen."""
	doc = frappe.get_doc(INWARD, purchase_inward)
	doc.check_permission("read")
	roles = set(frappe.get_roles(frappe.session.user))
	held = open_lines(doc)
	return {
		"held_rows": held,
		"any_held": bool(held),
		"all_held": all_received_held(doc),
		"purchase_quarantine": doc.get("purchase_quarantine"),
		"may_mark": bool(roles.intersection(MARK_ROLES)),
		"may_release": bool(roles.intersection(RELEASE_ROLES)),
		"warehouse": warehouse_name(doc.get("company")),
	}


# -------------------------------------------------------------------- reminders


def _recipients(q):
	from alpinos.raven_notifications import _role_users

	users = []
	for role in RELEASE_ROLES:
		for user in _role_users(role) or []:
			if user not in users:
				users.append(user)
	if q.get("quarantined_by") and q.quarantined_by not in users:
		users.append(q.quarantined_by)
	return users


def send_quarantine_reminders():
	"""Scheduler (daily): remind the teams about quarantines that are due for review.

	Each document reminds on its own interval and then schedules the next reminder, until
	every item is released. Best effort: a failed alert never stops the others.
	"""
	if not frappe.db.exists("DocType", QUARANTINE):
		return
	today = getdate()
	due = frappe.get_all(
		QUARANTINE,
		filters={
			"status": ["in", [C.QRN_QUARANTINED, C.QRN_PARTIALLY_RELEASED]],
			"reminder_days": [">", 0],
			"next_reminder_on": ["<=", today],
		},
		pluck="name",
	)
	for name in due:
		q = frappe.get_doc(QUARANTINE, name)
		held = [r for r in q.get("items") or [] if r.status == C.QUARANTINE_HELD]
		subject = _("Quarantine review due: {0} ({1} item(s) still held, Purchase Inward {2})").format(
			q.name, len(held), q.purchase_inward
		)
		users = _recipients(q)
		try:
			from alpinos.so_notifications import _send

			_send(users, subject, doctype=QUARANTINE, docname=q.name, priority="high")
		except Exception:
			frappe.log_error(title="Quarantine reminder (bell) failed", message=frappe.get_traceback())
		try:
			from alpinos.purchase.notifications import _emails

			emails = _emails(users)
			if emails:
				lines = "".join(
					f"<li>{escape_html(r.item_code or '')} — {flt(r.qty):g} {escape_html(r.uom or '')}</li>"
					for r in held
				)
				frappe.sendmail(
					recipients=emails,
					subject=subject,
					message=(
						f"<p>{escape_html(subject)}</p><ul>{lines}</ul>"
						f"<p><a href='{escape_html(get_url_to_form(QUARANTINE, q.name))}'>"
						f"{escape_html(_('Open the Quarantine document'))}</a></p>"
					),
				)
		except Exception:
			frappe.log_error(title="Quarantine reminder (email) failed", message=frappe.get_traceback())
		q.db_set(
			{
				"last_reminder_on": now_datetime(),
				"next_reminder_on": add_days(today, cint(q.reminder_days)),
			},
			update_modified=False,
		)
	if due:
		frappe.db.commit()
