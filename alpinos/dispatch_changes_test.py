"""Changes(HP) #35: dispatch date sync between Sales Order, Pick List and Delivery Note, and
#43: Dispatch Date editable on a draft Delivery Note.

Run:  bench --site alpinos.test execute alpinos.dispatch_changes_test.run

#35 is driven through the REAL save paths on real Pick Lists / Delivery Notes of the
site (after-submit edit, draft save, bulk edit, the Delivery Note entry page). Everything runs in one transaction that is
rolled back at the end, and commits made by the code under test are ignored while it runs.
"""

import frappe
from frappe.utils import add_days, get_datetime, getdate, today

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))


def skip(label, why):
	R.append(("SKIP", label, why))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.db_insert()
	return doc


def _day(v):
	return getdate(v) if v else None


def _logged(doctype, name, fragment):
	return frappe.db.exists(
		"Field Change Log",
		{"reference_doctype": doctype, "reference_name": name, "field_label": ["like", f"%{fragment}%"]},
	)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *args, **kwargs: None
	try:
		tag = "DCT-" + frappe.generate_hash(length=6).upper()
		_dispatch_date_sync_real_documents()
		_dispatch_date_sync_rules(tag)
		_dispatch_date_on_draft_note()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{sum(1 for r in R if r[0] != 'SKIP')} passed"
	      + (f", {sum(1 for r in R if r[0] == 'SKIP')} skipped" if any(r[0] == "SKIP" for r in R) else ""))
	return R


# ------------------------------------------------------------------ #35 real


def _dispatch_date_sync_real_documents():
	from alpinos.after_submit_sync import update_after_submit_fields

	target = add_days(today(), 7)

	pair = frappe.db.sql(
		"""
		SELECT pl.name AS pl, dni.parent AS dn, pl.custom_sales_order_id AS so
		FROM `tabPick List` pl
		JOIN `tabDelivery Note Item` dni ON dni.against_pick_list = pl.name
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE pl.docstatus = 1 AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		  AND IFNULL(pl.custom_sales_order_id, '') <> ''
		ORDER BY pl.modified DESC LIMIT 1
		""",
		as_dict=True,
	)
	if not pair:
		skip("#35 submitted Pick List -> Sales Order and Delivery Note", "no submitted PL + DN on this site")
	else:
		p = pair[0]

		def _submitted_pick_list():
			dn_time_before = get_datetime(frappe.db.get_value("Delivery Note", p.dn, "custom_dispatch_date")).time() \
				if frappe.db.get_value("Delivery Note", p.dn, "custom_dispatch_date") else None
			update_after_submit_fields("Pick List", p.pl, {"custom_dispatch_date": str(target)})
			_assert(_day(frappe.db.get_value("Pick List", p.pl, "custom_dispatch_date")) == getdate(target), "PL did not keep the date")
			_assert(_day(frappe.db.get_value("Sales Order", p.so, "custom_dispatch_date")) == getdate(target),
				f"Sales Order {p.so} still {frappe.db.get_value('Sales Order', p.so, 'custom_dispatch_date')}")
			dn_value = frappe.db.get_value("Delivery Note", p.dn, "custom_dispatch_date")
			_assert(_day(dn_value) == getdate(target), f"Delivery Note {p.dn} still {dn_value}")
			if dn_time_before is not None:
				_assert(get_datetime(dn_value).time() == dn_time_before, "the note lost its time of day")
			_assert(_logged("Sales Order", p.so, "from Pick List"), "no change log on the Sales Order")
			for pd in frappe.get_all("Post Dispatch", filters={"delivery_note": p.dn}, pluck="dispatch_date"):
				_assert(_day(pd) == getdate(target), f"Post Dispatch still {pd}")

		check("#35 submitted Pick List date -> Sales Order, Delivery Note, Post Dispatch", _submitted_pick_list)

		def _submitted_delivery_note():
			again = add_days(target, 2)
			update_after_submit_fields("Delivery Note", p.dn, {"custom_dispatch_date": f"{again} 10:00:00"})
			_assert(_day(frappe.db.get_value("Sales Order", p.so, "custom_dispatch_date")) == getdate(again), "SO not updated")
			_assert(_day(frappe.db.get_value("Pick List", p.pl, "custom_dispatch_date")) == getdate(again), "PL not updated")
			_assert(_logged("Pick List", p.pl, "from Delivery Note"), "no change log on the Pick List")

		check("#35 submitted Delivery Note date -> Sales Order and Pick List", _submitted_delivery_note)

		def _bulk_edit():
			from alpinos.pick_list_api import bulk_edit_pick_lists

			third = add_days(target, 5)
			bulk_edit_pick_lists(frappe.as_json([p.pl]), "custom_dispatch_date", str(third))
			_assert(_day(frappe.db.get_value("Sales Order", p.so, "custom_dispatch_date")) == getdate(third), "SO not updated")
			_assert(_day(frappe.db.get_value("Delivery Note", p.dn, "custom_dispatch_date")) == getdate(third), "DN not updated")

		check("#35 Pick List list bulk edit of the date -> Sales Order and Delivery Note", _bulk_edit)

	draft_pl = frappe.db.sql(
		"""
		SELECT pl.name, pl.custom_sales_order_id AS so FROM `tabPick List` pl
		JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id
		WHERE pl.docstatus = 0 AND so.docstatus = 1 ORDER BY pl.modified DESC LIMIT 1
		""",
		as_dict=True,
	)
	if not draft_pl:
		skip("#35 draft Pick List save", "no draft Pick List on this site")
	else:
		d = draft_pl[0]

		def _draft_pick_list_keeps_and_pushes():
			new = add_days(today(), 9)
			doc = frappe.get_doc("Pick List", d.name)
			doc.custom_dispatch_date = new
			doc.save(ignore_permissions=True)
			_assert(_day(frappe.db.get_value("Pick List", d.name, "custom_dispatch_date")) == getdate(new),
				"the draft Pick List was reset to the order's date")
			_assert(_day(frappe.db.get_value("Sales Order", d.so, "custom_dispatch_date")) == getdate(new),
				"the order did not take the Pick List's date")

		check("#35 draft Pick List save keeps a changed date and pushes it to the order", _draft_pick_list_keeps_and_pushes)

		def _unchanged_draft_still_follows_order():
			other = add_days(today(), 11)
			frappe.db.set_value("Sales Order", d.so, "custom_dispatch_date", other, update_modified=False)
			doc = frappe.get_doc("Pick List", d.name)
			doc.save(ignore_permissions=True)
			_assert(_day(frappe.db.get_value("Pick List", d.name, "custom_dispatch_date")) == getdate(other),
				"a draft saved without a date change no longer follows the order")

		check("#35 a draft Pick List saved without a date change still follows the order", _unchanged_draft_still_follows_order)

	draft_dn = frappe.db.sql(
		"""
		SELECT dn.name, dn.custom_sales_order_id AS so, MAX(dni.against_pick_list) AS pl
		FROM `tabDelivery Note` dn JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 0 AND IFNULL(dn.is_return, 0) = 0 AND IFNULL(dni.against_pick_list, '') <> ''
		  AND IFNULL(dn.custom_sales_order_id, '') <> ''
		GROUP BY dn.name ORDER BY dn.modified DESC LIMIT 1
		""",
		as_dict=True,
	)
	if not draft_dn:
		skip("#35 draft Delivery Note save", "no draft Delivery Note with a Pick List on this site")
	else:
		n = draft_dn[0]

		def _draft_delivery_note():
			new = add_days(today(), 13)
			doc = frappe.get_doc("Delivery Note", n.name)
			doc.custom_dispatch_date = f"{new} 09:30:00"
			# The site's old draft notes miss fields the note's own validation demands
			# (Transporter, Picklist PO No.). Skipping validation still runs the save's
			# on_update hooks, which is the wiring under test.
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.save(ignore_permissions=True)
			_assert(_day(frappe.db.get_value("Sales Order", n.so, "custom_dispatch_date")) == getdate(new), "SO not updated")
			_assert(_day(frappe.db.get_value("Pick List", n.pl, "custom_dispatch_date")) == getdate(new), "PL not updated")

		check("#35 draft Delivery Note save -> Sales Order and Pick List", _draft_delivery_note)


# ----------------------------------------------------------------- #35 rules


def _dispatch_date_sync_rules(tag):
	from alpinos import dispatch_date_sync as S

	so = _insert("Sales Order", name=f"{tag}-SO-R", docstatus=1, custom_workflow_status="Future Dispatch",
		custom_dispatch_date=add_days(today(), 5), customer="X", customer_name="X").name
	for n, day in (("1", "2026-09-11 15:30:00"), ("2", "2026-09-14 08:00:00")):
		_insert("Pick List", name=f"{tag}-PL-{n}", docstatus=1, custom_sales_order_id=so,
			custom_dispatch_date=str(day)[:10])
		_insert("Delivery Note", name=f"{tag}-DN-{n}", docstatus=1, is_return=0, custom_sales_order_id=so,
			custom_dispatch_date=day)
		_insert("Delivery Note Item", parent=f"{tag}-DN-{n}", parenttype="Delivery Note", parentfield="items",
			item_code="X", qty=1, against_pick_list=f"{tag}-PL-{n}", against_sales_order=so, idx=1)

	def _one_round_does_not_rewrite_another():
		S.from_pick_list(f"{tag}-PL-1", "2026-09-12")
		_assert(str(frappe.db.get_value("Delivery Note", f"{tag}-DN-1", "custom_dispatch_date")) == "2026-09-12 15:30:00",
			f"DN-1 {frappe.db.get_value('Delivery Note', f'{tag}-DN-1', 'custom_dispatch_date')} (time must be kept)")
		_assert(str(frappe.db.get_value("Delivery Note", f"{tag}-DN-2", "custom_dispatch_date")) == "2026-09-14 08:00:00",
			"the other round's note was rewritten")
		_assert(str(frappe.db.get_value("Pick List", f"{tag}-PL-2", "custom_dispatch_date")) == "2026-09-14",
			"the other round's Pick List was rewritten")
		_assert(str(frappe.db.get_value("Sales Order", so, "custom_dispatch_date")) == "2026-09-12", "order not updated")

	check("#35 a change in one dispatch round leaves the other round alone, and keeps the note's time",
		_one_round_does_not_rewrite_another)

	def _queue_status_follows_the_date():
		S.from_pick_list(f"{tag}-PL-1", today())
		_assert(frappe.db.get_value("Sales Order", so, "custom_workflow_status") == "Today's Dispatch",
			"moved to today but still Future Dispatch")
		S.from_delivery_note(f"{tag}-DN-1", f"{add_days(today(), 4)} 10:00:00")
		_assert(frappe.db.get_value("Sales Order", so, "custom_workflow_status") == "Future Dispatch",
			"moved to a future date but not Future Dispatch")
		_assert(str(frappe.db.get_value("Sales Order", so, "custom_expected_dispatch_date")) == str(add_days(today(), 4)),
			"expected dispatch date not moved")

	check("#35 an order still in the dispatch queue moves between Today's and Future with its date",
		_queue_status_follows_the_date)


# --------------------------------------------------- #43 draft DN date


def _dispatch_date_on_draft_note():
	from alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry import (
		get_delivery_note_data,
		save_delivery_note_data,
	)

	dn = frappe.db.sql(
		"""
		SELECT dn.name, dn.custom_sales_order_id AS so, MAX(dni.against_pick_list) AS pl
		FROM `tabDelivery Note` dn JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 0 AND IFNULL(dn.is_return, 0) = 0 AND IFNULL(dni.against_pick_list, '') <> ''
		  AND IFNULL(dn.custom_sales_order_id, '') <> '' AND IFNULL(dn.custom_transporter_name, '') <> ''
		GROUP BY dn.name ORDER BY dn.modified DESC LIMIT 1
		""",
		as_dict=True,
	)
	if not dn:
		skip("#43 draft Delivery Note date", "no draft Delivery Note with a Pick List and Transporter")
		return
	n = dn[0]
	new = add_days(today(), 6)

	def _editable_and_carried():
		frappe.db.set_value("Delivery Note", n.name, "custom_dispatch_date", f"{today()} 15:45:00", update_modified=False)
		data = get_delivery_note_data(n.name)
		_assert(data.get("custom_dispatch_date_value") == str(today()), f"page value {data.get('custom_dispatch_date_value')}")
		save_delivery_note_data(n.name, frappe.as_json({"custom_dispatch_date": str(new)}))
		value = frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date")
		_assert(getdate(value) == getdate(new), f"note still {value}")
		_assert(get_datetime(value).strftime("%H:%M:%S") == "15:45:00", f"time of day lost: {value}")
		_assert(getdate(frappe.db.get_value("Sales Order", n.so, "custom_dispatch_date")) == getdate(new), "Sales Order not updated")
		_assert(getdate(frappe.db.get_value("Pick List", n.pl, "custom_dispatch_date")) == getdate(new), "Pick List not updated")

	check("#43 a draft note's page saves a new Dispatch Date and carries it to the order and Pick List",
		_editable_and_carried)

	def _blank_does_not_clear():
		before = frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date")
		save_delivery_note_data(n.name, frappe.as_json({"custom_dispatch_date": None}))
		_assert(frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date") == before, "a blank date cleared it")

	check("#43 an empty date on the page does not blank the mandatory Dispatch Date", _blank_does_not_clear)
