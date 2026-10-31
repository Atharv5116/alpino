"""MRP-wise and batch-wise inventory, end to end (Purchase Inward draft "MRP-Wise and
Batch-Wise Inventory"). Run on a TEST site only:

	bench --site <test site> execute alpinos.mrp_batch_test.run

One PO line of 100 arrives as three batches at three MRPs (the draft's own example), goes
through QC and the GRN into three Batch / MRP lots, and then leaves stock again through a
Stock Entry that picks lots by itself. Along the way it checks the split rules, the totals
that must not count a split line twice, the purchase-rate policy and the invoice's rate log.

Records are prefixed PITEST-MRP and stay on the site; every run makes a fresh set.
"""

import frappe
from frappe.utils import add_days, flt, now_datetime, today

from alpinos import mrp_batch as MB
from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def expect_throw(label, fn, fragment=None):
	try:
		fn()
		R.append(("FAIL", label, "expected an exception, none raised"))
	except Exception as e:
		msg = str(e)
		if fragment and fragment.lower() not in msg.lower():
			R.append(("FAIL", label, f"threw, but message lacked '{fragment}': {msg[:200]}"))
		else:
			R.append(("PASS", label, ""))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


# ---------------------------------------------------------------- fixtures


def _fg_item(code, shelf_life=365):
	from alpinos.production import material_type as MT

	if not frappe.db.exists("Item", code):
		groups = frappe.get_all(
			"Item Group", filters={"name": ("in", MT.groups_of_type("FG")), "is_group": 0}, pluck="name", limit=1
		)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": groups[0],
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"shelf_life_in_days": shelf_life,
				"custom_gst_percent": 5,
				**H._test_hsn(),
			}
		).insert(ignore_permissions=True)
	return code


def _receive_split(inw, wh, splits, line_qty=None):
	"""Store receipt of the inward's only PO line as `splits` [(qty, batch, mrp, mfg)]."""
	inw.reload()
	inw.actual_arrival_datetime = now_datetime()
	inw.target_warehouse = wh
	line = inw.items[0]
	first, rest = splits[0], splits[1:]
	line.received_qty, line.batch_no, line.mrp, line.manufacturing_date = first
	line.target_warehouse = wh
	line.line_received_qty = line_qty if line_qty is not None else sum(s[0] for s in splits)
	for qty, batch, mrp, mfg in rest:
		inw.append(
			"items",
			{
				"item_code": line.item_code,
				"po_detail": line.po_detail,
				"is_split_row": 1,
				"received_qty": qty,
				"batch_no": batch,
				"mrp": mrp,
				"manufacturing_date": mfg,
				"target_warehouse": wh,
				"line_received_qty": line.line_received_qty,
			},
		)
	inw.save(ignore_permissions=True)
	return inw.reload()


def _complete_qc(inw, decisions):
	"""QC through to completion; `decisions` {batch_no: (approved, rejected)}."""
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod
	from alpinos.purchase import notifications as notif

	notif.submit_for_qc(inw.name)
	qc_name = frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
	qc_mod.start_qc(qc_name)
	qc = frappe.get_doc("Purchase QC", qc_name)
	item_code = qc.items[0].item_code
	for row in qc.items:
		approved, rejected = decisions[row.supplier_batch_no]
		row.approved_qty, row.rejected_qty = approved, rejected
		if rejected:
			row.rejection_reason = "Torn pouches"
	qc.append("vehicle_inspection", {"vehicle_no": "GJ01AB1234", "vehicle_condition": C.CONDITION_GOOD})
	qc.vehicle_inspection_done = 1
	qc.append("material_inspection", {"item_code": item_code, "material_condition": C.CONDITION_GOOD})
	qc.material_inspection_done = 1
	qc.append("packaging_inspection", {"item_code": item_code, "packaging_condition": C.CONDITION_GOOD})
	qc.packaging_inspection_done = 1
	qc.append("sample_testing", {"item_code": item_code, "sample_qty": 1})
	qc.sample_testing_done = 1
	qc.save(ignore_permissions=True)
	qc_mod.complete_qc(qc_name)
	return frappe.get_doc("Purchase QC", qc_name)


def _lot_qty(item_code, warehouse, lot):
	return flt(MB.balances(item_code, warehouse).get(lot))


# --------------------------------------------------------------------- run


def _free_qty(item_code, warehouse):
	return flt(frappe.db.sql("""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry` WHERE item_code=%s AND warehouse=%s
		AND is_cancelled=0 AND IFNULL(mrp_batch, '') = ''""", (item_code, warehouse))[0][0])


def run():
	R.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	H.COMPANY = H._company()
	H.SEQ = "MRP" + frappe.generate_hash(length=5).upper()
	seq = H.SEQ
	wh = frappe.db.get_value("Warehouse", {"company": H.COMPANY, "is_group": 0, "name": ("like", "Stores%")}, "name") or H._warehouse()
	other_wh = frappe.db.get_value(
		"Warehouse",
		{"company": H.COMPANY, "is_group": 0, "name": ("not in", [wh, "Rejected - AHFPL", "Quarantine - AHFPL"])},
		"name",
	)
	rejected_wh = frappe.db.get_single_value("Purchase Inward Settings", "rejected_warehouse")

	check("the Batch / MRP dimension is set up", lambda: _assert(MB.enabled(), "no Inventory Dimension for MRP Batch"))
	check(
		"the lot field is on the ledger, the GRN, the Stock Entry and the Pick List",
		lambda: [
			_assert(frappe.get_meta(dt).has_field(f), f"{dt}.{f} missing")
			for dt, f in (
				("Stock Ledger Entry", "mrp_batch"),
				("Purchase Receipt Item", "mrp_batch"),
				("Purchase Receipt Item", "rejected_mrp_batch"),
				("Stock Entry Detail", "to_mrp_batch"),
				("Pick List Item", "mrp_batch"),
				("Purchase Invoice", "custom_rate_change_log"),
			)
		],
	)

	# --- lots -------------------------------------------------------------
	item = _fg_item(f"PITEST-MRP-{seq}")
	lot_a = MB.get_or_create(item, " B101 ", 199, add_days(today(), -30), source="Other")
	check("a lot is named item:batch:MRP", lambda: _assert(lot_a == f"{item}:B101:199", lot_a))
	check("the same batch and MRP give the same lot", lambda: _assert(MB.get_or_create(item, "B101", 199.0) == lot_a))
	check("another MRP of the same batch is another lot", lambda: _assert(MB.get_or_create(item, "B101", 210) != lot_a))
	check("nothing to name, no lot", lambda: _assert(MB.get_or_create(item, "", 0) is None))
	expect_throw(
		"a second lot for the same item, batch and MRP is refused",
		lambda: frappe.get_doc({"doctype": "MRP Batch", "item_code": item, "batch_no": "B101", "mrp": 199}).insert(),
		"already",
	)

	# --- the inward: one PO line, three batches / MRPs --------------------
	supplier = H.ensure_supplier()
	po = H.make_po(supplier, [(item, 100, 80)], inward_type=C.INWARD_FG)
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-MRP-{seq}")
	check(
		"the inward takes the PO rate as the purchase rate and leaves the MRP to Store",
		lambda: _assert(
			flt(inw.items[0].purchase_rate) == 80 and not flt(inw.items[0].mrp),
			f"purchase_rate={inw.items[0].purchase_rate} mrp={inw.items[0].mrp}",
		),
	)
	inw.submit()
	mfg1, mfg2, mfg3 = add_days(today(), -60), add_days(today(), -40), add_days(today(), -20)

	# FG goods need their MRP at hand-over
	inw.reload()
	inw.actual_arrival_datetime = now_datetime()
	inw.target_warehouse = wh
	inw.items[0].received_qty = 100
	inw.items[0].batch_no = "B100"
	inw.items[0].manufacturing_date = mfg1
	inw.items[0].target_warehouse = wh
	inw.save(ignore_permissions=True)
	from alpinos.purchase import workflow

	check(
		"an FG line cannot go to QC without its Actual MRP",
		lambda: _assert("Actual MRP" in (workflow.receiving_incomplete_reason(inw.reload()) or ""),
			workflow.receiving_incomplete_reason(inw)),
	)

	inw = _receive_split(inw, wh, [(40, "B101", 199, mfg1), (35, "B102", 210, mfg2), (20, "B103", 220, mfg3)], line_qty=100)
	check(
		"splits that do not add up to the line are held back from QC",
		lambda: _assert("add up to 95" in (workflow.receiving_incomplete_reason(inw) or ""),
			workflow.receiving_incomplete_reason(inw)),
	)
	inw.items[2].received_qty = 25
	inw.items[1].batch_no, inw.items[1].mrp = "B101", 199
	inw.save(ignore_permissions=True)
	check(
		"two splits with the same batch and MRP are refused at hand-over",
		lambda: _assert("same Batch No. and MRP" in (workflow.receiving_incomplete_reason(inw.reload()) or ""),
			workflow.receiving_incomplete_reason(inw)),
	)
	inw.items[1].batch_no, inw.items[1].mrp = "B102", 210
	inw.save(ignore_permissions=True)
	inw.reload()

	check("the split rows share one group", lambda: _assert(
		len({r.split_group for r in inw.items}) == 1 and inw.items[0].split_group, [r.split_group for r in inw.items]))
	check("only the line's own row is not a split", lambda: _assert(
		[r.is_split_row for r in inw.items] == [0, 1, 1], [r.is_split_row for r in inw.items]))
	check("ordered and pending are counted once per PO line", lambda: _assert(
		flt(inw.total_order_qty) == 100 and flt(inw.total_pending_qty) == 100 and inw.total_items == 1,
		f"order={inw.total_order_qty} pending={inw.total_pending_qty} items={inw.total_items}"))
	check("received is the sum of the splits", lambda: _assert(flt(inw.total_received_qty) == 100, inw.total_received_qty))
	check("no excess when the splits add up to the planned qty", lambda: _assert(
		not any(flt(r.excess_qty) for r in inw.items), [r.excess_qty for r in inw.items]))
	check("the complete split receipt may go to QC", lambda: _assert(
		workflow.receiving_incomplete_reason(inw) is None, workflow.receiving_incomplete_reason(inw)))

	# --- after submit, PO lines are fixed; only splits come and go --------
	def _remove_primary():
		doc = frappe.get_doc("Purchase Inward", inw.name)
		doc.items = doc.items[1:]
		doc.save(ignore_permissions=True)

	expect_throw("a PO line cannot be removed after submit", _remove_primary, "Only a split can be removed")

	def _stray_row():
		doc = frappe.get_doc("Purchase Inward", inw.name)
		doc.append("items", {"item_code": item, "po_detail": "not-a-po-line", "received_qty": 1})
		doc.save(ignore_permissions=True)

	expect_throw("a new row that is not a split is refused after submit", _stray_row, "splitting")

	# --- purchase rate: Buying Settings keeps the PO rate ------------------
	def _change_rate():
		doc = frappe.get_doc("Purchase Inward", inw.name)
		doc.items[1].purchase_rate = 82
		doc.items[1].rate_change_reason = "Supplier billed the newer batch higher"
		doc.save(ignore_permissions=True)

	if frappe.db.get_single_value("Buying Settings", "maintain_same_rate"):
		expect_throw("with Maintain Same Rate on Stop the inward keeps the PO rate", _change_rate, "Maintain Same Rate")

	# --- QC: one row per split, each with its MRP --------------------------
	qc = _complete_qc(frappe.get_doc("Purchase Inward", inw.name), {"B101": (40, 0), "B102": (30, 5), "B103": (25, 0)})
	check("QC shows a row per split with its MRP", lambda: _assert(
		sorted((r.supplier_batch_no, flt(r.mrp)) for r in qc.items) == [("B101", 199), ("B102", 210), ("B103", 220)],
		[(r.supplier_batch_no, r.mrp) for r in qc.items]))
	check("QC is completed", lambda: _assert(qc.qc_status == C.QC_COMPLETED, qc.qc_status))

	# --- the GRN: three lines, three lots -----------------------------------
	pr_name = frappe.db.get_value("Purchase Receipt", {"custom_purchase_inward": inw.name, "docstatus": 0}, "name")
	check("complete_qc raised a draft GRN", lambda: _assert(pr_name, "no draft GRN"))
	if not pr_name:
		return _report()
	pr = frappe.get_doc("Purchase Receipt", pr_name)
	lots = {r.custom_internal_batch_no: r for r in pr.items}
	check("the GRN carries one line per split", lambda: _assert(len(pr.items) == 3, len(pr.items)))
	check("each GRN line has the Actual MRP, not a rate with GST", lambda: _assert(
		sorted(flt(r.custom_mrp) for r in pr.items) == [199, 210, 220], [r.custom_mrp for r in pr.items]))
	check("each GRN line is priced at the purchase rate", lambda: _assert(
		all(flt(r.rate) == 80 for r in pr.items), [r.rate for r in pr.items]))
	check("each GRN line names its Batch / MRP", lambda: _assert(
		lots["B101"].mrp_batch == lot_a and lots["B102"].mrp_batch == f"{item}:B102:210" and lots["B103"].mrp_batch == f"{item}:B103:220",
		[(k, r.mrp_batch) for k, r in lots.items()]))
	check("the rejected quantity keeps its lot", lambda: _assert(
		lots["B102"].rejected_mrp_batch == lots["B102"].mrp_batch and not lots["B101"].rejected_mrp_batch,
		[(k, r.rejected_mrp_batch) for k, r in lots.items()]))
	check("the inward lines show the lot their stock went into", lambda: _assert(
		sorted(frappe.get_all("Purchase Inward Item", {"parent": inw.name}, pluck="mrp_batch")) == sorted(r.mrp_batch for r in pr.items),
		frappe.get_all("Purchase Inward Item", {"parent": inw.name}, pluck="mrp_batch")))

	pr.submit()
	lot_b, lot_c = lots["B102"].mrp_batch, lots["B103"].mrp_batch
	check("stock is held per lot", lambda: _assert(
		(_lot_qty(item, wh, lot_a), _lot_qty(item, wh, lot_b), _lot_qty(item, wh, lot_c)) == (40, 30, 25),
		MB.balances(item, wh)))
	check("rejected stock sits in the Rejected warehouse under its lot", lambda: _assert(
		_lot_qty(item, rejected_wh, lot_b) == 5, MB.balances(item, rejected_wh)))
	note = frappe.db.get_value("Purchase Receipt", pr.name, "custom_debit_note")
	check("the debit note names the rejected lot", lambda: _assert(
		note and frappe.get_all("Purchase Invoice Item", {"parent": note}, pluck="mrp_batch") == [lot_b],
		note and frappe.get_all("Purchase Invoice Item", {"parent": note}, pluck="mrp_batch")))

	from alpinos.alpinos_development.report.stock_by_batch_and_mrp import stock_by_batch_and_mrp as rpt

	def _report_rows():
		rows = rpt.execute({"item_code": item, "company": H.COMPANY})[1]
		got = sorted((r.warehouse, r.batch_no, flt(r.mrp), flt(r.qty), r.location_kind) for r in rows)
		want = sorted([
			(wh, "B101", 199, 40, "Usable"), (wh, "B102", 210, 30, "Usable"),
			(wh, "B103", 220, 25, "Usable"), (rejected_wh, "B102", 210, 5, "Rejected"),
		])
		_assert(got == want, got)

	check("Stock by Batch and MRP lists each lot and location", _report_rows)

	# --- allocation -----------------------------------------------------------
	check("allocation prefers the order's MRP", lambda: _assert(
		MB.allocate(item, wh, 30, prefer_mrp=220) == [(lot_c, 25), (lot_a, 5)], MB.allocate(item, wh, 30, prefer_mrp=220)))
	check("allocation prefers a typed batch", lambda: _assert(
		MB.allocate(item, wh, 10, prefer_batch="b102")[0] == (lot_b, 10), MB.allocate(item, wh, 10, prefer_batch="b102")))
	check("otherwise the earliest expiry goes first", lambda: _assert(
		MB.allocate(item, wh, 50) == [(lot_a, 40), (lot_b, 10)], MB.allocate(item, wh, 50)))

	# --- outward: a Stock Entry takes lots by itself ------------------------
	issue = frappe.new_doc("Stock Entry")
	issue.stock_entry_type = issue.purpose = "Material Issue"
	issue.company = H.COMPANY
	issue.append("items", {"item_code": item, "qty": 50, "s_warehouse": wh, "uom": "Nos", "conversion_factor": 1})
	issue.insert(ignore_permissions=True)
	check("an issue with no lot is split across lots", lambda: _assert(
		[(r.mrp_batch, flt(r.qty)) for r in issue.items] == [(lot_a, 40), (lot_b, 10)],
		[(r.mrp_batch, r.qty) for r in issue.items]))
	check("each part of the issue shows its own lot's batch", lambda: _assert(
		[r.custom_batch_code for r in issue.items] == ["B101", "B102"], [r.custom_batch_code for r in issue.items]))
	issue.submit()
	check("the issue took the stock out of those lots", lambda: _assert(
		(_lot_qty(item, wh, lot_a), _lot_qty(item, wh, lot_b)) == (0, 20), MB.balances(item, wh)))

	if other_wh:
		move = frappe.new_doc("Stock Entry")
		move.stock_entry_type = move.purpose = "Material Transfer"
		move.company = H.COMPANY
		move.append("items", {"item_code": item, "qty": 5, "s_warehouse": wh, "t_warehouse": other_wh,
			"uom": "Nos", "conversion_factor": 1, "mrp_batch": lot_c})
		move.insert(ignore_permissions=True)
		move.submit()
		check("a transfer lands in the lot it left", lambda: _assert(
			_lot_qty(item, other_wh, lot_c) == 5 and _lot_qty(item, wh, lot_c) == 20,
			(MB.balances(item, other_wh), MB.balances(item, wh))))
		_production_lots(item, wh, other_wh, move, lot_b, lot_c)

	# --- stock from before lots: unassigned, guarded, then assigned ---------
	receipt = frappe.new_doc("Stock Entry")
	receipt.stock_entry_type = receipt.purpose = "Material Receipt"
	receipt.company = H.COMPANY
	receipt.append("items", {"item_code": item, "qty": 10, "t_warehouse": wh, "uom": "Nos", "conversion_factor": 1,
		"basic_rate": 80})
	receipt.insert(ignore_permissions=True)
	receipt.submit()
	check("a receipt with no batch or MRP stays unassigned", lambda: _assert(
		flt(MB.balances(item, wh).get(None)) == 10, MB.balances(item, wh)))

	def _ship_lot_stock_unnamed():
		sle = frappe.new_doc("Stock Ledger Entry")
		sle.update({"item_code": item, "warehouse": wh, "actual_qty": -15, "posting_datetime": now_datetime(),
			"voucher_type": "Stock Entry", "voucher_no": issue.name})
		MB.validate_outward_sle(sle)

	expect_throw("stock with no lot cannot leave out of lot stock", _ship_lot_stock_unnamed, "Batch / MRP")

	made = MB.assign_existing_stock([{"item_code": item, "warehouse": wh, "batch_no": "B099", "mrp": 189, "qty": 10}])
	check("old stock is given its Batch / MRP in place", lambda: _assert(
		made and not flt(MB.balances(item, wh).get(None)) and _lot_qty(item, wh, f"{item}:B099:189") == 10,
		MB.balances(item, wh)))
	expect_throw(
		"more than the unassigned stock cannot be assigned",
		lambda: MB.assign_existing_stock([{"item_code": item, "warehouse": wh, "batch_no": "B098", "qty": 1}]),
		"cannot be assigned",
	)

	# --- the invoice keeps a log of rate changes ----------------------------
	_rate_log(pr)

	# --- screens and reports show the Batch / MRP --------------------------
	try:
		_reports(inw, pr, item, wh)
	except Exception as e:
		R.append(("ERROR", "Reports", f"{type(e).__name__}: {e}"))

	# --- a purchase return leaves the lot the goods came in under ------------
	try:
		_purchase_return(pr, item, wh)
	except Exception as e:
		R.append(("ERROR", "Purchase return", f"{type(e).__name__}: {e}"))

	# --- sales: the Pick List takes the order's MRP, the Delivery Note ships it
	try:
		_pick_list_leg()
	except Exception as e:
		R.append(("ERROR", "Sales Order -> Pick List -> Delivery Note", f"{type(e).__name__}: {e}"))

	return _report()


def _pick_list_leg():
	from alpinos import e2e_ecom_test as E

	tag = "MRP" + frappe.generate_hash(length=4).upper()
	# The e-com fixtures make plain items; a site with India Compliance wants an HSN on them.
	for i in (1, 2):
		code = f"ECOMTEST-ITEM-{tag}-{i}"
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
			"stock_uom": "Nos", "is_stock_item": 1, "custom_gst_percent": 0, **H._test_hsn(),
		}).insert(ignore_permissions=True)
	# They also take the site's first State for a Surat pincode; India Compliance checks the
	# two agree, so the buyer is put in Gujarat.
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
	item, wh = f["items"][0], f["warehouse"]
	MB.assign_existing_stock([
		{"item_code": item, "warehouse": wh, "batch_no": "S1", "mrp": 199, "qty": 300,
			"expiry_date": add_days(today(), 200)},
		{"item_code": item, "warehouse": wh, "batch_no": "S2", "mrp": 249, "qty": 300,
			"expiry_date": add_days(today(), 400)},
	])
	lot_199, lot_249 = f"{item}:S1:199", f"{item}:S2:249"

	so = E._mk_ecom_so(f, f["cust_partial"], f"PO-{tag}", [(item, 350, 249, 10)])
	pl = E._mk_pl(so, f, {item: 350})
	pl_name = pl.get("name") if isinstance(pl, dict) else getattr(pl, "name", pl)
	rows = frappe.get_all("Pick List Item", {"parent": pl_name, "item_code": item},
		["mrp_batch", "qty", "custom_batch_code", "custom_expiry_date"], order_by="idx")
	check("the Pick List takes the order's MRP first, then stock with no lot", lambda: _assert(
		[(r.mrp_batch, flt(r.qty)) for r in rows] == [(lot_249, 300), (None, 50)], rows))
	check("the picked lot's batch is the row's batch code", lambda: _assert(rows[0].custom_batch_code == "S2", rows))
	check("the part with no lot does not borrow that lot's batch or expiry", lambda: _assert(
		not rows[1].custom_batch_code and not rows[1].custom_expiry_date, rows))
	check("a submitted Pick List holds its lot from the next one", lambda: _assert(
		not any(d.lot == lot_249 for d in MB.available(item, wh)[0]), MB.available(item, wh)))

	dn = E._mk_dn(pl_name)
	dn_rows = frappe.get_all("Delivery Note Item", {"parent": dn, "item_code": item}, ["mrp_batch", "qty"], order_by="idx")
	check("the Delivery Note ships the lots the Pick List chose", lambda: _assert(
		sorted((r.mrp_batch or "", flt(r.qty)) for r in dn_rows) == sorted([(lot_249, 300), ("", 50)]), dn_rows))
	check("the shipped lot is empty and the other untouched", lambda: _assert(
		_lot_qty(item, wh, lot_249) == 0 and _lot_qty(item, wh, lot_199) == 300, MB.balances(item, wh)))

	# --- a sales return goes back into the lot it left --------------------------
	_sales_return(dn, item, wh, lot_249, lot_199)


def _production_lots(item, wh, wip, issue, lot_b, lot_c):
	"""`issue` moved lot_c into `wip`; another lot (lot_b, earlier expiry) is put there too."""
	from alpinos.production import execution_inward as XI

	more = frappe.new_doc("Stock Entry")
	more.stock_entry_type = more.purpose = "Material Transfer"
	more.company = H.COMPANY
	more.append("items", {"item_code": item, "qty": 6, "s_warehouse": wh, "t_warehouse": wip,
		"uom": "Nos", "conversion_factor": 1, "mrp_batch": lot_b})
	more.insert(ignore_permissions=True)
	more.submit()

	check("by default the earliest expiry is taken first", lambda: _assert(
		MB.allocate(item, wip, 8) == [(lot_b, 6), (lot_c, 2)], MB.allocate(item, wip, 8)))
	check("allocation takes the lots it is told to prefer first", lambda: _assert(
		MB.allocate(item, wip, 8, prefer_lots=[lot_c]) == [(lot_c, 5), (lot_b, 3)],
		MB.allocate(item, wip, 8, prefer_lots=[lot_c])))
	parts = XI._lot_parts({"item_code": item, "s_warehouse": wip}, item, wip, 8, [lot_c])
	check("production consumes the lots issued for its Sub PO first", lambda: _assert(
		[(p.get("mrp_batch"), flt(p["qty"])) for p in parts] == [(lot_c, 5), (lot_b, 3)], parts))

	if not frappe.get_meta("Stock Entry Detail").has_field("custom_mi_detail"):
		return
	issued_row = issue.items[0].name

	def _return(qty):
		ret = frappe.new_doc("Stock Entry")
		ret.stock_entry_type = ret.purpose = "Material Transfer"
		ret.company = H.COMPANY
		ret.append("items", {"item_code": item, "qty": qty, "s_warehouse": wip, "t_warehouse": wh,
			"uom": "Nos", "conversion_factor": 1, "custom_mi_detail": issued_row})
		ret.insert(ignore_permissions=True)
		ret.submit()
		return [(r.mrp_batch, flt(r.qty)) for r in ret.items]

	got = _return(3)
	check("a material return goes back as the lot its issue moved into WIP", lambda: _assert(got == [(lot_c, 3)], got))
	got2 = _return(4)
	check("when WIP has less of that lot, the return takes what is left of it, then other lots", lambda: _assert(
		got2 == [(lot_c, 2), (lot_b, 2)], got2))


def _reports(inw, pr, item, wh):
	from alpinos.alpinos_development.report.purchase_grn_register import purchase_grn_register as grn_reg
	from alpinos.alpinos_development.report.purchase_qc_stock import purchase_qc_stock as qc_stock
	from alpinos.alpinos_development.report.stock_balance_report import stock_balance_report as bal
	from alpinos.alpinos_development.report.stock_transfer_report import stock_transfer_report as moves
	from alpinos.purchase.quarantine import line_lots

	row = next((r for r in grn_reg.execute({})[1] if r.name == pr.name), None)
	check("the GRN Register lists the receipt's Batch / MRP lots", lambda: _assert(
		row and all(b in (row.lots or "") for b in ("B101", "B102", "B103")), row and row.lots))

	f = {"company": H.COMPANY, "item_code": item, "warehouse": wh, "date": today()}
	items = bal.execute(dict(f))[1]
	cols, lots = bal.execute(dict(f, batch_mrp_wise=1))
	check("Stock Balance can show one row per Batch / MRP", lambda: _assert(
		len(lots) > 1 and all(r.get("batch_no") or not r.get("actual_mrp") for r in lots)
		and "batch_no" in [c["fieldname"] for c in cols] and "reserved_qty" not in [c["fieldname"] for c in cols],
		lots))
	check("its lot rows add up to the item's stock", lambda: _assert(
		abs(sum(flt(r["total_stock"]) for r in lots) - sum(flt(r["total_stock"]) for r in items)) < 1e-6,
		(items, lots)))

	moved = moves.get_data({"company": H.COMPANY, "item_code": item, "from_date": today()})
	check("the transfer report names each row's Batch and MRP", lambda: _assert(
		moved and all(r["batch_no"] and r["lot_mrp"] for r in moved), moved))
	check("the QC stock report runs with its Batch and MRP columns", lambda: _assert(
		"mrp" in [c["fieldname"] for c in qc_stock.execute({"item_code": item})[0]]))

	first = frappe.get_all("Purchase Inward Item", {"parent": inw.name, "batch_no": "B101"}, ["name"])[0].name
	got = line_lots([frappe._dict(name="q1", purchase_inward_item=first, batch_no=None)])
	check("a quarantine line shows its inward line's batch and MRP", lambda: _assert(
		got == {"q1": {"batch": "B101", "mrp": 199}}, got))


def _purchase_return(pr, item, wh):
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_return

	held = MB.balances(item, wh)
	lots = [r.mrp_batch for r in pr.items]
	full = max(lots, key=lambda lot: flt(held.get(lot)))
	empty = next((lot for lot in lots if flt(held.get(lot)) <= 0), None)
	other = next(lot for lot in lots if lot != full)

	def _return(lot, qty, typed=None):
		ret = make_purchase_return(pr.name)
		row = next(r for r in ret.items if r.purchase_receipt_item == next(x.name for x in pr.items if x.mrp_batch == lot))
		copied = row.mrp_batch
		if typed:
			row.mrp_batch = typed  # changed by hand on the return
		row.qty = row.received_qty = row.stock_qty = -qty
		row.rejected_qty = 0
		ret.items = [row]
		ret.insert(ignore_permissions=True)
		ret.submit()
		return row, copied

	def _refused():
		frappe.db.savepoint("mrp_empty_return")
		try:
			_return(empty, 5)
		finally:
			frappe.db.rollback(save_point="mrp_empty_return")

	if empty:
		expect_throw("a purchase return from a lot that has nothing left is refused", _refused)
	before = (flt(held.get(full)), flt(held.get(other)))
	row, copied = _return(full, 5, typed=other)
	check("Create Return copies the received Batch / MRP", lambda: _assert(copied == full, copied))
	check("a purchase return row keeps the lot the goods came in under", lambda: _assert(
		frappe.db.get_value("Purchase Receipt Item", row.name, "mrp_batch") == full,
		frappe.db.get_value("Purchase Receipt Item", row.name, "mrp_batch")))
	check("the returned stock leaves that lot and no other", lambda: _assert(
		(_lot_qty(item, wh, full), _lot_qty(item, wh, other)) == (before[0] - 5, before[1]),
		(before, MB.balances(item, wh))))


def _sales_return(dn, item, wh, lot_shipped, lot_other):
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_return

	before = (_lot_qty(item, wh, lot_shipped), _lot_qty(item, wh, lot_other), _free_qty(item, wh))
	ret = make_sales_return(dn)
	lot_row = next((r for r in ret.items if r.item_code == item and r.mrp_batch == lot_shipped), None)
	free_row = next((r for r in ret.items if r.item_code == item and not r.mrp_batch), None)
	check("Create Return copies the shipped Batch / MRP", lambda: _assert(lot_row and free_row, [(r.item_code, r.mrp_batch) for r in ret.items]))
	if not (lot_row and free_row):
		return
	lot_row.mrp_batch = lot_other  # changed by hand on the return
	lot_row.qty = lot_row.stock_qty = -100
	free_row.qty = free_row.stock_qty = -20
	ret.items = [lot_row, free_row]
	ret.insert(ignore_permissions=True)
	ret.submit()
	got = {r.dn_detail: r.mrp_batch for r in frappe.get_all("Delivery Note Item", {"parent": ret.name}, ["dn_detail", "mrp_batch"])}
	check("a sales return row keeps the lot it was shipped from", lambda: _assert(
		got.get(lot_row.dn_detail) == lot_shipped and not got.get(free_row.dn_detail), got))
	check("the returned stock is back in that lot, and stock shipped with no lot comes back with none", lambda: _assert(
		(_lot_qty(item, wh, lot_shipped), _lot_qty(item, wh, lot_other), _free_qty(item, wh))
		== (before[0] + 100, before[1], before[2] + 20),
		(before, MB.balances(item, wh), _free_qty(item, wh))))


def _rate_log(pr):
	from alpinos.purchase import purchase_invoice as PIM

	settings = frappe.get_single("Buying Settings")
	was = settings.maintain_same_rate
	try:
		if was:
			frappe.db.set_single_value("Buying Settings", "maintain_same_rate", 0)
			frappe.clear_document_cache("Buying Settings", "Buying Settings")
		res = PIM.create_from_grn(pr.name)
		name = res.get("purchase_invoice") if isinstance(res, dict) else getattr(res, "name", res)
		inv = frappe.get_doc("Purchase Invoice", name)
		inv.items[0].rate = flt(inv.items[0].rate) + 3

		expect_throw("an invoice rate off the GRN rate needs a reason", lambda: inv.save(ignore_permissions=True), "Rate Change Reason")
		inv = frappe.get_doc("Purchase Invoice", name)
		inv.items[0].rate = flt(inv.items[0].rate) + 3
		inv.items[0].custom_rate_change_reason = "Rate revised by the supplier"
		inv.save(ignore_permissions=True)
		log = inv.get("custom_rate_change_log") or []
		check("the invoice logs old rate, new rate, user and reason", lambda: _assert(
			len(log) == 1 and flt(log[0].old_value) == 80 and flt(log[0].new_value) == 83
			and log[0].changed_by == "Administrator" and log[0].reason,
			[(l.old_value, l.new_value, l.changed_by, l.reason) for l in log]))
	except Exception as e:
		R.append(("ERROR", "invoice rate log", f"{type(e).__name__}: {e}"))
	finally:
		if was:
			frappe.db.set_single_value("Buying Settings", "maintain_same_rate", was)
			frappe.clear_document_cache("Buying Settings", "Buying Settings")


def _report():
	width = max((len(r[1]) for r in R), default=10)
	print("=" * (width + 12))
	print("MRP-wise and batch-wise inventory")
	print("=" * (width + 12))
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 12))
	print(f"{passed}/{len(R)} passed")
	frappe.db.commit()
	return R
