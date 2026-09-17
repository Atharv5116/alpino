"""One Dispatch Date across a Sales Order, its Pick Lists and its Delivery Notes.

Changes(HP) #35: when a user changes the Dispatch Date on a Pick List or a Delivery
Note, the linked Sales Order takes the same date, before and after submission, so the
three documents (and the Post Dispatch record built from the note) always agree.

A change travels along the document's own links only:

  Pick List      -> its Sales Order, the Delivery Notes made from it
  Delivery Note  -> its Sales Order, the Pick Lists it was made from

When an order is dispatched in several rounds, each round has its own Pick List and
Delivery Note; changing one round moves the order's date (the most recent change wins)
but never rewrites the date of another round that already went out.

Everything is written with frappe.db.set_value, so the writes fire no hooks and the
sync cannot loop back on itself, and every document that changes gets a Field Change
Log entry saying where the new date came from.

The field is a Date on the Sales Order and the Pick List but a Datetime on the Delivery
Note, so dates are compared by day and the note keeps its time of day.
"""

import frappe
from frappe.utils import cint, get_datetime, getdate, today

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import log_field_change

FIELD = "custom_dispatch_date"
LABEL = "Dispatch Date"

SO_TODAYS_DISPATCH = "Today's Dispatch"
SO_FUTURE_DISPATCH = "Future Dispatch"


def _day(value):
	return getdate(value) if value else None


def _stored(doctype, day, current):
	"""The value to write: the day itself, or on a Delivery Note the day at its old time."""
	if day is None:
		return None
	if doctype != "Delivery Note":
		return day
	time = get_datetime(current).strftime("%H:%M:%S") if current else "00:00:00"
	return f"{day} {time}"


def _set(doctype, name, day, source):
	"""Give one document the day. True if it changed."""
	if not name or not frappe.db.exists(doctype, name):
		return False
	row = frappe.db.get_value(doctype, name, [FIELD, "docstatus"], as_dict=True)
	if row.docstatus == 2 or _day(row.get(FIELD)) == day:
		return False
	value = _stored(doctype, day, row.get(FIELD))
	frappe.db.set_value(doctype, name, FIELD, value, update_modified=False)
	submitted = cint(row.docstatus) == 1
	if submitted and doctype in ("Pick List", "Delivery Note"):
		frappe.db.set_value(doctype, name, "custom_changed_after_submit", 1, update_modified=False)
	log_field_change(doctype, name, f"{LABEL} (from {source})", row.get(FIELD), value, after_submit=submitted)
	return True


def _reschedule(sales_order, day):
	"""An order still waiting in the dispatch queue follows its date between Today's and Future.

	Only those two statuses depend on the date; once picking has started the status
	tracks the Pick List instead, and is left alone.
	"""
	status = frappe.db.get_value("Sales Order", sales_order, "custom_workflow_status")
	if status not in (SO_TODAYS_DISPATCH, SO_FUTURE_DISPATCH) or not day:
		return
	wanted = SO_TODAYS_DISPATCH if day <= getdate(today()) else SO_FUTURE_DISPATCH
	values = {"custom_expected_dispatch_date": day} if wanted == SO_FUTURE_DISPATCH else {}
	if status != wanted:
		values["custom_workflow_status"] = wanted
	if values:
		frappe.db.set_value("Sales Order", sales_order, values, update_modified=False)


def _post_dispatch(delivery_note, day, source):
	if not frappe.db.exists("DocType", "Post Dispatch"):
		return
	for pd in frappe.get_all("Post Dispatch", filters={"delivery_note": delivery_note}, pluck="name"):
		old = frappe.db.get_value("Post Dispatch", pd, "dispatch_date")
		if _day(old) != day:
			frappe.db.set_value("Post Dispatch", pd, "dispatch_date", day, update_modified=False)
			log_field_change("Post Dispatch", pd, f"{LABEL} (from {source})", old, day, after_submit=0)


# ------------------------------------------------------------------- links


def _sales_order_of_pick_list(pick_list):
	so = frappe.db.get_value("Pick List", pick_list, "custom_sales_order_id")
	if so:
		return so
	return frappe.db.get_value(
		"Pick List Item", {"parent": pick_list, "sales_order": ("is", "set")}, "sales_order"
	)


def _delivery_notes_of_pick_list(pick_list):
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT dni.parent
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_pick_list = %s AND dn.docstatus < 2 AND IFNULL(dn.is_return, 0) = 0
		""",
		pick_list,
	)


def _sales_order_of_delivery_note(delivery_note):
	so = frappe.db.get_value("Delivery Note", delivery_note, "custom_sales_order_id")
	if so:
		return so
	return frappe.db.get_value(
		"Delivery Note Item", {"parent": delivery_note, "against_sales_order": ("is", "set")},
		"against_sales_order",
	)


def _pick_lists_of_delivery_note(delivery_note):
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT against_pick_list FROM `tabDelivery Note Item`
		WHERE parent = %s AND IFNULL(against_pick_list, '') <> ''
		""",
		delivery_note,
	)


# ------------------------------------------------------------- propagation


def from_pick_list(pick_list, value):
	"""A Pick List's date is now `value`: carry it to its order and its notes."""
	day = _day(value)
	if not day:
		return
	source = f"Pick List {pick_list}"
	so = _sales_order_of_pick_list(pick_list)
	if so:
		_set("Sales Order", so, day, source)
		_reschedule(so, day)
	for dn in _delivery_notes_of_pick_list(pick_list):
		_set("Delivery Note", dn, day, source)
		_post_dispatch(dn, day, source)


def from_delivery_note(delivery_note, value):
	"""A Delivery Note's date is now `value`: carry it to its order and its pick lists."""
	day = _day(value)
	if not day:
		return
	source = f"Delivery Note {delivery_note}"
	so = _sales_order_of_delivery_note(delivery_note)
	if so:
		_set("Sales Order", so, day, source)
		_reschedule(so, day)
	for pl in _pick_lists_of_delivery_note(delivery_note):
		_set("Pick List", pl, day, source)
	_post_dispatch(delivery_note, day, source)


def _date_changed(doc):
	before = doc.get_doc_before_save()
	return bool(before) and bool(doc.get(FIELD)) and _day(before.get(FIELD)) != _day(doc.get(FIELD))


# ------------------------------------------------------------------- hooks


def pick_list_on_update(doc, method=None):
	"""Draft save and submit. pick_list_hooks keeps a user-changed date instead of
	resetting it to the order's, and flags it for here."""
	if doc.flags.get("dispatch_date_changed"):
		from_pick_list(doc.name, doc.get(FIELD))


def pick_list_on_update_after_submit(doc, method=None):
	if _date_changed(doc):
		from_pick_list(doc.name, doc.get(FIELD))


def delivery_note_on_update(doc, method=None):
	"""Draft save and submit (a submit that also changes the date is caught here)."""
	if doc.docstatus == 2 or cint(doc.get("is_return")):
		return
	if _date_changed(doc):
		from_delivery_note(doc.name, doc.get(FIELD))


def delivery_note_on_update_after_submit(doc, method=None):
	if cint(doc.get("is_return")):
		return
	if _date_changed(doc):
		from_delivery_note(doc.name, doc.get(FIELD))
