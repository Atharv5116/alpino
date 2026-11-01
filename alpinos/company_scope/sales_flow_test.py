"""The real sales / dispatch chain in a second company. Run on a TEST site:

	bench --site <test site> execute alpinos.company_scope.sales_flow_test.run

Alpino Hospitality (APC) gets its own Customer Type, Item, Price List, Customer + Buyer
Master (tagged to APC) and stock in "Finished Goods - APC" (Administrator, fixtures only).
Then, as users and through the methods the pages call:

	Sales Order (sales_order_api.create_sales_order) -> warehouse approval (workflow_engine)
	-> Pick List (pick list page) -> Delivery Note (pick_list_api + delivery note page)

and at each step: the document is APC's and named with APC, stock / GL land in APC, the
notification reaches APC's warehouse people only, a default-company user can neither list,
open nor act on it, and the lists / reports follow the active company. Everything is
cancelled and deleted at the end.
"""

import json

import frappe
from frappe.utils import add_days, flt, today

from alpinos.company_scope.testing import ALL, as_user, cleanup_user, companies, ensure_enabled, make_user, set_active

R = []
S = frappe._dict()  # names made along the chain
DMS = []  # Raven DMs sent along the chain (recipient users)

APC = "Alpino Hospitality Pvt. Ltd."
WH = "Finished Goods - APC"
TAG = "CS-FLOW-SALES"
CTYPE = f"{TAG} Type"
ITEM = f"{TAG}-ITEM-1"
PRICE_LIST = f"{TAG} Selling"
CUSTOMER = f"{TAG} Customer"
SITE = f"{TAG} Site"
INVOICE = "CSFLOWSALES1"

U_APC = "cs.flow.sales.apc@example.com"  # Sales + Warehouse Manager (+ Stock User) in APC only
U_DEF = "cs.flow.sales.def@example.com"  # the same roles in the default company only
U_MIX = "cs.flow.sales.mix@example.com"  # Sales User in APC, Warehouse Manager only in the default company
U_BOTH = "cs.flow.sales.both@example.com"  # Sales + Warehouse Manager in both
USERS = (U_APC, U_DEF, U_MIX, U_BOTH)
ROLES = ["Sales Manager", "Warehouse Manager"]


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))
	finally:
		frappe.clear_messages()


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, contains=None):
	try:
		fn()
	except Exception as e:
		frappe.db.rollback()
		frappe.clear_messages()
		if contains and contains.lower() not in str(e).lower():
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return str(e)
	raise AssertionError("did not raise")


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	for k, v in S.items():
		print(f"  {k}: {v}")
	frappe.db.commit()
	return R


def _in(user, company, fn):
	"""fn() as `user` working in `company` (or ALL)."""
	set_active(user, company)
	return as_user(user, fn)


# --- fixtures (Administrator) -----------------------------------------------------------


def _gstin():
	import hashlib

	h = hashlib.md5(TAG.encode()).hexdigest().upper()
	letters = "".join(chr(65 + (int(c, 16) % 26)) for c in h[:5])
	digits = ("".join(c for c in h if c.isdigit()) + "0000")[:4]
	return f"24{letters}{digits}A1Z5"


def _fixtures(A):
	frappe.set_user("Administrator")
	if not frappe.db.exists("Alpino Customer Type", CTYPE):
		frappe.get_doc({"doctype": "Alpino Customer Type", "name": CTYPE, "customer_type": CTYPE,
		                "channel": "Offline"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc({"doctype": "Price List", "price_list_name": PRICE_LIST, "selling": 1, "currency": "INR",
		                "enabled": 1, "custom_companies": [{"company": APC}]}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item", ITEM):
		frappe.get_doc({
			"doctype": "Item", "item_code": ITEM, "item_name": ITEM,
			"item_group": frappe.db.get_value("Item", {"item_code": ["like", "ECOMTEST-ITEM-%"]}, "item_group")
				or frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos", "is_stock_item": 1, "is_sales_item": 1, "custom_gst_percent": 0,
			"gst_hsn_code": "21061000", "custom_companies": [{"company": APC}],
		}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": PRICE_LIST}):
		frappe.get_doc({"doctype": "Item Price", "item_code": ITEM, "price_list": PRICE_LIST,
		                "price_list_rate": 100}).insert(ignore_permissions=True)

	if not frappe.db.exists("Customer", {"customer_name": CUSTOMER}):
		frappe.get_doc({
			"doctype": "Customer", "customer_name": CUSTOMER, "custom_order_type": CTYPE,
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			"default_price_list": PRICE_LIST, "custom_companies": [{"company": APC}],
		}).insert(ignore_permissions=True)
	customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	if not frappe.db.exists("Buyer Master", {"customer": customer}):
		state = frappe.db.get_value("State", {"name": "Gujarat"}) or frappe.db.get_value("State", {}, "name")
		city = frappe.db.get_value("City", {"state": state}, "name") or frappe.db.get_value("City", {}, "name")
		frappe.get_doc({
			"doctype": "Buyer Master", "customer_business_name": CUSTOMER, "customer": customer,
			"customer_type": CTYPE, "channel": "Offline", "is_parent": 1,
			"gst_no": _gstin(), "gst_type": "Registered Business", "level": "N/A", "site_name": SITE,
			"email": "cs.flow.sales@example.com", "contact_no": "9999999999", "contact_person": "CS Flow",
			"custom_companies": [{"company": APC}],
			"addresses": [{
				"is_primary": 1, "is_shipping": 1, "site_name": SITE, "address_line": f"{TAG} Street 1",
				"pincode": "395003", "state": state, "city": city, "country": "India",
			}],
		}).insert(ignore_permissions=True)
	S.customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER}, "name")
	S.buyer = frappe.db.get_value("Buyer Master", {"customer": S.customer}, "name")

	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt",
		"company": APC, "to_warehouse": WH,
		"items": [{"item_code": ITEM, "qty": 100, "t_warehouse": WH, "basic_rate": 50}],
	})
	se.insert(ignore_permissions=True)
	se.submit()
	S.stock_entry = se.name

	# Stock User: the reservation the Pick List makes needs it (Stock Reservation Entry create).
	make_user(U_APC, {APC: ROLES + ["Stock User"]})
	make_user(U_DEF, {A: ROLES})
	make_user(U_MIX, {APC: ["Sales User"], A: ["Warehouse Manager"]})
	make_user(U_BOTH, {A: ROLES, APC: ROLES})
	frappe.db.commit()


def _cleanup():
	frappe.set_user("Administrator")
	left = []

	def attempt(label, fn):
		try:
			fn()
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			left.append(f"{label}: {type(e).__name__}: {str(e)[:120]}")

	def cancel_delete(doctype, name):
		if not name or not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.flags.cancellation_reason = "CS flow test cleanup"
			doc.cancel()
		# The cancelled ledger rows go with the voucher (its name can be reused once deleted).
		for ledger in ("Stock Ledger Entry", "GL Entry"):
			frappe.db.delete(ledger, {"voucher_type": doctype, "voucher_no": name, "is_cancelled": 1})
		for log in ("Field Change Log", "Comment"):
			frappe.db.delete(log, {"reference_doctype": doctype, "reference_name": name})
		frappe.db.delete("Version", {"ref_doctype": doctype, "docname": name})
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	dns = set(frappe.get_all("Delivery Note", {"customer": S.get("customer") or "__none__"}, pluck="name"))
	pls = set(frappe.get_all("Pick List", {"custom_sales_order_id": S.get("sales_order") or "__none__"}, pluck="name"))
	for dn in dns:
		attempt(f"Delivery Note {dn}", lambda dn=dn: cancel_delete("Delivery Note", dn))
	for pl in pls:
		attempt(f"Pick List {pl}", lambda pl=pl: cancel_delete("Pick List", pl))
	for sre in frappe.get_all("Stock Reservation Entry", {"voucher_no": S.get("sales_order") or "__none__"}, pluck="name"):
		attempt(f"Stock Reservation Entry {sre}", lambda sre=sre: cancel_delete("Stock Reservation Entry", sre))
	for so in frappe.get_all("Sales Order", {"customer": S.get("customer") or "__none__"}, pluck="name"):
		attempt(f"Sales Order {so}", lambda so=so: cancel_delete("Sales Order", so))
	if S.get("stock_entry"):
		attempt(f"Stock Entry {S.stock_entry}", lambda: cancel_delete("Stock Entry", S.stock_entry))
	docs = [S.get("sales_order"), *pls, *dns]
	for name in [d for d in docs if d]:
		frappe.db.delete("Notification Log", {"document_name": name})
		frappe.db.delete("Invoice Sync Log", {"order_id": name})
	if S.get("customer"):
		for addr in frappe.get_all("Dynamic Link", {"link_doctype": "Customer", "link_name": S.customer,
		                                             "parenttype": ["in", ["Address", "Contact"]]}, ["parent", "parenttype"]):
			attempt(f"{addr.parenttype} {addr.parent}",
			        lambda addr=addr: frappe.delete_doc(addr.parenttype, addr.parent, ignore_permissions=True, force=True))
	for bi in frappe.get_all("Buyer Items", {"buyer": S.get("customer") or CUSTOMER}, pluck="name"):
		attempt(f"Buyer Items {bi}", lambda bi=bi: frappe.delete_doc("Buyer Items", bi, ignore_permissions=True, force=True))
	for bm in frappe.get_all("Buyer Master", {"customer_business_name": CUSTOMER}, pluck="name"):
		attempt(f"Buyer Master {bm}", lambda bm=bm: frappe.delete_doc("Buyer Master", bm, ignore_permissions=True, force=True))
	for cust in frappe.get_all("Customer", {"customer_name": CUSTOMER}, pluck="name"):
		attempt(f"Customer {cust}", lambda cust=cust: frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True))
	for ip in frappe.get_all("Item Price", {"item_code": ITEM}, pluck="name"):
		attempt(f"Item Price {ip}", lambda ip=ip: frappe.delete_doc("Item Price", ip, ignore_permissions=True, force=True))
	# Cancelling stock vouchers queues reposts for the item; they would fail once it is gone.
	attempt("Repost Item Valuation", lambda: frappe.db.delete("Repost Item Valuation", {"item_code": ITEM}))
	for bin_name in frappe.get_all("Bin", {"item_code": ITEM}, pluck="name"):
		attempt(f"Bin {bin_name}", lambda b=bin_name: frappe.db.delete("Bin", {"name": b}))
	if frappe.db.exists("Item", ITEM):
		attempt(f"Item {ITEM}", lambda: frappe.delete_doc("Item", ITEM, ignore_permissions=True, force=True))
	if frappe.db.exists("Price List", PRICE_LIST):
		attempt(f"Price List {PRICE_LIST}", lambda: frappe.delete_doc("Price List", PRICE_LIST, ignore_permissions=True, force=True))
	if frappe.db.exists("Alpino Customer Type", CTYPE):
		attempt(f"Customer Type {CTYPE}", lambda: frappe.delete_doc("Alpino Customer Type", CTYPE, ignore_permissions=True, force=True))
	for user in USERS:
		attempt(f"User {user}", lambda user=user: cleanup_user(user))
	# Errors the run logged about its own users / pick list (e.g. a Raven DM to a non-Raven user).
	for name in frappe.get_all("Error Log", or_filters=[["error", "like", "%cs.flow.sales.%"],
	                                                     ["method", "like", f"%{S.get('pick_list') or '__none__'}%"]],
	                           filters={"creation": [">=", S.get("started")]}, pluck="name"):
		frappe.db.delete("Error Log", {"name": name})
	frappe.db.commit()
	return left


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	S.clear()
	frappe.set_user("Administrator")
	A, _B, _C = companies()
	ensure_enabled()
	DMS.clear()
	S.started = frappe.utils.now_datetime()
	from alpinos import raven_notifications as rn

	saved = (rn._get_bot, rn._send_dm)
	# Raven DMs are captured, not sent: the recipients are what is checked.
	rn._get_bot = lambda: "CS-FLOW-BOT"
	rn._send_dm = lambda bot, user, text, doc=None: DMS.append(user)
	try:
		_fixtures(A)
		_chain(A)
	finally:
		rn._get_bot, rn._send_dm = saved
		left = _cleanup()
		if left:
			R.append(("NOTE", "left in the database", "; ".join(left)))
	return _report()


def _chain(A):
	from alpinos import pick_list_api, sales_order_api, workflow_engine
	from alpinos.alpinos_development.page.delivery_note_entry import delivery_note_entry
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry

	# The dispatch date: tomorrow (today is refused after 2 PM), so approval parks it in Future Dispatch.
	day = add_days(today(), 1)
	S.dispatch_day = day

	# 1. Sales Order, as the APC user through the entry page's method (company left to resolve).
	items = [{"item_code": ITEM, "qty": 10, "custom_customer_mrp": 120, "custom_selling_price": 100,
	          "custom_gst_percent": 0}]

	def create():
		out = _in(U_APC, APC, lambda: sales_order_api.create_sales_order(
			customer=S.customer, order_type=CTYPE, company="", items=json.dumps(items),
			delivery_date=add_days(day, 7), dispatch_date=day, site_name=SITE, submit_now=1,
		))
		S.sales_order = out["name"]
		frappe.db.commit()

	check("1. SO created + submitted by the APC user (create_sales_order)", create)
	if not S.get("sales_order"):
		return
	so = frappe.get_doc("Sales Order", S.sales_order)
	check("1. SO belongs to APC and is named SOR-APC-...", lambda: _assert(
		so.company == APC and so.name.startswith("SOR-APC-"), f"{so.name} / {so.company}"))
	check("1. SO lines take an APC warehouse", lambda: _assert(
		all(r.warehouse == WH for r in so.items), [r.warehouse for r in so.items]))
	check("1. SO uses the APC price list and APC tax template (if any)", lambda: _assert(
		so.selling_price_list == PRICE_LIST and (not so.taxes_and_charges or so.taxes_and_charges.endswith("- APC")),
		f"{so.selling_price_list} / {so.taxes_and_charges}"))
	check("1. SO waits for warehouse approval", lambda: _assert(
		so.custom_workflow_status == "Warehouse Approval Pending", so.custom_workflow_status))

	def n01():
		got = set(frappe.get_all("Notification Log", {"document_name": S.sales_order}, pluck="for_user"))
		_assert(U_APC in got and U_BOTH in got, f"APC warehouse people missing: {sorted(got)}")
		_assert(U_DEF not in got and U_MIX not in got, f"default-company warehouse people told: {sorted(got)}")

	check("1. N01 reaches APC warehouse role holders only", n01)

	def default_user_cannot_create_in_apc():
		# Asking for APC by name from the default company: the company falls back to theirs, never APC.
		got = as_user(U_DEF, lambda: sales_order_api._resolve_company(APC))
		_assert(got == A, got)

	check("1. Default-company user cannot create an order in APC", default_user_cannot_create_in_apc)

	# 2. Warehouse approval.
	check("2. Default-company-only approver refused", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: workflow_engine.approve_sales_order(S.sales_order))))
	check("2. Approver with Warehouse Manager only in the default company refused", lambda: _in(U_MIX, APC, lambda: _raises(
		lambda: workflow_engine.approve_sales_order(S.sales_order), contains="not permitted")))

	def approve():
		out = _in(U_APC, APC, lambda: workflow_engine.approve_sales_order(S.sales_order))
		frappe.db.commit()
		_assert(out.get("status") == "Future Dispatch", out)

	check("2. APC warehouse approver approves -> Future Dispatch (dispatch date tomorrow)", approve)

	# 3. Pick List through the pick list page.
	def pl_payload():
		mapping = sales_order_api.get_pick_list_mapping_data(S.sales_order)
		rows = []
		for loc in mapping["locations"]:
			rows.append({"name": loc.get("name"), "item_code": loc.get("item_code"), "qty": loc.get("qty"),
			             "custom_box": 0, "custom_batch_code": "", "batch_no": "",
			             "custom_mfg_date": add_days(day, -10), "custom_expiry_date": add_days(day, 300),
			             "custom_source_table": loc.get("custom_source_table") or "Items"})
		header = {"custom_qc_attended_by": U_APC, "custom_assigned_to": U_APC, "custom_dispatch_date": day,
		          "custom_transporter": f"{TAG} Transport", "custom_po_no": f"{TAG}-PO"}
		return json.dumps(header), json.dumps(rows)

	check("3. Default-company user cannot build a Pick List for the APC order", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: pick_list_entry.create_and_submit_pick_list(S.sales_order, *pl_payload()))))

	def make_pl():
		def go():
			header, rows = pl_payload()
			return pick_list_entry.create_and_submit_pick_list(S.sales_order, header, rows)

		S.pick_list = _in(U_APC, APC, go)
		frappe.db.commit()

	check("3. APC user creates + submits the Pick List (page API)", make_pl)
	if not S.get("pick_list"):
		return
	pl = frappe.get_doc("Pick List", S.pick_list)
	check("3. Pick List belongs to APC and carries APC in its name", lambda: _assert(
		pl.company == APC and pl.docstatus == 1 and "APC" in pl.name, f"{pl.name} / {pl.company} / {pl.docstatus}"))
	check("3. Pick List rows pick from the APC warehouse", lambda: _assert(
		all(r.warehouse == WH for r in pl.locations), [r.warehouse for r in pl.locations]))

	def reserved():
		rows = frappe.get_all("Stock Reservation Entry", {"voucher_no": S.sales_order, "docstatus": 1},
		                      ["company", "warehouse", "reserved_qty"])
		_assert(rows and all(r.company == APC and r.warehouse == WH for r in rows), rows)

	check("3. Stock reserved for the order in APC", reserved)

	def pl_names(user, company):
		return _in(user, company, lambda: {r.name for r in pick_list_entry.get_pick_list_entry_list(
			search=S.pick_list, page_length=50)["data"]})

	check("3. Pick List list: APC user sees it", lambda: _assert(S.pick_list in pl_names(U_APC, APC)))
	check("3. Pick List list: default-company user does not", lambda: _assert(S.pick_list not in pl_names(U_DEF, A)))
	check("3. Pick List page: default-company user cannot open it", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: pick_list_entry.get_pick_list_data(S.pick_list))))

	# 4. Delivery Note from the Pick List, then submitted from the delivery note page.
	check("4. Default-company user cannot make the Delivery Note", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: pick_list_api.create_delivery_note_from_pick_list(S.pick_list))))

	def make_dn():
		out = _in(U_APC, APC, lambda: pick_list_api.create_delivery_note_from_pick_list(S.pick_list))
		S.delivery_note = out.get("name") if isinstance(out, dict) else out
		frappe.db.commit()

	check("4. APC user creates the Delivery Note from the Pick List", make_dn)
	if not S.get("delivery_note"):
		return
	header = json.dumps({"custom_lr_gr_no": f"{TAG}-LR-1", "custom_dispatch_date": day,
	                     "custom_transporter_name": f"{TAG} Transport"})
	check("4. Default-company user cannot submit it", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: delivery_note_entry.submit_delivery_note(S.delivery_note, header=header))))

	def submit_dn():
		_in(U_APC, APC, lambda: delivery_note_entry.submit_delivery_note(S.delivery_note, header=header))
		frappe.db.commit()

	check("4. APC user submits the Delivery Note (page API)", submit_dn)
	dn = frappe.get_doc("Delivery Note", S.delivery_note)
	# This site's Delivery Note series is DN-YY-.#####, so APC's reads DN-APC-YY-.#####.
	check("4. Delivery Note belongs to APC, named DN-APC-... / MAT-APC-DN-...", lambda: _assert(
		dn.company == APC and dn.docstatus == 1 and dn.name.startswith(("DN-APC-", "MAT-APC-DN-")),
		f"{dn.name} / {dn.company} / {dn.docstatus}"))

	def ledgers():
		sle = frappe.get_all("Stock Ledger Entry", {"voucher_no": dn.name, "is_cancelled": 0},
		                     ["company", "warehouse", "actual_qty"])
		gle = frappe.get_all("GL Entry", {"voucher_no": dn.name, "is_cancelled": 0}, ["company", "account"])
		_assert(sle and all(r.company == APC and r.warehouse == WH for r in sle), f"SLE {sle}")
		_assert(sum(flt(r.actual_qty) for r in sle) == -10, f"SLE qty {sle}")
		_assert(gle and all(r.company == APC and r.account.endswith(" - APC") for r in gle), f"GL {gle}")

	check("4. Stock and GL entries land in APC", ledgers)
	check("4. Order moves to Dispatched", lambda: _assert(
		frappe.db.get_value("Sales Order", S.sales_order, "custom_workflow_status") == "Dispatched",
		frappe.db.get_value("Sales Order", S.sales_order, "custom_workflow_status")))
	check("4. Delivery note page: default-company user cannot open it", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: delivery_note_entry.get_delivery_note_data(S.delivery_note))))

	# 5. Lists and reports follow the company.
	_lists(A, day)

	def told():
		names = [S.sales_order, S.pick_list, S.delivery_note]
		logs = set(frappe.get_all("Notification Log", {"document_name": ["in", names]}, pluck="for_user"))
		outsiders = {U_DEF, U_MIX} & (logs | set(DMS))
		_assert(not outsiders, f"told: {sorted(outsiders)}")
		_assert(U_APC in logs and U_APC in DMS, f"bell {U_APC in logs} / DM {U_APC in DMS}")

	check("6. Bell + Raven DMs of the whole chain: APC role holders only", told)


def _lists(A, day):
	from alpinos import dispatch_report_api, invoice_queue_api, invoice_sync, sales_order_api
	from alpinos.alpinos_development.page.delivery_note_entry import delivery_note_entry
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry

	def so_rows():
		return sales_order_api.get_sales_order_entry_list(page_length=100)["data"]

	def pl_rows():
		return pick_list_entry.get_pick_list_entry_list(page_length=100)["data"]

	def dn_rows():
		return delivery_note_entry.get_delivery_note_list(page_length=100)["data"]

	for label, rows_fn, name in (("Sales Order", so_rows, S.sales_order), ("Pick List", pl_rows, S.pick_list),
	                             ("Delivery Note", dn_rows, S.delivery_note)):

		def apc_sees(rows_fn=rows_fn, name=name):
			rows = _in(U_APC, APC, rows_fn)
			_assert(name in {r.name for r in rows}, "missing")
			_assert({r.company for r in rows} == {APC}, {r.company for r in rows})

		def default_does_not(rows_fn=rows_fn, name=name):
			rows = _in(U_DEF, A, rows_fn)
			_assert(name not in {r.name for r in rows} and APC not in {r.company for r in rows})

		def all_mode(rows_fn=rows_fn, name=name):
			try:
				rows = _in(U_BOTH, ALL, rows_fn)
			finally:
				set_active(U_BOTH, APC)
			_assert(name in {r.name for r in rows}, "missing")
			_assert({A, APC} <= {r.company for r in rows}, {r.company for r in rows})

		def switched_to_default(rows_fn=rows_fn, name=name):
			try:
				rows = _in(U_BOTH, A, rows_fn)
			finally:
				set_active(U_BOTH, APC)
			_assert(name not in {r.name for r in rows}, "listed")

		check(f"5. {label} list: APC user sees it (APC only)", apc_sees)
		check(f"5. {label} list: default-company user does not", default_does_not)
		check(f"5. {label} list: All mode shows both companies", all_mode)
		check(f"5. {label} list: switched to the default company, gone", switched_to_default)

	check("5. SO view: default-company user cannot open it", lambda: _in(U_DEF, A, lambda: _raises(
		lambda: sales_order_api.get_sales_order_entry_view_payload(S.sales_order))))

	def breakup(user, company):
		return _in(user, company, lambda: {r["sales_order"] for r in dispatch_report_api.get_quantity_breakup(
			date=day, item_code=ITEM, kind="dispatch")["rows"]})

	check("5. Dispatch report: APC user sees the day's APC dispatch", lambda: _assert(
		S.sales_order in breakup(U_APC, APC)))
	check("5. Dispatch report: default-company user does not", lambda: _assert(
		not breakup(U_DEF, A)))

	# Invoice number from the Accounts upload (the job process_invoice_excel queues, run as the user).
	def foreign_upload():
		_in(U_DEF, A, lambda: invoice_sync._run_invoice_sync({S.sales_order: INVOICE}))
		_assert(not frappe.db.get_value("Sales Order", S.sales_order, "custom_invoice_no"),
		        "a default-company user wrote APC's invoice number")

	check("5. Invoice upload from the default company leaves APC's order alone", foreign_upload)

	def upload():
		_in(U_APC, APC, lambda: invoice_sync._run_invoice_sync({S.sales_order: INVOICE}))
		_assert(frappe.db.get_value("Sales Order", S.sales_order, "custom_invoice_no") == INVOICE)

	check("5. Invoice upload by the APC user stamps the order", upload)

	def queue(user, company):
		return _in(user, company, lambda: {r["sales_order"] for r in invoice_queue_api.get_rows(
			filters={"sales_order": S.sales_order})["rows"]})

	check("5. Order Fulfilment queue: APC user sees it", lambda: _assert(S.sales_order in queue(U_APC, APC)))
	check("5. Order Fulfilment queue: default-company user does not", lambda: _assert(
		S.sales_order not in queue(U_DEF, A)))

	def queue_all():
		try:
			got = queue(U_BOTH, ALL)
		finally:
			set_active(U_BOTH, APC)
		_assert(S.sales_order in got)

	check("5. Order Fulfilment queue: All mode shows it", queue_all)
	check("5. Administrator still sees it in the queue", lambda: _assert(S.sales_order in {
		r["sales_order"] for r in invoice_queue_api.get_rows(filters={"sales_order": S.sales_order})["rows"]}))
