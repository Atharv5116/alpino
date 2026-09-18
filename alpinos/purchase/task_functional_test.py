"""Task-sheet functional test — every task line exercised, including the wrong-input paths.

    bench --site alpinos.test execute alpinos.purchase.task_functional_test.run

WHAT THIS IS FOR
----------------
The other suites prove the happy path. The errors users actually meet come from the
paths around it: the wrong role, a blank field, a quantity one over, an action in the
wrong status. So each task line gets probes that RUN the function the task delivers and
record how it behaved, sorted into:

    PASS   behaves as the BRD says
    GAP    the rule is not enforced, or the feature is not there
    FAIL   it runs, but does the wrong thing or refuses with the wrong message
    ERROR  a raw crash or framework error reaches the user -- AttributeError, "not
           found", a bare mandatory list. Nothing in this class should ever happen.
    DIFF   works, but differently from the BRD (a design decision to confirm)
    INFO   observed value, recorded for the reader

Every probe runs inside a savepoint. A probe that fails, or that is ALLOWED when it
should have been refused, is rolled back, so one broken rule cannot cascade into the
probes after it.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, flt, get_datetime, getdate, now_datetime, today

from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H

R = []

_RAW = (AttributeError, TypeError, KeyError, IndexError, NameError, ValueError, ZeroDivisionError)


def _kind(e):
	if isinstance(e, _RAW):
		return "crash"
	if isinstance(e, frappe.DoesNotExistError):
		return "not-found"
	if isinstance(e, frappe.MandatoryError):
		return "raw-mandatory"
	if isinstance(e, frappe.TimestampMismatchError):
		return "raw-timestamp"
	return "handled"


def _msg(e):
	"""What the user is actually shown.

	Document.check_permission raises a PermissionError with an EMPTY message and puts the
	text in frappe.flags.error_message ("You need the 'write' permission on ..."), which is
	what the desk displays. Reading only str(e) made those correct refusals look blank.
	"""
	text = frappe.utils.strip_html(str(e)).strip()
	if not text and isinstance(e, frappe.PermissionError):
		text = frappe.utils.strip_html(frappe.flags.get("error_message") or "").strip()
	return text.replace("\n", " ")[:240]


def _rollback():
	try:
		frappe.db.rollback(save_point="tft_probe")
	except Exception:
		pass


def probe(task, label, fn, expect=None, as_user=None, diff=None):
	"""Run one function as `as_user`.

	expect=None  -> must succeed.
	expect="txt" -> must be refused with a handled error containing txt.
	expect=""    -> must be refused with any handled error.
	diff="..."   -> a refusal that is by design but differs from the BRD is DIFF, not FAIL.
	"""
	frappe.db.savepoint("tft_probe")
	try:
		if as_user:
			frappe.set_user(as_user)
		out = fn()
		frappe.set_user("Administrator")
		if expect is None:
			R.append((task, "PASS", label, ""))
			return out
		_rollback()
		R.append((task, "GAP", label, "expected a refusal, but it was allowed"))
		return None
	except Exception as e:
		frappe.set_user("Administrator")
		_rollback()
		kind, msg = _kind(e), _msg(e)
		if expect is None:
			state = "ERROR" if kind != "handled" else ("DIFF" if diff else "FAIL")
			R.append((task, state, label, f"{type(e).__name__}: {msg}" + (f" -- {diff}" if diff else "")))
		elif kind != "handled":
			R.append((task, "ERROR", label, f"refused, but as a raw {type(e).__name__}: {msg}"))
		elif expect == "" or expect.lower() in msg.lower():
			R.append((task, "PASS", label, ""))
		else:
			R.append((task, "FAIL", label, f"refused with a different message: {msg}"))
		return None


def check(task, label, ok, detail="", state_if_false="FAIL"):
	R.append((task, "PASS" if ok else state_if_false, label, "" if ok else detail))


def info(task, label, detail):
	R.append((task, "INFO", label, detail))


# ---------------------------------------------------------------- fixtures

T = {}


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0],
			 "send_welcome_email": 0, "enabled": 1}
		).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	u.set("roles", [])
	for role in roles:
		if frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
	return email


def uniq(prefix):
	return f"{prefix}-{H.SEQ}-{frappe.generate_hash(length=5)}"


def mk_po(qty=100, itype=C.INWARD_RM, direct=0, shelf=0, lines=1):
	items = [
		(H.ensure_item(uniq(f"TFT-{itype}"), shelf_life_days=shelf), qty, 10) for _ in range(lines)
	]
	return H.make_po(T["supplier"], items, inward_type=itype, direct_invoice=direct)


def mk_inward(po, invoice=None, challan=None):
	return H.make_inward(po, po.items, invoice_no=invoice or uniq("INV"), challan=challan)


def receive(pi, qty, mfg=None, batch=None, wh="__default__", arrival=True, verified=False,
            excess=0, as_admin=True):
	pi = frappe.get_doc("Purchase Inward", pi.name if hasattr(pi, "name") else pi)
	if arrival:
		pi.actual_arrival_datetime = now_datetime()
	pi.vehicle_details_verified = 1 if verified else 0
	if verified:
		pi.actual_vehicle_no = "GJ-05-TF-0001"
		pi.actual_driver_contact_no = "9000000031"
	pi.allow_excess_qty = excess
	if wh is None:
		# No location anywhere: a Default Target Location would fill the blank lines.
		pi.target_warehouse = None
	for r in pi.items:
		r.received_qty = qty
		r.target_warehouse = T["wh"] if wh == "__default__" else wh
		r.manufacturing_date = mfg or today()
		if batch:
			r.batch_no = batch
	if as_admin:
		pi.flags.ignore_permissions = True
	pi.save()
	return pi


def to_qc(pi):
	from alpinos.purchase import notifications as notif

	notif.submit_for_qc(pi.name)
	return frappe.db.get_value("Purchase Inward", pi.name, "purchase_qc")


def fill_qc(qc_name, rejected=0, reason="Damaged in transit", sample=1, approved=None,
            vehicle=None, material=None, packaging=None, control=None, sample_row=None):
	qc = frappe.get_doc("Purchase QC", qc_name)
	item = qc.items[0].item_code
	for row in qc.items:
		rec = flt(row.received_qty)
		row.approved_qty = (rec - rejected) if approved is None else approved
		row.rejected_qty = rejected
		row.rejection_reason = reason if rejected else None
	qc.set("vehicle_inspection", [])
	qc.append("vehicle_inspection", dict(
		{"vehicle_no": "GJ01AB1234", "vehicle_condition": C.CONDITION_GOOD}, **(vehicle or {})))
	qc.vehicle_inspection_done = 1
	qc.set("material_inspection", [])
	qc.append("material_inspection", dict(
		{"item_code": item, "material_condition": C.CONDITION_GOOD}, **(material or {})))
	qc.material_inspection_done = 1
	qc.set("packaging_inspection", [])
	qc.append("packaging_inspection", dict(
		{"item_code": item, "packaging_condition": C.CONDITION_GOOD}, **(packaging or {})))
	qc.packaging_inspection_done = 1
	qc.set("sample_testing", [])
	if sample:
		qc.append("sample_testing", dict({"item_code": item, "sample_qty": sample}, **(sample_row or {})))
		qc.sample_testing_done = 1
	if control is not None:
		qc.set("control_sample", [])
		qc.append("control_sample", dict({"control_sample_taken": 1, "item_code": item}, **control))
	qc.save(ignore_permissions=True)
	return qc


def chain(itype=C.INWARD_RM, qty=50, rejected=0, sample=1, shelf=0, control=None):
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod

	po = mk_po(qty=qty, itype=itype, shelf=shelf)
	pi = mk_inward(po)
	pi.submit()
	receive(pi, qty, batch=uniq("FGB") if itype == C.INWARD_FG else None)
	qcn = to_qc(pi)
	qc_mod.start_qc(qcn)
	no_sample = itype not in C.BATCH_FROM_INVOICE_TYPES
	fill_qc(qcn, rejected=rejected, sample=0 if no_sample else sample, control=control)
	qc_mod.complete_qc(qcn)
	pr = frappe.db.get_value("Purchase Receipt", {"custom_purchase_inward": pi.name, "docstatus": 0}, "name")
	return po, frappe.get_doc("Purchase Inward", pi.name), qcn, pr


def notif_count():
	total = 0
	for dt in ("Notification Log", "Email Queue", "ToDo"):
		try:
			total += frappe.db.count(dt)
		except Exception:
			pass
	return total


def section_edit(doctype, name, key, user):
	from alpinos.purchase.roles import get_section_access

	frappe.set_user(user)
	try:
		acc = get_section_access(doctype, name) or {}
	finally:
		frappe.set_user("Administrator")
	sections = acc.get("sections", acc) if isinstance(acc, dict) else {}
	node = sections.get(key) if isinstance(sections, dict) else None
	if isinstance(node, dict):
		return node.get("edit")
	return None


TASKS = {
	1: "PO custom fields and form layout",
	2: "GRN custom fields and layout on Purchase Receipt",
	3: "Purchase QC doctype and child tables",
	4: "Roles, permissions and role-gated sections",
	5: "Workflow engine: statuses, transitions, guards, per-role actions",
	6: "Warehouses for rejected / QC sample stock, tolerance settings",
	7: "Naming series for inward, QC and GRN",
	8: "Inward list page: filters, paging, actions by status",
	9: "Entry page header frozen after submit",
	10: "Entry page item grid: rows, fetch filtered by inward type",
	11: "Save / Submit / Cancel / Print and creation validations",
	12: "Purchase Inward print format",
	13: "Receiving section: fields, role gate, expiry from shelf life",
	14: "Previously Received and Pending across receipts",
	15: "Draft Purchase Receipt creation and sync",
	16: "Receipt validations and over-receipt tolerance",
	17: "Photo / video attachments for disputes",
	18: "Submit for QC and QC notification",
	19: "QC list page: filters and actions by status",
	20: "QC entry page with read-only inward header",
	21: "Vehicle inspection section",
	22: "Material inspection section",
	23: "Packaging / box inspection section",
	24: "Sample testing with stock movement to QC warehouse",
	25: "Control sample with retention and storage location",
	26: "QC decision: manual and system-generated result",
	27: "QC validation rules",
	28: "QC inspection report print format",
	29: "Approved / rejected split into the Purchase Receipt",
	30: "GRN list page and filters",
	31: "GRN read-only detail view",
	32: "GRN print format",
	33: "Debit note for rejected quantity",
	34: "Cancellation chain and consumed-stock guard",
	35: "Purchase Invoice creation from the GRN",
	36: "Payment reference capture and closure",
	37: "Invoice / payment queue page",
	38: "Pending receipts, QC pending and GRN register reports",
	39: "Notifications",
	40: "Master data readiness",
	41: "Quarantine: QC holds approved items until released",
	42: "PO creation and approval before inward",
	43: "QC SLA 2-hour timer",
	44: "SLA escalation every 30 minutes",
	45: "Internal Batch Number rules (RM/PM, FG)",
	46: "RMID / PMID and sample sticker",
	47: "Draft GRN editable review by Purchase Team",
	48: "Admin final GRN submission gate",
	49: "Audit log of Draft GRN edits",
}


# ------------------------------------------------------------------- run


def run():
	from alpinos.alpinos_development.doctype.purchase_qc import purchase_qc as qc_mod
	from alpinos.purchase import grn as G
	from alpinos.purchase import inward_api as IA
	from alpinos.purchase import notifications as notif
	from alpinos.purchase import purchase_invoice as INV
	from alpinos.purchase import quarantine as Q

	import alpinos.raven_notifications as RN
	from alpinos.purchase.test_cleanup import purge

	R.clear()
	frappe.set_user("Administrator")
	# The suite commits, so every alert it raises is real: QC hand-over, SLA escalation and
	# quarantine reminders went to every real QC / Store user as bell, Raven DM and email.
	# Every recipient lookup resolves roles through this one function at call time, so
	# narrowing it to the suite's own tft- users keeps real inboxes out of the run.
	real_role_users = RN._role_users
	RN._role_users = lambda role: [
		u for u in (real_role_users(role) or []) if str(u).startswith("tft-")
	]
	H.SEQ = H._seq()
	H.COMPANY = H._company()
	T["supplier"] = H.ensure_supplier()
	T["wh"] = H._warehouse()
	T["purchase"] = _user("tft-purchase@example.com", list(C.PURCHASE_ROLES) + ["Purchase User"])
	T["store"] = _user("tft-store@example.com", [C.ROLE_STORE_USER])
	T["store_mgr"] = _user("tft-storemgr@example.com", [C.ROLE_STORE_USER, C.ROLE_STORE_MANAGER])
	T["qc"] = _user("tft-qc@example.com", [C.ROLE_QC_USER])
	T["qc_mgr"] = _user("tft-qcmgr@example.com", [C.ROLE_QC_USER, C.ROLE_QC_MANAGER])
	T["accounts"] = _user("tft-accounts@example.com", list(C.ACCOUNTS_ROLES))
	T["admin"] = _user("tft-admin@example.com", [C.ROLE_ADMIN])
	settings_before = frappe.db.get_singles_dict("Purchase Inward Settings") or {}
	# notify_qc_on_submit is OFF on this site, which would leave task 39 untested.
	frappe.db.set_single_value("Purchase Inward Settings", "notify_qc_on_submit", 1)
	frappe.db.commit()

	try:
		_run_all(qc_mod, G, IA, notif, INV, Q)
	except Exception as e:
		R.append((0, "ERROR", "suite aborted before the end", f"{type(e).__name__}: {_msg(e)}"))
		frappe.db.rollback()
	finally:
		frappe.set_user("Administrator")
		from alpinos.purchase.settings import _DEFAULTS
		for key in ("block_over_receipt", "over_receipt_tolerance_percent", "notify_qc_on_submit"):
			frappe.db.set_single_value("Purchase Inward Settings", key,
			                           settings_before.get(key, _DEFAULTS.get(key)))
		frappe.db.commit()
		RN._role_users = real_role_users
		# Everything the run committed -- documents, ledgers, TFT- items, tft- users and
		# their alerts -- is removed, so the site's lists show real work only.
		try:
			cleaned = purge(dry_run=False)
			R.append((0, "INFO", "test data removed after the run",
			          f"{cleaned['documents']} errors={cleaned['errors']}"))
		except Exception as e:
			frappe.db.rollback()
			R.append((0, "ERROR", "test data cleanup failed -- run test_cleanup.purge()",
			          f"{type(e).__name__}: {_msg(e)}"))

	return _report()


def _run_all(qc_mod, G, IA, notif, INV, Q):
	P, S, SM, QU, QM, A, AD = (T["purchase"], T["store"], T["store_mgr"], T["qc"], T["qc_mgr"],
	                           T["accounts"], T["admin"])

	# ---------------------------------------------------------------- 1
	pom = frappe.get_meta("Purchase Order")
	for f in ("custom_inward_type", "custom_supplier_order_no", "custom_direct_purchase_invoice",
	          "custom_inward_attachment", "custom_inward_remarks", "custom_vehicle_no",
	          "custom_driver_contact_no", "custom_estimated_arrival", "custom_inward_status",
	          "custom_approval_status"):
		check(1, f"Purchase Order has {f}", bool(pom.get_field(f)), "field missing", "GAP")
	has_inv = bool(pom.get_field("custom_invoice_no") or pom.get_field("custom_invoice_number"))
	has_gw = bool(pom.get_field("custom_gross_weight"))
	info(1, "invoice no / gross weight on the PO",
	     f"invoice field on PO={has_inv}, gross weight on PO={has_gw}; the BRD puts both on the Purchase Inward, where they exist")

	def t_eta_default():
		po = frappe.new_doc("Purchase Order")
		po.supplier = T["supplier"]
		po.company = H.COMPANY
		po.transaction_date = today()
		po.schedule_date = add_days(today(), 5)
		po.set_warehouse = T["wh"]
		po.custom_inward_type = C.INWARD_RM
		po.custom_estimated_arrival = str(add_days(today(), 3))
		po.append("items", {"item_code": H.ensure_item(uniq("TFT-ETA")), "qty": 1, "rate": 1,
		                    "schedule_date": add_days(today(), 5), "warehouse": T["wh"]})
		po.insert(ignore_permissions=True)
		got = get_datetime(po.custom_estimated_arrival)
		assert (got.hour, got.minute) == (9, 0), f"stored {po.custom_estimated_arrival}"
	probe(1, "Estimated Arrival given as a date alone is stored as 9:00 AM", t_eta_default)

	# ---------------------------------------------------------------- 2
	prm = frappe.get_meta("Purchase Receipt")
	for f in ("custom_purchase_inward", "custom_purchase_qc", "custom_grn_status",
	          "custom_receiving_remarks", "custom_debit_note", "custom_grn_change_log"):
		check(2, f"Purchase Receipt has {f}", bool(prm.get_field(f)), "field missing", "GAP")
	veh = [f.fieldname for f in prm.fields if "vehicle" in (f.fieldname or "")]
	att = [f.fieldname for f in prm.fields if "attach" in (f.fieldname or "")]
	check(2, "Purchase Receipt carries a vehicle number field", bool(veh), "no vehicle field on the GRN", "GAP")
	check(2, "Purchase Receipt carries an attachments field", bool(att), "no attachment field on the GRN", "GAP")

	# ---------------------------------------------------------------- 3
	for dt in ("Purchase QC", "Purchase QC Item", "Purchase QC Vehicle Inspection",
	           "Purchase QC Material Inspection", "Purchase QC Packaging Inspection",
	           "Purchase QC Sample", "Purchase QC Control Sample"):
		check(3, f"DocType {dt} exists", bool(frappe.db.exists("DocType", dt)), "missing", "GAP")

	# Shared chain for tasks 4, 5, 9, 11, 13, 16, 17
	po_a = mk_po(qty=100)
	pi_a = mk_inward(po_a)
	frappe.db.commit()

	# ---------------------------------------------------------------- 7
	check(7, "Purchase Inward named PIW-", pi_a.name.startswith("PIW-"), pi_a.name)

	# ---------------------------------------------------------------- 4 (draft)
	check(4, "Purchase team can edit the header of a draft",
	      section_edit("Purchase Inward", pi_a.name, "header", P) is True,
	      f"header edit={section_edit('Purchase Inward', pi_a.name, 'header', P)!r}")
	check(4, "Store cannot edit the header of a draft",
	      section_edit("Purchase Inward", pi_a.name, "header", S) is not True,
	      "store has header edit on a draft")

	def t_store_submits_draft():
		frappe.get_doc("Purchase Inward", pi_a.name).submit()
	probe(5, "Store cannot submit a draft inward (Purchase-only transition)", t_store_submits_draft,
	      expect="", as_user=S)

	# ---------------------------------------------------------------- 11 creation validations
	def t_no_po():
		d = frappe.new_doc("Purchase Inward")
		d.invoice_number = uniq("INV")
		d.invoice_date = today()
		d.inward_datetime = now_datetime()
		d.append("items", {"item_code": po_a.items[0].item_code})
		d.insert()
	probe(11, "VAL-PI-01 inward with no Purchase Order is refused", t_no_po,
	      expect="valid Purchase Order", as_user=P)

	def t_draft_po():
		po = frappe.new_doc("Purchase Order")
		po.supplier = T["supplier"]
		po.company = H.COMPANY
		po.transaction_date = today()
		po.schedule_date = add_days(today(), 5)
		po.set_warehouse = T["wh"]
		po.custom_inward_type = C.INWARD_RM
		po.append("items", {"item_code": po_a.items[0].item_code, "qty": 5, "rate": 1,
		                    "schedule_date": add_days(today(), 5), "warehouse": T["wh"]})
		po.insert(ignore_permissions=True)
		d = frappe.new_doc("Purchase Inward")
		d.purchase_order = po.name
		d.invoice_number = uniq("INV")
		d.invoice_date = today()
		d.inward_datetime = now_datetime()
		d.append("items", {"item_code": po_a.items[0].item_code})
		d.insert(ignore_permissions=True)
	probe(11, "VAL-PI-02 / VAL-PO-15 inward on an unapproved PO is refused", t_draft_po,
	      expect="Approved Purchase Order")

	def t_direct_po():
		po = mk_po(qty=5, direct=1)
		mk_inward(po)
	probe(11, "VAL-PO-13 inward on a Direct Purchase Invoice PO is refused", t_direct_po,
	      expect="Direct Purchase Invoice")

	def t_dup_invoice():
		mk_inward(mk_po(qty=5), invoice=pi_a.invoice_number)
	probe(11, "VAL-PI-15 duplicate invoice number for the same vendor is refused", t_dup_invoice,
	      expect="already exists for this Vendor")

	def t_dup_challan():
		ch = uniq("CH")
		mk_inward(mk_po(qty=5), challan=ch)
		mk_inward(mk_po(qty=5), challan=ch)
	probe(11, "VAL-PI-22 duplicate challan number for the same vendor is refused", t_dup_challan,
	      expect="Challan")

	def t_cancel_draft():
		pi = mk_inward(mk_po(qty=5))
		IA.cancel_draft(pi.name)
	probe(11, "cancel_draft discards a draft inward", t_cancel_draft, as_user=P)

	# ---------------------------------------------------------------- 10
	def t_dup_rows():
		po = mk_po(qty=10)
		d = frappe.new_doc("Purchase Inward")
		d.purchase_order = po.name
		d.invoice_number = uniq("INV")
		d.invoice_date = today()
		d.inward_datetime = now_datetime()
		d.append("items", {"item_code": po.items[0].item_code, "po_detail": po.items[0].name})
		d.append("items", {"item_code": po.items[0].item_code, "po_detail": po.items[0].name})
		d.insert(ignore_permissions=True)
	probe(10, "the same PO line twice on one inward is refused", t_dup_rows, expect="")

	def t_type_filter():
		if not frappe.db.exists("Item Group", "Packaging Material"):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": "Packaging Material",
			                "parent_item_group": "All Item Groups", "is_group": 0}).insert(ignore_permissions=True)
		pm_item = H.ensure_item(uniq("TFT-PMITEM"))
		# Ordered while unclassified, reclassified as PM afterwards: an order typed RM cannot
		# be saved with a PM item on it any more (validate_items_match_po_type), but an item
		# moved to another group after ordering is exactly what the filter still has to catch.
		po = H.make_po(T["supplier"], [(pm_item, 10, 5)], inward_type=C.INWARD_RM)
		frappe.db.set_value("Item", pm_item, "item_group", "Packaging Material")
		off = IA.get_purchase_order_items(po.name, include_unmatched=0)
		on = IA.get_purchase_order_items(po.name, include_unmatched=1)
		assert not off["items"] and off["skipped"]["type_mismatch"] == 1, f"filter off: {off['skipped']}"
		assert len(on["items"]) == 1, "include_unmatched did not offer it"
		# Undo everything this probe created. e2e_test.ensure_item puts new items in ANY
		# leaf Item Group, so a committed "Packaging Material" group silently turned every
		# later test item into PM and emptied every RM order's fetch.
		_rollback()
	probe(10, "a PM item on an RM order is filtered out, and offered on request", t_type_filter)

	# ---------------------------------------------------------------- 12
	def t_print_inward():
		html = frappe.get_print("Purchase Inward", pi_a.name, print_format="Purchase Inward")
		assert pi_a.name in html, "print does not contain the inward number"
	probe(12, "Purchase Inward print format renders", t_print_inward)

	# ---------------------------------------------------------------- submit shared inward
	probe(11, "Purchase team submits the draft inward", lambda: frappe.get_doc("Purchase Inward", pi_a.name).submit(), as_user=P)
	frappe.db.commit()

	# ---------------------------------------------------------------- 9 / 4 after submit
	def t_header_after_submit():
		d = frappe.get_doc("Purchase Inward", pi_a.name)
		d.invoice_number = uniq("CHANGED")
		d.save()
	probe(9, "the header cannot be changed after submit", t_header_after_submit, expect="", as_user=P)
	check(4, "Store can edit the receiving section after submit",
	      section_edit("Purchase Inward", pi_a.name, "receiving", S) is True,
	      f"receiving edit={section_edit('Purchase Inward', pi_a.name, 'receiving', S)!r}")
	check(4, "Purchase team cannot edit the receiving section",
	      section_edit("Purchase Inward", pi_a.name, "receiving", P) is not True,
	      "purchase has receiving edit")

	def t_purchase_receives():
		d = frappe.get_doc("Purchase Inward", pi_a.name)
		d.actual_arrival_datetime = now_datetime()
		for r in d.items:
			r.received_qty = 10
		d.save()
	probe(4, "Purchase team recording received quantity is refused", t_purchase_receives, expect="", as_user=P)
	probe(4, "Accounts cannot write to the inward", t_purchase_receives, expect="", as_user=A)
	probe(4, "QC cannot write to the receiving section", t_purchase_receives, expect="", as_user=QU)

	# ---------------------------------------------------------------- 16 receipt validations
	frappe.db.set_single_value("Purchase Inward Settings", "over_receipt_tolerance_percent", 0)
	frappe.db.set_single_value("Purchase Inward Settings", "block_over_receipt", 1)
	frappe.db.commit()

	def t_over_pending():
		receive(pi_a, 101, as_admin=False)
	probe(16, "VAL-PI-07 receiving above pending without Allow Excess is refused", t_over_pending,
	      expect="cannot be greater than Pending", as_user=S)

	def t_excess_store_user():
		receive(pi_a, 110, excess=1, as_admin=False)
	probe(16, "Store User ticking Allow Excess Quantity", t_excess_store_user, as_user=S,
	      diff="the tick is limited to Store Manager; BRD 2.2.1 gives it to the Store Team")

	def t_excess_manager():
		d = receive(pi_a, 110, excess=1, as_admin=False)
		d.reload()
		assert flt(d.items[0].excess_qty) == 10.0, f"excess_qty={d.items[0].excess_qty}"
	probe(16, "VAL-PI-08 Store Manager with Allow Excess: excess quantity calculated", t_excess_manager, as_user=SM)

	def t_no_location():
		receive(pi_a, 50, wh=None)
		notif.submit_for_qc(pi_a.name)
	probe(16, "VAL-PI-09 Submit for QC without Target Location is refused", t_no_location, expect="Target Location")

	def t_no_arrival():
		receive(pi_a, 50, arrival=False)
		d = frappe.get_doc("Purchase Inward", pi_a.name)
		d.actual_arrival_datetime = None
		d.flags.ignore_permissions = True
		d.save()
		notif.submit_for_qc(pi_a.name)
	probe(16, "VAL-PI-12 Submit for QC without Actual Arrival is refused", t_no_arrival, expect="Arrival")

	def t_no_received():
		receive(pi_a, 0)
		notif.submit_for_qc(pi_a.name)
	probe(16, "VAL-PI-10 Submit for QC with no received quantity is refused", t_no_received, expect="Received Quantity")

	def t_verified_no_details():
		d = frappe.get_doc("Purchase Inward", pi_a.name)
		d.vehicle_details_verified = 1
		d.actual_vehicle_no = None
		d.actual_driver_contact_no = None
		d.actual_arrival_datetime = now_datetime()
		for r in d.items:
			r.received_qty = 50
			r.target_warehouse = T["wh"]
		d.flags.ignore_permissions = True
		d.save()
		notif.submit_for_qc(pi_a.name)
	probe(16, "VAL-PI-05 Verified ticked without corrected details is refused", t_verified_no_details,
	      expect="correct vehicle and driver details")

	def t_tolerance():
		frappe.db.set_single_value("Purchase Inward Settings", "block_over_receipt", 1)
		frappe.db.set_single_value("Purchase Inward Settings", "over_receipt_tolerance_percent", 10)
		po = mk_po(qty=100)
		pi = mk_inward(po)
		pi.submit()
		receive(pi, 105)
		try:
			receive(pi, 111)
		except frappe.ValidationError:
			return
		raise AssertionError("111 of 100 was accepted with a 10% tolerance")
	probe(16, "10% tolerance: 105 of 100 accepted, 111 refused", t_tolerance)

	# ---------------------------------------------------------------- 13
	def t_expiry():
		po = mk_po(qty=20, shelf=30)
		pi = mk_inward(po)
		pi.submit()
		d = receive(pi, 20, mfg=today())
		d.reload()
		exp = d.items[0].expiry_date
		assert exp and getdate(exp) == getdate(add_days(today(), 30)), f"expiry={exp}"
	probe(13, "Expiry = Mfg Date + item shelf life (30 days)", t_expiry)

	def t_fg_batch():
		po = mk_po(qty=10, itype=C.INWARD_FG)
		pi = mk_inward(po)
		pi.submit()
		receive(pi, 10)
	probe(13, "FG receipt without Batch No. is refused", t_fg_batch, expect="Batch")

	# ---------------------------------------------------------------- 17
	def t_dispute():
		d = frappe.get_doc("Purchase Inward", pi_a.name)
		d.append("dispute_attachments", {"file": "/files/tft-damage.jpg", "kind": "Photo",
		                                 "description": "Crushed carton"})
		d.save()
		d.reload()
		row = d.dispute_attachments[-1]
		assert row.uploaded_by, "uploaded_by not stamped"
	probe(17, "Store attaches a dispute photo; uploader is stamped", t_dispute, as_user=S)

	# ---------------------------------------------------------------- 14
	def t_multi_receipts():
		po = mk_po(qty=100)
		a = mk_inward(po)
		a.submit()
		receive(a, 40)
		b_items = IA.get_purchase_order_items(po.name)["items"]
		assert b_items and flt(b_items[0]["previously_received_qty"]) == 40 and flt(b_items[0]["pending_qty"]) == 60, \
			f"second inward sees {b_items}"
		b = mk_inward(po)
		b.submit()
		receive(b, 60)
		left = IA.get_purchase_order_items(po.name)
		assert not left["items"] and left["skipped"]["fully_received"] == 1, f"third fetch {left}"
	probe(14, "40 then 60 of 100: second inward sees 40 / 60, third sees nothing pending", t_multi_receipts)

	# ---------------------------------------------------------------- 18 / 5 / 43
	pi_q = mk_inward(mk_po(qty=30))
	pi_q.submit()
	receive(pi_q, 30)
	frappe.db.commit()
	probe(5, "Purchase team cannot run Submit for QC", lambda: IA.run_action(pi_q.name, "submit_for_qc"), expect="", as_user=P)
	probe(5, "Run an action that does not belong to the status (complete_qc now)",
	      lambda: IA.run_action(pi_q.name, "complete_qc"), expect="")
	before = notif_count()
	qc_q = probe(18, "Store runs Submit for QC", lambda: IA.run_action(pi_q.name, "submit_for_qc"), as_user=S)
	frappe.db.commit()
	qc_name = frappe.db.get_value("Purchase Inward", pi_q.name, "purchase_qc")
	check(18, "a Purchase QC was raised", bool(qc_name), "no QC")
	from alpinos.purchase.settings import get_settings
	notify_on = get_settings().get("notify_qc_on_submit")
	delta = notif_count() - before
	if notify_on:
		check(39, "QC team notified on hand-over (notification / email / ToDo created)", delta > 0,
		      "notify_qc_on_submit is on, but nothing was created", "GAP")
	else:
		info(39, "QC notification on hand-over", "notify_qc_on_submit is OFF in Purchase Inward Settings, so no notification is sent")

	if qc_name:
		qd = frappe.get_doc("Purchase QC", qc_name)
		check(7, "Purchase QC named PQC-", qc_name.startswith("PQC-"), qc_name)
		if qd.sla_start and qd.sla_due:
			hours = (get_datetime(qd.sla_due) - get_datetime(qd.sla_start)).total_seconds() / 3600.0
			check(43, "SLA due = start + 2 hours", abs(hours - 2.0) < 0.01, f"{hours:.2f} hours")
		else:
			check(43, "SLA start and due stamped", False, f"start={qd.sla_start} due={qd.sla_due}", "GAP")

		# ------------------------------------------------------------ 20 / 5
		probe(5, "Store cannot start QC", lambda: qc_mod.start_qc(qc_name), expect="", as_user=S)

		def t_qc_header_readonly():
			q = frappe.get_doc("Purchase QC", qc_name)
			orig = q.supplier_order_no
			q.supplier_order_no = "EDITED-BY-QC"
			q.save()
			q.reload()
			assert q.supplier_order_no == orig, f"inward header on QC was changed to {q.supplier_order_no}"
		probe(20, "QC user cannot change the read-only inward header on the QC", t_qc_header_readonly, as_user=QU)

		# ------------------------------------------------------------ 19
		from alpinos.purchase import qc_list_api as QL
		probe(19, "QC list: filter by Purchase Inward", lambda: _assert_in(QL.get_purchase_qc_list(purchase_inward=pi_q.name), qc_name), as_user=QU)
		for kw in ({"qc_status": C.QC_PENDING}, {"inward_type": C.INWARD_RM}, {"supplier": T["supplier"]},
		           {"inspector": QU}, {"qc_result": C.QC_RESULT_PENDING}, {"from_date": today(), "to_date": today()},
		           {"sla_state": "breached"}):
			probe(19, f"QC list filter {list(kw)[0]}", lambda kw=kw: QL.get_purchase_qc_list(**kw), as_user=QU)
		probe(19, "QC list: Start QC as the QC team", lambda: qc_mod.start_qc(qc_name), as_user=QU)
		frappe.db.commit()

		# ------------------------------------------------------------ 21 / 22 / 23 / 27
		def _complete_with(**kw):
			fill_qc(qc_name, **kw)
			qc_mod.complete_qc(qc_name)

		probe(21, "VAL-QC-03 vehicle damage without reason is refused",
		      lambda: _complete_with(vehicle={"vehicle_condition": C.CONDITION_DAMAGED, "vehicle_damage": 1}),
		      expect="Vehicle Damage Reason", as_user=QU)
		probe(22, "material damage without damaged quantity is refused",
		      lambda: _complete_with(material={"material_condition": C.CONDITION_DAMAGED, "material_damage": 1}),
		      expect="Damaged Quantity", as_user=QU)
		probe(22, "damaged quantity without damage reason is refused",
		      lambda: _complete_with(material={"material_condition": C.CONDITION_DAMAGED, "material_damage": 1, "damaged_qty": 2}),
		      expect="Damage Reason", as_user=QU)
		probe(23, "packaging damage without reason is refused",
		      lambda: _complete_with(packaging={"packaging_condition": C.CONDITION_DAMAGED, "packaging_damage": 1, "damaged_qty": 1}),
		      expect="Damage Reason", as_user=QU)
		probe(27, "VAL-QC-06 approved above received is refused",
		      lambda: _complete_with(approved=31), expect="Approved Quantity cannot exceed", as_user=QU)
		probe(27, "VAL-QC-08 approved + rejected not equal to received is refused",
		      lambda: _complete_with(approved=10, rejected=5), expect="", as_user=QU)
		probe(27, "VAL-QC-04 rejected quantity without reason is refused",
		      lambda: _complete_with(rejected=5, reason=None), expect="Rejection Reason", as_user=QU)
		probe(27, "VAL-QC-09 sample quantity above received is refused",
		      lambda: _complete_with(sample=31), expect="Sample Quantity", as_user=QU)
		probe(25, "control sample ticked without quantity is refused",
		      lambda: _complete_with(control={"batch_no": "X"}), expect="Control Sample Quantity", as_user=QU)
		def t_uninspected():
			q = frappe.get_doc("Purchase QC", qc_name)
			for row in q.items:
				row.approved_qty = flt(row.received_qty)
				row.rejected_qty = 0
			for tbl, flag in (("vehicle_inspection", "vehicle_inspection_done"),
			                  ("material_inspection", "material_inspection_done"),
			                  ("packaging_inspection", "packaging_inspection_done"),
			                  ("sample_testing", "sample_testing_done")):
				q.set(tbl, [])
				q.set(flag, 0)
			q.save(ignore_permissions=True)
			qc_mod.complete_qc(qc_name)
		probe(27, "Complete QC with quantities filled but no inspections lists what is pending",
		      t_uninspected, expect="mandatory QC inspections", as_user=QU)

	# ---------------------------------------------------------------- 26
	from alpinos.alpinos_development.doctype.purchase_qc.purchase_qc import qc_result_for
	for rec, app, rej, want in ((10, 10, 0, C.QC_RESULT_APPROVED), (10, 6, 4, C.QC_RESULT_PARTIAL),
	                            (10, 0, 10, C.QC_RESULT_REJECTED)):
		got = qc_result_for(rec, app, rej)
		check(26, f"received {rec}, approved {app}, rejected {rej} -> {want}", got == want, f"got {got}")

	# ---------------------------------------------------------------- full RM chain with a rejection
	chain_rm = probe(29, "RM chain with a 5-unit rejection reaches a Draft GRN",
	                 lambda: chain(C.INWARD_RM, qty=50, rejected=5, sample=2))
	frappe.db.commit()
	if chain_rm:
		po_r, pi_r, qc_r, pr_r = chain_rm
		check(15, "Draft Purchase Receipt created after QC", bool(pr_r), "no draft GRN")
		if pr_r:
			pr_doc = frappe.get_doc("Purchase Receipt", pr_r)
			check(7, "GRN named GRN-", pr_r.startswith("GRN-"), pr_r)
			check(29, "Draft GRN holds approved 45 and rejected 5",
			      flt(pr_doc.items[0].qty) == 45 and flt(pr_doc.items[0].rejected_qty) == 5,
			      f"qty={pr_doc.items[0].qty} rejected={pr_doc.items[0].rejected_qty}")
			probe(15, "sync_from_inward re-pulls the Draft GRN", lambda: G.sync_from_inward(pr_r), as_user=P)

			# 45 / 46 before submit
			qcd = frappe.get_doc("Purchase QC", qc_r)
			srow = qcd.sample_testing[0] if qcd.sample_testing else None
			info(45, "RM internal batch number", f"{srow.internal_batch_no if srow else None!r} (inward invoice {pi_r.invoice_number}, date {getdate(pi_r.inward_datetime)})")
			check(45, "RM sample row carries an internal batch number", bool(srow and srow.internal_batch_no), "blank", "GAP")
			check(46, "RM sample row has an RMID", bool(srow and (srow.sample_id or "").upper().startswith("RMID")),
			      f"sample_id={srow.sample_id if srow else None!r}", "GAP")
			probe(28, "QC Inspection Report print renders",
			      lambda: _assert_contains(frappe.get_print("Purchase QC", qc_r, print_format="QC Inspection Report"), qc_r))
			probe(46, "QC Sample Sticker print renders",
			      lambda: frappe.get_print("Purchase QC", qc_r, print_format="QC Sample Sticker"))

			# 47 / 49 Draft GRN review by Purchase
			log_before = len(pr_doc.get("custom_grn_change_log") or [])

			def t_purchase_edits_remarks():
				g = frappe.get_doc("Purchase Receipt", pr_r)
				g.custom_receiving_remarks = "Reviewed by purchase"
				g.save()
			probe(47, "Purchase team edits a permitted field on the Draft GRN", t_purchase_edits_remarks, as_user=P)
			frappe.db.commit()
			log_after = len(frappe.get_doc("Purchase Receipt", pr_r).get("custom_grn_change_log") or [])
			check(49, "the edit was captured in the GRN change log", log_after > log_before,
			      f"change log rows before={log_before} after={log_after}", "GAP")

			def t_purchase_edits_qty():
				g = frappe.get_doc("Purchase Receipt", pr_r)
				g.items[0].qty = flt(g.items[0].qty) + 5
				g.save()
			probe(47, "Purchase team changing the QC-approved quantity on the Draft GRN is refused",
			      t_purchase_edits_qty, expect="", as_user=P)

			# 35 / 48 before final submit
			probe(48, "invoice before the GRN is finally submitted is refused",
			      lambda: INV.create_from_grn(pr_r), expect="finally submitted", as_user=P)
			probe(48, "Purchase team cannot final-submit the GRN",
			      lambda: frappe.get_doc("Purchase Receipt", pr_r).submit(), expect="submit a GRN", as_user=P)
			probe(30, "GRN list filter by Purchase Inward", lambda: _assert_in(_grn_list(purchase_inward=pi_r.name), pr_r), as_user=P)
			for kw in ({"grn_status": "Draft"}, {"supplier": T["supplier"]}, {"has_rejection": 1},
			           {"from_date": today(), "to_date": today()}):
				probe(30, f"GRN list filter {list(kw)[0]}", lambda kw=kw: _grn_list(**kw), as_user=P)

			ok = probe(48, "Admin final-submits the GRN", lambda: frappe.get_doc("Purchase Receipt", pr_r).submit(), as_user=AD)
			frappe.db.commit()
			if ok is not None or frappe.db.get_value("Purchase Receipt", pr_r, "docstatus") == 1:
				g = frappe.get_doc("Purchase Receipt", pr_r)
				rej_wh = g.items[0].rejected_warehouse
				check(29, "rejected quantity routed to the Rejected warehouse",
				      bool(rej_wh) and "reject" in (rej_wh or "").lower(), f"rejected_warehouse={rej_wh!r}")
				sle_rej = frappe.db.sql("""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry`
				    WHERE voucher_no=%s AND warehouse=%s AND is_cancelled=0""", (pr_r, rej_wh))[0][0] if rej_wh else 0
				check(29, "5 units posted into the Rejected warehouse", flt(sle_rej) == 5.0, f"posted {sle_rej}")
				check(33, "debit note raised for the rejected quantity", bool(g.custom_debit_note),
				      "custom_debit_note blank", "GAP")
				qcd.reload()
				srow = qcd.sample_testing[0] if qcd.sample_testing else None
				# Samples are recorded on the QC and move no stock: the whole approved
				# quantity stays in the warehouse (decided 2026-09-16).
				check(24, "sample recorded without a stock movement", bool(srow) and not srow.stock_entry,
				      f"stock_entry={srow.stock_entry if srow else None!r}")
				acc_wh = g.items[0].warehouse
				acc_in = frappe.db.sql("""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry`
				    WHERE voucher_no=%s AND warehouse=%s AND is_cancelled=0""", (pr_r, acc_wh))[0][0]
				check(24, "the whole approved quantity is received into the warehouse",
				      flt(acc_in) == flt(g.items[0].qty), f"received {acc_in} of approved {g.items[0].qty}")
				probe(32, "GRN print renders", lambda: _assert_contains(frappe.get_print("Purchase Receipt", pr_r, print_format="GRN"), pr_r))
				probe(31, "GRN detail loads through frappe.client.get", lambda: frappe.client.get("Purchase Receipt", pr_r), as_user=P)

				# 35 / 36
				inv = probe(35, "Purchase team creates the invoice from the GRN",
				            lambda: INV.create_from_grn(pr_r), as_user=P)
				frappe.db.commit()
				if inv:
					def t_submit_invoice():
						d = frappe.get_doc("Purchase Invoice", inv.name)
						d.bill_no = uniq("SUPP")
						d.bill_date = today()
						d.custom_payment_due_date = add_days(today(), 30)
						d.custom_invoice_attachment = "/files/tft-invoice.pdf"
						d.save()
						d.submit()
					probe(35, "Purchase team fills and submits the invoice", t_submit_invoice, as_user=P)
					frappe.db.commit()
					billed = flt(frappe.db.get_value("Purchase Invoice", inv.name, "rounded_total")
					             or frappe.db.get_value("Purchase Invoice", inv.name, "grand_total"))
					probe(36, "Accounts records a UPI payment without a reference: refused",
					      lambda: INV.add_payment(inv.name, C.UNF_PAYMENT_SUPPLIER, 10, today(), "UPI"),
					      expect="Reference", as_user=A)
					probe(36, "Accounts records the full payment",
					      lambda: INV.add_payment(inv.name, C.UNF_PAYMENT_SUPPLIER, billed, today(), "NEFT", reference_number="UTR-TFT"),
					      as_user=A)
					frappe.db.commit()
					check(36, "invoice closes as Paid",
					      frappe.db.get_value("Purchase Invoice", inv.name, "custom_unified_status") == C.UNF_PAID,
					      str(frappe.db.get_value("Purchase Invoice", inv.name, "custom_unified_status")))


	# ---------------------------------------------------------------- 33 no rejection -> no debit note
	def t_no_debit_note():
		_po, _pi, _qc, pr = chain(C.INWARD_RM, qty=20, rejected=0, sample=1)
		frappe.get_doc("Purchase Receipt", pr).submit()
		assert not frappe.db.get_value("Purchase Receipt", pr, "custom_debit_note"), "debit note raised with no rejection"
	probe(33, "VAL-GRN-09 no rejection means no debit note", t_no_debit_note)

	# ---------------------------------------------------------------- 34 consumed-stock guard
	def t_consumed():
		_po, _pi, _qc, pr = chain(C.INWARD_RM, qty=40, rejected=0, sample=1)
		g = frappe.get_doc("Purchase Receipt", pr)
		g.submit()
		g.reload()
		line = g.items[0]
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Issue"
		se.company = H.COMPANY
		se.set_posting_time = 1
		se.posting_date = today()
		se.posting_time = "23:59:00"
		se.append("items", {"item_code": line.item_code, "qty": 1,
		                    "s_warehouse": line.warehouse, "uom": line.uom, "conversion_factor": 1,
		                    "batch_no": line.batch_no, "use_serial_batch_fields": 1})
		se.insert(ignore_permissions=True)
		se.submit()
		frappe.get_doc("Purchase Receipt", pr).cancel()
	probe(34, "VAL-GRN-11 cancelling a GRN whose stock was consumed is refused", t_consumed,
	      expect="consumed")

	# ---------------------------------------------------------------- 34 cancel order
	def t_cancel_inward_with_qc():
		_po, pi, _qc, _pr = chain(C.INWARD_RM, qty=10, rejected=0, sample=1)
		frappe.get_doc("Purchase Inward", pi.name).cancel()
	probe(34, "cancelling an inward that has a QC and Draft GRN is refused", t_cancel_inward_with_qc, expect="")

	def t_cancel_qc_with_grn():
		_po, _pi, qc, _pr = chain(C.INWARD_RM, qty=10, rejected=0, sample=1)
		frappe.get_doc("Purchase QC", qc).cancel()
	probe(34, "cancelling a QC while its GRN exists is refused", t_cancel_qc_with_grn, expect="Cancel GRN")

	# ---------------------------------------------------------------- 45 FG batch
	def t_fg_chain():
		_po, pi, qc, pr = chain(C.INWARD_FG, qty=10, rejected=0, sample=0)
		return pi, qc, pr
	fg = probe(45, "FG chain (with batch and mfg date) reaches a Draft GRN", t_fg_chain)
	if fg:
		pi_f, qc_f, pr_f = fg
		q = frappe.get_doc("Purchase QC", qc_f)
		line = q.items[0]
		ib = line.get("internal_batch_no") or (frappe.db.get_value("Purchase Receipt Item", {"parent": pr_f}, "batch_no") if pr_f else None)
		info(45, "FG internal batch number", f"{ib!r} (receiving batch {pi_f.items[0].batch_no}, mfg {pi_f.items[0].manufacturing_date})")
		check(45, "FG internal batch uses the batch number", bool(ib) and (pi_f.items[0].batch_no or "~") in (ib or ""),
		      f"internal batch {ib!r} does not include {pi_f.items[0].batch_no!r}", "FAIL")

	def t_pm_pmid():
		_po, _pi, qc, _pr = chain(C.INWARD_PM, qty=10, rejected=0, sample=1)
		row = frappe.get_doc("Purchase QC", qc).sample_testing[0]
		assert (row.sample_id or "").upper().startswith("PMID"), f"sample_id={row.sample_id!r}"
	probe(46, "PM sample row gets a PMID", t_pm_pmid)

	# ---------------------------------------------------------------- 25 control sample recorded
	ctrl_wh = frappe.db.get_single_value("Purchase Inward Settings", "control_sample_warehouse")

	def t_control_sample(storage):
		_po, _pi, qc, pr = chain(C.INWARD_RM, qty=20, rejected=0, sample=1,
		                         control={"control_sample_qty": 1, "batch_no": uniq("CTRL"),
		                                  "storage_location": storage})
		frappe.get_doc("Purchase Receipt", pr).submit()
		row = frappe.get_doc("Purchase QC", qc).control_sample[0]
		# Recorded with its storage location and retention; no stock leaves the warehouse.
		assert not row.stock_entry, f"control sample moved stock: {row.stock_entry}"
		assert row.storage_location == storage, f"storage location {row.storage_location!r}"
		wh = frappe.db.get_value("Purchase Receipt Item", {"parent": pr}, "warehouse")
		assert flt(frappe.db.sql("""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry`
		    WHERE item_code=%s AND warehouse=%s AND is_cancelled=0""", (row.item_code, wh))[0][0]) == 20, \
			"the approved 20 are not all in the warehouse"
	probe(25, "control sample is recorded without moving stock; all 20 approved stay in the warehouse",
	      lambda: t_control_sample(ctrl_wh))

	# ---------------------------------------------------------------- 41 quarantine (decided at QC)
	from alpinos.purchase import grn_edit as GE

	def _quar_qc():
		pi = mk_inward(mk_po(qty=20, lines=2))
		pi.submit()
		receive(pi, 20)
		qcn = to_qc(pi)
		qc_mod.start_qc(qcn)
		# 15 approved / 5 rejected on both lines; the one sample is drawn from line 1.
		fill_qc(qcn, rejected=5, sample=1)
		return pi.name, qcn

	q_pi, q_qc = _quar_qc()
	frappe.db.commit()
	check(41, "the inward no longer offers a quarantine of its own (QC decides it)",
	      "create_quarantine" not in [a["action"] for a in IA.get_form_context(q_pi)["actions"]], "Create Quarantine still offered")

	def _mark_qc(name, rows=None, all_items=0, reason="Suspected contamination"):
		d = frappe.get_doc("Purchase QC", name)
		d.quarantine_items = 1
		d.quarantine_all_items = all_items
		d.quarantine_reminder_days = 2
		d.quarantine_reason = reason
		for line in d.items:
			line.quarantine = 1 if (rows and line.idx in rows) else 0
		d.save()

	probe(41, "QC quarantines one of two items", lambda: _mark_qc(q_qc, rows=[2]), as_user=QM)
	probe(41, "QC completes the inspection with the item quarantined", lambda: qc_mod.complete_qc(q_qc), as_user=QM)
	qdoc = frappe.db.get_value("Purchase QC", q_qc, "quarantine_document")
	grn = frappe.db.get_value("Purchase QC", q_qc, "purchase_receipt")
	store = Q.warehouse_name(frappe.db.get_value("Purchase QC", q_qc, "company"))
	held = frappe.get_all("Purchase Quarantine Item", filters={"parent": qdoc}, fields=["name", "qty", "target_warehouse"]) if qdoc else []
	check(41, "the Quarantine document holds the quarantined item's approved quantity",
	      [flt(r.qty) for r in held] == [15.0], f"qrn={qdoc} rows={held}")
	if qdoc and grn:
		lines = frappe.get_all("Purchase Receipt Item", filters={"parent": grn},
		                       fields=["idx", "warehouse", "custom_quarantine_status"], order_by="idx")
		check(41, "the GRN receives the quarantined item into the Quarantine warehouse, the other into its own",
		      len(lines) == 2 and lines[1].warehouse == store and lines[1].custom_quarantine_status == "Quarantined"
		      and lines[0].warehouse != store, str(lines))
		probe(41, "Admin submits the GRN", lambda: GE.submit_grn(grn), as_user=AD)
		probe(41, "Store releases the quarantined item", lambda: Q.release_items(qdoc, [held[0].name], "Cleared"), as_user=SM)
		entry = frappe.db.get_value("Purchase Quarantine Item", held[0].name, "release_stock_entry")
		moved = frappe.db.get_value("Stock Entry Detail", {"parent": entry}, ["s_warehouse", "t_warehouse", "qty"], as_dict=True) if entry else None
		check(41, "release moves the stock from the Quarantine warehouse into its warehouse",
		      bool(moved) and moved.s_warehouse == store and moved.t_warehouse == held[0].target_warehouse and flt(moved.qty) == 15,
		      f"entry={entry} moved={moved}")
	check(41, "Quarantine Stock view exists", bool(frappe.db.exists("Page", "purchase_quarantine_list")), "page missing", "GAP")

	# ---------------------------------------------------------------- 42
	def t_reject_no_remarks():
		from alpinos.purchase import purchase_order_approval as POA
		po = frappe.new_doc("Purchase Order")
		po.supplier = T["supplier"]
		po.company = H.COMPANY
		po.transaction_date = today()
		po.schedule_date = add_days(today(), 5)
		po.set_warehouse = T["wh"]
		po.custom_inward_type = C.INWARD_RM
		po.append("items", {"item_code": H.ensure_item(uniq("TFT-REJ")), "qty": 1, "rate": 1,
		                    "schedule_date": add_days(today(), 5), "warehouse": T["wh"]})
		po.insert(ignore_permissions=True)
		POA.perform_action(po.name, "Submit for Approval")
		frappe.set_user(T["qc_mgr"])  # not an approver
		frappe.set_user("Administrator")
		POA.perform_action(po.name, "Reject")
	probe(42, "VAL-PO-09 rejecting a PO without remarks is refused", t_reject_no_remarks, expect="Rejection Remarks")

	# ---------------------------------------------------------------- 44 escalation
	def t_escalation():
		pi = mk_inward(mk_po(qty=5))
		pi.submit()
		receive(pi, 5)
		qcn = to_qc(pi)
		frappe.db.set_value("Purchase QC", qcn, {"sla_due": add_to_date(now_datetime(), hours=-1),
		                                         "sla_breached": 0, "last_escalation_on": None})
		frappe.db.commit()
		c0 = notif_count()
		notif.run_qc_sla_escalation()
		frappe.db.commit()
		q = frappe.get_doc("Purchase QC", qcn)
		c1 = notif_count()
		assert cint_(q.sla_breached) == 1, "sla_breached not set after the SLA passed"
		assert q.last_escalation_on, "last_escalation_on not stamped"
		notif.run_qc_sla_escalation()
		frappe.db.commit()
		c2 = notif_count()
		assert c2 == c1, f"escalated again inside the interval ({c1} -> {c2})"
		frappe.db.set_value("Purchase QC", qcn, "last_escalation_on", add_to_date(now_datetime(), minutes=-31))
		frappe.db.commit()
		notif.run_qc_sla_escalation()
		frappe.db.commit()
		c3 = notif_count()
		return (c1 - c0, c3 - c2)
	esc = probe(44, "SLA breach escalates, stays quiet inside 30 min, escalates again after 30", t_escalation)
	if esc:
		first, again = esc
		check(44, "an escalation was actually sent on breach", first > 0, "nothing created on first escalation", "GAP")
		check(44, "a repeat escalation was sent after 30 minutes", again > 0, "nothing created after 31 minutes", "GAP")
	interval = frappe.db.get_single_value("Purchase Inward Settings", "qc_escalation_interval_minutes") or C.QC_ESCALATION_INTERVAL_MINUTES
	check(44, "escalation interval is 30 minutes", int(interval) == 30, f"interval={interval}")

	# ---------------------------------------------------------------- 6
	for key in ("qc_hold_warehouse", "qc_sample_warehouse", "rejected_warehouse",
	            "quarantine_warehouse", "control_sample_warehouse"):
		val = frappe.db.get_single_value("Purchase Inward Settings", key)
		check(6, f"{key} configured and exists", bool(val) and bool(frappe.db.exists("Warehouse", val)), f"value={val!r}")
	hold = frappe.db.get_single_value("Purchase Inward Settings", "qc_hold_warehouse")
	posted = frappe.db.sql("SELECT COUNT(*) FROM `tabStock Ledger Entry` WHERE warehouse=%s", hold)[0][0] if hold else 0
	check(6, "received stock is ever posted into QC Hold (BRD 2.7)", posted > 0,
	      f"{posted} stock ledger entries in {hold!r}", "GAP")

	# ---------------------------------------------------------------- 8
	from alpinos.purchase import inward_list_api as IL
	probe(8, "Inward list filter by PO number", lambda: _assert_in(IL.get_purchase_inward_list(purchase_order=po_a.name), pi_a.name), as_user=P)
	for kw in ({"inward_type": C.INWARD_RM}, {"supplier": T["supplier"]}, {"from_date": today(), "to_date": today()},
	           {"vehicle_no": "GJ"}, {"qc_status": C.QC_PENDING}, {"inward_status": C.PI_PENDING_RECEIPT},
	           {"created_by": "Administrator"}, {"supplier_order_no": "SO"}, {"search": "PIW"}):
		probe(8, f"Inward list filter {list(kw)[0]}", lambda kw=kw: IL.get_purchase_inward_list(**kw), as_user=P)

	def t_paging():
		a = IL.get_purchase_inward_list(start=0, page_length=5)
		b = IL.get_purchase_inward_list(start=5, page_length=5)
		na = [r["name"] for r in a["data"]]
		nb = [r["name"] for r in b["data"]]
		assert len(na) <= 5 and not (set(na) & set(nb)), "pages overlap"
	probe(8, "Inward list paging returns distinct pages", t_paging, as_user=P)
	for field in ("name", "posting_date", "supplier", "inward_status"):
		probe(8, f"Inward list sort by {field}", lambda f=field: IL.get_purchase_inward_list(sort_field=f, sort_dir="asc"), as_user=P)

	# ---------------------------------------------------------------- 37 / 38 / 40
	check(37, "Invoice / payment queue page exists", bool(frappe.db.exists("Page", "purchase_invoice_list")),
	      "no page", "GAP")
	for rep in ("Purchase Pending Receipts", "Purchase QC Pending", "Purchase GRN Register"):
		probe(38, f"report '{rep}' runs for the purchase team", lambda r=rep: _run_report(r), as_user=P)
	probe(40, "report 'Purchase Master Data Readiness' runs", lambda: _run_report("Purchase Master Data Readiness"), as_user=P)

	frappe.db.commit()


# ----------------------------------------------------------------- small helpers


def cint_(v):
	try:
		return int(v or 0)
	except Exception:
		return 0


def _assert_in(payload, name):
	rows = payload.get("data") or payload.get("rows") or [] if isinstance(payload, dict) else payload
	names = [r.get("name") for r in rows]
	assert name in names, f"{name} not in the {len(names)} rows returned"
	return payload


def _assert_contains(html, text):
	assert text in (html or ""), "document number missing from the print"
	return True


def _grn_list(**kw):
	from alpinos.purchase import grn_list_api as GL
	return GL.get_grn_list(**kw)


def _run_report(name):
	from frappe.desk.query_report import run as run_report
	return run_report(name, filters={}, ignore_prepared_report=True)


def _report():
	order = {"ERROR": 0, "FAIL": 1, "GAP": 2, "DIFF": 3, "INFO": 4, "PASS": 5}
	counts = {}
	for task, state, _l, _d in R:
		counts[state] = counts.get(state, 0) + 1
	print("\nTask-sheet functional test")
	print("=" * 110)
	for task in sorted({t for t, *_ in R}):
		rows = sorted((r for r in R if r[0] == task), key=lambda r: order.get(r[1], 9))
		states = {r[1] for r in rows}
		head = "OK" if states <= {"PASS", "INFO"} else "/".join(s for s in ("ERROR", "FAIL", "GAP", "DIFF") if s in states)
		print(f"\n{task:>2}. {TASKS.get(task, 'suite')}  [{head}]")
		for _t, state, label, detail in rows:
			print(f"     [{state:5}] {label}" + (f"\n             -> {detail}" if detail else ""))
	print("\n" + "-" * 110)
	print("  ".join(f"{k}={counts.get(k, 0)}" for k in ("PASS", "ERROR", "FAIL", "GAP", "DIFF", "INFO")))
	return R
