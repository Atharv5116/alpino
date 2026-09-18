"""Quarantine — hold QC-approved stock in the Quarantine warehouse until it is released.

QC decides it. On the Purchase QC, QC ticks the lines to hold in the Quarantine column of
the QC Decision table, with one reason and one reminder interval for the lot ("Quarantine
Items" is derived from those ticks). What is held is the line's approved quantity; the rejected
quantity goes to the Rejected warehouse and the debit note exactly as without quarantine.

When the QC is completed:

    * the Draft GRN receives a quarantined line into the Quarantine warehouse, marks it
      Quarantined and records the warehouse it belongs in (custom_release_warehouse);
      every other line is received into its warehouse as usual;
    * one Purchase Quarantine document holds the quarantined lines and the reminder.

So submitting the GRN puts the quarantined quantity into stock, but only in the Quarantine
warehouse, out of use. The Purchase Invoice bills the GRN as usual.

Release (Store, QC or Admin, from the Quarantine document) moves a line to its warehouse:

    GRN still Draft   the draft line is re-pointed at its warehouse, so the GRN receives it
                      there directly when it is submitted;
    GRN submitted     a Material Transfer moves the whole quantity from the Quarantine
                      warehouse into its warehouse.

Release is the only way out; there is no reject from quarantine.

Older flow (before quarantine moved to QC): Store marked items on the Purchase Inward, those
lines were kept out of QC, and releasing one raised a Purchase QC of its own. Documents
raised that way have no purchase_qc; release_items still releases them the old way so they
can be finished, and nothing creates new ones.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, flt, get_url_to_form, getdate, now_datetime

from alpinos.purchase import constants as C

INWARD = "Purchase Inward"
INWARD_ITEM = "Purchase Inward Item"
QUARANTINE = "Purchase Quarantine"
QUARANTINE_ITEM = "Purchase Quarantine Item"
QC = "Purchase QC"
GRN = "Purchase Receipt"
GRN_ITEM = "Purchase Receipt Item"

#: QC quarantines while deciding; Store, QC or an Admin may release.
MARK_ROLES = C.QC_ROLES + C.ADMIN_ROLES
RELEASE_ROLES = C.STORE_ROLES + C.QC_ROLES + C.ADMIN_ROLES


def warehouse_name(company=None):
	"""The provisioned Quarantine warehouse for the document company."""
	from alpinos.purchase.settings import warehouse as settings_warehouse

	try:
		return settings_warehouse(C.WH_QUARANTINE, company)
	except Exception:
		return None


# ============================================================ QC quarantine (current)


def held_qty(line):
	"""What a quarantined QC line holds: its whole approved quantity (samples move no stock)."""
	return flt(line.get("approved_qty"))


def apply_qc_selection(qc):
	"""Normalise the picks while the QC is a draft. Runs in PurchaseQC.validate.

	QC ticks the items to hold in the Quarantine column of the decision table. "Quarantine
	Items" is derived from those ticks, never typed.
	"""
	if cint(qc.get("docstatus")) != 0:
		return
	lines = qc.get("items") or []
	qc.quarantine_all_items = 0
	qc.quarantine_items = 1 if any(cint(line.quarantine) for line in lines) else 0


def assert_qc_ready(qc):
	"""Before the QC is submitted: a quarantine that is asked for must be complete."""
	if not cint(qc.get("quarantine_items")):
		return
	picked = [line for line in qc.get("items") or [] if cint(line.quarantine)]
	if not picked:
		frappe.throw(
			_("Tick the items to quarantine in the Quarantine column of the QC Decision table."),
			title=_("Quarantine"),
		)
	if cint(qc.get("quarantine_reminder_days")) <= 0:
		frappe.throw(
			_("Enter after how many days you want to be reminded about the quarantined items."),
			title=_("Quarantine"),
		)
	if not warehouse_name(qc.get("company")):
		frappe.throw(
			_("The Quarantine warehouse is not set in Purchase Inward Settings, so nothing can be quarantined."),
			title=_("Quarantine"),
		)
	for line in picked:
		if held_qty(line) <= 0:
			frappe.throw(
				_("Row {0} ({1}): nothing is approved, so there is nothing to quarantine. Untick it.").format(
					line.idx, line.item_code
				),
				title=_("Quarantine"),
			)


def qc_line_state(qc, line):
	"""Quarantined / Released / None for one QC decision line, for the GRN builder.

	A ticked line on a completed QC is Quarantined until its Quarantine row says otherwise;
	the Quarantine document itself is raised a moment after the GRN, in the same submit.
	"""
	if not qc or cint(qc.get("docstatus")) != 1 or not cint(line.get("quarantine")):
		return None
	if not cint(qc.get("quarantine_items")):
		return None
	status = frappe.db.get_value(QUARANTINE_ITEM, {"purchase_qc_item": line.name}, "status")
	return status or C.QUARANTINE_HELD


def create_from_qc(qc):
	"""Raise the Purchase Quarantine for a just-submitted QC. Runs in PurchaseQC.on_submit."""
	if not cint(qc.get("quarantine_items")):
		return None
	lines = [line for line in qc.get("items") or [] if cint(line.quarantine)]
	if not lines:
		return None
	if qc.get("quarantine_document") and frappe.db.exists(QUARANTINE, qc.quarantine_document):
		return frappe.get_doc(QUARANTINE, qc.quarantine_document)

	inward = frappe.get_doc(INWARD, qc.purchase_inward)
	inward_lines = {line.name: line for line in inward.get("items") or []}
	store = warehouse_name(qc.company)
	approved = [line for line in qc.get("items") or [] if flt(line.approved_qty) > 0]

	q = frappe.new_doc(QUARANTINE)
	q.purchase_inward = inward.name
	q.purchase_qc = qc.name
	q.purchase_order = inward.get("purchase_order")
	q.supplier = inward.get("supplier")
	q.supplier_name = inward.get("supplier_name")
	q.company = qc.company
	q.quarantine_date = now_datetime()
	q.quarantined_by = frappe.session.user
	q.entire_inward = 1 if len(lines) == len(approved) else 0
	q.reason = qc.get("quarantine_reason")
	q.reminder_days = cint(qc.get("quarantine_reminder_days"))
	for line in lines:
		src = inward_lines.get(line.purchase_inward_item)
		q.append(
			"items",
			{
				"purchase_inward_item": line.purchase_inward_item,
				"purchase_qc_item": line.name,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"uom": line.uom,
				"qty": held_qty(line),
				"batch_no": line.get("internal_batch_no") or (src.get("batch_no") if src else None),
				"target_warehouse": line.get("target_warehouse")
				or (src.get("target_warehouse") if src else None)
				or inward.get("target_warehouse"),
				"quarantine_warehouse": store,
				"status": C.QUARANTINE_HELD,
			},
		)
	# The system raises it as part of completing the QC; who may complete a QC was decided
	# by the workflow transition that submitted it.
	q.insert(ignore_permissions=True)

	qc.db_set("quarantine_document", q.name, update_modified=False)
	receipt = qc.get("purchase_receipt")
	if receipt and frappe.db.exists(GRN, receipt):
		frappe.db.set_value(GRN, receipt, "custom_purchase_quarantine", q.name, update_modified=False)
	if not inward.get("purchase_quarantine"):
		inward.db_set("purchase_quarantine", q.name, update_modified=False)
	return q


def assert_grn_cancellable(pr):
	"""A GRN whose quarantined stock was already moved out cannot be cancelled first.

	Cancelling it would take that quantity back out of the Quarantine warehouse, where it no
	longer is. Say which transfers to cancel instead of failing with a negative-stock error.
	"""
	name = pr.get("custom_purchase_quarantine")
	if not name or not frappe.db.exists(QUARANTINE, name):
		return
	moved = [
		row.release_stock_entry
		for row in frappe.get_doc(QUARANTINE, name).get("items") or []
		if row.get("release_stock_entry")
		and frappe.db.get_value("Stock Entry", row.release_stock_entry, "docstatus") == 1
	]
	if moved:
		frappe.throw(
			_(
				"Quarantined items on this GRN were already released into their warehouse by {0}. "
				"Cancel those Stock Entries first."
			).format(", ".join(frappe.bold(m) for m in moved)),
			title=_("Released From Quarantine"),
		)


def on_qc_cancel(qc):
	"""A cancelled QC takes its quarantine with it; a fresh QC decides again."""
	name = qc.get("quarantine_document")
	if not name or not frappe.db.exists(QUARANTINE, name):
		return
	q = frappe.get_doc(QUARANTINE, name)
	moved = [
		row.release_stock_entry
		for row in q.get("items") or []
		if row.get("release_stock_entry")
		and frappe.db.get_value("Stock Entry", row.release_stock_entry, "docstatus") == 1
	]
	if moved:
		frappe.throw(
			_("Items of Quarantine Document {0} were released by {1}. Cancel those Stock Entries first.").format(
				name, ", ".join(moved)
			)
		)
	if frappe.db.get_value(INWARD, q.purchase_inward, "purchase_quarantine") == name:
		frappe.db.set_value(INWARD, q.purchase_inward, "purchase_quarantine", None, update_modified=False)
	for receipt in frappe.get_all(GRN, filters={"custom_purchase_quarantine": name}, pluck="name"):
		frappe.db.set_value(GRN, receipt, "custom_purchase_quarantine", None, update_modified=False)
	qc.db_set("quarantine_document", None, update_modified=False)
	frappe.delete_doc(QUARANTINE, name, force=True, ignore_permissions=True)


def _release_from_qc(q, targets, remarks):
	"""Move released lines into their warehouse: re-point the draft GRN, or transfer the stock."""
	qc = frappe.get_doc(QC, q.purchase_qc)
	receipt = qc.get("purchase_receipt")
	if not receipt or frappe.db.get_value(GRN, receipt, "docstatus") in (None, 2):
		frappe.throw(
			_("Purchase QC {0} has no live GRN, so there is no stock to release. Generate or amend its GRN first.").format(
				qc.name
			),
			title=_("No GRN"),
		)
	pr = frappe.get_doc(GRN, receipt)
	by_inward_item = {r.get("custom_purchase_inward_item"): r for r in pr.get("items") or []}
	pairs = []
	for row in targets:
		pr_row = by_inward_item.get(row.purchase_inward_item)
		if not pr_row:
			frappe.throw(_("Row {0}: {1} is not on GRN {2}.").format(row.idx, row.item_code, pr.name))
		pairs.append((row, pr_row))

	entries = {}
	if cint(pr.docstatus) == 0:
		for row, pr_row in pairs:
			pr_row.warehouse = pr_row.get("custom_release_warehouse") or row.target_warehouse
			pr_row.custom_quarantine_status = C.QUARANTINE_RELEASED
		# The Quarantine document moving its own lines, not a person editing the draft: kept
		# out of the Draft Edit Log and past the quarantined-line guard.
		pr.flags.grn_system_sync = True
		pr.flags.ignore_permissions = True
		pr.save()
	else:
		for row, pr_row in pairs:
			entries[row.name] = _transfer_out_of_quarantine(q, qc, pr, pr_row, row, remarks)
			frappe.db.set_value(
				GRN_ITEM, pr_row.name, "custom_quarantine_status", C.QUARANTINE_RELEASED, update_modified=False
			)
	return entries


def _grn_row_batch(pr_row):
	if pr_row.get("batch_no"):
		return pr_row.batch_no
	if pr_row.get("serial_and_batch_bundle"):
		return frappe.db.get_value(
			"Serial and Batch Entry", {"parent": pr_row.serial_and_batch_bundle}, "batch_no", order_by="idx asc"
		)
	return None


def _transfer_out_of_quarantine(q, qc, pr, pr_row, row, remarks):
	"""Post the Material Transfer that releases one submitted GRN line."""
	store = pr_row.warehouse
	target = pr_row.get("custom_release_warehouse") or row.target_warehouse
	if not target or target == store:
		frappe.throw(_("Row {0}: {1} has no warehouse to be released into.").format(row.idx, row.item_code))

	factor = flt(pr_row.conversion_factor) or 1.0
	# The whole quantity the GRN received into the Quarantine warehouse.
	stock_qty = flt(pr_row.stock_qty) or flt(pr_row.qty) * factor
	if stock_qty <= 0:
		frappe.throw(_("Row {0}: nothing of {1} is left in quarantine to release.").format(row.idx, row.item_code))

	stock_uom = frappe.get_cached_value("Item", row.item_code, "stock_uom")
	batch_no = _grn_row_batch(pr_row)
	if batch_no:
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		available = flt(get_batch_qty(batch_no=batch_no, warehouse=store))
	else:
		# The ledger, not Bin: Bin can trail the sample transfer the GRN submit just posted.
		from erpnext.stock.utils import get_stock_balance

		available = flt(get_stock_balance(row.item_code, store))
	if available + 1e-6 < stock_qty:
		frappe.throw(
			_("Row {0}: only {1} {2} of {3} is in {4}, so {5} cannot be released.").format(
				row.idx, flt(available), stock_uom, row.item_code, store, flt(stock_qty)
			),
			title=_("Not In Quarantine"),
		)

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = pr.company
	entry.remarks = _("Released from Quarantine Document {0} (GRN {1}).{2}").format(
		q.name, pr.name, (" " + remarks) if remarks else ""
	)
	entry.append(
		"items",
		{
			"item_code": row.item_code,
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": 1.0,
			"qty": stock_qty,
			"s_warehouse": store,
			"t_warehouse": target,
			"use_serial_batch_fields": 1 if batch_no else 0,
			"batch_no": batch_no,
		},
	)
	# The release role is the gate (release_items); Store and QC hold no Stock Entry or
	# Account permission of their own, and the ledger lookups check Account read.
	entry.flags.ignore_permissions = True
	previous = frappe.flags.ignore_account_permission
	frappe.flags.ignore_account_permission = True
	try:
		entry.insert()
		entry.submit()
	finally:
		frappe.flags.ignore_account_permission = previous
	return entry.name


# ================================================================ release (both)


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
	"""Release the selected quarantined lines into their warehouse."""
	_assert_role(RELEASE_ROLES, _("release quarantined items"))
	q = frappe.get_doc(QUARANTINE, purchase_quarantine)
	q.check_permission("read")

	wanted = set(_parse_rows(rows))
	if not wanted:
		frappe.throw(_("Select the items to release."))

	frappe.db.get_value(QUARANTINE, q.name, "name", for_update=True)
	targets = [r for r in q.get("items") or [] if r.name in wanted and r.status == C.QUARANTINE_HELD]
	if not targets:
		frappe.throw(_("None of the selected items is still quarantined."))

	remarks = (remarks or "").strip() or None
	if not q.get("purchase_qc"):
		return _release_older_flow(q, targets, remarks)

	entries = _release_from_qc(q, targets, remarks)
	now = now_datetime()
	for row in targets:
		row.status = C.QUARANTINE_RELEASED
		row.released_on = now
		row.released_by = frappe.session.user
		row.release_remarks = remarks
		row.release_stock_entry = entries.get(row.name)
	q.flags.ignore_permissions = True
	q.save()
	return {
		"released": [row.name for row in targets],
		"stock_entries": [e for e in entries.values() if e],
		"purchase_receipt": frappe.db.get_value(QC, q.purchase_qc, "purchase_receipt"),
		"status": q.status,
	}


# ============================================================== older flow (inward)


def _held(line):
	"""An inward line under an older-flow hold: ticked and not yet released."""
	return bool(cint(line.get("quarantine"))) and line.get("quarantine_status") == C.QUARANTINE_HELD


def held_lines(doc):
	"""Received inward lines still held by an older-flow Quarantine document."""
	return [
		line for line in (doc.get("items") or []) if flt(line.get("received_qty")) > 0 and _held(line)
	]


def all_received_held(doc):
	received = [line for line in (doc.get("items") or []) if flt(line.get("received_qty")) > 0]
	return bool(received) and all(_held(line) for line in received)


def target_for_line(line, fallback):
	"""Backstop for the older flow: an inward line still held never reaches usable stock."""
	if not _held(line):
		return fallback
	return warehouse_name() or fallback


def _release_older_flow(q, targets, remarks):
	"""Release lines quarantined on the inward: they get a Purchase QC of their own."""
	from alpinos.purchase import notifications, workflow
	from alpinos.purchase.settings import get_settings

	inward = frappe.get_doc(INWARD, q.purchase_inward)
	if cint(inward.docstatus) != 1:
		frappe.throw(_("Purchase Inward {0} is not submitted.").format(inward.name))

	inward_lines = {line.name: line for line in inward.get("items") or []}
	lines = []
	for row in targets:
		line = inward_lines.get(row.purchase_inward_item)
		if not line:
			frappe.throw(_("Row {0}: its Purchase Inward line no longer exists.").format(row.idx))
		lines.append(line)

	main_qc = inward.get("purchase_qc")
	main_live = bool(main_qc) and frappe.db.get_value(QC, main_qc, "docstatus") != 2

	now = now_datetime()
	for line in lines:
		frappe.db.set_value(
			INWARD_ITEM,
			line.name,
			{"quarantine_status": C.QUARANTINE_RELEASED, "quarantine_date": now},
			update_modified=False,
		)
		line.quarantine_status = C.QUARANTINE_RELEASED

	qc = notifications.build_purchase_qc(inward, lines, sla_start=now, purchase_quarantine=q.name)

	for row in targets:
		row.status = C.QUARANTINE_RELEASED
		row.released_on = now
		row.released_by = frappe.session.user
		row.release_remarks = remarks
		row.purchase_qc = qc.name
	q.flags.ignore_permissions = True
	q.save()

	if not main_live:
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
	"""Older flow: a cancelled release-QC puts its lines back under quarantine."""
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
	"""What the Quarantine, QC and GRN screens may offer for one Quarantine document."""
	q = frappe.get_doc(QUARANTINE, purchase_quarantine)
	q.check_permission("read")
	may = bool(set(frappe.get_roles()).intersection(RELEASE_ROLES))
	held = [r.name for r in q.get("items") or [] if r.status == C.QUARANTINE_HELD]
	receipt = frappe.db.get_value(QC, q.purchase_qc, "purchase_receipt") if q.get("purchase_qc") else None

	if q.get("purchase_qc"):
		qcs = {q.purchase_qc: "quarantined"}
	else:
		# Older flow: the QC each release raised, and the inward's own QC.
		qcs = {}
		for row in q.get("items") or []:
			if row.purchase_qc and row.purchase_qc not in qcs:
				qcs[row.purchase_qc] = "released"
		main_qc = frappe.db.get_value(INWARD, q.purchase_inward, "purchase_qc")
		if main_qc and main_qc not in qcs:
			qcs[main_qc] = "inward"
	return {
		"flow": "qc" if q.get("purchase_qc") else "inward",
		"can_release": may and bool(held),
		"can_edit_reminder": may and q.status != C.QRN_RELEASED,
		"held_rows": held,
		"purchase_qc": q.get("purchase_qc"),
		"purchase_receipt": receipt,
		"receipt_docstatus": cint(frappe.db.get_value(GRN, receipt, "docstatus")) if receipt else None,
		"line_states": {r.purchase_qc_item: r.status for r in q.get("items") or [] if r.get("purchase_qc_item")},
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
	return {
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
