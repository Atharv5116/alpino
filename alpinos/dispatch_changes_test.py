"""Changes(HP) #35-#38: dispatch date sync, Dispatch Report sections, hidden finished
orders, and the Pick List packing sheet.

Run:  bench --site alpinos.test execute alpinos.dispatch_changes_test.run

#35 is driven through the REAL save paths on real Pick Lists / Delivery Notes of the
site (after-submit edit, draft save, bulk edit); #36 and #37 run on fixture documents
written straight to the tables. Everything runs in one transaction that is rolled back
at the end, and commits made by the code under test are ignored while it runs.
"""

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate, today

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
		_dispatch_report(tag)
		_hidden_finished_orders(tag)
		_packing_sheet()
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


# ---------------------------------------------------------------- #36 report


def _dispatch_report(tag):
	from alpinos.dispatch_report_api import get_dispatch_report_data

	day = getdate("2026-09-11")
	ct = f"{tag}-CT"
	_insert("Alpino Customer Type", name=ct, abbreviation=tag[-4:], sequence=0)
	i1, c1, c2, bundle = f"{tag}-I1", f"{tag}-C1", f"{tag}-C2", f"{tag}-BUNDLE"
	for n, code in enumerate((i1, c1, c2), start=1):
		_insert("Item", name=code, item_code=code, item_name=code, custom_sequence=90000 + n, disabled=0, stock_uom="Nos")

	def so(n, status, lines, **extra):
		name = f"{tag}-SO-{n}"
		_insert("Sales Order", name=name, docstatus=1, custom_workflow_status=status, order_type=ct,
			custom_dispatch_date=add_days(day, 20), status="To Deliver and Bill", customer="X", customer_name="X", **extra)
		rows = {}
		for idx, (code, qty) in enumerate(lines, start=1):
			rows[code] = _insert("Sales Order Item", parent=name, parenttype="Sales Order", parentfield="items",
				item_code=code, qty=qty, stock_qty=qty, idx=idx).name
		return name, rows

	def dn(n, sales_order, lines, dispatch, posting, docstatus=1, packed=None, pick_list=None):
		name = f"{tag}-DN-{n}"
		_insert("Delivery Note", name=name, docstatus=docstatus, is_return=0, custom_sales_order_id=sales_order,
			custom_dispatch_date=dispatch, posting_date=posting)
		items = {}
		for idx, (code, qty, so_detail) in enumerate(lines, start=1):
			items[code] = _insert("Delivery Note Item", parent=name, parenttype="Delivery Note", parentfield="items",
				item_code=code, qty=qty, stock_qty=qty, so_detail=so_detail, against_sales_order=sales_order,
				against_pick_list=pick_list, idx=idx).name
		for idx, (parent_code, code, qty) in enumerate(packed or [], start=1):
			_insert("Packed Item", parent=name, parenttype="Delivery Note", parentfield="packed_items",
				parent_item=parent_code, item_code=code, qty=qty, parent_detail_docname=items[parent_code], idx=idx)
		return name

	# Approved, far-future date: pending whatever its date.
	so("A", "Today's Dispatch", [(i1, 10)])
	# Not approved yet: never pending.
	so("B", "Warehouse Approval Pending", [(i1, 7)])
	# Picking, a DRAFT note and a Pick List dated the report day: still all pending, nothing dispatched.
	c, c_rows = so("C", "Picking In Progress", [(i1, 5)])
	dn("C", c, [(i1, 5, c_rows[i1])], f"{day} 10:00:00", day, docstatus=0)
	_insert("Pick List", name=f"{tag}-PL-C", docstatus=0, purpose="Delivery", custom_sales_order_id=c,
		custom_dispatch_date=day, custom_total_box=9, custom_gross_weight=90)
	# Partial: 8 of 20 out on the day, posted the same day.
	d, d_rows = so("D", "Partial Dispatched", [(i1, 20)])
	_insert("Pick List", name=f"{tag}-PL-D", docstatus=1, purpose="Delivery", custom_sales_order_id=d,
		custom_dispatch_date=day, custom_total_box=3, custom_gross_weight=30)
	dn("D", d, [(i1, 8, d_rows[i1])], f"{day} 11:00:00", day, pick_list=f"{tag}-PL-D")
	# The spec's example: dated the 11th, submitted (posted) on the 12th.
	e, e_rows = so("E", "Delivery Note Created", [(i1, 6)])
	dn("E", e, [(i1, 6, e_rows[i1])], f"{day} 18:00:00", add_days(day, 1))
	# Combo of 2 x C1 + 1 x C2, 3 ordered; 2 combos' worth packed on the day.
	f, f_rows = so("F", "Partial Dispatched", [(bundle, 3)])
	for idx, (code, qty) in enumerate(((c1, 6), (c2, 3)), start=1):
		_insert("Packed Item", parent=f, parenttype="Sales Order", parentfield="packed_items", parent_item=bundle,
			item_code=code, qty=qty, parent_detail_docname=f_rows[bundle], idx=idx)
	dn("F", f, [(bundle, 2, f_rows[bundle])], f"{day} 12:00:00", day, packed=[(bundle, c1, 4), (bundle, c2, 2)])
	# Finished by force, and force closed: never pending.
	so("G", "Forced Completed", [(i1, 4)])
	so("H", "Partial Dispatched", [(i1, 3)], custom_force_closed=1)

	def report(on):
		data = get_dispatch_report_data(date=str(on))
		return {i["item_code"]: i for i in data["items"] if i["item_code"] in (i1, c1, c2)}, data["summary"]

	items, summary = report(day)

	check("#36 pending = approved orders less SUBMITTED notes, whatever the date or status",
		lambda: _assert(flt(items[i1]["pending_dispatch"]) == 27,
			f"I1 pending {items[i1]['pending_dispatch']}, expected 27 (A 10 + C 5 + D 12; B, E, G, H excluded)"))

	check("#36 dispatch on a date = submitted notes carrying that Dispatch Date (draft note and Pick List ignored)",
		lambda: _assert(flt(items[i1]["today_dispatch"]) == 14,
			f"I1 dispatched {items[i1]['today_dispatch']}, expected 14 (D 8 + E 6)"))

	def _submitted_later_stays_on_its_date():
		nxt, _ = report(add_days(day, 1))
		_assert(flt(nxt[i1]["today_dispatch"]) == 0,
			f"a note dated the 11th but posted the 12th shows under the 12th ({nxt[i1]['today_dispatch']})")

	check("#36 a note dated the 11th and submitted the 12th appears under the 11th only", _submitted_later_stays_on_its_date)

	def _combo_in_components():
		_assert(flt(items[c1]["today_dispatch"]) == 4 and flt(items[c2]["today_dispatch"]) == 2,
			f"combo dispatch C1 {items[c1]['today_dispatch']} C2 {items[c2]['today_dispatch']}")
		_assert(flt(items[c1]["pending_dispatch"]) == 2 and flt(items[c2]["pending_dispatch"]) == 1,
			f"combo pending C1 {items[c1]['pending_dispatch']} C2 {items[c2]['pending_dispatch']}")

	check("#36 a combo is counted in its components, dispatched and pending", _combo_in_components)

	check("#36 per customer type columns carry the same numbers",
		lambda: _assert(
			flt(items[i1]["dispatch_by_ct"].get(ct)) == 14 and flt(items[i1]["pending_by_ct"].get(ct)) == 27,
			f"by_ct {items[i1]['dispatch_by_ct']} / {items[i1]['pending_by_ct']}"))

	check("#36 the day's boxes come from the notes' Pick Lists, not every Pick List dated that day",
		lambda: _assert(flt(summary["box_by_ct"].get(ct)) == 3 and flt(summary["gw_by_ct"].get(ct)) == 30,
			f"box {summary['box_by_ct'].get(ct)} gw {summary['gw_by_ct'].get(ct)}"))

	check("#36 Net Unit subtracts only the dispatch not yet in the day's stock",
		lambda: _assert(flt(items[i1]["net_unit"]) == flt(items[i1]["today_stock"]) - 6 - 27,
			f"net {items[i1]['net_unit']} stock {items[i1]['today_stock']}"))


# --------------------------------------------------------------- #37 hidden


def _hidden_finished_orders(tag):
	from alpinos.sales_order_api import get_sales_order_entry_list

	statuses = ["Today's Dispatch", "Dispatched", "Forced Dispatched", "Completed", "Forced Completed",
		"Cancelled", "Rejected", "Partial Dispatched"]
	for n, status in enumerate(statuses):
		_insert("Sales Order", name=f"{tag}-HID-{n}", docstatus=1, custom_workflow_status=status,
			customer="X", customer_name="X", transaction_date=today(), company=frappe.defaults.get_global_default("company"))

	email = "dctest.warehouse@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "DCT", "send_welcome_email": 0,
			"user_type": "System User"}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	u.set("roles", [{"role": "Warehouse Manager"}])
	u.save(ignore_permissions=True)

	def listed(show_all):
		frappe.set_user(email)
		try:
			rows = get_sales_order_entry_list(search=f"{tag}-HID", page_length=100, show_all=show_all)["data"]
		finally:
			frappe.set_user("Administrator")
		return {r.get("custom_workflow_status") for r in rows}

	def _default_hides_finished():
		got = listed(0)
		hidden = {"Dispatched", "Forced Dispatched", "Completed", "Forced Completed", "Cancelled", "Rejected"}
		_assert(not (got & hidden), f"shown by default: {sorted(got & hidden)}")
		_assert({"Today's Dispatch", "Partial Dispatched"} <= got, f"open orders missing: {sorted(got)}")

	check("#37 Forced Dispatched, Completed and Forced Completed are hidden by default (warehouse)", _default_hides_finished)
	check("#37 Show All brings every status back",
		lambda: _assert(listed(1) == set(statuses), f"Show All listed {sorted(listed(1))}"))


# --------------------------------------------------------------- #38 PDF


def _packing_sheet():
	from frappe.utils.pdf import prepare_options

	pl = frappe.db.get_value("Pick List", {"docstatus": ["<", 2]}, "name", order_by="modified desc")
	if not pl:
		skip("#38 packing sheet", "no Pick List on this site")
		return

	def _layout_and_margins():
		html = frappe.get_print("Pick List", pl, print_format="Pick List Packing Sheet", no_letterhead=1)
		for text in ("QC Attended By", "Sales Order ID", "ACTUAL BOX", "TOTAL UNITS", "SAMPLE QTY", "BATCH CODE"):
			_assert(text in html, f"{text!r} missing from the sheet")
		_assert(">QTY<" in html and ">BOX<" in html, "item headings are not QTY / BOX")
		_html, options = prepare_options(html, {})
		for side in ("margin-top", "margin-bottom", "margin-left", "margin-right"):
			_assert(options.get(side) == "5mm", f"{side} is {options.get(side)}")

	check("#38 packing sheet has the reference layout and 5mm PDF margins", _layout_and_margins)
