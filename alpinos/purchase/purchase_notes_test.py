"""Purchase Module Meeting Notes (26 Nov 2026): points 3, 4, 6, 7, 8, 9, 10.
TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.purchase.purchase_notes_test.run
"""

import frappe
from frappe.utils import nowdate

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")
		frappe.clear_messages()


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _item(kind):
	"""An enabled stock item of an inward type (RM / PM / FG)."""
	from alpinos.purchase.inward_api import item_inward_type

	cache = {}
	for name in frappe.get_all("Item", filters={"disabled": 0, "has_variants": 0, "is_stock_item": 1}, pluck="name", limit=600):
		if item_inward_type(name, cache) == kind:
			return name
	return None


def _run():
	from alpinos.purchase import constants as C

	# ---------------------------------------------------------------- point 4
	def _inward_optional():
		from alpinos.purchase import workflow

		rm = _item(C.INWARD_RM) or _item(C.INWARD_PM)
		wh = frappe.db.get_value("Warehouse", {"is_group": 0}, "name")
		doc = frappe.new_doc("Purchase Inward")
		doc.inward_type = C.INWARD_RM
		doc.vehicle_details_verified = 1
		doc.actual_vehicle_no = None
		doc.actual_driver_contact_no = None
		doc.actual_arrival_datetime = None
		doc.append("items", {"item_code": rm, "received_qty": 5, "target_warehouse": wh, "manufacturing_date": nowdate()})
		reason = workflow.receiving_incomplete_reason(doc) or ""
		_assert("arrival" not in reason.lower() and "vehicle" not in reason.lower(), reason)
		guard = workflow._guard_receiving_complete(doc) or ""
		_assert("arrival" not in guard.lower(), guard)

	check("Inward: Actual Arrival, Vehicle No. and Driver Contact are not demanded at Submit for QC", _inward_optional)

	def _arrival_stamped_in_code():
		import inspect

		from alpinos.purchase import notifications

		src = inspect.getsource(notifications.submit_for_qc)
		_assert('"actual_arrival_datetime": inward.actual_arrival_datetime or now' in src, "not stamped")

	check("Inward: Submit for QC fills a blank Actual Arrival with the hand-over time", _arrival_stamped_in_code)

	# ------------------------------------------------------------ points 6, 7
	def _qc_mandatory():
		def missing(kind):
			qc = frappe.new_doc("Purchase QC")
			qc.inward_type = kind
			return qc._missing_inspections()

		_assert(missing(C.INWARD_RM) == ["Packaging / Box Inspection", "Material Inspection", "Sample Testing"], missing(C.INWARD_RM))
		_assert(missing(C.INWARD_FG) == ["Packaging / Box Inspection", "Material Inspection", "Sample Testing"], missing(C.INWARD_FG))
		_assert(missing(C.INWARD_PM) == ["Packaging / Box Inspection", "Material Inspection"], missing(C.INWARD_PM))
		qc = frappe.new_doc("Purchase QC")
		qc.inward_type = C.INWARD_RM
		qc.packaging_inspection_done = qc.material_inspection_done = qc.sample_testing_done = 1
		_assert(qc._missing_inspections() == [], "vehicle still demanded")

	check("QC: Vehicle optional; Packing, Material mandatory; Sample Testing for FG and RM, not PM", _qc_mandatory)

	def _qc_order():
		order = [f.fieldname for f in frappe.get_meta("Purchase QC").fields if f.fieldname in
			("vehicle_section", "packaging_section", "material_section", "sample_section")]
		_assert(order == ["vehicle_section", "packaging_section", "material_section", "sample_section"], order)

	check("QC: sections run Vehicle, Packing / Box, Material, Sample Testing", _qc_order)

	def _sample_uom():
		from alpinos.purchase.qc_sample_uom import get_sample_conversion

		item = _item(C.INWARD_RM) or _item(C.INWARD_PM)
		_assert(get_sample_conversion(item, "Kg", "Kg") == 1)
		g_to_kg = get_sample_conversion(item, "Gram", "Kg")
		qc = frappe.new_doc("Purchase QC")
		qc.inward_type = C.INWARD_RM
		line = qc.append("items", {"item_code": item, "uom": "Kg", "received_qty": 10})
		line.name = "pn-line-1"
		row = qc.append("sample_testing", {"item_code": item, "qc_item": "pn-line-1", "sample_qty": 200, "uom": "Gram"})
		if g_to_kg:
			qc._roll_up_sample_qty()
			_assert(abs(g_to_kg - 0.001) < 1e-9, g_to_kg)
			_assert(abs(row.qty_in_line_uom - 0.2) < 1e-6 and abs(line.sample_qty - 0.2) < 1e-6, (row.qty_in_line_uom, line.sample_qty))
		row.conversion_factor = 0.5
		row.uom = "Nos"
		qc._roll_up_sample_qty()
		_assert(abs(line.sample_qty - 100) < 1e-6, f"typed factor not used: {line.sample_qty}")
		same = qc.append("sample_testing", {"item_code": item, "qc_item": "pn-line-1", "sample_qty": 1})
		qc._roll_up_sample_qty()
		_assert(same.uom == "Kg" and same.conversion_factor == 1 and abs(line.sample_qty - 101) < 1e-6, line.sample_qty)

	check("QC: a sample in another UOM counts on the line in the received UOM", _sample_uom)

	# ---------------------------------------------------------------- point 8
	def _logistic_status():
		from alpinos.purchase.purchase_invoice import _payable_logistics

		doc = frappe._dict(custom_include_logistics="Yes", custom_freight_amount=1000)
		_assert(_payable_logistics(doc) == 1000, "Pending")
		doc.custom_logistics_payment_status = "Partial"
		doc.custom_logistics_paid_amount = 300
		_assert(_payable_logistics(doc) == 700, "Partial")
		doc.custom_logistics_payment_status = "Paid"
		_assert(_payable_logistics(doc) == 0, "Paid shows nothing pending")
		doc.custom_include_logistics = "No"
		doc.custom_logistics_payment_status = "Pending"
		_assert(_payable_logistics(doc) == 0, "no logistics")

	check("Invoice: Logistic Payment Status Pending = freight, Partial = freight - paid, Paid = 0", _logistic_status)

	# ----------------------------------------------------------- points 9, 10
	def _grn_needs_invoice():
		from alpinos.purchase.purchase_receipt_fields import validate_grn_completeness

		pr = frappe.new_doc("Purchase Receipt")
		pr.custom_purchase_inward = "PN-TEST"
		try:
			validate_grn_completeness(pr)
		except frappe.ValidationError as e:
			_assert("Supplier Invoice" in str(e), str(e))
		else:
			raise AssertionError("submitted without anything")
		pr.custom_grn_attachment = "/files/supplier-invoice.pdf"
		try:
			validate_grn_completeness(pr)
		except frappe.ValidationError as e:
			_assert("Supplier Invoice" not in str(e), "still demanded with the invoice attached")

	check("GRN: cannot be submitted without the Supplier Invoice attached", _grn_needs_invoice)

	def _checkpoints():
		from alpinos.purchase.purchase_invoice import invoice_checkpoints

		pr = frappe.new_doc("Purchase Receipt")
		pr.docstatus = 1
		pr.append("items", {"item_code": "X", "qty": 5, "rejected_qty": 0})
		pts = {p["key"]: p["ok"] for p in invoice_checkpoints(pr)}
		_assert(pts == {"grn_submitted": True, "supplier_invoice": False, "debit_note": True}, pts)
		pr.custom_grn_attachment = "/files/inv.pdf"
		pr.items[0].rejected_qty = 2
		pts = {p["key"]: p["ok"] for p in invoice_checkpoints(pr)}
		_assert(pts == {"grn_submitted": True, "supplier_invoice": True, "debit_note": False}, pts)

	check("Invoice checkpoints: GRN submitted, invoice attached, Debit Note when QC rejected qty", _checkpoints)

	def _create_refused():
		from alpinos.purchase.purchase_invoice import create_from_grn

		grn = frappe.db.sql(
			"""select pr.name from `tabPurchase Receipt` pr
			   where pr.docstatus = 1 and ifnull(pr.custom_purchase_inward, '') != ''
			     and not exists (select 1 from `tabPurchase Invoice` pi where pi.custom_grn = pr.name and pi.docstatus < 2)
			   limit 1""",
			pluck=True,
		)
		if not grn:
			return
		frappe.db.set_value("Purchase Receipt", grn[0], "custom_grn_attachment", None)
		try:
			create_from_grn(grn[0])
		except frappe.ValidationError as e:
			_assert("Supplier Invoice" in str(e), str(e))
		else:
			raise AssertionError("invoice created without the supplier invoice")

	check("Invoice: Create Invoice from a GRN is refused while a checkpoint is red", _create_refused)

	def _invoice_takes_attachment():
		import inspect

		from alpinos.purchase import purchase_invoice

		src = inspect.getsource(purchase_invoice.create_from_grn)
		_assert("invoice.custom_invoice_attachment = grn.custom_grn_attachment" in src)

	check("Invoice: the Purchase Invoice takes over the GRN's Supplier Invoice", _invoice_takes_attachment)

	# ---------------------------------------------------------------- point 3
	def _supplier_terms():
		po = frappe.db.get_value("Purchase Order", {"docstatus": ["<", 2]}, ["name", "supplier"], as_dict=True, order_by="creation desc")
		_assert(po, "no Purchase Order on this site")
		sup = frappe.get_doc("Supplier", po.supplier)
		sup.set("custom_supplier_instructions", [
			{"instruction": "Deliver between 9 AM and 5 PM only."},
			{"instruction": "Pallets must be shrink-wrapped."},
		])
		sup.flags.ignore_permissions = True
		sup.flags.ignore_mandatory = True
		sup.save()
		from alpinos.purchase.supplier_terms import supplier_instructions

		_assert(supplier_instructions(po.supplier) == ["Deliver between 9 AM and 5 PM only.", "Pallets must be shrink-wrapped."])
		from alpinos.purchase.print_formats import PO_PF_NAME

		html = frappe.get_print("Purchase Order", po.name, PO_PF_NAME)
		_assert("SUPPLIER INSTRUCTIONS" in html and "1. Deliver between 9 AM and 5 PM only." in html
			and "2. Pallets must be shrink-wrapped." in html, "instructions missing on the PO print")

	check("Supplier T&C table prints on the supplier's Purchase Orders, numbered", _supplier_terms)
