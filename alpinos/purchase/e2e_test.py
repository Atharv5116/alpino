"""End-to-end script test for the Purchase Inward chain (run on a TEST site).

Run:  bench --site alpinos.test execute alpinos.purchase.e2e_test.run

Walks the BRD's happy path and the validations that guard it:

    Purchase Order -> Purchase Inward -> Store Receipt -> Purchase QC -> Draft GRN

Records are prefixed PITEST and persist on the test site; re-runs mint a fresh set
via a counter suffix, so the suite is safe to run repeatedly.
"""

import frappe
from frappe.utils import add_days, flt, now_datetime, today

from alpinos.purchase import constants as C

R = []  # (status, label, detail)


# ------------------------------------------------------------------ harness


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


def _seq():
	"""A per-run suffix so repeated runs never collide."""
	n = frappe.db.count("Purchase Inward", {"invoice_number": ("like", "PITEST-%")})
	return f"{n + 1:03d}"


SEQ = None
COMPANY = None


# ------------------------------------------------------------------ fixtures


def _company():
	return frappe.db.get_value("Company", {}, "name", order_by="creation asc")


def _warehouse():
	"""Any non-group warehouse in the company, for target locations."""
	return frappe.db.get_value(
		"Warehouse", {"company": COMPANY, "is_group": 0}, "name", order_by="creation asc"
	)


def ensure_supplier():
	name = f"PITEST Supplier {SEQ}"
	if not frappe.db.exists("Supplier", name):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
			}
		).insert(ignore_permissions=True)
	return name


def ensure_item(code, shelf_life_days=0):
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"shelf_life_in_days": shelf_life_days,
			}
		).insert(ignore_permissions=True)
	elif shelf_life_days:
		frappe.db.set_value("Item", code, "shelf_life_in_days", shelf_life_days)
	return code


def make_po(supplier, items, inward_type=C.INWARD_RM, direct_invoice=0):
	"""A submitted Purchase Order carrying the module's custom fields."""
	po = frappe.new_doc("Purchase Order")
	po.supplier = supplier
	po.company = COMPANY
	po.transaction_date = today()
	po.schedule_date = add_days(today(), 7)
	po.set_warehouse = _warehouse()
	po.custom_inward_type = inward_type
	po.custom_direct_purchase_invoice = direct_invoice
	po.custom_supplier_order_no = f"SO-{SEQ}"
	po.custom_vehicle_no = "GJ-05-AB-1234"
	po.custom_driver_contact_no = "9876543210"
	for code, qty, rate in items:
		po.append(
			"items",
			{
				"item_code": code,
				"qty": qty,
				"rate": rate,
				"schedule_date": add_days(today(), 7),
				"warehouse": _warehouse(),
			},
		)
	po.insert(ignore_permissions=True)
	po.submit()
	return po.reload()


def make_inward(po, lines, invoice_no=None, challan=None):
	"""A DRAFT Purchase Inward against `po`. `lines` is [(po_item_row_name, None)]."""
	pi = frappe.new_doc("Purchase Inward")
	pi.purchase_order = po.name
	pi.invoice_number = invoice_no or f"PITEST-INV-{SEQ}"
	pi.invoice_date = today()
	pi.challan_no = challan
	pi.gross_weight = 1200
	pi.inward_datetime = now_datetime()
	for po_item in lines:
		pi.append("items", {"item_code": po_item.item_code, "po_detail": po_item.name})
	pi.insert(ignore_permissions=True)
	return pi


# ------------------------------------------------------------------- the run


def run():
	global SEQ, COMPANY
	R.clear()
	COMPANY = _company()
	assert COMPANY, "no Company on this site"
	SEQ = _seq()

	frappe.set_user("Administrator")
	frappe.flags.in_test = True

	# --- prerequisites the module itself must have provisioned ------------
	check(
		"doctypes migrated",
		lambda: [
			_assert(frappe.db.exists("DocType", dt), f"{dt} not migrated")
			for dt in ("Purchase Inward", "Purchase Inward Item", "Purchase QC")
		],
	)
	check(
		"roles seeded",
		lambda: [
			_assert(frappe.db.exists("Role", r), f"role {r} missing")
			for r in C.ALL_PURCHASE_ROLES
		],
	)
	check(
		"PO custom fields exist",
		lambda: [
			_assert(
				frappe.db.exists(
					"Custom Field", {"dt": "Purchase Order", "fieldname": f}
				),
				f"Purchase Order.{f} missing",
			)
			for f in (
				"custom_inward_type",
				"custom_direct_purchase_invoice",
				"custom_vehicle_no",
				"custom_inward_status",
			)
		],
	)
	check(
		"GRN naming series kept the return series",
		lambda: _assert(
			"MAT-PR-RET-.YYYY.-"
			in (
				frappe.db.get_value(
					"Property Setter",
					{"doc_type": "Purchase Receipt", "field_name": "naming_series",
					 "property": "options"},
					"value",
				)
				or frappe.db.get_value(
					"DocField",
					{"parent": "Purchase Receipt", "fieldname": "naming_series"},
					"options",
				)
				or ""
			),
			"the MAT-PR-RET return series was destroyed",
		),
	)

	supplier = ensure_supplier()
	item_a = ensure_item(f"PITEST-RM-A-{SEQ}", shelf_life_days=180)
	item_b = ensure_item(f"PITEST-RM-B-{SEQ}")

	# --- the gate: only an approved, non-direct-invoice PO ----------------
	draft_po = frappe.new_doc("Purchase Order")
	draft_po.supplier = supplier
	draft_po.company = COMPANY
	draft_po.transaction_date = today()
	draft_po.schedule_date = add_days(today(), 7)
	draft_po.custom_inward_type = C.INWARD_RM
	draft_po.append(
		"items",
		{"item_code": item_a, "qty": 10, "rate": 5,
		 "schedule_date": add_days(today(), 7), "warehouse": _warehouse()},
	)
	draft_po.insert(ignore_permissions=True)
	expect_throw(
		"VAL-PO-15 draft PO cannot be inwarded",
		lambda: make_inward(draft_po, draft_po.items),
		"Approved Purchase Order",
	)

	direct_po = make_po(supplier, [(item_a, 10, 5)], direct_invoice=1)
	expect_throw(
		"VAL-PO-13 direct-invoice PO cannot be inwarded",
		lambda: make_inward(direct_po, direct_po.items),
		"Direct Purchase Invoice",
	)

	# --- the happy path ---------------------------------------------------
	po = make_po(supplier, [(item_a, 1000, 25), (item_b, 500, 40)])
	pi1 = make_inward(po, po.items)

	check(
		"inward fetched PO header",
		lambda: _assert(
			pi1.supplier == supplier and pi1.inward_type == C.INWARD_RM,
			f"supplier={pi1.supplier} type={pi1.inward_type}",
		),
	)
	check(
		"first inward: pending == ordered",
		lambda: _assert(
			flt(pi1.items[0].previously_received_qty) == 0
			and flt(pi1.items[0].pending_qty) == 1000,
			f"prev={pi1.items[0].previously_received_qty} pending={pi1.items[0].pending_qty}",
		),
	)

	# duplicate invoice number for the same vendor (BR-PI-15)
	expect_throw(
		"VAL-PI-15 duplicate invoice number blocked",
		lambda: make_inward(po, po.items, invoice_no=pi1.invoice_number),
		"already exists for this Vendor",
	)

	pi1.submit()
	check(
		"submit -> Pending Material Receipt",
		lambda: _assert(
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status")
			== C.PI_PENDING_RECEIPT,
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status"),
		),
	)

	# --- store receipt ----------------------------------------------------
	pi1.reload()
	pi1.actual_arrival_datetime = now_datetime()
	pi1.target_warehouse = _warehouse()
	pi1.items[0].received_qty = 600
	pi1.items[0].manufacturing_date = today()
	pi1.items[1].received_qty = 500

	# over-receipt without the tick (VAL-PI-07)
	pi1.items[0].received_qty = 1200
	expect_throw(
		"VAL-PI-07 over-receipt blocked without Allow Excess",
		lambda: pi1.save(ignore_permissions=True),
		"cannot be greater than Pending",
	)

	pi1.reload()
	pi1.actual_arrival_datetime = now_datetime()
	pi1.target_warehouse = _warehouse()
	pi1.items[0].received_qty = 600
	pi1.items[0].manufacturing_date = today()
	pi1.items[0].target_warehouse = _warehouse()
	pi1.items[1].received_qty = 500
	pi1.items[1].target_warehouse = _warehouse()
	pi1.save(ignore_permissions=True)

	check(
		"expiry derived from shelf life",
		lambda: _assert(
			str(pi1.items[0].expiry_date) == str(add_days(today(), 180)),
			f"expiry={pi1.items[0].expiry_date}",
		),
	)
	check(
		"totals rolled up",
		lambda: _assert(flt(pi1.total_received_qty) == 1100, str(pi1.total_received_qty)),
	)

	# --- second inward sees the first one's receipt (task 298) ------------
	pi2 = make_inward(po, [po.items[0]], invoice_no=f"PITEST-INV-{SEQ}-B")
	check(
		"BR-PI-11 previously received carried across inwards",
		lambda: _assert(
			flt(pi2.items[0].previously_received_qty) == 600
			and flt(pi2.items[0].pending_qty) == 400,
			f"prev={pi2.items[0].previously_received_qty} "
			f"pending={pi2.items[0].pending_qty}",
		),
	)

	# --- PO rollup --------------------------------------------------------
	check(
		"PO inward progress refreshed",
		lambda: _assert(
			flt(frappe.db.get_value("Purchase Order", po.name, "custom_total_inward_qty"))
			> 0,
			"custom_total_inward_qty still zero",
		),
	)

	# ================= hand over to QC (task 302) =========================
	from alpinos.purchase import grn as grn_mod
	from alpinos.purchase import notifications as notif
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

	qc_name = [None]

	def _submit_for_qc():
		res = notif.submit_for_qc(pi1.name)
		qc_name[0] = res if isinstance(res, str) else (
			res.get("purchase_qc") if isinstance(res, dict) else None
		)
		if not qc_name[0]:
			qc_name[0] = frappe.db.get_value("Purchase Inward", pi1.name, "purchase_qc")
		_assert(qc_name[0], "no Purchase QC was created")

	check("submit_for_qc raises a Purchase QC", _submit_for_qc)

	check(
		"inward moved to Pending QC",
		lambda: _assert(
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status")
			== C.PI_PENDING_QC,
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status"),
		),
	)

	check(
		"BR-QC-03 SLA clock started",
		lambda: _assert(
			frappe.db.get_value("Purchase QC", qc_name[0], "sla_due"),
			"sla_due not set",
		),
	)

	check(
		"QC seeded one item row per received line",
		lambda: _assert(
			frappe.db.count("Purchase QC Item", {"parent": qc_name[0]}) == 2,
			str(frappe.db.count("Purchase QC Item", {"parent": qc_name[0]})),
		),
	)

	# --- BRD 2.3: QC must be STARTED before it can be completed -----------
	check("start_qc moves the inward to QC In Progress", lambda: (
		qc_mod.start_qc(qc_name[0]),
		_assert(
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status")
			== C.PI_QC_IN_PROGRESS,
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status"),
		),
	))

	# --- the QC decision (tasks 310, 311) ---------------------------------
	def _qc_reconciliation_blocks():
		qc = frappe.get_doc("Purchase QC", qc_name[0])
		qc.items[0].approved_qty = flt(qc.items[0].received_qty) - 10
		qc.items[0].rejected_qty = 0  # deliberately does not reconcile
		qc.save(ignore_permissions=True)

	expect_throw(
		"VAL-QC-08 approved + rejected must equal received",
		_qc_reconciliation_blocks,
	)

	def _qc_rejection_needs_reason():
		qc = frappe.get_doc("Purchase QC", qc_name[0])
		qc.items[0].approved_qty = flt(qc.items[0].received_qty) - 10
		qc.items[0].rejected_qty = 10
		qc.items[0].rejection_reason = None
		qc.save(ignore_permissions=True)

	expect_throw(
		"VAL-QC-04 rejected qty needs a rejection reason",
		_qc_rejection_needs_reason,
		"Reason",
	)

	def _qc_partial():
		qc = frappe.get_doc("Purchase QC", qc_name[0])
		qc.items[0].approved_qty = flt(qc.items[0].received_qty) - 10
		qc.items[0].rejected_qty = 10
		qc.items[0].rejection_reason = "Moisture above spec"
		qc.items[1].approved_qty = flt(qc.items[1].received_qty)
		qc.items[1].rejected_qty = 0
		# BRD 4.1.2 - 4.1.5: the four inspections run in parallel, each with its own
		# completion flag (BR-QC-05 / BR-QC-06).
		qc.vehicle_inspection = []
		qc.append("vehicle_inspection", {"vehicle_condition": C.CONDITION_GOOD})
		qc.vehicle_inspection_done = 1

		qc.material_inspection = []
		qc.append("material_inspection", {
			"item_code": item_a,
			"material_condition": C.CONDITION_DAMAGED,
			"material_damage": 1,
			"damaged_qty": 10,
			"damage_reason": "Moisture above spec",
		})
		qc.material_inspection_done = 1

		qc.packaging_inspection = []
		qc.append("packaging_inspection", {
			"item_code": item_a,
			"packaging_condition": C.CONDITION_GOOD,
		})
		qc.packaging_inspection_done = 1

		qc.sample_testing = []
		qc.append("sample_testing", {"item_code": item_a, "sample_qty": 5})
		qc.sample_testing_done = 1

		qc.save(ignore_permissions=True)
		qc.reload()
		_assert(
			qc.qc_result == C.QC_RESULT_PARTIAL,
			f"expected Partially Approved, got {qc.qc_result}",
		)

	check("BRD 4.6.2 result derives to Partially Approved", _qc_partial)

	# --- complete QC -> draft GRN (tasks 299, 5.x) ------------------------
	def _complete():
		qc_mod.complete_qc(qc_name[0])

	check("complete_qc submits the inspection", _complete)

	check(
		"QC reached QC Completed",
		lambda: _assert(
			frappe.db.get_value("Purchase QC", qc_name[0], "docstatus") == 1,
			"QC not submitted",
		),
	)

	pr_name = [None]

	def _grn_exists():
		pr_name[0] = frappe.db.get_value("Purchase Inward", pi1.name, "purchase_receipt")
		if not pr_name[0]:
			pr_name[0] = grn_mod.generate_grn(pi1.name)
			if not isinstance(pr_name[0], str):
				pr_name[0] = frappe.db.get_value(
					"Purchase Inward", pi1.name, "purchase_receipt"
				)
		_assert(pr_name[0], "no Purchase Receipt was generated")

	check("BR-GRN-03 draft GRN generated", _grn_exists)

	check(
		"GRN is Draft, not submitted",
		lambda: _assert(
			frappe.db.get_value("Purchase Receipt", pr_name[0], "docstatus") == 0,
			"GRN should be Draft until Admin final-submits (BR-GRN-06)",
		),
	)

	check(
		"GRN uses the GRN- naming series",
		lambda: _assert(
			pr_name[0].startswith("GRN-"), f"GRN named {pr_name[0]}"
		),
	)

	def _grn_qty_mapping():
		pr = frappe.get_doc("Purchase Receipt", pr_name[0])
		row = next(r for r in pr.items if r.item_code == item_a)
		# qty IS the accepted quantity; received_qty is forced to qty + rejected_qty
		_assert(
			flt(row.qty) == 590 and flt(row.rejected_qty) == 10,
			f"qty={row.qty} rejected={row.rejected_qty} (expected 590 / 10)",
		)
		_assert(
			flt(row.received_qty) == 600,
			f"received_qty={row.received_qty} (expected 600)",
		)

	check("GRN maps approved->qty and rejected->rejected_qty", _grn_qty_mapping)

	expect_throw(
		"BR-GRN-02 a second generate_grn is refused",
		lambda: grn_mod.generate_grn(pi1.name),
		"not available",
	)
	check(
		"BR-GRN-02 exactly one live GRN exists",
		lambda: _assert(
			frappe.db.count(
				"Purchase Receipt",
				{"custom_purchase_inward": pi1.name, "docstatus": ("<", 2)},
			)
			== 1,
			str(
				frappe.db.count(
					"Purchase Receipt", {"custom_purchase_inward": pi1.name}
				)
			),
		),
	)

	def _rejected_wh():
		pr = frappe.get_doc("Purchase Receipt", pr_name[0])
		row = next(r for r in pr.items if flt(r.rejected_qty) > 0)
		_assert(
			row.rejected_warehouse == "Rejected - AHF",
			f"rejected_warehouse={row.rejected_warehouse}",
		)

	check("rejected qty routed to the Rejected warehouse", _rejected_wh)

	# --- Admin final submit (BR-GRN-06 / VAL-GRN-04) ----------------------
	def _submit_grn():
		pr = frappe.get_doc("Purchase Receipt", pr_name[0])
		pr.submit()
		_assert(pr.docstatus == 1, "GRN did not submit")

	check("BR-GRN-06 Admin final-submits the GRN", _submit_grn)

	def _stock_split():
		"""Approved stock to the target warehouse, rejected stock to Rejected."""
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": pr_name[0], "is_cancelled": 0},
			fields=["item_code", "warehouse", "actual_qty"],
		)
		_assert(sles, "the GRN posted no Stock Ledger Entries")
		rej = [s for s in sles if s.warehouse == "Rejected - AHF"]
		_assert(rej, "nothing landed in the Rejected warehouse")
		_assert(
			flt(rej[0].actual_qty) == 10,
			f"Rejected warehouse got {rej[0].actual_qty}, expected 10",
		)

	check("BR-QC-09 rejected qty excluded from usable stock", _stock_split)

	check(
		"inward reached GRN Generated",
		lambda: _assert(
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status")
			in (C.PI_GRN_GENERATED, C.PI_PAYMENT_PENDING),
			frappe.db.get_value("Purchase Inward", pi1.name, "inward_status"),
		),
	)

	# --- print formats render (tasks 296, 312) ----------------------------
	def _render(pf, dt, name):
		from frappe.www.printview import get_html_and_style

		out = get_html_and_style(doc=frappe.get_doc(dt, name).as_json(), print_format=pf)
		_assert(out and out.get("html"), f"{pf} rendered nothing")

	check("print format: Purchase Inward renders",
	      lambda: _render("Purchase Inward", "Purchase Inward", pi1.name))
	check("print format: QC Inspection Report renders",
	      lambda: _render("QC Inspection Report", "Purchase QC", qc_name[0]))

	_report()
	return R


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)
	return True


def _report():
	width = max((len(r[1]) for r in R), default=10) + 2
	print("\n" + "=" * (width + 30))
	print("Purchase Inward end-to-end")
	print("=" * (width + 30))
	for status, label, detail in R:
		mark = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR "}[status]
		print(f"[{mark}] {label.ljust(width)} {detail}")
	fails = [r for r in R if r[0] != "PASS"]
	print("-" * (width + 30))
	print(f"{len(R) - len(fails)}/{len(R)} passed")
	if fails:
		print(f"{len(fails)} NOT passing")
