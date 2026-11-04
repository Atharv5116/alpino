"""Sales-side Multiple MRP FRD, end to end. Run on a TEST site:

	bench --site <test site> execute alpinos.sales_multi_mrp_test.run

SKU A has stock at two MRPs (FRD 8: ABC and CDE at 599, XYZ at 699) plus older stock with no
MRP; SKU B has one MRP (250); SKU C is not in the MRP table. Records are prefixed ECOMTEST /
SMMRP and stay on the site; every run makes a fresh set.
"""

import frappe
from frappe.utils import add_days, flt, today

from alpinos import item_mrp as IM
from alpinos import mrp_batch as MB

R = []


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
	"""The error text fn() raises ("" when it went through), undoing only what fn() did."""
	sp = "smmrp_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	return ""


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R


def _fixtures():
	"""e2e_ecom_test fixtures, made to pass India Compliance (HSN on items, a Gujarat buyer)."""
	from alpinos import e2e_ecom_test as E
	from alpinos.purchase import e2e_test as H

	tag = "SMM" + frappe.generate_hash(length=4).upper()
	for i in (1, 2):
		code = f"ECOMTEST-ITEM-{tag}-{i}"
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos", "is_stock_item": 1, "custom_gst_percent": 0, **H._test_hsn(),
		}).insert(ignore_permissions=True)
	get_value = frappe.db.get_value

	def _gujarat(doctype, filters=None, *args, **kwargs):
		if filters == {} and doctype in ("State", "City"):
			return "Gujarat" if doctype == "State" else "Ahmedabad"
		return get_value(doctype, filters, *args, **kwargs)

	frappe.db.get_value = _gujarat
	try:
		f = E._fixtures(tag)
	finally:
		frappe.db.get_value = get_value
	f["tag"] = tag
	return f


def run():
	R.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		_run()
	finally:
		frappe.flags.in_import = False
	return _report()


def _run():
	from alpinos import e2e_ecom_test as E

	f = _fixtures()
	tag, wh, cust = f["tag"], f["warehouse"], f["cust_partial"]
	A, B = f["items"]
	C = f"ECOMTEST-ITEM-{tag}-C"
	frappe.get_doc({"doctype": "Item", "item_code": C, "item_name": C, "is_stock_item": 0,
		"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"), "stock_uom": "Nos",
		**__import__("alpinos.purchase.e2e_test", fromlist=["_test_hsn"])._test_hsn()}).insert(ignore_permissions=True)

	# ------------------------------------------------ 2. the Item MRP table and its flag
	far = add_days(today(), 300)
	MB.assign_existing_stock([
		{"item_code": A, "warehouse": wh, "batch_no": "ABC", "mrp": 599, "qty": 6, "expiry_date": add_days(today(), 100)},
		{"item_code": A, "warehouse": wh, "batch_no": "CDE", "mrp": 599, "qty": 6, "expiry_date": add_days(today(), 200)},
		{"item_code": A, "warehouse": wh, "batch_no": "XYZ", "mrp": 699, "qty": 20, "expiry_date": far},
	])
	check("stock received at a new MRP adds it to the Item's MRP table", lambda: _assert(
		IM.applicable(A).mrps == [599, 699], IM.applicable(A)))
	check("two active MRPs set Multiple MRP on the Item", lambda: _assert(
		frappe.db.get_value("Item", A, IM.FLAG) == 1))
	check("the row says where the MRP came from", lambda: _assert(
		set(frappe.get_all(IM.CHILD, {"parent": A}, pluck="source")) == {"Stock Entry"},
		frappe.get_all(IM.CHILD, {"parent": A}, ["mrp", "source", "reference_name"])))
	IM.register(B, 250, "Manual")
	check("one active MRP: tracked, Multiple MRP off", lambda: _assert(
		IM.applicable(B).tracked and not IM.applicable(B).multiple and frappe.db.get_value("Item", B, IM.FLAG) == 0))
	check("an Item with no rows is not tracked", lambda: _assert(not IM.applicable(C).tracked))

	quarantine = IM.held_warehouses()
	if quarantine:
		lot = MB.get_or_create(B, "QX", 275)
		IM.stock_ledger_on_submit(frappe._dict(is_cancelled=0, actual_qty=5, mrp_batch=lot, voucher_type="Purchase Receipt",
			voucher_no="X", warehouse=quarantine[0], posting_date=today()))
		check("stock landing in quarantine adds no MRP", lambda: _assert(275 not in IM.applicable(B).mrps, IM.applicable(B)))

	item = frappe.get_doc("Item", A)
	next(r for r in item.get(IM.TABLE) if flt(r.mrp) == 699).active = 0
	IM.item_validate(item)
	check("unticking Active on one of two MRPs clears Multiple MRP", lambda: _assert(item.get(IM.FLAG) == 0))
	item.append(IM.TABLE, {"mrp": 599, "active": 1})
	refused_dup = refused(lambda: IM.item_validate(item))
	frappe.db.commit()
	check("the same MRP twice on an Item is refused", lambda: _assert("more than once" in refused_dup, refused_dup))

	row_699 = frappe.db.get_value(IM.CHILD, {"parent": A, "mrp": 699}, "name")
	frappe.db.set_value(IM.CHILD, row_699, "active", 0)
	IM.refresh_flag(A)
	IM.register(A, 699, "GRN")
	check("stock arriving at a retired MRP makes it active again", lambda: _assert(
		IM.applicable(A).mrps == [599, 699] and frappe.db.get_value("Item", A, IM.FLAG) == 1))

	opts = IM.get_sales_mrp_options(A)
	check("order screen, Multiple MRP: both MRPs offered with their stock, no default", lambda: _assert(
		opts["multiple"] == 1 and opts["default"] is None
		and [(m["mrp"], m["stock_qty"]) for m in opts["mrps"]] == [(599, 12), (699, 20)], opts))
	check("order screen, one MRP: filled in", lambda: _assert(
		IM.get_sales_mrp_options(B)["default"] == 250 and IM.get_sales_mrp_options(B)["multiple"] == 0))
	check("order screen, untracked SKU: old pricing", lambda: _assert(IM.get_sales_mrp_options(C)["tracked"] == 0))

	check("no MRP chosen for a Multiple MRP SKU is refused", lambda: _assert(
		"Select the MRP" in (IM.line_mrp_error(A, 0) or "")))
	check("an MRP not in the table is refused", lambda: _assert(
		"not an applicable MRP" in (IM.line_mrp_error(A, 799) or "")))
	check("import, one MRP: another MRP gets the FRD mismatch message", lambda: _assert(
		(IM.line_mrp_error(B, 300, imported=True) or "").startswith("MRP mismatch for SKU")
		and "Imported MRP: ₹ 300.00" in IM.line_mrp_error(B, 300, imported=True)
		and "Applicable MRP: ₹ 250.00" in IM.line_mrp_error(B, 300, imported=True),
		IM.line_mrp_error(B, 300, imported=True)))
	check("an applicable MRP passes; an untracked SKU is never refused", lambda: _assert(
		IM.line_mrp_error(A, 699) is None and IM.line_mrp_error(B, 250) is None and IM.line_mrp_error(C, 123) is None))

	# ------------------------------------------------ 3-4. Buyer Catalog per SKU + MRP
	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate

	cat = frappe.new_doc("Buyer Items")
	cat.title = f"{tag} Catalogue"
	cat.buyer = cust
	cat.append("items", {"item_code": A, "mrp": 599, "margin_percent": 30, "selling_rate": 419.30})
	cat.flags.ignore_permissions = True
	cat.flags.ignore_mandatory = True
	cat.insert()
	at_599 = get_offline_buyer_item_rate(cust, A, mrp=599)
	check("Scenario A: MRP 599 fetches the 599 price (30%, 419.30)", lambda: _assert(
		at_599 and flt(at_599["margin_percent"]) == 30 and flt(at_599["rate"]) == 419.30, at_599))
	at_699 = get_offline_buyer_item_rate(cust, A, mrp=699)
	check("Scenario B: MRP 699 with no 699 price stays blank (not the 599 price)", lambda: _assert(
		at_699 and at_699["rate"] is None and at_699["margin_percent"] is None and flt(at_699["mrp"]) == 699, at_699))
	obm = frappe.db.get_value("Buyer Master", {"customer": cust}, "name")
	frappe.get_doc({"doctype": "Buyer Margin", "parent": obm, "parenttype": "Buyer Master", "parentfield": "margins",
		"sku": B, "margin_percent": 10, "idx": 99}).db_insert()
	at_250 = get_offline_buyer_item_rate(cust, B, mrp=250)
	check("one-MRP SKU with no catalogue row: the buyer's SKU margin applies at that MRP", lambda: _assert(
		at_250 and flt(at_250["margin_percent"]) == 10 and flt(at_250["rate"]) == 225, at_250))

	# ------------------------------------------------ 4 / 6. Sales Order entry and submission
	from alpinos.sales_order_api import create_sales_order

	def offline_so(item_code, mrp, selling, flat, qty=4, submit=1):
		return create_sales_order(
			customer=cust, order_type=f["ctype"], company=f["company"],
			items=frappe.as_json([{"item_code": item_code, "qty": qty, "custom_customer_mrp": mrp,
				"custom_selling_price": selling, "custom_flat_discount": flat, "custom_gst_percent": 0}]),
			dispatch_date=E.DISPATCH(), submit_now=submit,
		)["name"]

	frappe.db.commit()
	t = refused(lambda: offline_so(A, 0, 100, 0))
	check("submitting a Multiple MRP SKU with no MRP is refused", lambda: _assert("Select the MRP" in t, t))
	t = refused(lambda: offline_so(A, 799, 500, 0))
	check("submitting an MRP not in the table is refused", lambda: _assert("not an applicable MRP" in t, t))

	def catalogue():
		return sorted(
			(flt(r.mrp), flt(r.margin_percent), flt(r.selling_rate))
			for r in frappe.get_all("Buyer Item", {"parent": cat.name, "item_code": A}, ["mrp", "margin_percent", "selling_rate"])
		)

	so_699 = offline_so(A, 699, 524.25, 25)
	check("6.1: a submitted order at a new MRP adds that MRP's price; the 599 price is kept", lambda: _assert(
		catalogue() == [(599, 30, 419.30), (699, 25, 524.25)], catalogue()))
	draft = offline_so(A, 599, 400, flt((599 - 400) / 599 * 100, 2), submit=0)
	check("6.3: a draft does not touch the catalogue", lambda: _assert(
		catalogue() == [(599, 30, 419.30), (699, 25, 524.25)], catalogue()))
	frappe.get_doc("Sales Order", draft).submit()
	frappe.db.commit()
	check("6.2: submitting it updates only the 599 row", lambda: _assert(
		catalogue() == [(599, 33.22, 400), (699, 25, 524.25)], catalogue()))

	dup = frappe.get_doc("Sales Order", so_699)
	two = frappe.copy_doc(dup)
	two.append("items", dict(dup.items[0].as_dict(), name=None, idx=2, custom_customer_mrp=599))
	from alpinos.sales_mrp import validate_sales_order_mrps

	t = refused(lambda: validate_sales_order_mrps(two))
	check("BR-09: one SKU at two MRPs in one Sales Order is refused", lambda: _assert("Only one MRP per SKU" in t, t))

	imp = frappe.copy_doc(dup)
	imp.items[0].item_code = B
	imp.items[0].custom_customer_mrp = 300
	frappe.flags.in_import = True
	try:
		t = refused(lambda: validate_sales_order_mrps(imp))
		imp.items[0].custom_customer_mrp = 0
		t0 = refused(lambda: validate_sales_order_mrps(imp))
		imp.items[0].custom_customer_mrp = 250
		validate_sales_order_mrps(imp)
	finally:
		frappe.flags.in_import = False
	free = frappe.copy_doc(dup)
	free.items[0].custom_customer_mrp = 0
	free.custom_is_freebie_po = 1
	free._action = "submit"
	t_free = refused(lambda: validate_sales_order_mrps(free))
	check("an entire-PO-free order (lines at MRP 0) is not refused", lambda: _assert(t_free == "", t_free))
	check("5.2: import at another MRP refused with the FRD message", lambda: _assert("Please correct the import sheet" in t, t))
	check("5.2: import with a blank MRP refused", lambda: _assert("MRP is blank" in t0, t0))

	frappe.db.set_value(IM.CHILD, row_699, "active", 0)
	IM.refresh_flag(A)
	after = frappe.get_doc("Sales Order", so_699)
	after._action = "update_after_submit"
	validate_sales_order_mrps(after)
	check("BR-19: retiring an MRP leaves submitted orders as they are", lambda: _assert(
		flt(frappe.db.get_value("Sales Order Item", {"parent": so_699}, "custom_customer_mrp")) == 699))
	frappe.db.set_value(IM.CHILD, row_699, "active", 1)
	IM.refresh_flag(A)

	# ------------------------------------------------ 5.1 e-com import
	from alpinos import ecom_sales_order_import as EI

	def sheet(mrp):
		return [{"SKU": A, "Qty": 2, "MRP": mrp, "Margin %": 10}]

	t = refused(lambda: EI._create_one_order(cust, f"PO-{tag}-IMP", sheet(799)))
	check("5.1: e-com import, an MRP not in the table is refused", lambda: _assert("not an applicable MRP" in t, t))
	t = refused(lambda: EI._create_one_order(cust, f"PO-{tag}-IMP", sheet("")))
	check("5.1: e-com import, a blank MRP is refused", lambda: _assert("Select the MRP" in t, t))
	ok = refused(lambda: EI._create_one_order(cust, f"PO-{tag}-IMP", sheet(599)))
	frappe.db.commit()
	check("5.1: e-com import, an applicable MRP passes the MRP check", lambda: _assert("MRP" not in ok, ok))

	# ------------------------------------------------ 7-8. Pick List
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry as P
	from alpinos.mrp_batch_hooks import get_batch_code_options, get_lot_options
	from alpinos.sales_order_api import get_pick_list_mapping_data

	so_13 = E._mk_ecom_so(f, cust, f"PO-{tag}-13", [(A, 13, 599, 10)])
	t = refused(lambda: E._mk_pl(so_13, f, {A: 13}))
	check("8.1: 13 needed at 599, 12 there: refused with the FRD message (no 699, no old stock)", lambda: _assert(
		"Insufficient stock for SKU" in t and "Required Qty: 13" in t and "Available Qty: 12" in t, t))

	so_10 = E._mk_ecom_so(f, cust, f"PO-{tag}-10", [(A, 10, 599, 10)])
	line = frappe.db.get_value("Sales Order Item", {"parent": so_10, "item_code": A}, "name")
	mapping = get_pick_list_mapping_data(so_10)
	check("7.1: a new Pick List carries the order MRP for the SKU", lambda: _assert(
		[flt(l.get("order_mrp")) for l in mapping["locations"] if l.get("item_code") == A] == [599], mapping["locations"]))
	lot_opts = get_lot_options(A, wh, sales_order_item=line)
	check("7.2: only 599 batches are offered, no stock without an MRP", lambda: _assert(
		sorted(l["batch_no"] for l in lot_opts["lots"]) == ["ABC", "CDE"] and lot_opts["unassigned"] == 0 and lot_opts["strict"] == 1, lot_opts))
	check("7.2: batch code suggestions hold only 599 batches", lambda: _assert(
		sorted(get_batch_code_options(A, wh, sales_order_item=line)) == ["ABC", "CDE"], get_batch_code_options(A, wh, sales_order_item=line)))

	header = frappe.as_json({"custom_qc_attended_by": "Administrator", "custom_dispatch_date": E.DISPATCH(),
		"custom_transporter": "ECOMTEST Transport", "custom_po_no": "ECOMTEST-PO"})
	blank = {"custom_box": 0, "batch_no": "", "custom_mfg_date": "", "custom_expiry_date": ""}
	draft_pl = P.create_pick_list_as_draft(so_10, header, frappe.as_json([
		dict(blank, name=l.get("name"), item_code=A, qty=10, custom_batch_code="", custom_source_table="Items")
		for l in mapping["locations"] if l.get("item_code") == A]))
	rows = frappe.get_all("Pick List Item", {"parent": draft_pl, "item_code": A}, ["name", "qty"])

	def edit(**kw):
		return frappe.as_json([dict(blank, name=r.name, qty=flt(r.qty), **dict({"custom_batch_code": "", "mrp_batch": ""}, **kw)) for r in rows])

	t = refused(lambda: P.save_pick_list_keep_draft(draft_pl, header, edit(custom_batch_code="XYZ")))
	check("7.2: a 699 batch typed by hand is refused on save", lambda: _assert(
		"Batch XYZ has MRP ₹ 699.00" in t and "₹ 599.00" in t, t))
	xyz = frappe.db.get_value(MB.DOCTYPE, {"item_code": A, "batch_no": "XYZ"}, "name")
	t = refused(lambda: P.save_pick_list_keep_draft(draft_pl, header, edit(mrp_batch=xyz)))
	check("7.2: a 699 Batch / MRP chosen on the row is refused on save", lambda: _assert("has MRP" in t, t))
	try:
		P.save_pick_list_data(draft_pl, header, edit())
		sub = True
	except Exception as e:
		sub = f"{type(e).__name__}: {e}"
	check("8.2: 10 at 599 submits", lambda: _assert(sub is True, sub))
	picked = sorted(
		(r.custom_batch_code, flt(r.qty))
		for r in frappe.get_all("Pick List Item", {"parent": draft_pl, "item_code": A}, ["custom_batch_code", "qty"])
	)
	check("8.2: split across ABC 6 and CDE 4, nothing from XYZ", lambda: _assert(picked == [("ABC", 6), ("CDE", 4)], picked))

	from alpinos import pick_list_print_format

	pick_list_print_format.execute()
	html = frappe.get_print("Pick List", draft_pl, print_format=pick_list_print_format.PF_NAME)
	check("7.1: the Pick List PDF shows MRP under the SKU", lambda: _assert("MRP: ₹ 599.00" in html, "no MRP line"))

	so_b = E._mk_ecom_so(f, cust, f"PO-{tag}-B", [(B, 20, 250, 10)])
	try:
		pl_b = E._mk_pl(so_b, f, {B: 20})
		pl_b = pl_b.get("name") if isinstance(pl_b, dict) else getattr(pl_b, "name", pl_b)
		ok = True
	except Exception as e:
		ok = f"{type(e).__name__}: {e}"
	check("one-MRP SKU: its older stock with no Batch / MRP still picks", lambda: _assert(ok is True, ok))

	# ------------------------------------------------ 9. Accounts Format Report
	from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

	_cols, data = AFR.execute({"sales_order": so_10, "show_all": 1})
	mrps = {flt(r.get("alpino_mrp")) for r in data if r.get("alpino_mrp") is not None}
	check("9: the Accounts Format Report shows the Sales Order MRP", lambda: _assert(mrps == {599}, mrps))
