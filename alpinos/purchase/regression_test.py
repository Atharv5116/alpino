"""Regression tests for the defects found by the Purchase Inward audit (run on a TEST site).

Run:  bench --site alpinos.test execute alpinos.purchase.regression_test.run

Each test names the defect it pins down. They are written so that reverting the fix makes
the test fail, not merely so they pass today. Records are prefixed PITEST and reuse the
e2e harness, so re-runs mint a fresh set.
"""

import frappe
from frappe.utils import add_days, cint, flt, now_datetime, today

from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H
from alpinos.purchase import workflow

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


def _receive(inward, per_row_qty, mfg=None):
	"""Record a Store receipt on a submitted inward, the way the desk form does."""
	inward.actual_arrival_datetime = now_datetime()
	# VAL-PI-05: ticking "verified" means the fetched details were WRONG and the
	# corrected ones must be supplied, so give both rather than only the tick.
	inward.vehicle_details_verified = 1
	inward.actual_vehicle_no = "GJ-05-ZZ-9999"
	inward.actual_driver_contact_no = "9000000001"
	for row in inward.items:
		row.received_qty = per_row_qty
		row.target_warehouse = H._warehouse()
		if mfg:
			row.manufacturing_date = mfg
	inward.flags.ignore_permissions = True
	inward.save()
	return inward


def run(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")

	supplier = H.ensure_supplier()
	item_a = H.ensure_item(f"PITEST-REG-A-{H.SEQ}", shelf_life_days=180)
	item_b = H.ensure_item(f"PITEST-REG-B-{H.SEQ}")

	# ---------------------------------------------------------------- H7
	# Derived values were computed in on_update_after_submit, which frappe runs AFTER
	# db_update() has flushed the row, so every one of them was silently discarded.
	po = H.make_po(supplier, [(item_a, 1000, 10), (item_b, 500, 20)])
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-REG-INV-{H.SEQ}")
	inw.submit()
	inw.reload()
	_receive(inw, 400, mfg=today())
	fresh = frappe.get_doc("Purchase Inward", inw.name)

	def h7_expiry():
		row = next(r for r in fresh.items if r.item_code == item_a)
		want = add_days(today(), 180)
		assert str(row.expiry_date) == str(want), (
			f"expiry_date {row.expiry_date!r} not persisted (expected {want})"
		)

	def h7_totals():
		assert flt(fresh.total_received_qty) == 800.0, (
			f"total_received_qty {fresh.total_received_qty} not persisted (expected 800)"
		)

	def h7_stock_qty():
		row = next(r for r in fresh.items if r.item_code == item_a)
		assert flt(row.stock_qty) == 400.0, f"stock_qty {row.stock_qty} not persisted"

	check("H7 expiry date survives the reload", h7_expiry)
	check("H7 total_received_qty survives the reload", h7_totals)
	check("H7 stock_qty survives the reload", h7_stock_qty)

	# ---------------------------------------------------------------- H3
	# set_status writes with db_set, which never enters the save path, so the Purchase
	# Order rollup was never refreshed after a transition.
	def h3_rollup():
		workflow.set_status(frappe.get_doc("Purchase Inward", inw.name), C.PI_PENDING_QC)
		frappe.db.commit()
		po_status = frappe.db.get_value("Purchase Order", po.name, "custom_inward_status")
		assert po_status == C.PI_PENDING_QC, (
			f"Purchase Order shows {po_status!r} after a transition to {C.PI_PENDING_QC!r}"
		)

	check("H3 Purchase Order rollup follows a transition", h3_rollup)

	# ---------------------------------------------------------------- H4
	# inward_status / the downstream links are read_only + allow_on_submit; read_only is
	# a client-side hint only, so a REST write could drive the whole workflow.
	expect_throw(
		"H4 inward_status cannot be set through the REST API",
		lambda: frappe.client.set_value("Purchase Inward", inw.name, "inward_status", C.PI_COMPLETED),
		"cannot be edited directly",
	)
	frappe.db.rollback()

	# A REAL receipt: a non-existent name would trip frappe's link validation first and
	# never reach the guard under test.
	real_grn = frappe.db.get_value("Purchase Receipt", {"docstatus": ("<", 2)}, "name")
	if real_grn:
		expect_throw(
			"H4 purchase_receipt link cannot be set through the REST API",
			lambda: frappe.client.set_value(
				"Purchase Inward", inw.name, "purchase_receipt", real_grn
			),
			"cannot be edited directly",
		)
		frappe.db.rollback()
	else:
		R.append(("SKIP", "H4 purchase_receipt link cannot be set through the REST API",
		          "no Purchase Receipt on this site"))

	def h4_engine_still_moves():
		workflow.set_status(frappe.get_doc("Purchase Inward", inw.name), C.PI_QC_IN_PROGRESS)
		frappe.db.commit()
		got = frappe.db.get_value("Purchase Inward", inw.name, "inward_status")
		assert got == C.PI_QC_IN_PROGRESS, f"engine transition blocked: status is {got!r}"

	def h4_ordinary_edit_still_saves():
		d = frappe.get_doc("Purchase Inward", inw.name)
		d.items[0].item_remarks = "regression probe"
		d.flags.ignore_permissions = True
		d.save()
		frappe.db.commit()

	check("H4 the workflow engine can still move the status", h4_engine_still_moves)
	check("H4 an ordinary Store edit still saves", h4_ordinary_edit_still_saves)

	# ---------------------------------------------------------------- H10
	# Two rows against one PO line each saw the FULL pending quantity, so 100 + 100
	# against an order of 100 passed VAL-PI-07 with excess_qty 0.
	po2 = H.make_po(supplier, [(item_a, 100, 10)])
	frappe.db.commit()  # the rollback below must not discard this fixture
	dup = frappe.new_doc("Purchase Inward")
	dup.purchase_order = po2.name
	dup.invoice_number = f"PITEST-REG-DUP-{H.SEQ}"
	dup.invoice_date = today()
	dup.inward_datetime = now_datetime()
	for _ in range(2):
		dup.append("items", {"item_code": item_a, "po_detail": po2.items[0].name})

	expect_throw(
		"H10 two rows against one PO line are refused",
		lambda: dup.insert(ignore_permissions=True),
		"same Purchase Order line",
	)
	frappe.db.rollback()

	def h10_single_row_ok():
		ok = frappe.new_doc("Purchase Inward")
		ok.purchase_order = po2.name
		ok.invoice_number = f"PITEST-REG-OK-{H.SEQ}"
		ok.invoice_date = today()
		ok.inward_datetime = now_datetime()
		ok.append("items", {"item_code": item_a, "po_detail": po2.items[0].name})
		ok.insert(ignore_permissions=True)
		frappe.db.commit()

	check("H10 a single row against that PO line still inserts", h10_single_row_ok)

	# ---------------------------------------------------------------- H11
	# The form offered enabled Start QC / Complete QC / Create Purchase Invoice buttons
	# whose only outcome was "... cannot be run from the Purchase Inward form."
	def h11_invoice_greyed_out():
		stub = frappe.get_doc("Purchase Inward", inw.name)
		stub.inward_status = C.PI_GRN_GENERATED
		actions = {a["action"]: a for a in workflow.available_actions(stub)}
		act = actions.get("create_purchase_invoice")
		assert act, "create_purchase_invoice not offered at GRN Generated"
		assert not act["enabled"], "create_purchase_invoice is still offered as enabled"
		assert act["reason"], "create_purchase_invoice is disabled with no reason shown"

	def h11_qc_actions_dispatch():
		from alpinos.purchase.inward_api import QC_ACTION_ENDPOINTS

		assert "start_qc" in QC_ACTION_ENDPOINTS and "complete_qc" in QC_ACTION_ENDPOINTS, (
			"QC transitions have no endpoint, so run_action still dead-ends"
		)
		for path in QC_ACTION_ENDPOINTS.values():
			assert callable(frappe.get_attr(path)), f"{path} is not importable"

	check("H11 Create Purchase Invoice is greyed out with a reason", h11_invoice_greyed_out)
	check("H11 Start/Complete QC dispatch to the Purchase QC document", h11_qc_actions_dispatch)

	return _report() if _report_now else R


def _report():
	width = max((len(r[1]) for r in R), default=10)
	print("=" * (width + 12))
	print("Purchase Inward regression (audit defects)")
	print("=" * (width + 12))
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 12))
	print(f"{passed}/{len(R)} passed")
	return R


# =====================================================================================
# Fixes applied after the audit's second pass (H2, H5, H6, H8, H1/H9).
# =====================================================================================


def _chain(supplier, item_code, order_qty, recv_qty, *, allow_excess=0,
           sample_qty=0, control_qty=0, mfg=None):
	"""PO -> inward -> Store receipt -> QC (decided) -> complete_qc -> Draft GRN."""
	from alpinos.purchase import notifications as notif
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

	po = H.make_po(supplier, [(item_code, order_qty, 10)])
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-CHAIN-{H.SEQ}-{frappe.generate_hash(length=6)}")
	inw.submit()
	inw.reload()
	inw.allow_excess_qty = allow_excess
	_receive(inw, recv_qty, mfg=mfg)

	notif.submit_for_qc(inw.name)
	qc_name = frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
	qc_mod.start_qc(qc_name)

	qc = frappe.get_doc("Purchase QC", qc_name)
	for row in qc.items:
		row.approved_qty = flt(row.received_qty)
		row.rejected_qty = 0
	qc.append("vehicle_inspection", {"vehicle_condition": C.CONDITION_GOOD})
	qc.vehicle_inspection_done = 1
	qc.append("material_inspection", {"item_code": item_code, "material_condition": C.CONDITION_GOOD})
	qc.material_inspection_done = 1
	qc.append("packaging_inspection", {"item_code": item_code, "packaging_condition": C.CONDITION_GOOD})
	qc.packaging_inspection_done = 1
	# An RM inward is refused without at least one Sample Testing row, so always send one.
	qc.append("sample_testing", {"item_code": item_code, "sample_qty": sample_qty or 1})
	qc.sample_testing_done = 1
	if control_qty:
		qc.append("control_sample", {
			"control_sample_taken": 1, "item_code": item_code, "control_sample_qty": control_qty,
		})
	qc.save(ignore_permissions=True)

	# complete_qc already mints the Draft GRN (BR-GRN-03); calling generate_grn again
	# would be refused with "not available while the Purchase Inward is GRN Generated".
	qc_mod.complete_qc(qc_name)
	pr = frappe.db.get_value(
		"Purchase Receipt", {"custom_purchase_inward": inw.name, "docstatus": 0}, "name"
	)
	return {"po": po, "inward": inw, "qc": qc_name, "pr": pr}


def _ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "enabled": 1,
		})
		u.insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	have = {r.role for r in u.roles}
	for role in roles:
		if role not in have and frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
	return email


def run_fixes(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")
	supplier = H.ensure_supplier()
	# Commit the shared fixture immediately: several cases below deliberately provoke an
	# exception and roll back, and a bare rollback would otherwise discard the supplier
	# and strand every case after it with "Supplier ... does not exist".
	frappe.db.commit()

	# ---------------------------------------------------------------- H8
	# The approved+rejected == received reconciliation ran on EVERY save, so a QC user
	# could not save partial progress on a multi-line inward (BRD 4.x / BR-QC-06 put the
	# completeness gate at final submission, not at every draft save).
	from alpinos.purchase import notifications as notif
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

	item_x = H.ensure_item(f"PITEST-FIX-X-{H.SEQ}")
	item_y = H.ensure_item(f"PITEST-FIX-Y-{H.SEQ}")
	po8 = H.make_po(supplier, [(item_x, 600, 10), (item_y, 500, 10)])
	inw8 = H.make_inward(po8, po8.items, invoice_no=f"PITEST-FIX-H8-{H.SEQ}")
	inw8.submit(); inw8.reload()
	_receive(inw8, 300)
	notif.submit_for_qc(inw8.name)
	qc8 = frappe.db.get_value("Purchase Inward", inw8.name, "purchase_qc")
	qc_mod.start_qc(qc8)
	frappe.db.commit()  # H6 below reads inw8 after a rollback

	def h8_partial_draft_saves():
		qc = frappe.get_doc("Purchase QC", qc8)
		qc.items[0].approved_qty = flt(qc.items[0].received_qty)
		qc.items[0].rejected_qty = 0
		qc.items[1].approved_qty = 0  # not inspected yet
		qc.items[1].rejected_qty = 0
		qc.save(ignore_permissions=True)
		frappe.db.commit()

	def h8_submit_still_reconciles():
		qc = frappe.get_doc("Purchase QC", qc8)
		qc.submit()

	check("H8 a draft QC saves with only one line decided", h8_partial_draft_saves)
	expect_throw(
		"H8 the reconciliation still blocks SUBMIT of an undecided line",
		h8_submit_still_reconciles,
		"must equal",
	)
	# only unwinds the failed submit attempt; the fixtures above are already committed
	frappe.db.rollback()

	# ---------------------------------------------------------------- H6
	# The QC form picked its buttons from Purchase QC.qc_status, which drifts away from
	# the inward workflow, so an SLA-breached QC lost Start QC and offered a Complete QC
	# that always threw.
	def h6_form_reads_the_engine():
		from alpinos.purchase.qc_client import purchase_qc_client_script

		script = purchase_qc_client_script()
		assert "get_actions" in script or "get_form_context" in script, (
			"the QC form still picks its buttons without asking the workflow engine"
		)
		assert "qc_status === 'Pending QC'" not in script, (
			"the QC form still gates Start QC on qc_status alone"
		)

	def h6_engine_offers_start_not_complete():
		stub = frappe.get_doc("Purchase Inward", inw8.name)
		stub.inward_status = C.PI_PENDING_QC
		actions = {a["action"] for a in workflow.available_actions(stub)}
		assert "start_qc" in actions, "engine does not offer start_qc at Pending QC"
		assert "complete_qc" not in actions, "engine wrongly offers complete_qc at Pending QC"

	check("H6 the QC form takes its buttons from the workflow engine", h6_form_reads_the_engine)
	check("H6 engine offers Start QC (not Complete QC) at Pending QC", h6_engine_offers_start_not_complete)

	# ---------------------------------------------------------------- H2
	# Stock Settings names ONE role for the over-receipt bypass and ERPNext checks it per
	# user; it used to name the role that may NOT submit a GRN, so an approved
	# over-receipt could never be posted by anyone but Administrator.
	def h2_bypass_role_can_submit_grn():
		role = frappe.db.get_single_value("Stock Settings", "role_allowed_to_over_deliver_receive")
		assert role in C.GRN_FINAL_SUBMIT_ROLES, (
			f"role_allowed_to_over_deliver_receive={role!r}, which cannot submit a GRN"
		)

	check("H2 the over-receipt bypass role may actually submit a GRN", h2_bypass_role_can_submit_grn)

	def h2_over_receipt_grn_submits():
		"""End to end, as a real Purchase Inward Admin (NOT Administrator)."""
		item_o = H.ensure_item(f"PITEST-FIX-OVR-{H.SEQ}")
		chain = _chain(supplier, item_o, 10, 15, allow_excess=1)
		admin = _ensure_user("pitest.regadmin@example.com", [C.ROLE_ADMIN])
		frappe.db.commit()
		try:
			frappe.set_user(admin)
			pr = frappe.get_doc("Purchase Receipt", chain["pr"])
			pr.submit()
			assert pr.docstatus == 1, "GRN did not submit"
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()

	check("H2 an approved over-receipt can be GRN-submitted by the Admin role", h2_over_receipt_grn_submits)

	# ------------------------------------------------------------- H1/H9
	# _blocked_reason treated has_batch_no=1 as a permanent block, so the sample and
	# control-sample transfer was deferred forever and the receiving warehouse
	# permanently overstated the stock that is physically in the QC lab.
	def h1_batch_sample_posts():
		code = f"PITEST-FIX-BATCH-{H.SEQ}"
		if not frappe.db.exists("Item", code):
			frappe.get_doc({
				"doctype": "Item", "item_code": code, "item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos", "is_stock_item": 1,
				"has_batch_no": 1, "create_new_batch": 1,
				"batch_number_series": f"PITB-{H.SEQ}-.####",
			}).insert(ignore_permissions=True)
		chain = _chain(supplier, code, 100, 100, sample_qty=5, control_qty=2)
		pr = frappe.get_doc("Purchase Receipt", chain["pr"])
		pr.submit()
		frappe.db.commit()

		qc = frappe.get_doc("Purchase QC", chain["qc"])
		se = qc.sample_testing[0].stock_entry
		assert se, "batch-tracked sample stock entry was never posted (deferred forever)"
		row = frappe.get_doc("Stock Entry", se).items[0]
		assert row.batch_no, "sample Stock Entry does not name the batch the GRN received"

		wh = frappe.db.get_single_value("Purchase Inward Settings", "qc_sample_warehouse")
		qty = flt(frappe.db.get_value("Bin", {"item_code": code, "warehouse": wh}, "actual_qty"))
		assert qty > 0, f"QC Sample warehouse {wh} still holds {qty}"

	check("H1/H9 a batch-tracked sample actually moves to the QC Sample warehouse", h1_batch_sample_posts)

	return _report() if _report_now else R


def run_all():
	"""Every audit-defect regression in one pass.

	    bench --site <site> execute alpinos.purchase.regression_test.run_all
	"""
	R.clear()
	run(_report_now=False)
	run_fixes(_report_now=False)
	run_wave_b(_report_now=False)
	run_wave_a(_report_now=False)
	run_wave_c(_report_now=False)
	run_wave_d(_report_now=False)
	run_wave_e(_report_now=False)
	run_wave_f(_report_now=False)
	return _report()


# =====================================================================================
# Wave B - the medium/low defects fixed after the high-severity pass.
# =====================================================================================


def run_wave_b(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")
	supplier = H.ensure_supplier()
	frappe.db.commit()

	from alpinos.purchase import inward_api, inward_list_api, settings as st

	# ---------------------------------------------------------------- M06
	# inward_type was copied from the PO only when blank, so a user could raise an
	# inward against an FG order, retype the type as RM, and skip the FG batch rule.
	def m06_type_forced_from_po():
		item = H.ensure_item(f"PITEST-WB-FG-{H.SEQ}")
		po = H.make_po(supplier, [(item, 10, 5)], inward_type=C.INWARD_FG)
		pi = frappe.new_doc("Purchase Inward")
		pi.purchase_order = po.name
		pi.invoice_number = f"PITEST-WB-M06-{H.SEQ}"
		pi.invoice_date = today()
		pi.inward_datetime = now_datetime()
		pi.inward_type = C.INWARD_RM  # the tampering the defect allowed
		pi.append("items", {"item_code": item, "po_detail": po.items[0].name})
		pi.insert(ignore_permissions=True)
		assert pi.inward_type == C.INWARD_FG, (
			f"inward_type stayed {pi.inward_type!r} instead of following the PO"
		)
		frappe.db.commit()

	check("M06 Inward Type always follows the Purchase Order", m06_type_forced_from_po)

	# ---------------------------------------------------------------- L08
	# Manufacturing Date was never enforced, so a shelf-life item stored expiry NULL.
	def l08_mfg_required_for_shelf_life():
		item = H.ensure_item(f"PITEST-WB-SL-{H.SEQ}", shelf_life_days=90)
		po = H.make_po(supplier, [(item, 50, 5)])
		pi = H.make_inward(po, po.items, invoice_no=f"PITEST-WB-L08-{H.SEQ}")
		pi.submit(); pi.reload()
		frappe.db.commit()
		pi.actual_arrival_datetime = now_datetime()
		pi.items[0].received_qty = 10
		pi.items[0].target_warehouse = H._warehouse()
		pi.items[0].manufacturing_date = None  # the hole
		pi.flags.ignore_permissions = True
		pi.save()

	expect_throw(
		"L08 Manufacturing Date is required for a shelf-life item",
		l08_mfg_required_for_shelf_life,
		"Manufacturing Date",
	)
	frappe.db.rollback()

	# ---------------------------------------------------------------- M13
	# Child before_insert never runs in frappe, so dispute evidence had a NULL uploader.
	def m13_attachment_stamped():
		item = H.ensure_item(f"PITEST-WB-AT-{H.SEQ}")
		po = H.make_po(supplier, [(item, 20, 5)])
		pi = H.make_inward(po, po.items, invoice_no=f"PITEST-WB-M13-{H.SEQ}")
		pi.append("dispute_attachments", {"file": "/files/probe.png", "description": "damaged carton"})
		pi.flags.ignore_permissions = True
		pi.save()
		row = frappe.get_doc("Purchase Inward", pi.name).dispute_attachments[0]
		assert row.uploaded_by, "uploaded_by is still NULL"
		assert row.uploaded_on, "uploaded_on is still NULL"
		frappe.db.commit()

	check("M13 dispute attachments record who uploaded them and when", m13_attachment_stamped)

	# ---------------------------------------------------------------- L10
	# The search box DELETED underscores instead of escaping them.
	def l10_underscore_escaped():
		pattern = inward_list_api._like("INV_2026_001")
		assert "\\_" in pattern, f"underscore not escaped: {pattern!r}"
		rows = frappe.db.sql(
			"SELECT %s LIKE %s AS literal_hit, %s LIKE %s AS wildcard_hit",
			("INV_2026_001", pattern, "INVX2026X001", pattern),
			as_dict=True,
		)[0]
		assert rows["literal_hit"] == 1, "the literal underscore no longer matches"
		assert rows["wildcard_hit"] == 0, "the underscore is still behaving as a wildcard"

	def l10_percent_still_stripped():
		assert "%" not in inward_list_api._like("50%off").strip("%"), (
			"a typed % survived and would dump the table"
		)

	check("L10 search escapes the underscore instead of deleting it", l10_underscore_escaped)
	check("L10 a typed percent sign is still stripped", l10_percent_still_stripped)

	# ---------------------------------------------------------------- M21
	# BRD 1.2 asks for QC outcomes; only workflow statuses were filterable.
	def m21_qc_result_filter():
		opts = inward_list_api.get_filter_options()
		assert "qc_results" in opts, "the list page is not served the QC outcome vocabulary"
		base = inward_list_api.get_purchase_inward_list(page_length=1)
		hit = inward_list_api.get_purchase_inward_list(page_length=1, qc_result=C.QC_RESULT_PARTIAL)
		assert hit["total"] < base["total"], (
			f"qc_result filter did not narrow the list ({hit['total']} vs {base['total']})"
		)
		bogus = inward_list_api.get_purchase_inward_list(page_length=1, qc_result="Nonsense")
		assert bogus["total"] == base["total"], "an unknown qc_result was not ignored"

	check("M21 the list can filter by QC outcome", m21_qc_result_filter)

	# ---------------------------------------------------------------- L12
	def l12_vehicle_sort_matches_display():
		assert "vehicle_no" in inward_list_api._SORT_EXPRESSIONS, (
			"Vehicle No. still sorts on a column it does not display"
		)
		inward_list_api.get_purchase_inward_list(page_length=3, sort_field="vehicle_no", sort_dir="asc")

	check("L12 Vehicle No. sorts on the value it displays", l12_vehicle_sort_matches_display)

	# ---------------------------------------------------------------- M14
	def m14_notification_roles_exist():
		roles = st.notification_roles()
		assert roles, "no QC notification roles resolved"
		for role in roles:
			assert frappe.db.exists("Role", role), f"notification role {role!r} does not exist"

	check("M14 QC notification roles all exist", m14_notification_roles_exist)

	# ---------------------------------------------------------------- M08
	def m08_purchase_can_submit_invoice():
		for role in (C.ROLE_PURCHASE_USER, C.ROLE_PURCHASE_MANAGER):
			got = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": "Purchase Invoice", "role": role, "permlevel": 0},
				"submit",
			)
			assert cint(got) == 1, f"{role} still cannot submit a Purchase Invoice (BR-UNF-03)"

	check("M08 Purchase roles can submit the Purchase Invoice", m08_purchase_can_submit_invoice)

	# ---------------------------------------------------------------- M19
	def m19_invoice_correction():
		item = H.ensure_item(f"PITEST-WB-IC-{H.SEQ}")
		po = H.make_po(supplier, [(item, 20, 5)])
		pi = H.make_inward(po, po.items, invoice_no=f"PITEST-WB-M19-{H.SEQ}")
		pi.submit()
		frappe.db.commit()
		new_no = f"PITEST-WB-M19FIX-{H.SEQ}"
		inward_api.correct_invoice_number(pi.name, new_no, reason="Vendor reissued the invoice")
		got = frappe.db.get_value(
			"Purchase Inward", pi.name, ["invoice_number", "original_invoice_number"], as_dict=True
		)
		assert got.invoice_number == new_no, f"invoice not corrected: {got.invoice_number}"
		assert got.original_invoice_number == f"PITEST-WB-M19-{H.SEQ}", "original not preserved"
		log = frappe.get_all(
			"Purchase Invoice Change Log", filters={"parent": pi.name}, fields=["reason", "changed_by"]
		)
		assert len(log) == 1 and log[0].reason, "no audit row written (BR-PI-20)"
		frappe.db.commit()
		return pi.name

	holder = {}

	def m19_wrapper():
		holder["pi"] = m19_invoice_correction()

	def m19_reason_required():
		inward_api.correct_invoice_number(holder["pi"], "PITEST-WB-NOREASON", reason="")

	check("M19 an Admin can correct the Invoice Number after submit", m19_wrapper)
	expect_throw(
		"M19 the correction is refused without a reason",
		m19_reason_required,
		"reason",
	)
	frappe.db.rollback()

	return _report() if _report_now else R


# =====================================================================================
# Wave A - the structural defects (cancel deadlock, GRN status, QC override,
# inspector stamping, child-row binding).
# =====================================================================================


def run_wave_a(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")
	supplier = H.ensure_supplier()
	frappe.db.commit()

	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod
	from alpinos.purchase import notifications as notif

	# ---------------------------------------------------------------- H12
	# GRN submit posts the QC sample transfers out of the receiving warehouse, so
	# cancelling it died with NegativeStockError while the QC refused to go first.
	state = {}

	def h12_grn_cancels():
		item = H.ensure_item(f"PITEST-WA-CX-{H.SEQ}")
		ch = _chain(supplier, item, 100, 100, sample_qty=5, control_qty=2)
		pr = frappe.get_doc("Purchase Receipt", ch["pr"])
		pr.submit()
		frappe.db.commit()
		qc = frappe.get_doc("Purchase QC", ch["qc"])
		assert any(r.stock_entry for r in qc.sample_testing), "no sample Stock Entry was posted"
		pr.reload()
		pr.cancel()
		frappe.db.commit()
		assert pr.docstatus == 2, "GRN did not cancel"
		state["qc"] = ch["qc"]

	def h12_samples_unwound():
		qc = frappe.get_doc("Purchase QC", state["qc"])
		left = [r.stock_entry for r in qc.sample_testing if r.stock_entry]
		assert not left, f"sample Stock Entry still linked after the GRN cancel: {left}"

	def h12_qc_cancels_after():
		qc = frappe.get_doc("Purchase QC", state["qc"])
		qc.cancel()
		frappe.db.commit()
		assert qc.docstatus == 2, "QC did not cancel after its GRN"

	check("H12 a GRN with QC samples can be cancelled", h12_grn_cancels)
	check("H12 the sample stock movement is unwound by the cancel", h12_samples_unwound)
	check("H12 the QC can then be cancelled (BRD 5.3 order)", h12_qc_cancels_after)

	# ---------------------------------------------------------------- M04 / M22
	# C.GRN_COMPLETED / C.GRN_CANCELLED had no writer anywhere in the app.
	def m04_submitted_grn_is_completed():
		item = H.ensure_item(f"PITEST-WA-ST-{H.SEQ}")
		ch = _chain(supplier, item, 40, 40)
		pr = frappe.get_doc("Purchase Receipt", ch["pr"])
		assert pr.custom_grn_status == C.GRN_DRAFT, f"draft GRN reads {pr.custom_grn_status}"
		pr.submit()
		frappe.db.commit()
		pr.reload()
		assert pr.custom_grn_status == C.GRN_COMPLETED, (
			f"submitted GRN still reads {pr.custom_grn_status!r}"
		)
		assert pr.custom_final_submitted_by, "Final Submitted By not stamped (BRD 5.2.1)"
		assert pr.custom_final_submission_datetime, "Final Submission Date & Time not stamped"
		inward_grn = frappe.db.get_value("Purchase Inward", ch["inward"].name, "grn_status")
		assert inward_grn == C.GRN_COMPLETED, f"inward grn_status is {inward_grn!r}"

	check("M04 a submitted GRN reads Completed and records who submitted it", m04_submitted_grn_is_completed)

	# ---------------------------------------------------------------- M02 / M16 / L09
	def m02_override_fields_exist():
		meta = frappe.get_meta("Purchase QC")
		for fn in ("manual_qc_result", "system_qc_result", "qc_result_overridden", "override_reason"):
			assert meta.get_field(fn), f"{fn} still does not exist, so the override has no provenance"

	def l09_override_blocked_with_live_grn():
		item = H.ensure_item(f"PITEST-WA-OV-{H.SEQ}")
		ch = _chain(supplier, item, 30, 30)
		qc_mod.override_qc_result(ch["qc"], C.QC_RESULT_REJECTED, "late lab result")

	check("M02 the QC override provenance fields exist", m02_override_fields_exist)
	expect_throw(
		"L09 overriding to Rejected is refused while a Draft GRN is live",
		l09_override_blocked_with_live_grn,
	)
	frappe.db.rollback()

	# ---------------------------------------------------------------- M09 / M10
	# _sync_header stamped the STORE user and the handoff time onto a brand-new QC.
	def m09_inspector_blank_at_handoff():
		item = H.ensure_item(f"PITEST-WA-IN-{H.SEQ}")
		po = H.make_po(supplier, [(item, 30, 5)])
		inw = H.make_inward(po, po.items, invoice_no=f"PITEST-WA-M09-{H.SEQ}")
		inw.submit(); inw.reload()
		_receive(inw, 10)
		notif.submit_for_qc(inw.name)
		frappe.db.commit()
		qc = frappe.get_doc(
			"Purchase QC", frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
		)
		assert not qc.inspector, (
			f"a brand-new Pending QC is already assigned to {qc.inspector} (the Store user)"
		)
		assert not qc.inspection_date, (
			"Inspection Date was stamped at handoff, not at inspection"
		)
		state["pending_qc"] = qc.name

	def m10_start_qc_stamps_the_qc_user():
		qc_mod.start_qc(state["pending_qc"])
		frappe.db.commit()
		qc = frappe.get_doc("Purchase QC", state["pending_qc"])
		assert qc.inspector, "start_qc did not stamp an inspector"
		assert qc.inspection_date, "start_qc did not stamp the inspection date"

	check("M09 a QC awaiting inspection has no inspector yet", m09_inspector_blank_at_handoff)
	check("M10 Start QC stamps the inspector and the inspection date", m10_start_qc_stamps_the_qc_user)

	# ---------------------------------------------------------------- M01 / M11 / M17
	def m01_child_rows_can_name_their_line():
		for dt in ("Purchase QC Sample", "Purchase QC Control Sample"):
			assert frappe.get_meta(dt).get_field("qc_item_idx"), (
				f"{dt} still cannot say which decision line it came from"
			)

	check("M01 sample rows can identify their QC decision line", m01_child_rows_can_name_their_line)

	return _report() if _report_now else R


# =====================================================================================
# Wave C - Debit Note (VAL-QC-17 / BR-QC-21) and internal batch / sample sticker.
# =====================================================================================


def _chain_with_rejection(supplier, item_code, order_qty, recv_qty, rejected):
	"""Same as _chain but the QC rejects `rejected` units, so a Debit Note is due."""
	from alpinos.purchase import notifications as notif
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

	po = H.make_po(supplier, [(item_code, order_qty, 25)])
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-DN-{H.SEQ}-{frappe.generate_hash(length=6)}")
	inw.submit(); inw.reload()
	_receive(inw, recv_qty)
	notif.submit_for_qc(inw.name)
	qc_name = frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
	qc_mod.start_qc(qc_name)

	qc = frappe.get_doc("Purchase QC", qc_name)
	qc.items[0].approved_qty = flt(recv_qty) - flt(rejected)
	qc.items[0].rejected_qty = flt(rejected)
	if rejected:
		qc.items[0].rejection_reason = "Moisture above spec"
	qc.append("vehicle_inspection", {"vehicle_condition": C.CONDITION_GOOD})
	qc.vehicle_inspection_done = 1
	qc.append("material_inspection", {"item_code": item_code, "material_condition": C.CONDITION_GOOD})
	qc.material_inspection_done = 1
	qc.append("packaging_inspection", {"item_code": item_code, "packaging_condition": C.CONDITION_GOOD})
	qc.packaging_inspection_done = 1
	qc.append("sample_testing", {"item_code": item_code, "sample_qty": 1})
	qc.sample_testing_done = 1
	qc.save(ignore_permissions=True)
	qc_mod.complete_qc(qc_name)
	pr_name = frappe.db.get_value(
		"Purchase Receipt", {"custom_purchase_inward": inw.name, "docstatus": 0}, "name"
	)
	pr = frappe.get_doc("Purchase Receipt", pr_name)
	pr.submit()
	frappe.db.commit()
	return {"inward": inw, "qc": qc_name, "pr": pr.reload()}


def run_wave_c(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")
	supplier = H.ensure_supplier()
	frappe.db.commit()

	from alpinos.purchase import grn as grn_mod

	# ---------------------------------------------------- VAL-QC-17 / BR-GRN-09
	state = {}

	def dn_generated_for_rejection():
		item = H.ensure_item(f"PITEST-WC-DN-{H.SEQ}")
		ch = _chain_with_rejection(supplier, item, 100, 100, rejected=10)
		state["ch"] = ch
		note = ch["pr"].custom_debit_note
		assert note, "no Debit Note raised for a rejected quantity (BR-GRN-09)"
		d = frappe.get_doc("Purchase Invoice", note)
		assert cint(d.is_return) == 1, "the debit note is not a return"
		assert d.docstatus == 0, "the debit note was auto-submitted; Accounts must submit it"
		assert flt(d.items[0].qty) == -10.0, f"debit note qty is {d.items[0].qty}, expected -10"
		state["note"] = note

	def dn_mirrors_linked():
		ch = state["ch"]
		assert frappe.db.get_value("Purchase Inward", ch["inward"].name, "debit_note") == state["note"]
		assert frappe.db.get_value("Purchase QC", ch["qc"], "debit_note") == state["note"]

	def dn_idempotent():
		before = frappe.db.count("Purchase Invoice", {"is_return": 1, "docstatus": ("<", 2)})
		grn_mod.generate_debit_note(state["ch"]["pr"].name)
		after = frappe.db.count("Purchase Invoice", {"is_return": 1, "docstatus": ("<", 2)})
		assert before == after, "a second Debit Note was raised for the same GRN"

    # BR-GRN-10: no rejection, no debit note.
	def dn_none_when_nothing_rejected():
		item = H.ensure_item(f"PITEST-WC-OK-{H.SEQ}")
		ch = _chain_with_rejection(supplier, item, 50, 50, rejected=0)
		assert not ch["pr"].custom_debit_note, "a Debit Note was raised with nothing rejected"

	def dn_refused_on_foreign_receipt():
		"""An ordinary stock receipt is none of this module's business.

		roles.assert_can_submit_grn returns SILENTLY for a receipt with no
		custom_purchase_inward, and make_debit_note inserts with ignore_permissions, so
		without the marker check anyone who could READ a plain receipt could mint a
		financial document against it.
		"""
		other = frappe.db.get_value(
			"Purchase Receipt", {"custom_purchase_inward": ("is", "not set"), "docstatus": 1}, "name"
		)
		if not other:
			# build a plain, non-module receipt so the guard is genuinely exercised
			item = H.ensure_item(f"PITEST-WC-PLAIN-{H.SEQ}")
			pr = frappe.new_doc("Purchase Receipt")
			pr.supplier = supplier
			pr.company = H.COMPANY
			pr.append("items", {
				"item_code": item, "qty": 5, "rate": 10,
				"warehouse": H._warehouse(), "received_qty": 5,
			})
			pr.insert(ignore_permissions=True)
			pr.submit()
			frappe.db.commit()
			other = pr.name
		grn_mod.generate_debit_note(other)

	check("VAL-QC-17 a rejected quantity raises a Draft Debit Note", dn_generated_for_rejection)
	check("BR-QC-21 the Debit Note is linked from the inward and the QC", dn_mirrors_linked)
	check("BR-GRN-09 re-running does not raise a second Debit Note", dn_idempotent)
	check("BR-GRN-10 no Debit Note when nothing was rejected", dn_none_when_nothing_rejected)
	expect_throw(
		"the Debit Note generator refuses a non-module Purchase Receipt",
		dn_refused_on_foreign_receipt,
		"not a Purchase Inward GRN",
	)

	# ---------------------------------------------------------------- M15 / L01
	def m15_internal_batch_is_minted():
		code = f"PITEST-WC-BATCH-{H.SEQ}"
		if not frappe.db.exists("Item", code):
			frappe.get_doc({
				"doctype": "Item", "item_code": code, "item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos", "is_stock_item": 1,
				"has_batch_no": 1, "create_new_batch": 1,
				"batch_number_series": f"PIWC-{H.SEQ}-.####",
			}).insert(ignore_permissions=True)
		ch = _chain(supplier, code, 60, 60, sample_qty=2)
		qc = frappe.get_doc("Purchase QC", ch["qc"])
		internal = qc.items[0].internal_batch_no
		assert internal, "no internal batch number was generated"
		assert frappe.db.exists("Batch", internal), (
			f"internal batch {internal!r} was never minted as a Batch, so the ledger uses another id"
		)
		pr = frappe.get_doc("Purchase Receipt", ch["pr"])
		assert pr.items[0].batch_no == internal, (
			f"GRN line carries {pr.items[0].batch_no!r}, not the QC's internal batch"
		)

	def l01_sticker_format_exists():
		assert frappe.db.exists("Print Format", "QC Sample Sticker"), (
			"BRD 4.1.5 sample sticker has no print format"
		)

	check("M15 the internal batch is minted and reaches the GRN line", m15_internal_batch_is_minted)
	check("L01 a QC Sample Sticker print format exists", l01_sticker_format_exists)

	# ---------------------------------------------------------------- M18
	# BRD 4.6.2's excess result was tested against the whole PO line, so every over-receipt
	# on a SECOND delivery against that line was reported as a plain "Approved".
	def m18_excess_measured_against_pending():
		from alpinos.purchase import notifications as notif
		from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

		item = H.ensure_item(f"PITEST-WC-EX-{H.SEQ}")
		po = H.make_po(supplier, [(item, 100, 10)])

		def one(recv, allow_excess):
			inw = H.make_inward(
				po, po.items, invoice_no=f"PITEST-WC-EX-{H.SEQ}-{frappe.generate_hash(length=5)}"
			)
			inw.submit(); inw.reload()
			inw.allow_excess_qty = allow_excess
			_receive(inw, recv)
			notif.submit_for_qc(inw.name)
			qc_name = frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
			qc_mod.start_qc(qc_name)
			qc = frappe.get_doc("Purchase QC", qc_name)
			for row in qc.items:
				row.approved_qty = flt(row.received_qty)
				row.rejected_qty = 0
			qc.append("vehicle_inspection", {"vehicle_condition": C.CONDITION_GOOD})
			qc.vehicle_inspection_done = 1
			qc.append("material_inspection", {"item_code": item, "material_condition": C.CONDITION_GOOD})
			qc.material_inspection_done = 1
			qc.append("packaging_inspection", {"item_code": item, "packaging_condition": C.CONDITION_GOOD})
			qc.packaging_inspection_done = 1
			qc.append("sample_testing", {"item_code": item, "sample_qty": 1})
			qc.sample_testing_done = 1
			qc.save(ignore_permissions=True)
			qc_mod.complete_qc(qc_name)
			frappe.db.commit()
			return frappe.db.get_value("Purchase QC", qc_name, "qc_result")

		first = one(60, 0)
		assert first == C.QC_RESULT_APPROVED, f"first delivery of 60/100 read {first!r}"
		# pending is now 40; receiving 50 is a 10-unit excess
		second = one(50, 1)
		assert second == C.QC_RESULT_EXCESS_APPROVED, (
			f"second delivery over the pending quantity read {second!r}, "
			f"expected {C.QC_RESULT_EXCESS_APPROVED!r}"
		)

	check("M18 excess is measured against pending, not the whole PO line", m18_excess_measured_against_pending)

	return _report() if _report_now else R


# =====================================================================================
# Wave D - the BRD screen layouts as custom desk Pages (BRD 2 and BRD 4).
# =====================================================================================

APP_PAGE_DIR = "/Users/hetvi/frappe-bench/apps/alpinos/alpinos/alpinos_development/page"
SHARED_CSS = "/Users/hetvi/frappe-bench/apps/alpinos/alpinos/public/css/alpinos_pages.css"

MODULE_PAGES = ("purchase_inward_list", "purchase_qc_list", "purchase_inward_entry", "purchase_qc_entry")


def run_wave_d(_report_now=True):
	if _report_now:
		R.clear()
	frappe.set_user("Administrator")

	def pages_exist():
		for name in MODULE_PAGES:
			assert frappe.db.exists("Page", name), f"desk page {name} does not exist"
			roles = frappe.get_all("Has Role", filters={"parenttype": "Page", "parent": name})
			assert roles, f"page {name} has no Has Role rows, so nobody can open it"

	def entry_pages_render_their_template():
		"""The .html is compiled into the served script by Page.load_assets.

		frappe prepends html_to_js_template(...) onto the script, registering
		frappe.templates['<page>'] — which is exactly what the page's own
		frappe.render_template('<page>') call looks up. A name mismatch would leave the
		page blank with no error, so both halves are asserted together.
		"""
		import re
		from frappe.desk.desk_page import get as get_page

		for name in ("purchase_inward_entry", "purchase_qc_entry"):
			script = get_page(name)["script"]
			m = re.search(r"frappe\.templates\[['\"]([a-z_]+)['\"]\]", script)
			assert m, f"{name}: no template compiled into the served script"
			assert m.group(1) == name, f"{name}: template registered as {m.group(1)!r}"
			assert f"frappe.render_template('{name}')" in script, (
				f"{name}: the page never renders the template it registered"
			)

	def entry_pages_use_the_house_design():
		"""They must reuse the shared design system, not invent a second look."""
		from frappe.desk.desk_page import get as get_page

		for name in ("purchase_inward_entry", "purchase_qc_entry"):
			script = get_page(name)["script"]
			for cls in ("eso-card", "eso-card-title", "eso-fld", "alp-scroll", "alp-actions"):
				assert cls in script, f"{name} does not use the shared {cls} class"

	def shared_css_covers_the_module():
		"""alpinos_pages.css scopes every rule on data-page-route, so a page missing from
		those selector lists silently gets none of the house design."""
		css = open(SHARED_CSS).read()
		for name in MODULE_PAGES:
			assert f'data-page-route="{name}"' in css, (
				f"{name} is not in the shared stylesheet's scope, so it gets no house design"
			)

	def lists_open_the_entry_pages():
		"""A row click must land on the BRD screen, not the raw desk form."""
		for page, doctype in (
			("purchase_inward_list", "Purchase Inward"),
			("purchase_qc_list", "Purchase QC"),
		):
			js = open(f"{APP_PAGE_DIR}/{page}/{page}.js").read()
			assert f"set_route('Form', '{doctype}'" not in js, (
				f"{page} still opens the raw desk form for {doctype}"
			)
		inward_js = open(f"{APP_PAGE_DIR}/purchase_inward_list/purchase_inward_list.js").read()
		assert "purchase_inward_entry" in inward_js, "the inward list never routes to its entry page"
		qc_js = open(f"{APP_PAGE_DIR}/purchase_qc_list/purchase_qc_list.js").read()
		assert "purchase_qc_entry" in qc_js, "the QC list never routes to its entry page"

	def workspace_reaches_them():
		from alpinos.purchase.workspace import WORKSPACE

		ws = frappe.get_doc("Workspace", WORKSPACE)
		targets = {s.link_to for s in ws.shortcuts}
		for name in ("purchase_inward_list", "purchase_qc_list", "purchase_inward_entry"):
			assert name in targets, f"no workspace shortcut points at {name}"

	def workspace_does_not_collide_with_a_doctype():
		"""A Workspace and a DocType of the same name both resolve to the same /app route,
		which sent the desk to the DocType's new-document URL with an empty body."""
		from alpinos.purchase.workspace import WORKSPACE

		assert not frappe.db.exists("DocType", WORKSPACE), (
			f"workspace {WORKSPACE!r} collides with a DocType of the same name"
		)
		assert not frappe.db.exists("Workspace", "Purchase Inward"), (
			"the colliding 'Purchase Inward' workspace is still present"
		)

	def workspace_actually_renders():
		"""A workspace draws from `content`; shortcuts/links rows alone render nothing."""
		import json

		from alpinos.purchase.workspace import WORKSPACE

		ws = frappe.get_doc("Workspace", WORKSPACE)
		blocks = json.loads(ws.content or "[]")
		assert blocks, "workspace content is empty, so the page renders blank"
		kinds = {b.get("type") for b in blocks}
		assert "shortcut" in kinds, "no shortcut blocks, so the shortcuts are invisible"
		assert "card" in kinds, "no card block, so the links are invisible"
		named = {b["data"].get("shortcut_name") for b in blocks if b.get("type") == "shortcut"}
		for shortcut in ws.shortcuts:
			assert shortcut.label in named, f"shortcut {shortcut.label!r} has no block drawing it"

	check("Wave D all four module desk pages exist and are role-granted", pages_exist)
	check("Wave D the entry pages register and render their own template", entry_pages_render_their_template)
	check("Wave D the entry pages reuse the shared design system", entry_pages_use_the_house_design)
	check("Wave D the shared stylesheet scopes the module's pages", shared_css_covers_the_module)
	check("Wave D the list pages open the BRD entry screens", lists_open_the_entry_pages)
	check("Wave D the workspace reaches every module page", workspace_reaches_them)
	check("Wave D the workspace name does not collide with a DocType", workspace_does_not_collide_with_a_doctype)
	check("Wave D the workspace has content blocks so it renders", workspace_actually_renders)

	return _report() if _report_now else R


# =====================================================================================
# Wave E - navigation. Every route out of a module screen must resolve, and every role
# that can reach a screen must be able to open what that screen links to.
# =====================================================================================

# Route names that are frappe built-ins rather than module pages.
_BUILTIN_ROUTES = {"Form", "List", "print", "query-report", "new"}


def _page_js(page, strip_comments=False):
	src = open(f"{APP_PAGE_DIR}/{page}/{page}.js").read()
	if strip_comments:
		# Comments legitimately quote the wrong-way-round call they warn against, so a
		# scan for bad calls has to read code only.
		import re

		src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
		src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
	return src


def _routes_in(page):
	"""[(target, is_doctype_route)] for every frappe.set_route(...) in a page."""
	import re

	out = []
	for m in re.finditer(
		r"frappe\.set_route\(\s*'([^']+)'\s*(?:,\s*'([^']+)')?", _page_js(page, strip_comments=True)
	):
		first, second = m.group(1), m.group(2)
		if first in _BUILTIN_ROUTES:
			if second:
				out.append((second, True))
		else:
			out.append((first, False))
	return out


def run_wave_e(_report_now=True):
	if _report_now:
		R.clear()
	frappe.set_user("Administrator")

	def every_route_target_exists():
		"""A typo'd page name routes to a blank 'Not Found', silently."""
		problems = []
		for page in MODULE_PAGES:
			for target, is_doctype in _routes_in(page):
				if is_doctype:
					if not frappe.db.exists("DocType", target):
						problems.append(f"{page} -> DocType {target!r} does not exist")
				elif not frappe.db.exists("Page", target):
					problems.append(f"{page} -> Page {target!r} does not exist")
		assert not problems, "; ".join(problems)

	def module_docs_never_open_the_raw_form():
		"""Purchase Inward / Purchase QC must always open on their BRD screens."""
		import re

		problems = []
		for page in MODULE_PAGES:
			js = _page_js(page, strip_comments=True)
			for dt in ("Purchase Inward", "Purchase QC"):
				# 'print' also names a doctype and is perfectly legitimate; only a Form
				# route means "opened the raw desk form".
				if re.search(rf"set_route\(\s*'Form'\s*,\s*'{dt}'", js):
					problems.append(f"{page} still opens the raw desk form for {dt}")
		assert not problems, "; ".join(problems)

	def new_button_opens_the_entry_screen():
		js = _page_js("purchase_inward_list")
		assert "frappe.new_doc('Purchase Inward')" not in js, (
			"the + New button still opens the raw desk form"
		)
		assert "set_route('purchase_inward_entry')" in js, (
			"the + New button does not open the entry screen"
		)

    # A role that can open a list, click a row, and then be refused the entry screen
    # is a dead end. Screen access must never be narrower than the screen linking to it.
	def entry_access_is_never_narrower_than_the_list():
		def roles(page):
			return set(
				frappe.get_all("Has Role", filters={"parenttype": "Page", "parent": page}, pluck="role")
			)

		inward_list, inward_entry = roles("purchase_inward_list"), roles("purchase_inward_entry")
		qc_list, qc_entry = roles("purchase_qc_list"), roles("purchase_qc_entry")
		assert not (inward_list - inward_entry), (
			f"can open the inward list but not the inward entry: {sorted(inward_list - inward_entry)}"
		)
		assert not (qc_list - qc_entry), (
			f"can open the QC list but not the QC entry: {sorted(qc_list - qc_entry)}"
		)
		# the QC list and the QC entry both link to the inward entry
		assert not (qc_list - inward_entry), (
			f"the QC list links to the inward entry but these roles cannot open it: "
			f"{sorted(qc_list - inward_entry)}"
		)

	def print_routes_are_well_formed():
		"""frappe's print page builds the docname as route.slice(2).join('/'), so a 4th
		set_route argument silently corrupts the name. A specific format must go through
		/printview?format=... instead."""
		import re

		for page in MODULE_PAGES:
			js = _page_js(page, strip_comments=True)
			bad = re.search(r"set_route\(\s*'print'\s*,[^)]*\{", js)
			assert not bad, f"{page} passes an options object to set_route('print', ...)"
		qc = _page_js("purchase_qc_entry")
		assert "/printview?doctype=" in qc, "the sample sticker does not use the printview endpoint"
		assert "format=" in qc, "the sticker route names no print format"

	check("Wave E every route target resolves to a real Page or DocType", every_route_target_exists)
	check("Wave E module documents never open the raw desk form", module_docs_never_open_the_raw_form)
	check("Wave E the + New button opens the entry screen", new_button_opens_the_entry_screen)
	check("Wave E entry-screen access is never narrower than its list", entry_access_is_never_narrower_than_the_list)
	check("Wave E print routes are well formed", print_routes_are_well_formed)

	return _report() if _report_now else R


# =====================================================================================
# Wave F - the partial task and the seven named gaps, closed.
# =====================================================================================


def run_wave_f(_report_now=True):
	if _report_now:
		R.clear()
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	frappe.set_user("Administrator")
	supplier = H.ensure_supplier()
	frappe.db.commit()

	from alpinos.purchase import grn as grn_mod, settings as st, workflow as wf
	from alpinos.purchase import purchase_receipt_fields as prf

	# ---------------------------------------------------------------- 299
	# The draft GRN was minted once and never looked at its inward again.
	def t299_draft_grn_resyncs():
		item = H.ensure_item(f"PITEST-WF-SYNC-{H.SEQ}")
		ch = _chain(supplier, item, 80, 80)
		pr = frappe.get_doc("Purchase Receipt", ch["pr"])
		inw = frappe.get_doc("Purchase Inward", ch["inward"].name)
		inw.items[0].mrp = 499.0
		inw.items[0].usp = "WF-CORRECTED"
		inw.flags.ignore_permissions = True
		inw.save()
		frappe.db.commit()
		pr.reload()
		assert flt(pr.items[0].custom_mrp) == 499.0, (
			f"draft GRN kept a stale MRP ({pr.items[0].custom_mrp}) after the inward changed"
		)
		assert pr.items[0].custom_usp == "WF-CORRECTED", "draft GRN kept a stale USP"

	def t299_resync_is_not_whitelisted():
		"""The system path must not be reachable from the client."""
		fn = grn_mod.resync_draft_grn
		assert not getattr(fn, "whitelisted", False), (
			"resync_draft_grn is whitelisted; it bypasses the receipt write check by design"
		)

	check("299 a Draft GRN re-syncs when its inward changes", t299_draft_grn_resyncs)
	check("299 the system re-sync path is not client-reachable", t299_resync_is_not_whitelisted)

	# ---------------------------------------------------------------- 288
	def t288_qc_has_a_server_guard():
		src = open(
			"/Users/hetvi/frappe-bench/apps/alpinos/alpinos/alpinos_development/"
			"doctype/purchase_qc/purchase_qc.py"
		).read()
		assert "assert_section_edits_allowed" in src, (
			"Purchase QC section gating is still Client Script only"
		)
		assert "_assert_section_access" in src.split("def validate(self)")[1][:200], (
			"the guard is defined but validate() does not call it"
		)

	check("288 Purchase QC section gating has a server twin", t288_qc_has_a_server_guard)

	# ---------------------------------------------------------------- 289
	def t289_illegal_qc_transitions_refused():
		wf.assert_qc_transition(C.QC_PENDING, C.QC_IN_PROGRESS)          # legal
		wf.assert_qc_transition(C.QC_SLA_BREACHED, C.QC_READY_FOR_DECISION)  # legal
		for old, new in (
			(C.QC_PENDING, C.QC_COMPLETED),
			(C.QC_COMPLETED, C.QC_IN_PROGRESS),
			(C.QC_IN_PROGRESS, "Nonsense"),
		):
			try:
				wf.assert_qc_transition(old, new)
				raise AssertionError(f"{old} -> {new} was allowed")
			except AssertionError:
				raise
			except Exception:
				pass

	def t289_table_covers_every_status():
		for status in C.QC_STATUSES:
			assert status in wf.QC_TRANSITIONS, f"{status} has no row in QC_TRANSITIONS"

	check("289 illegal Purchase QC transitions are refused", t289_illegal_qc_transitions_refused)
	check("289 the QC transition table covers every status", t289_table_covers_every_status)

	# ---------------------------------------------------------------- 290
	def t290_warehouse_resolves_per_company():
		got = st.warehouse(C.WH_REJECTED, H.COMPANY)
		assert got, "no rejected warehouse resolved for the settings company"
		assert frappe.db.get_value("Warehouse", got, "company") == H.COMPANY, (
			f"{got} belongs to another company"
		)
		# the resolver must key on the label, not only on the stored single value
		assert C.WH_REJECTED in st.WAREHOUSE_KEYS, "the rejected warehouse has no resolver key"
		assert C.WH_CONTROL_SAMPLE in st.WAREHOUSE_KEYS, "control sample has no resolver key"

	check("290 module warehouses resolve for the document's own company", t290_warehouse_resolves_per_company)

	# ---------------------------------------------------------------- 309
	def t309_control_sample_has_its_own_warehouse():
		control = frappe.db.get_single_value("Purchase Inward Settings", "control_sample_warehouse")
		sample = frappe.db.get_single_value("Purchase Inward Settings", "qc_sample_warehouse")
		assert control, "control_sample_warehouse is still unprovisioned"
		assert control != sample, (
			"control samples still share the QC Sample warehouse, so retained stock cannot "
			"be told apart from consumed test quantity"
		)

	check("309 retained control samples have their own warehouse", t309_control_sample_has_its_own_warehouse)

	# ---------------------------------------------------------------- 305
	def t305_multiple_evidence_per_inspection():
		meta = frappe.get_meta("Purchase QC")
		assert meta.get_field("inspection_evidence"), "no inspection evidence table"
		item = H.ensure_item(f"PITEST-WF-EV-{H.SEQ}")
		po = H.make_po(supplier, [(item, 20, 5)])
		inw = H.make_inward(po, po.items, invoice_no=f"PITEST-WF-EV-{H.SEQ}")
		inw.submit(); inw.reload()
		_receive(inw, 10)
		from alpinos.purchase import notifications as notif
        # two photos against ONE vehicle inspection, which is what BRD 4.1.2 asks for
		notif.submit_for_qc(inw.name)
		qc = frappe.get_doc(
			"Purchase QC", frappe.db.get_value("Purchase Inward", inw.name, "purchase_qc")
		)
		qc.append("inspection_evidence", {"section": "Vehicle", "file": "/files/a.png", "kind": "Photo"})
		qc.append("inspection_evidence", {"section": "Vehicle", "file": "/files/b.mp4", "kind": "Video"})
		qc.flags.ignore_permissions = True
		qc.save()
		frappe.db.commit()
		fresh = frappe.get_doc("Purchase QC", qc.name)
		assert len(fresh.inspection_evidence) == 2, "a second piece of evidence was not kept"
		for row in fresh.inspection_evidence:
			assert row.uploaded_by, "evidence row has no uploader"
			assert row.uploaded_on, "evidence row has no timestamp"

	check("305 an inspection can carry more than one image or video", t305_multiple_evidence_per_inspection)

	# ---------------------------------------------------------------- 307
	def t307_packaging_qty_mandatory_client_side():
		f = frappe.get_meta("Purchase QC Packaging Inspection").get_field("damaged_qty")
		assert f.mandatory_depends_on, (
			"packaging damaged qty is still server-only, so the form gives no warning"
		)

	check("307 packaging damaged qty is mandatory on the form too", t307_packaging_qty_mandatory_client_side)

	# ---------------------------------------------------------------- 311
	def t311_completeness_names_what_is_missing():
		item = H.ensure_item(f"PITEST-WF-VAL-{H.SEQ}")
		ch = _chain(supplier, item, 30, 30)
		pr = frappe.get_doc("Purchase Receipt", ch["pr"])
		pr.items[0].warehouse = None          # something a person can actually fix
		try:
			prf.validate_grn_completeness(pr)
			raise AssertionError("an incomplete GRN was allowed through")
		except AssertionError:
			raise
		except Exception as e:
			msg = str(e)
			assert "Target Location" in msg, f"the message does not name what is missing: {msg[:160]}"
		frappe.db.rollback()

	def t311_complete_grn_passes():
		item = H.ensure_item(f"PITEST-WF-OK-{H.SEQ}")
		ch = _chain(supplier, item, 30, 30)
		prf.validate_grn_completeness(frappe.get_doc("Purchase Receipt", ch["pr"]))
		frappe.db.commit()

	check("311 an incomplete GRN is blocked and the gap is named", t311_completeness_names_what_is_missing)
	check("311 a complete GRN passes the same check", t311_complete_grn_passes)

	return _report() if _report_now else R
