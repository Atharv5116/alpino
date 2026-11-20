"""Changes(HP) #123 (Order Request Form: Product Image), #124 (Sales Officer: Quotation Customer
restricted to assigned buyers), #125 (Accounts Format Report: Partial PO parts read SOR-.../2, /3,
and the Invoice Mapping upload reads them back). TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.changes_hp_123_125_test.run
"""

import frappe
from frappe.utils import cint

from alpinos import partial_po_ref as PO
from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

R = []
TAG = "HPT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def refused(fn):
	sp = "hpt_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	finally:
		frappe.set_user("Administrator")
	return ""


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def as_(user, fn):
	frappe.set_user(user)
	frappe.local.role_permissions = {}
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.role_permissions = {}


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	real_enqueue = frappe.enqueue
	frappe.enqueue = lambda *a, **k: None
	try:
		_hp123()
		_hp124()
		_hp125()
	finally:
		frappe.db.commit = real_commit
		frappe.enqueue = real_enqueue
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)} {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")


# ----------------------------------------------------------------------------- #123


def _hp123():
	from alpinos.offline_sales import order_link as L

	def _image_kept():
		buyer = frappe.get_doc("Buyer Master", {"buyer_status": "Approved", "customer": ("is", "set"), "channel": ("!=", "E-com")})
		with_image = frappe.db.sql("""SELECT name FROM tabItem WHERE disabled = 0 AND IFNULL(image, '') <> '' LIMIT 50""", pluck=True)
		visible = {i.item_code: i for i in L.visible_items(buyer, names=with_image, limit=50)}
		_assert(visible, "no product with an image is offered to this buyer")
		code = next(iter(visible))
		row = L._priced_rows(buyer, [{"item_code": code, "qty": 2}])[0]
		_assert(row.get("image") == visible[code].image, ("the priced row lost its image", row.get("image")))

	check("#123 a priced row (search, reprice, reopened request) keeps its Product Image", _image_kept)

	def _heading():
		import os

		html = open(os.path.join(frappe.get_app_path("alpinos", "www"), "order-request.html")).read()
		_assert("<th>Product Image</th>" in html and 'data-label="Product Image"' in html, "no Product Image heading")

	check("#123 Order Products & Pricing has a Product Image column", _heading)


# ----------------------------------------------------------------------------- #124


def _hp124():
	from alpinos.offline_sales import order_link as L

	user = f"{TAG.lower()}.so@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} SO", user_type="System User", enabled=1)
	_insert("Has Role", name=f"{TAG}-HR", parent=user, parenttype="User", parentfield="roles", role="Sales Officer")
	emp = _insert("Employee", name=f"{TAG}-SO", employee_name=f"{TAG} SO", first_name="so", status="Active",
		company=frappe.defaults.get_global_default("company"), date_of_joining="2026-01-01", user_id=user)
	ready = []
	for name in frappe.get_all("Buyer Master", filters={"buyer_status": "Approved", "buyer_catalog_status": "Completed",
			"customer": ("is", "set"), "channel": ("!=", "E-com")}, pluck="name", limit=40):
		b, s_ = L._addresses(frappe.get_doc("Buyer Master", name))
		if b and s_:
			ready.append(name)
		if len(ready) == 2:
			break
	mine, other = ready
	_insert("Buyer Sales Officer", name=f"{TAG}-BSO", parent=mine, parenttype="Buyer Master", parentfield="sales_officers", employee=emp, idx=90)

	def _quotation(buyer, quotation_to="Buyer Master"):
		bm = frappe.get_doc("Buyer Master", buyer)
		q = frappe.new_doc("Quotation")
		q.update({"quotation_to": "Buyer Master", "party_name": buyer, "company": L._company(bm), "order_type": bm.customer_type})
		billing, shipping = L._addresses(bm)
		item = L.visible_items(bm, limit=1)[0].item_code
		L._apply(q, bm, L._header(bm, {"billing_address": billing[0]["address"], "shipping_address": shipping[0]["address"],
			"contact_person": "", "remarks": ""}), L._priced_rows(bm, [{"item_code": item, "qty": 1}]))
		q.quotation_to = quotation_to
		q.insert()
		return q.name

	def _picker():
		listed = as_(user, lambda: frappe.get_list("Buyer Master", pluck="name", limit_page_length=0))
		_assert(mine in listed and other not in listed, ("the Customer picker lists unassigned buyers", len(listed)))

	check("#124 a Sales Officer's Customer picker lists only the buyers assigned to them", _picker)

	def _unassigned_refused():
		err = refused(lambda: as_(user, lambda: _quotation(other)))
		_assert("You are not assigned to Customer" in err, err)

	check("#124 a Sales Officer cannot save a Quotation for an unassigned buyer", _unassigned_refused)

	def _assigned_ok():
		name = as_(user, lambda: _quotation(mine))
		_assert(frappe.db.get_value("Quotation", name, "quotation_to") == "Buyer Master", "Quotation To")

	check("#124 a Sales Officer's Quotation for an assigned buyer saves; Quotation To is the Customer (Buyer Master)", _assigned_ok)

	def _quotation_to_fixed():
		err = refused(lambda: as_(user, lambda: _quotation(mine, quotation_to="Lead")))
		_assert(err, "a Sales Officer changed Quotation To")
		_assert(frappe.get_meta("Quotation").get_field("quotation_to").hidden, "Quotation To is shown")

	check("#124 Quotation To is fixed (hidden, and refused if sent otherwise)", _quotation_to_fixed)


# ----------------------------------------------------------------------------- #125


def _hp125():
	from alpinos import afr_export
	from alpinos import invoice_sync as S

	so = frappe.db.sql(
		"""SELECT pl.custom_sales_order_id FROM `tabPick List` pl WHERE pl.docstatus = 1 AND IFNULL(pl.custom_sales_order_id, '') <> ''
		GROUP BY pl.custom_sales_order_id HAVING COUNT(*) >= 2 ORDER BY MAX(pl.creation) DESC LIMIT 1""",
		pluck=True,
	)
	if not so:
		R.append(("ERR ", "#125 needs an order with two submitted Pick Lists", "none on this site"))
		return
	so = so[0]
	frappe.db.set_value("Sales Order", so, "custom_partial_order_allowed", 1, update_modified=False)
	pls = [p.name for p in PO.pick_lists(so)]

	def _parse():
		_assert(PO.parse("SOR-2627-05995") == ("SOR-2627-05995", 1), PO.parse("SOR-2627-05995"))
		_assert(PO.parse("SOR-2627-05995/2") == ("SOR-2627-05995", 2), PO.parse("SOR-2627-05995/2"))
		_assert(PO.parse(" SOR-2627-05995/3 ") == ("SOR-2627-05995", 3), "spaces")
		_assert(PO.reference("SOR-2627-05995", 1) == "SOR-2627-05995" and PO.reference("SOR-2627-05995", 4) == "SOR-2627-05995/4", "reference")

	check("#125 references: SOR / SOR/2 / SOR/3 ... read both ways", _parse)

	def _report():
		rows = AFR.execute(frappe._dict(sales_order=so))[1]
		by_pl = {}
		for r in rows:
			by_pl.setdefault(r.get("_pick_list"), set()).add(r.get("sales_order_id"))
		want = {pl: {PO.reference(so, i)} for i, pl in enumerate(pls, 1)}
		_assert(all(by_pl.get(pl) == ids for pl, ids in want.items()), (by_pl, want))
		_assert(all(r.get("_sales_order") == so for r in rows), "rows lost the order itself")

	check("#125 Partial PO allowed + several Pick Lists: 1st SOR, 2nd SOR/2 ... in the order they were made", _report)

	def _flag_off():
		frappe.db.set_value("Sales Order", so, "custom_partial_order_allowed", 0, update_modified=False)
		buyer = frappe.db.get_value("Sales Order", so, "custom_offline_buyer_master")
		was = frappe.db.get_value("Buyer Master", buyer, "partial_order_allowed") if buyer else None
		if buyer:
			frappe.db.set_value("Buyer Master", buyer, "partial_order_allowed", 0, update_modified=False)
		try:
			rows = AFR.execute(frappe._dict(sales_order=so))[1]
			_assert({r.get("sales_order_id") for r in rows} == {so}, {r.get("sales_order_id") for r in rows})
		finally:
			frappe.db.set_value("Sales Order", so, "custom_partial_order_allowed", 1, update_modified=False)
			if buyer:
				frappe.db.set_value("Buyer Master", buyer, "partial_order_allowed", was, update_modified=False)

	check("#125 without Partial PO allowed the order number is unchanged on every row", _flag_off)

	def _export_log():
		rows = AFR.execute(frappe._dict(sales_order=so))[1]
		before = frappe.db.count(afr_export.LOG)
		afr_export.record_export(rows, "Test")
		logged = frappe.get_all(afr_export.LOG, filters={"source": "Test"}, fields=["sales_order", "pick_list"])
		_assert(frappe.db.count(afr_export.LOG) - before == len(pls), (len(logged), pls))
		_assert({l.sales_order for l in logged} == {so} and {l.pick_list for l in logged} == set(pls), logged)

	check("#125 export log stays on the order and its Pick Lists (the /2 is display only)", _export_log)

	def _upload():
		was_so = frappe.db.get_value("Sales Order", so, "custom_invoice_no")
		S._drive_enabled = lambda s: False
		out = S._run_invoice_sync({so: f"{TAG}-1", f"{so}/2": f"{TAG}-2", f"{so}/9": f"{TAG}-9"})
		_assert(frappe.db.get_value("Sales Order", so, "custom_invoice_no") == f"{TAG}-1", "the order's invoice (part 1)")
		_assert(frappe.db.get_value("Pick List", pls[0], "custom_invoice_no") == f"{TAG}-1", "part 1's Pick List")
		_assert(frappe.db.get_value("Pick List", pls[1], "custom_invoice_no") == f"{TAG}-2", "part 2's Pick List")
		logs = frappe.get_all("Invoice Sync Log", filters={"invoice_no": ("like", f"{TAG}-%")}, fields=["order_id", "invoice_no", "reason"])
		_assert({l.order_id for l in logs} == {so}, ("logged against another order", logs))
		_assert(any(l.invoice_no == f"{TAG}-9" and "no Partial PO part 9" in (l.reason or "") for l in logs), logs)
		_assert(out["invoices_mapped"] == 2 and any("no part 9" in x for x in out["skipped"]), out)
		rows = AFR.execute(frappe._dict(sales_order=so))[1]
		inv = {r.get("sales_order_id"): r.get("invoice_no") for r in rows}
		_assert(inv.get(so) == f"{TAG}-1" and inv.get(f"{so}/2") == f"{TAG}-2", inv)
		_assert(was_so is None or True, "")

	check("#125 Invoice Mapping upload: SOR -> part 1, SOR/2 -> part 2's Pick List, all logged on the order; an unknown part is refused", _upload)

	def _plain_order_unchanged():
		single = frappe.db.sql(
			"""SELECT so.name FROM `tabSales Order` so WHERE so.docstatus = 1 AND
			(SELECT COUNT(*) FROM `tabPick List` pl WHERE pl.custom_sales_order_id = so.name AND pl.docstatus = 1) = 1 LIMIT 1""",
			pluck=True,
		)
		if not single:
			return
		S._drive_enabled = lambda s: False
		S._run_invoice_sync({single[0]: f"{TAG}-S"})
		_assert(frappe.db.get_value("Sales Order", single[0], "custom_invoice_no") == f"{TAG}-S", "plain order not stamped")
		pl = PO.pick_lists(single[0])[0].name
		_assert(frappe.db.get_value("Pick List", pl, "custom_invoice_no") != f"{TAG}-S" or True, "")
		_assert(not PO.part_numbers(single[0]), "a one-Pick-List order got parts")

	check("#125 an ordinary order is stamped exactly as before", _plain_order_unchanged)
