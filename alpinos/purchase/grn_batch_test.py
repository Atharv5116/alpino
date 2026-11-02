"""A batch-tracked finished-goods item through Inward, QC and the GRN. Run on a TEST site:

	bench --site <test site> execute alpinos.purchase.grn_batch_test.run

The item is set up like C-C-1000 on UAT: Has Batch No, Has Expiry Date with a shelf life, and
no "Automatically Create New Batch". Store types the supplier's batches on the inward; QC needs
no Internal Batch Code for finished goods. Before the fix no Batch was ever made for those
batches, so every GRN row was left without a Batch Number and the final submit was refused
(VAL-GRN-03 / VAL-QC-20).

Records are prefixed PITEST-GB and stay on the site; every run makes a fresh set.
"""

import frappe
from frappe.utils import add_days, cint, flt, getdate, today

from alpinos.mrp_batch_test import _complete_qc, _receive_split
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
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _batch_item(code):
	from alpinos.production import material_type as MT

	if not frappe.db.exists("Item", code):
		group = frappe.get_all(
			"Item Group", filters={"name": ("in", MT.groups_of_type("FG")), "is_group": 0}, pluck="name", limit=1
		)[0]
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": group,
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"has_batch_no": 1,
				"create_new_batch": 0,
				"has_expiry_date": 1,
				"shelf_life_in_days": 365,
				"custom_gst_percent": 5,
				**H._test_hsn(),
			}
		).insert(ignore_permissions=True)
	return code


def run():
	R.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	H.COMPANY = H._company()
	seq = "GB" + frappe.generate_hash(length=5).upper()
	H.SEQ = seq
	wh = frappe.db.get_value("Warehouse", {"company": H.COMPANY, "is_group": 0, "name": ("like", "Stores%")}, "name") or H._warehouse()
	item = _batch_item(f"PITEST-GB-{seq}")
	b1, b2 = f"{seq}/23/10", f"{seq}/24/10"
	mfg1, mfg2 = add_days(today(), -10), add_days(today(), -5)

	supplier = H.ensure_supplier()
	po = H.make_po(supplier, [(item, 100, 80)], inward_type=C.INWARD_FG)
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-GB-{seq}")
	inw.submit()
	inw = _receive_split(inw, wh, [(60, b1, 199, mfg1), (40, b2, 199, mfg2)], line_qty=100)

	# QC: no Internal Batch Code (finished goods); part of the first batch quarantined, so it
	# arrives on the GRN as two rows, like GRN-2627-00007 on UAT.
	qc = _complete_qc(frappe.get_doc("Purchase Inward", inw.name), {b1: (60, 0), b2: (30, 10)}, quarantine={b1: 20})
	check("QC completes with no Internal Batch Code on finished goods", lambda: _assert(
		qc.qc_status == C.QC_COMPLETED and not any((r.internal_batch_no or "").strip() for r in qc.items),
		[(r.supplier_batch_no, r.internal_batch_no) for r in qc.items]))

	pr_name = frappe.db.get_value("Purchase Receipt", {"custom_purchase_inward": inw.name, "docstatus": 0}, "name")
	check("a draft GRN was raised", lambda: _assert(pr_name, "no draft GRN"))
	if not pr_name:
		return _report()
	pr = frappe.get_doc("Purchase Receipt", pr_name)
	rows = [(r.custom_internal_batch_no, r.batch_no, flt(r.qty)) for r in pr.items]
	check("every GRN row links a Batch (the supplier batch Store typed)", lambda: _assert(
		all(r.batch_no for r in pr.items) and sorted({r.batch_no for r in pr.items}) == sorted({b1, b2}), rows))
	check("the quarantined part and the free part carry the same batch", lambda: _assert(
		[r.batch_no for r in pr.items].count(b1) == 2, rows))
	for code, mfg in ((b1, mfg1), (b2, mfg2)):
		batch = frappe.db.get_value("Batch", code, ["item", "manufacturing_date", "expiry_date", "reference_doctype", "reference_name"], as_dict=True) or {}
		check(f"Batch {code} belongs to the item, with its manufacturing date", lambda batch=batch, mfg=mfg: _assert(
			batch.get("item") == item and getdate(batch.get("manufacturing_date")) == getdate(mfg), batch))
		check(f"Batch {code} expiry follows the shelf life", lambda batch=batch, mfg=mfg: _assert(
			getdate(batch.get("expiry_date")) == getdate(add_days(mfg, 365)), batch))
		check(f"Batch {code} points back to the inward", lambda batch=batch: _assert(
			batch.get("reference_doctype") == "Purchase Inward" and batch.get("reference_name") == inw.name, batch))

	# A Draft GRN raised before this fix has no Batch on its rows: the next save fills it in.
	row = pr.items[0]
	expected = row.batch_no
	row.batch_no = None
	pr.save(ignore_permissions=True)
	check("an old draft's empty Batch is filled on save", lambda: _assert(
		frappe.db.get_value("Purchase Receipt Item", row.name, "batch_no") == expected,
		frappe.db.get_value("Purchase Receipt Item", row.name, "batch_no")))

	# A batch typed on the GRN screen is made, not refused by the Batch link check.
	from alpinos.purchase import grn_edit

	typed = f"{seq}/TYPED"
	pr = frappe.get_doc("Purchase Receipt", pr_name)
	last = pr.items[-1]
	try:
		grn_edit._apply(pr, {"items": [{"name": last.name, "batch_no": typed}]})
		pr.save(ignore_permissions=True)
	except Exception as e:
		# the Batch link check refuses before anything is written
		R.append(("FAIL", "a batch typed on the GRN screen is saved", f"{type(e).__name__}: {e}"))
	check("a batch typed on the GRN screen is created and linked", lambda: _assert(
		frappe.db.get_value("Purchase Receipt Item", last.name, "batch_no") == typed
		and frappe.db.get_value("Batch", typed, "item") == item,
		frappe.db.get_value("Purchase Receipt Item", last.name, "batch_no")))

	# The final submit now goes through and the stock lands in those batches.
	pr = frappe.get_doc("Purchase Receipt", pr_name)
	try:
		pr.submit()
		submitted = True
	except Exception as e:
		submitted = f"{type(e).__name__}: {e}"
	check("the GRN final-submits (no VAL-GRN-03 for the Batch Number)", lambda: _assert(submitted is True, submitted))
	if submitted is True:
		ledger = frappe.db.sql(
			"""select sbe.batch_no, sum(sbe.qty) from `tabSerial and Batch Entry` sbe
			join `tabSerial and Batch Bundle` sbb on sbb.name = sbe.parent
			where sbb.voucher_no = %s and sbb.is_cancelled = 0 and sbb.docstatus = 1 group by sbe.batch_no""",
			pr_name,
		)
		got = {b: flt(q) for b, q in ledger}
		check("stock is received into the batches the GRN names", lambda: _assert(
			set(got) >= {b1, typed} and abs(sum(got.values()) - 100) < 0.001, got))

	# A code that needs an expiry nobody can work out is left for the GRN check to name.
	try:
		from alpinos.purchase.batches import ensure_batch
	except ImportError:  # code from before the fix
		R.append(("FAIL", "alpinos.purchase.batches exists", "not found"))
		return _report()

	frappe.db.set_value("Item", item, "shelf_life_in_days", 0)
	frappe.clear_document_cache("Item", item)
	check("no shelf life and no expiry date: no Batch is made", lambda: _assert(
		ensure_batch(item, f"{seq}/NOEXP") is None and not frappe.db.exists("Batch", f"{seq}/NOEXP")))
	frappe.db.set_value("Item", item, "shelf_life_in_days", 365)
	check("an item that is not batch tracked gets no Batch", lambda: _assert(
		ensure_batch(frappe.db.get_value("Item", {"has_batch_no": 0, "is_stock_item": 1}, "name"), f"{seq}/X") is None))
	return _report()


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R
