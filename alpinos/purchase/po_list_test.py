"""Purchase Order List (BRD 1.2 - 1.4) and the Direct Purchase Invoice button.

    bench --site alpinos.test execute alpinos.purchase.po_list_test.run

The most important check here is the first block: every PO state the BRD names is built
for real, then each Current Status filter is asked for its rows and compared, order by
order, with the label the same row DISPLAYS. The status is derived twice -- once in
Python for the cell and once in SQL for the filter, because the filter must page and
count on the server -- and those two must never disagree. An order that shows "Partially
Received" but is missing from the "Partially Received" filter is exactly the kind of
bug nobody notices until a buyer cannot find an order.

Everything runs against a supplier minted for this run, so the rest of the site's orders
never enter the comparison.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H
from alpinos.purchase import po_list_api as PL
from alpinos.purchase import purchase_invoice as INV
from alpinos.purchase import purchase_order_approval as POA
from alpinos.purchase.regression_test import _receive

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {frappe.utils.strip_html(str(e))[:220]}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
		                "send_welcome_email": 0, "enabled": 1}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	u.set("roles", [])
	for role in roles:
		if frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
	return email


def _draft_po(supplier, item, qty=10, direct=0, itype=C.INWARD_RM):
	po = frappe.new_doc("Purchase Order")
	po.supplier = supplier
	po.company = H.COMPANY
	po.transaction_date = today()
	po.schedule_date = add_days(today(), 7)
	po.set_warehouse = H._warehouse()
	po.custom_inward_type = itype
	po.custom_direct_purchase_invoice = direct
	po.append("items", {"item_code": item, "qty": qty, "rate": 10,
	                    "schedule_date": add_days(today(), 7), "warehouse": H._warehouse()})
	po.insert(ignore_permissions=True)
	return po


def _rows(**kw):
	return PL.get_purchase_order_list(page_length=100, **kw)["data"]


def _names(**kw):
	return {r["name"] for r in _rows(**kw)}


def _row(name, supplier):
	for r in _rows(supplier=supplier, po_id=name):
		if r["name"] == name:
			return r
	raise AssertionError(f"{name} not returned by the list")


def _actions(row):
	return {a["action"]: a for a in row["actions"]}


def run():
	R.clear()
	frappe.set_user("Administrator")
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	supplier = H.ensure_supplier()
	other_supplier_item = H.ensure_item(f"PITEST-POL-OTHER-{H.SEQ}")
	item_a = H.ensure_item(f"PITEST-POL-A-{H.SEQ}")
	item_b = H.ensure_item(f"PITEST-POL-B-{H.SEQ}")
	# Purchase Inward User only: Purchase Inward Manager is in PO_APPROVER_ROLES, so a user
	# holding all of C.PURCHASE_ROLES genuinely IS an approver and would see Approve.
	purchaser = _user("pol-purchase@example.com", [C.ROLE_PURCHASE_USER, "Purchase User"])

	# ------------------------------------------------------------ one order per state
	S = {}
	S["Draft"] = _draft_po(supplier, item_a).name

	pend = _draft_po(supplier, item_a)
	POA.perform_action(pend.name, "Submit for Approval")
	S["Pending Approval"] = pend.name

	rej = _draft_po(supplier, item_a)
	POA.perform_action(rej.name, "Submit for Approval")
	POA.perform_action(rej.name, "Reject", remarks="Rate too high")
	S["Rejected"] = rej.name

	S["Approved"] = H.make_po(supplier, [(item_a, 10, 10)]).name

	sent = H.make_po(supplier, [(item_a, 10, 10)])
	POA.perform_action(sent.name, "Send to Supplier")
	S["Sent to Supplier"] = sent.name

	part = H.make_po(supplier, [(item_a, 100, 10), (item_b, 50, 10)])
	POA.perform_action(part.name, "Send to Supplier")
	inw = H.make_inward(part, [part.items[0]], invoice_no=f"POL-P-{H.SEQ}-{frappe.generate_hash(length=5)}")
	inw.submit()
	inw.reload()
	_receive(inw, 40)
	S["Partially Received"] = part.name

	full = H.make_po(supplier, [(item_a, 30, 10)])
	POA.perform_action(full.name, "Send to Supplier")
	inw_f = H.make_inward(full, full.items, invoice_no=f"POL-F-{H.SEQ}-{frappe.generate_hash(length=5)}")
	inw_f.submit()
	inw_f.reload()
	_receive(inw_f, 30)
	S["Fully Received"] = full.name

	# Received while still only Approved -- never marked Sent. The server allows it, and
	# it is the case the first fixture above (sent first) could not see.
	unsent = H.make_po(supplier, [(item_a, 20, 10)])
	inw_u = H.make_inward(unsent, unsent.items, invoice_no=f"POL-U-{H.SEQ}-{frappe.generate_hash(length=5)}")
	inw_u.submit()
	inw_u.reload()
	_receive(inw_u, 20)
	S["Fully Received (never sent)"] = unsent.name

	closed = H.make_po(supplier, [(item_a, 10, 10)])
	from erpnext.buying.doctype.purchase_order.purchase_order import update_status
	update_status("Closed", closed.name)
	S["Closed"] = closed.name

	canc = H.make_po(supplier, [(item_a, 10, 10)])
	frappe.get_doc("Purchase Order", canc.name).cancel()
	S["Cancelled"] = canc.name

	direct = H.make_po(supplier, [(item_b, 5, 100)], direct_invoice=1)
	S["Direct Approved"] = direct.name

	frappe.db.commit()
	fixture = set(S.values())

	# -------------------------------------- each state displays what it should
	for state, name in S.items():
		want = {"Direct Approved": "Approved", "Fully Received (never sent)": "Fully Received"}.get(state, state)
		check(f"an order that is {state} is shown as {want}",
		      lambda n=name, w=want: _assert(_row(n, supplier)["current_status"] == w,
		                                     f"{n} shows {_row(n, supplier)['current_status']!r}"))

	# ------------------------ the filter and the displayed label always agree
	displayed = {r["name"]: r["current_status"] for r in _rows(supplier=supplier) if r["name"] in fixture}
	for value in PL.CURRENT_STATUSES:
		def t(v=value):
			got = _names(supplier=supplier, current_status=v) & fixture
			want = {n for n, s in displayed.items() if s == v}
			_assert(got == want, f"filter returns {sorted(got)}, rows labelled {v!r} are {sorted(want)}")
		check(f"Current Status filter '{value}' returns exactly the rows labelled '{value}'", t)

	for value in PL.RECEIVING_STATUSES:
		def t(v=value):
			rows = {r["name"]: r for r in _rows(supplier=supplier)}
			got = _names(supplier=supplier, receiving_status=v) & fixture
			want = {n for n in fixture if rows.get(n, {}).get("receiving_status") == v}
			_assert(got == want, f"filter {sorted(got)} vs labelled {sorted(want)}")
		check(f"Receiving Status filter '{value}' matches the rows' receiving status", t)

	check("Receiving Status excludes a Direct Purchase Invoice order",
	      lambda: _assert(S["Direct Approved"] not in _names(supplier=supplier, receiving_status=PL.RECV_PENDING)))
	check("Approval Status 'Rejected' returns the rejected order only",
	      lambda: _assert(_names(supplier=supplier, approval_status=C.PO_REJECTED) & fixture == {S["Rejected"]},
	                      str(_names(supplier=supplier, approval_status=C.PO_REJECTED) & fixture)))
	check("an unknown status value narrows to nothing rather than widening to everything",
	      lambda: _assert(not _names(supplier=supplier, current_status="Nonsense")))

	# ------------------------------------------------------------- columns
	def t_columns():
		r = _row(S["Partially Received"], supplier)
		_assert(r["total_items"] == 2, f"total_items={r['total_items']}")
		_assert(sorted(l["item_code"] for l in r["lines"]) == sorted([item_a, item_b]), f"lines={r['lines']}")
		_assert(sum(u["qty"] for u in r["qty_by_uom"]) == 150, f"qty_by_uom={r['qty_by_uom']}")
		_assert(flt(r["po_value"]) > 0 and r["transaction_date"] and r["schedule_date"], "value / dates missing")
		_assert(r["custom_inward_type"] == C.INWARD_RM, r["custom_inward_type"])
	check("row carries PO Type, dates, Total Items, value and the SKU breakdown for the hover", t_columns)

	# ------------------------------------------------------------- filters
	check("PO Type filter", lambda: _assert(
		_names(supplier=supplier, po_type=C.INWARD_FG) & fixture == set(),
		"an RM fixture matched FG"))
	check("PO ID filter matches part of an order number", lambda: _assert(
		S["Draft"] in _names(supplier=supplier, po_id=S["Draft"][-5:])))

	def t_sku():
		# Restricted to this run's orders like every other check: H._seq() can repeat
		# between runs, so an earlier run's orders for the same SKU and supplier also match.
		rows = [r for r in _rows(supplier=supplier, sku_code=item_b) if r["name"] in fixture]
		names = {r["name"] for r in rows}
		_assert(names == {S["Partially Received"], S["Direct Approved"]}, f"SKU {item_b} returned {sorted(names)}")
		part_row = next(r for r in rows if r["name"] == S["Partially Received"])
		_assert(part_row["sku"]["ordered_qty"] == 50 and part_row["sku"]["received_qty"] == 0
		        and part_row["sku"]["pending_qty"] == 50, f"sku block {part_row['sku']}")
		rows_a = {r["name"]: r for r in _rows(supplier=supplier, sku_code=item_a)}
		pa = rows_a[S["Partially Received"]]["sku"]
		_assert(pa["ordered_qty"] == 100 and pa["received_qty"] == 40 and pa["pending_qty"] == 60, f"sku A {pa}")
	check("SKU Code shows only orders with that SKU, with its ordered / received / pending", t_sku)
	check("SKU Code with no match returns nothing",
	      lambda: _assert(not _names(supplier=supplier, sku_code=other_supplier_item)))
	check("SKU Code and PO ID combine (both apply)", lambda: _assert(
		_names(supplier=supplier, sku_code=item_a, po_id=S["Partially Received"]) == {S["Partially Received"]}))
	check("PO Date range covers today", lambda: _assert(
		fixture <= _names(supplier=supplier, from_date=today(), to_date=today())))
	check("Expected Delivery range excludes a window with no deliveries", lambda: _assert(
		not (_names(supplier=supplier, delivery_from=add_days(today(), 60), delivery_to=add_days(today(), 90)) & fixture)))

	def t_paging():
		a = PL.get_purchase_order_list(supplier=supplier, start=0, page_length=4)
		b = PL.get_purchase_order_list(supplier=supplier, start=4, page_length=4)
		na, nb = {r["name"] for r in a["data"]}, {r["name"] for r in b["data"]}
		_assert(len(na) == 4 and a["has_more"] and not (na & nb), f"a={len(na)} has_more={a['has_more']} overlap={na & nb}")
		_assert(a["total"] >= len(fixture), f"total={a['total']}")
	check("paging returns distinct pages and a total", t_paging)
	check("an unknown sort field falls back instead of erroring",
	      lambda: PL.get_purchase_order_list(supplier=supplier, sort_field="name; DROP TABLE x", sort_dir="asc"))

	# ------------------------------------------------------------- actions
	def acts(state):
		return _actions(_row(S[state], supplier))

	check("Draft: View, Edit, Delete, Submit for Approval", lambda: _assert(
		{"view", "edit", "delete", "Submit for Approval"} <= set(acts("Draft")), sorted(acts("Draft"))))
	check("Pending Approval (approver): Approve, Reject, Return for Correction", lambda: _assert(
		{"Approve", "Reject", "Return for Correction"} <= set(acts("Pending Approval")), sorted(acts("Pending Approval"))))
	check("Rejected: Edit and Submit for Approval, no Delete", lambda: _assert(
		{"edit", "Submit for Approval"} <= set(acts("Rejected")) and "delete" not in acts("Rejected"), sorted(acts("Rejected"))))

	def t_approved():
		a = acts("Approved")
		_assert("Send to Supplier" in a, sorted(a))
		ci = a.get("create_inward")
		_assert(ci and ci["enabled"] is False and "Send this Purchase Order" in ci["reason"], f"create_inward={ci}")
	check("Approved: Send to Supplier, Create Inward shown disabled with the reason (BRD 1.4)", t_approved)
	check("Sent to Supplier: Create Inward enabled", lambda: _assert(
		acts("Sent to Supplier").get("create_inward", {}).get("enabled") is True and
		acts("Sent to Supplier")["create_inward"]["label"] == "Create Inward", str(acts("Sent to Supplier").get("create_inward"))))

	def t_partial():
		a = acts("Partially Received")
		_assert(a.get("create_inward", {}).get("label") == "Continue Receiving" and a["create_inward"]["enabled"], str(a.get("create_inward")))
		_assert("view_inwards" in a, sorted(a))
	check("Partially Received: Continue Receiving and View Inwards", t_partial)
	check("Fully Received: no Create Inward", lambda: _assert("create_inward" not in acts("Fully Received"), sorted(acts("Fully Received"))))
	check("received without ever being sent: no Send to Supplier (BRD 1.4 Fully Received -> View)",
	      lambda: _assert(not ({"Send to Supplier", "create_inward"} & set(acts("Fully Received (never sent)"))),
	                      sorted(acts("Fully Received (never sent)"))))
	check("the PO form agrees: no approval action on a received order",
	      lambda: _assert(not POA.get_available_actions(S["Fully Received (never sent)"])["actions"],
	                      str(POA.get_available_actions(S["Fully Received (never sent)"])["actions"])))
	check("Closed and Cancelled offer no forward action", lambda: _assert(
		not ({"create_inward", "create_invoice", "Send to Supplier"} & (set(acts("Closed")) | set(acts("Cancelled")))),
		f"closed={sorted(acts('Closed'))} cancelled={sorted(acts('Cancelled'))}"))

	def t_direct():
		a = acts("Direct Approved")
		_assert("create_invoice" in a and "create_inward" not in a, sorted(a))
	check("Direct Purchase Invoice order: Create Invoice, never Create Inward (BR-PO-22 / 24)", t_direct)

	check("purchase team without approver roles is not offered Approve", lambda: (
		frappe.set_user(purchaser),
		_assert("Approve" not in _actions(_row(S["Pending Approval"], supplier)), "Approve offered to a buyer"),
	))
	frappe.set_user("Administrator")

	# ---------------------------------- Direct invoice: create, then never twice
	inv = None
	try:
		inv = INV.create_direct_from_po(S["Direct Approved"])
		frappe.db.commit()
		R.append(("PASS", "Create Invoice raises the Direct Purchase Invoice", ""))
	except Exception as e:
		R.append(("ERROR", "Create Invoice raises the Direct Purchase Invoice", f"{type(e).__name__}: {e}"))

	if inv:
		check("after invoicing, the row offers View Invoice instead of Create Invoice", lambda: _assert(
			"view_invoice" in acts("Direct Approved") and "create_invoice" not in acts("Direct Approved")
			and _row(S["Direct Approved"], supplier)["direct_invoice"] == inv.name, sorted(acts("Direct Approved"))))

		def t_twice():
			try:
				INV.create_direct_from_po(S["Direct Approved"])
			except frappe.ValidationError as e:
				_assert("already exists" in str(e), str(e))
				return
			raise AssertionError("a second invoice was created for the same Direct order")
		check("BR-PO-25 a second Create Invoice on the same order is refused", t_twice)
		check("the PO form is told about the existing invoice", lambda: _assert(
			POA.get_available_actions(S["Direct Approved"]).get("direct_invoice") == inv.name,
			str(POA.get_available_actions(S["Direct Approved"]))))

	# ----------------------------------------------------------- page access
	check("page is registered and a buyer can open it",
	      lambda: _assert(frappe.db.exists("Has Role", {"parent": "purchase_order_list", "role": "Purchase Inward User"})))

	def t_as_buyer():
		frappe.set_user(purchaser)
		try:
			out = PL.get_purchase_order_list(supplier=supplier)
			_assert(out["total"] >= 1, "buyer sees no orders")
		finally:
			frappe.set_user("Administrator")
	check("a buyer can load the list", t_as_buyer)

	frappe.db.commit()
	width = max(len(r[1]) for r in R)
	print("\nPurchase Order List (BRD 1.2 - 1.4)")
	print("=" * (width + 22))
	for state, label, detail in R:
		print(f"[{state}] {label.ljust(width)}  {detail}")
	print("-" * (width + 22))
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R
