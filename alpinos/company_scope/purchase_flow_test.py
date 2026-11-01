"""The real purchase chain in the second company, as its users, through the page APIs.

	bench --site <test site> execute alpinos.company_scope.purchase_flow_test.run

Alpino Hospitality Pvt. Ltd. (APC):

	Purchase Order (page insert, Submit for Approval, Approve, Send to Supplier)
	-> Purchase Inward (insert, submit, Store receipt, Submit for QC + QC alert)
	-> Purchase QC (start, partial reject + partial quarantine, complete -> draft GRN + Quarantine)
	-> GRN final submit (stock / ledger in APC, Debit Note for the rejected quantity)
	-> Purchase Invoice from the GRN (create, submit)

and at each step: the document's company and number, its warehouses and ledgers, that a user
of the default company only can neither list, open nor act on it, that a user holding the role
only in the default company is refused in APC, who is notified, and the lists and reports in
APC, in the default company and in "All my companies".

Fixtures are named CS-FLOW-PURCHASE-... / cs.flow.purchase.*@example.com; everything the run
creates is cancelled and deleted at the end.
"""

import os

import frappe
from frappe.utils import add_days, flt, now_datetime, today

from alpinos.company_scope.testing import ALL, as_user, cleanup_user, companies, ensure_enabled, make_user, set_active
from alpinos.purchase import constants as C

R = []
S = frappe._dict()

APC = "Alpino Hospitality Pvt. Ltd."
P = "CS-FLOW-PURCHASE"
SUPPLIER = f"{P}-SUPPLIER"
PRICE_LIST = f"{P}-BUYING"
ITEM_A, ITEM_B = f"{P}-RM-A", f"{P}-RM-B"
STORES = "Stores - APC"

BUYER = "cs.flow.purchase.buyer@example.com"  # Purchase Inward User in APC
MANAGER = "cs.flow.purchase.manager@example.com"  # Purchase Inward Manager in APC
STORE = "cs.flow.purchase.store@example.com"  # Store Receiving Manager in APC
QC_USER = "cs.flow.purchase.qc@example.com"  # Purchase QC Manager in APC
ADMIN = "cs.flow.purchase.admin@example.com"  # Purchase Inward Admin in APC
MIX = "cs.flow.purchase.mix@example.com"  # approver / admin / QC in the default company, buyer in APC
HOME = "cs.flow.purchase.home@example.com"  # everything, in the default company only
USERS = (BUYER, MANAGER, STORE, QC_USER, ADMIN, MIX, HOME)
ATTACHMENT = "cs-flow-purchase-invoice.txt"


# --- harness -------------------------------------------------------------------------------


def check(label, fn):
	"""One step or assertion; what it wrote is kept only when it passed."""
	try:
		fn()
		R.append(("PASS", label, ""))
		frappe.db.commit()
		return
	except AssertionError as e:
		R.append(("FAIL", label, str(e)[:300]))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))
		if os.environ.get("CS_FLOW_DEBUG"):
			print(frappe.get_traceback())
	frappe.db.rollback()
	frappe.local.message_log = []


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, contains=None, exc=Exception):
	try:
		fn()
	except exc as e:
		if contains and contains.lower() not in str(e).lower():
			raise AssertionError(f"raised, but '{contains}' not in: {str(e)[:200]}")
		frappe.db.rollback()
		frappe.local.message_log = []
		return
	raise AssertionError("did not raise")


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	for key in ("po", "inward", "qc", "quarantine", "grn", "debit_note", "invoice"):
		if S.get(key):
			print(f"  {key}: {S[key]}")
	if S.get("left"):
		print("  left in the database:", S.left)
	frappe.db.commit()
	return R


def _client(method, *args, **kwargs):
	import frappe.client as client

	return getattr(client, method)(*args, **kwargs)


def _apc_warehouse(name):
	return frappe.db.get_value("Warehouse", name, "company") == APC


# --- fixtures ------------------------------------------------------------------------------


def _tags(company):
	return [{"company": company}]


def _fixtures(A):
	from alpinos.purchase.e2e_test import _test_hsn, _untyped_leaf_group

	if not frappe.db.exists("Price List", PRICE_LIST):
		frappe.get_doc(
			{"doctype": "Price List", "price_list_name": PRICE_LIST, "buying": 1, "selling": 0,
			 "currency": "INR", "enabled": 1, "custom_companies": _tags(APC)}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Supplier", SUPPLIER):
		frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": SUPPLIER, "supplier_group": "Raw Material",
			 "supplier_type": "Company", "gst_category": "Unregistered", "default_price_list": PRICE_LIST,
			 "custom_companies": _tags(APC)}
		).insert(ignore_permissions=True)
	group = _untyped_leaf_group()
	S.hsn = _test_hsn().get("gst_hsn_code") or ""
	# The supplier invoice copy the invoice must carry (VAL-UNF-02).
	S.attachment = frappe.get_doc({"doctype": "File", "file_name": ATTACHMENT, "is_private": 0,
		"content": b"CS flow purchase invoice"}).insert(ignore_permissions=True).file_url
	for code, shelf_life in ((ITEM_A, 180), (ITEM_B, 0)):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{"doctype": "Item", "item_code": code, "item_name": code, "item_group": group,
				 "stock_uom": "Nos", "is_stock_item": 1, "shelf_life_in_days": shelf_life,
				 "custom_gst_percent": 5, **_test_hsn(), "custom_companies": _tags(APC)}
			).insert(ignore_permissions=True)
	make_user(BUYER, {APC: ["Purchase Inward User"]})
	make_user(MANAGER, {APC: ["Purchase Inward Manager"]})
	make_user(STORE, {APC: ["Store Receiving Manager"]})
	make_user(QC_USER, {APC: ["Purchase QC Manager"]})
	make_user(ADMIN, {APC: ["Purchase Inward Admin"]})
	make_user(MIX, {A: ["Purchase Inward Manager", "Purchase Inward Admin", "Purchase QC Manager"],
		APC: ["Purchase Inward User"]}, active_company=APC)
	make_user(HOME, {A: ["Purchase Inward Admin", "Purchase Inward Manager", "Purchase QC Manager",
		"Store Receiving Manager", "Purchase Accounts User"]})
	for user in USERS:
		_as_employee(user)
	frappe.db.commit()


def _as_employee(user):
	"""Staff on this site are Employees: the global Employee role, which also gives `select` on
	Account (ERPNext checks it on the party account even inside ignore_permissions, e.g. when
	the GRN is drafted as the QC user completes the QC). ERPNext strips the role from a User
	saved without an Employee record, so it is written straight to Has Role."""
	if not frappe.db.exists("Has Role", {"parenttype": "User", "parent": user, "role": "Employee"}):
		frappe.get_doc({"doctype": "Has Role", "parenttype": "User", "parentfield": "roles", "parent": user,
			"role": "Employee", "idx": 99}).db_insert()
		frappe.cache.hdel("roles", user)


# --- cleanup -------------------------------------------------------------------------------


def _ours(doctype, field="supplier"):
	return frappe.get_all(doctype, {field: SUPPLIER}, pluck="name") if frappe.db.exists("DocType", doctype) else []


#: Module documents that post nothing to a ledger: one a cancel refuses is marked cancelled.
_NO_LEDGER = ("Purchase Order", "Purchase Inward", "Purchase QC", "Purchase Quarantine")


def _cancel_delete(doctype, name, left):
	if not frappe.db.exists(doctype, name):
		return
	if doctype == "Purchase Inward":
		# Its downstream is already gone; the links would refuse the cancel.
		frappe.db.set_value(doctype, name, {f: None for f in (
			"purchase_qc", "purchase_receipt", "purchase_invoice", "debit_note", "purchase_quarantine")},
			update_modified=False)
	try:
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			# Cleanup only: the chain is unwound from the end, so back links are expected.
			doc.flags.ignore_links = True
			doc.cancel()
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
		frappe.db.commit()
		return
	except Exception as e:
		frappe.db.rollback()
		error = str(e)[:120]
	if doctype in _NO_LEDGER:
		try:
			frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
			frappe.db.commit()
			return
		except Exception:
			frappe.db.rollback()
	left.append(f"{doctype} {name}: {error}")


def _cleanup():
	frappe.set_user("Administrator")
	left = []
	invoices = _ours("Purchase Invoice")
	receipts = _ours("Purchase Receipt")
	qcs = _ours("Purchase QC")
	quarantines = _ours("Purchase Quarantine")
	inwards = _ours("Purchase Inward")
	orders = _ours("Purchase Order")
	vouchers = invoices + receipts + qcs + quarantines + inwards + orders
	# Normal invoices first, then the debit notes (returns), the GRNs, QCs, inwards, orders.
	for name in sorted(invoices, key=lambda n: frappe.db.get_value("Purchase Invoice", n, "is_return") or 0):
		_cancel_delete("Purchase Invoice", name, left)
	for name in receipts:
		_cancel_delete("Purchase Receipt", name, left)
	for name in qcs:
		_cancel_delete("Purchase QC", name, left)
	for name in quarantines:
		_cancel_delete("Purchase Quarantine", name, left)
	for name in inwards:
		_cancel_delete("Purchase Inward", name, left)
	for name in orders:
		_cancel_delete("Purchase Order", name, left)
	# The ledgers the cancelled vouchers leave behind, and what hangs off our own items.
	if vouchers:
		for dt in ("Stock Ledger Entry", "GL Entry", "Payment Ledger Entry", "Repost Item Valuation"):
			if frappe.db.exists("DocType", dt):
				frappe.db.delete(dt, {"voucher_no": ["in", vouchers]})
		frappe.db.delete("Notification Log", {"document_name": ["in", vouchers]})
		frappe.db.delete("Comment", {"reference_name": ["in", vouchers]})
		frappe.db.delete("Version", {"docname": ["in", vouchers]})
	for dt in ("Stock Ledger Entry", "Bin"):
		frappe.db.delete(dt, {"item_code": ["in", [ITEM_A, ITEM_B]]})
	if frappe.db.exists("DocType", "MRP Batch"):
		for name in frappe.get_all("MRP Batch", {"item_code": ["in", [ITEM_A, ITEM_B]]}, pluck="name"):
			frappe.delete_doc("MRP Batch", name, force=True, ignore_permissions=True, delete_permanently=True)
	for name in frappe.get_all("Batch", {"item": ["in", [ITEM_A, ITEM_B]]}, pluck="name"):
		frappe.delete_doc("Batch", name, force=True, ignore_permissions=True, delete_permanently=True)
	for dt, name in (("Item", ITEM_A), ("Item", ITEM_B), ("Supplier", SUPPLIER), ("Price List", PRICE_LIST)):
		try:
			if frappe.db.exists(dt, name):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True, delete_permanently=True)
		except Exception as e:
			frappe.db.rollback()
			left.append(f"{dt} {name}: {str(e)[:120]}")
	for name in frappe.get_all("File", {"file_name": ATTACHMENT}, pluck="name"):
		frappe.delete_doc("File", name, force=True, ignore_permissions=True, delete_permanently=True)
	for user in USERS:
		cleanup_user(user)
	# The trash copies of what was deleted here, and the errors the run logged on purpose
	# (a refused report run).
	frappe.db.sql(
		"""delete from `tabDeleted Document` where deleted_name like %(names)s
		or data like %(supplier)s or data like %(users)s""",
		{"names": f"{P}%", "supplier": f"%{SUPPLIER}%", "users": "%cs.flow.purchase.%"},
	)
	if S.get("started"):
		frappe.db.sql(
			"""delete from `tabError Log` where creation >= %(since)s and method like %(method)s
			and error like %(apc)s""",
			{"since": S.started, "method": "Report execution failed for: Purchase GRN Register",
			 "apc": f"%Purchase GRN Register for <strong>{APC}%"},
		)
	frappe.db.commit()
	return left


# --- the run -------------------------------------------------------------------------------


def run():
	from alpinos.company_scope import reports

	R.clear()
	S.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	ensure_enabled()
	reports.patch()  # what before_request does on the server: reports follow the company
	A = companies()[0]
	S.A = A
	_cleanup()
	S.started = now_datetime()
	captured = _capture_messages()
	try:
		_fixtures(A)
		check("fixtures: supplier, items and price list are tagged to APC only", lambda: _assert(
			all(frappe.db.get_value(dt, n, "custom_company_scope") == f"|{APC}|"
				for dt, n in (("Supplier", SUPPLIER), ("Item", ITEM_A), ("Item", ITEM_B), ("Price List", PRICE_LIST)))))
		_purchase_order()
		_inward()
		_qc()
		_grn()
		_invoice()
		_lists_and_reports()
	finally:
		_restore_messages(captured)
		frappe.set_user("Administrator")
		frappe.flags.in_test = False
		S.left = _cleanup()
	return _report()


# --- messages: capture instead of sending ---------------------------------------------------


def _capture_messages():
	import alpinos.raven_notifications as raven

	saved = {"sendmail": frappe.sendmail, "dm": getattr(raven, "_send_dm", None)}
	S.mails, S.dms = [], []

	def sendmail(recipients=None, **kwargs):
		S.mails.append(list(recipients or []))

	def send_dm(bot, user, *args, **kwargs):
		S.dms.append(user)

	frappe.sendmail = sendmail
	if saved["dm"]:
		raven._send_dm = send_dm
	return saved


def _restore_messages(saved):
	import alpinos.raven_notifications as raven

	frappe.sendmail = saved["sendmail"]
	if saved["dm"]:
		raven._send_dm = saved["dm"]


# --- 2. Purchase Order ---------------------------------------------------------------------


def _purchase_order():
	from alpinos.purchase import po_list_api, purchase_order_approval as POA, purchase_order_fields as POF

	set_active(MIX, APC)

	def create():
		as_user(BUYER, lambda: POF.get_supplier_info(SUPPLIER, company=APC))
		payload = {
			"doctype": "Purchase Order",
			"company": as_user(BUYER, _current),
			"custom_inward_type": C.INWARD_RM,
			"supplier": SUPPLIER,
			"transaction_date": today(),
			"schedule_date": add_days(today(), 7),
			"set_warehouse": STORES,
			"custom_direct_purchase_invoice": 0,
			"items": [
				{"item_code": code, "qty": qty, "price_list_rate": rate, "discount_percentage": 0,
				 "custom_gst_percent": 5, "custom_hsn_code": S.hsn, "schedule_date": add_days(today(), 7),
				 "warehouse": STORES}
				for code, qty, rate in ((ITEM_A, 100, 50), (ITEM_B, 50, 20))
			],
		}
		S.po = as_user(BUYER, lambda: _client("insert", payload))["name"]

	check("PO: the buyer creates it on the PO page", create)
	if not S.get("po"):
		return
	po = lambda: frappe.get_doc("Purchase Order", S.po)
	check("PO: company APC, number POR-APC-<FY>-NNNNN", lambda: _assert(
		po().company == APC and S.po.startswith("POR-APC-"), (po().company, S.po)))
	check("PO: price list and warehouses are APC's", lambda: _assert(
		po().buying_price_list == PRICE_LIST and all(_apc_warehouse(r.warehouse) for r in po().items)))
	check("PO: a default-company user does not list it", lambda: _assert(
		not as_user(HOME, lambda: po_list_api.get_purchase_order_list(po_id=S.po))["data"]))
	check("PO: a default-company user cannot open it", lambda: _raises(
		lambda: as_user(HOME, lambda: POA.get_available_actions(S.po)), exc=frappe.PermissionError))
	check("PO: the buyer submits it for approval", lambda: as_user(
		BUYER, lambda: POA.perform_action(S.po, "Submit for Approval")))
	check("PO: an approver of the default company only is refused in APC", lambda: _raises(
		lambda: as_user(MIX, lambda: POA.perform_action(S.po, "Approve")), "not available"))
	check("PO: ...and is not offered Approve", lambda: _assert(
		"Approve" not in [a["action"] for a in as_user(MIX, lambda: POA.get_available_actions(S.po))["actions"]]))
	check("PO: a default-company user cannot approve it", lambda: _raises(
		lambda: as_user(HOME, lambda: POA.perform_action(S.po, "Approve")), exc=frappe.PermissionError))
	check("PO: the APC approver approves (submits) it", lambda: (
		as_user(MANAGER, lambda: POA.perform_action(S.po, "Approve")),
		_assert(po().docstatus == 1, po().docstatus)))
	check("PO: the APC approver sends it to the supplier", lambda: (
		as_user(MANAGER, lambda: POA.perform_action(S.po, "Send to Supplier")),
		_assert(po().custom_approval_status == C.PO_SENT_TO_SUPPLIER, po().custom_approval_status)))


def _current():
	from alpinos.company_scope.helpers import current_company

	return current_company()


# --- 3. Purchase Inward --------------------------------------------------------------------


def _inward():
	from alpinos.purchase import inward_api, inward_list_api

	if not S.get("po") or frappe.db.get_value("Purchase Order", S.po, "docstatus") != 1:
		return

	def create():
		_assert(as_user(BUYER, lambda: inward_api.validate_creation(purchase_order=S.po))["company"] == APC)
		got = as_user(BUYER, lambda: inward_api.get_purchase_order_items(S.po, inward_type=C.INWARD_RM))
		_assert(len(got["items"]) == 2, got)
		doc = {
			"doctype": "Purchase Inward",
			"purchase_order": S.po,
			"company": got["company"],
			"gross_weight": 150,
			"inward_datetime": str(now_datetime()),
			"items": [{"item_code": r["item_code"], "po_detail": r["po_detail"], "planned_qty": r["pending_qty"]}
				for r in got["items"]],
		}
		S.inward = as_user(BUYER, lambda: _client("insert", doc))["name"]
		as_user(BUYER, lambda: inward_api.run_action(S.inward, "submit"))

	check("Inward: the buyer creates and submits it", create)
	if not S.get("inward"):
		return
	inward = lambda: frappe.get_doc("Purchase Inward", S.inward)
	check("Inward: company APC, number INW-APC-<FY>-NNNNN", lambda: _assert(
		inward().company == APC and S.inward.startswith("INW-APC-") and inward().docstatus == 1,
		(inward().company, S.inward, inward().docstatus)))
	check("Inward: the PO picker offers the PO to the buyer", lambda: _assert(
		S.po in [r[0] for r in as_user(BUYER, lambda: inward_api.inward_po_query("Purchase Order", S.po, "name", 0, 20, {}))]))
	check("Inward: a default-company user does not list it", lambda: _assert(
		not as_user(HOME, lambda: inward_list_api.get_purchase_inward_list(search=S.inward))["data"]))
	check("Inward: a default-company user cannot open it", lambda: _raises(
		lambda: as_user(HOME, lambda: inward_api.get_form_context(S.inward)), exc=frappe.PermissionError))
	check("Inward: a default-company Store user cannot hand it to QC", lambda: _raises(
		lambda: as_user(HOME, lambda: inward_api.run_action(S.inward, "submit_for_qc")), exc=frappe.PermissionError))

	def receive():
		doc = as_user(STORE, lambda: _client("get", "Purchase Inward", S.inward))
		doc.update({
			"actual_arrival_datetime": str(now_datetime()),
			"target_warehouse": STORES,
			"invoice_number": f"{P}-INV-{frappe.generate_hash(length=6)}",
			"invoice_date": today(),
		})
		for row in doc["items"]:
			row.update({"received_qty": 100 if row["item_code"] == ITEM_A else 50, "target_warehouse": STORES,
				"gst_percent": 5, "hsn_code": S.hsn})
			if row["item_code"] == ITEM_A:
				row["manufacturing_date"] = today()
		as_user(STORE, lambda: _client("save", doc))

	check("Inward: Store records the receipt (100 + 50) into Stores - APC", receive)
	S.mails.clear()
	S.dms.clear()
	check("Inward: Store hands it to QC", lambda: as_user(STORE, lambda: inward_api.run_action(S.inward, "submit_for_qc")))
	S.qc = frappe.db.get_value("Purchase Inward", S.inward, "purchase_qc")
	if not S.qc:
		return
	# A new QC: every bell about it was rung by this hand-over.
	logs = frappe.get_all("Notification Log", {"document_type": "Purchase QC", "document_name": S.qc}, pluck="for_user")
	from alpinos.company_scope.helpers import users_with_roles

	apc_qc = set(users_with_roles(list(C.QC_ROLES), APC))
	check("QC alert: the APC QC user is told", lambda: _assert(QC_USER in logs, logs))
	check("QC alert: every bell goes to a QC role holder in APC", lambda: _assert(
		logs and set(logs) <= apc_qc, set(logs) - apc_qc))
	check("QC alert: QC people of the default company only are not told", lambda: _assert(
		MIX not in logs and HOME not in logs, logs))
	check("QC alert: e-mail and Raven go to the same people", lambda: _assert(
		all(set(m) <= {frappe.db.get_value("User", u, "email") for u in apc_qc} for m in S.mails)
		and set(S.dms) <= apc_qc, (S.mails, S.dms)))


# --- 4. Purchase QC ------------------------------------------------------------------------


def _qc():
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as QCM
	from alpinos.purchase import qc_list_api
	from alpinos.purchase.settings import get_settings

	if not S.get("qc"):
		return
	qc = lambda: frappe.get_doc("Purchase QC", S.qc)
	check("QC: company APC", lambda: _assert(qc().company == APC, qc().company))
	S.qc_series_note = "" if "APC" in S.qc else "Purchase QC has no naming series, so no APC code"
	check("QC: a default-company user does not list it", lambda: _assert(
		not as_user(HOME, lambda: qc_list_api.get_purchase_qc_list(qc_id=S.qc))["data"]))
	check("QC: a default-company QC Manager cannot start it", lambda: _raises(
		lambda: as_user(HOME, lambda: QCM.start_qc(S.qc)), exc=frappe.PermissionError))
	check("QC Stock report: the QC lot is with QC in APC", lambda: _assert(
		S.qc in {r.get("purchase_qc") for r in _report_rows(MIX, "Purchase QC Stock", {"company": APC})}))
	check("QC: the APC QC user starts it", lambda: as_user(QC_USER, lambda: QCM.start_qc(S.qc)))

	def decide():
		doc = as_user(QC_USER, lambda: _client("get", "Purchase QC", S.qc))
		for row in doc["items"]:
			if row["item_code"] == ITEM_A:
				# 100 received: 80 approved (30 of it held in quarantine), 20 rejected
				row.update({"approved_qty": 80, "rejected_qty": 20, "rejection_reason": "CS flow: moisture above spec",
					"quarantine": 1, "quarantine_qty": 30, "internal_batch_no": "CSFLOWA"})
			else:
				row.update({"approved_qty": 50, "rejected_qty": 0, "quarantine": 0, "quarantine_qty": 0,
					"internal_batch_no": "CSFLOWB"})
		a = next(r for r in doc["items"] if r["item_code"] == ITEM_A)
		doc.update({
			"quarantine_items": 1, "quarantine_reminder_days": 3, "quarantine_reason": "CS flow: lab report awaited",
			"vehicle_inspection": [{"vehicle_no": "GJ01CS0001", "vehicle_condition": C.CONDITION_GOOD}],
			"material_inspection": [{"item_code": c, "material_condition": C.CONDITION_GOOD} for c in (ITEM_A, ITEM_B)],
			"packaging_inspection": [{"item_code": c, "packaging_condition": C.CONDITION_GOOD} for c in (ITEM_A, ITEM_B)],
			"sample_testing": [{"item_code": ITEM_A, "sample_qty": 1, "qc_item": a["name"]}],
			"control_sample": [{"item_code": ITEM_A, "control_sample_taken": 1, "control_sample_qty": 1, "qc_item": a["name"]}],
			"vehicle_inspection_done": 1, "material_inspection_done": 1, "packaging_inspection_done": 1,
			"sample_testing_done": 1,
		})
		as_user(QC_USER, lambda: _client("save", doc))

	check("QC: decision saved (A 80 ok / 20 rejected / 30 quarantined, B 50 ok)", decide)
	check("QC: the APC QC user completes it", lambda: as_user(QC_USER, lambda: QCM.complete_qc(S.qc)))
	check("QC: submitted, Partially Approved", lambda: _assert(
		qc().docstatus == 1 and qc().qc_result == C.QC_RESULT_PARTIAL, (qc().docstatus, qc().qc_result)))
	settings = get_settings(APC)
	check("QC: control sample stored in APC's Control Sample warehouse", lambda: _assert(
		qc().control_sample and qc().control_sample[0].storage_location == settings.get("control_sample_warehouse")
		== "Control Sample - APC", [r.storage_location for r in qc().control_sample]))
	S.quarantine = frappe.db.get_value("Purchase QC", S.qc, "quarantine_document")
	S.grn = frappe.db.get_value("Purchase QC", S.qc, "purchase_receipt")
	check("Quarantine: raised in APC, holding 30 of A in Quarantine - APC", lambda: _assert(
		S.quarantine and frappe.db.get_value("Purchase Quarantine", S.quarantine, "company") == APC
		and [(r.item_code, flt(r.qty), r.quarantine_warehouse)
			for r in frappe.get_doc("Purchase Quarantine", S.quarantine).items] == [(ITEM_A, 30, "Quarantine - APC")],
		S.quarantine))
	check("Quarantine: number carries APC (QRN-APC-...)", lambda: _assert(
		S.quarantine and S.quarantine.startswith("QRN-APC-"), S.quarantine))
	check("Quarantine: the warehouses come from APC's row in Purchase Inward Settings", lambda: _assert(
		(settings.get("quarantine_warehouse"), settings.get("rejected_warehouse"), settings.get("qc_hold_warehouse"))
		== ("Quarantine - APC", "Rejected - APC", "QC Hold - APC"), settings))


# --- 5. GRN --------------------------------------------------------------------------------


def _grn():
	from alpinos.purchase import grn as G
	from alpinos.purchase import grn_edit, grn_list_api, quarantine

	if not S.get("grn"):
		check("GRN: drafted by completing the QC", lambda: _assert(False, "no GRN"))
		return
	grn = lambda: frappe.get_doc("Purchase Receipt", S.grn)
	check("GRN: drafted in APC, number GRN-APC-<FY>-NNNNN", lambda: _assert(
		grn().company == APC and grn().docstatus == 0 and S.grn.startswith("GRN-APC-"), (grn().company, S.grn)))

	def lines():
		out = {}
		for r in grn().items:
			out.setdefault(r.item_code, []).append((flt(r.qty), flt(r.rejected_qty), r.warehouse, r.rejected_warehouse))
		return out

	def a_split():
		rows = lines()[ITEM_A]
		_assert(sum(q for q, *_ in rows) == 80 and sum(r for _q, r, *_ in rows) == 20, rows)
		_assert({w for _q, _r, w, _rw in rows} == {STORES, "Quarantine - APC"}, rows)
		_assert(all(rw == "Rejected - APC" for _q, r, _w, rw in rows if r), rows)

	check("GRN: A 80 accepted into Stores / Quarantine - APC, 20 rejected into Rejected - APC", a_split)
	check("GRN: B 50 into Stores - APC", lambda: _assert(
		[(q, w) for q, _r, w, _rw in lines()[ITEM_B]] == [(50, STORES)], lines()[ITEM_B]))
	check("GRN: a second Generate GRN is refused", lambda: _raises(
		lambda: as_user(BUYER, lambda: G.generate_grn(S.inward)), "not available"))
	check("GRN: a default-company user does not list it", lambda: _assert(
		not as_user(HOME, lambda: grn_list_api.get_grn_list(grn_id=S.grn))["data"]))
	check("GRN: a default-company user cannot open it", lambda: _raises(
		lambda: as_user(HOME, lambda: grn_edit.get_grn_context(S.grn)), exc=frappe.PermissionError))
	check("GRN: an Admin of the default company only cannot submit it in APC", lambda: _raises(
		lambda: as_user(MIX, lambda: grn_edit.submit_grn(S.grn)), "Only", exc=frappe.PermissionError))
	check("GRN: the APC Admin is offered Submit", lambda: _assert(
		as_user(ADMIN, lambda: grn_edit.get_grn_context(S.grn))["can_submit"]))
	check("GRN: the APC Admin final-submits it", lambda: (
		as_user(ADMIN, lambda: grn_edit.submit_grn(S.grn)), _assert(grn().docstatus == 1, grn().docstatus)))
	if grn().docstatus != 1:
		return

	sle = frappe.get_all("Stock Ledger Entry", {"voucher_no": S.grn, "is_cancelled": 0},
		["company", "warehouse", "item_code", "actual_qty"])
	gle = frappe.get_all("GL Entry", {"voucher_no": S.grn, "is_cancelled": 0}, ["company", "account"])
	stock = {}
	for r in sle:
		stock[(r.item_code, r.warehouse)] = stock.get((r.item_code, r.warehouse), 0) + flt(r.actual_qty)
	check("GRN: stock ledger in APC warehouses only", lambda: _assert(
		sle and all(r.company == APC and _apc_warehouse(r.warehouse) for r in sle), sle))
	check("GRN: A 50 Stores / 30 Quarantine / 20 Rejected, B 50 Stores", lambda: _assert(
		stock == {(ITEM_A, STORES): 50, (ITEM_A, "Quarantine - APC"): 30, (ITEM_A, "Rejected - APC"): 20,
			(ITEM_B, STORES): 50}, stock))
	check("GRN: general ledger in APC accounts only", lambda: _assert(
		gle and all(r.company == APC and r.account.endswith(" - APC") for r in gle), gle))

	S.debit_note = frappe.db.get_value("Purchase Receipt", S.grn, "custom_debit_note")
	note = lambda: frappe.get_doc("Purchase Invoice", S.debit_note)
	check("Debit Note: raised in APC for the 20 rejected", lambda: _assert(
		S.debit_note and note().company == APC and note().is_return
		and [(r.item_code, flt(r.qty), r.warehouse) for r in note().items] == [(ITEM_A, -20, "Rejected - APC")]
		and note().credit_to.endswith(" - APC"),
		S.debit_note))
	check("Debit Note: number carries APC", lambda: _assert(S.debit_note and "-APC-" in S.debit_note, S.debit_note))
	check("Quarantine: a default-company user cannot release it", lambda: _raises(
		lambda: as_user(HOME, lambda: quarantine.release_items(S.quarantine, [])), exc=frappe.PermissionError))


# --- 6. Purchase Invoice -------------------------------------------------------------------


def _invoice():
	from alpinos.purchase import invoice_list_api, purchase_invoice as INV

	if not S.get("grn") or frappe.db.get_value("Purchase Receipt", S.grn, "docstatus") != 1:
		return
	check("Invoice: the GRN picker offers the GRN to the APC buyer", lambda: _assert(
		S.grn in [r[0] for r in as_user(BUYER, lambda: invoice_list_api.eligible_grn_query(
			"Purchase Receipt", S.grn, "name", 0, 20, {}))]))
	check("Invoice: the default-company picker does not", lambda: _assert(
		S.grn not in [r[0] for r in as_user(HOME, lambda: invoice_list_api.eligible_grn_query(
			"Purchase Receipt", S.grn, "name", 0, 20, {}))]))
	check("Invoice: a default-company user cannot raise one on the GRN", lambda: _raises(
		lambda: as_user(HOME, lambda: invoice_list_api.create_invoice("grn", S.grn)), exc=frappe.PermissionError))

	def create():
		S.invoice = as_user(BUYER, lambda: invoice_list_api.create_invoice("grn", S.grn))["name"]

	check("Invoice: the APC buyer creates it from the GRN", create)
	if not S.get("invoice"):
		return
	inv = lambda: frappe.get_doc("Purchase Invoice", S.invoice)
	check("Invoice: company APC, number PIV-APC-<FY>-NNNNN, Creditors - APC", lambda: _assert(
		inv().company == APC and S.invoice.startswith("PIV-APC-") and inv().credit_to == "Creditors - APC",
		(inv().company, S.invoice, inv().credit_to)))
	check("Invoice: bills the 130 approved", lambda: _assert(
		sum(flt(r.qty) for r in inv().items) == 130, [(r.item_code, r.qty) for r in inv().items]))
	check("Invoice: a default-company user cannot open it", lambda: _raises(
		lambda: as_user(HOME, lambda: INV.get_invoice_context(S.invoice)), exc=frappe.PermissionError))
	check("Invoice: the APC buyer submits it", lambda: (
		as_user(BUYER, lambda: INV.submit_invoice(S.invoice, {
			"bill_no": f"{P}-BILL", "bill_date": today(), "custom_payment_due_date": add_days(today(), 30),
			"custom_invoice_attachment": S.attachment})),
		_assert(inv().docstatus == 1, inv().docstatus)))
	check("Invoice: general ledger in APC accounts only", lambda: _assert(
		all(r.company == APC and r.account.endswith(" - APC")
			for r in frappe.get_all("GL Entry", {"voucher_no": S.invoice, "is_cancelled": 0}, ["company", "account"]))
		and frappe.db.count("GL Entry", {"voucher_no": S.invoice, "is_cancelled": 0}) > 0))


# --- 7. lists and reports ------------------------------------------------------------------


def _report_rows(user, report, filters):
	from frappe.desk.query_report import run as run_report

	out = as_user(user, lambda: run_report(report, filters=filters, ignore_prepared_report=True))
	rows = out.get("result") or []
	return [r for r in rows if isinstance(r, dict)]


def _lists_and_reports():
	from alpinos.purchase import grn_list_api, invoice_list_api, inward_list_api, po_list_api, qc_list_api

	docs = [
		("PO", S.get("po"), lambda n: po_list_api.get_purchase_order_list(po_id=n)),
		("Inward", S.get("inward"), lambda n: inward_list_api.get_purchase_inward_list(search=n)),
		("QC", S.get("qc"), lambda n: qc_list_api.get_purchase_qc_list(qc_id=n)),
		("GRN", S.get("grn"), lambda n: grn_list_api.get_grn_list(grn_id=n)),
		("Invoice", S.get("invoice"), lambda n: invoice_list_api.get_invoice_list(invoice_id=n)),
	]
	for label, name, fetch in docs:
		if not name:
			continue

		def listed(user, name=name, fetch=fetch):
			return name in [r.get("name") for r in as_user(user, lambda: fetch(name))["data"]]

		set_active(MIX, APC)
		check(f"{label} list: shown working in APC", lambda f=listed: _assert(f(MIX)))
		set_active(MIX, S.A)
		check(f"{label} list: hidden after switching to the default company", lambda f=listed: _assert(not f(MIX)))
		set_active(MIX, ALL)
		check(f"{label} list: shown in All my companies", lambda f=listed: _assert(f(MIX)))
		check(f"{label} list: never for a default-company user", lambda f=listed: _assert(not f(HOME)))

	if S.get("grn"):
		set_active(MIX, APC)
		check("GRN Register: lists the GRN for APC", lambda: _assert(
			S.grn in {r.get("name") for r in _report_rows(MIX, "Purchase GRN Register", {"company": APC})}))
		set_active(MIX, S.A)
		check("GRN Register: not in the default company", lambda: _assert(
			S.grn not in {r.get("name") for r in _report_rows(MIX, "Purchase GRN Register", {"company": S.A})}))
		set_active(MIX, ALL)
		check("GRN Register: All my companies, no company picked, lists it", lambda: _assert(
			S.grn in {r.get("name") for r in _report_rows(MIX, "Purchase GRN Register", {})}))
		check("GRN Register: a default-company user gets nothing of APC", lambda: _assert(
			S.grn not in {r.get("name") for r in _report_rows(HOME, "Purchase GRN Register", {})}))
		check("GRN Register: a default-company user cannot ask for APC", lambda: _raises(
			lambda: _report_rows(HOME, "Purchase GRN Register", {"company": APC})))
		set_active(MIX, APC)
