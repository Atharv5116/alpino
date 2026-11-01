"""The real production chain in the second company (Alpino Hospitality, series code APC).

	bench --site <test site> execute alpinos.company_scope.production_flow_test.run

Own masters tagged to APC (items, BOMs, a machine type, an oven, a filling line, two
processes), a Production Settings "Warehouses by Company" row for APC and RM / PM stock in
Stores - APC are set up as Administrator. Then every step runs as a user through the
methods the pages call:

	Production Order (planner) -> approval (approver of APC; the default company's approver
	is refused) -> Send To Store -> Store Planning -> Material Request -> Material Issue ->
	Shop Floor start / complete -> Process Inward (stock posted) -> Production QC ->
	Filling Plan -> Filling Inward (FG batch in QC Hold) -> Final QC

At each step: the document is APC's (APC numbering where the series has it), stock and
ledger rows land in APC, notifications reach APC's people only, and a user of the default
company cannot list, open or act on it. Everything created is removed at the end.
"""

import frappe
from frappe.utils import add_days, cint, flt, nowdate

from alpinos.company_scope import ALL
from alpinos.company_scope.testing import (
	as_user,
	cleanup_user,
	companies,
	ensure_enabled,
	make_user,
	set_active,
)

R = []
APC = "Alpino Hospitality Pvt. Ltd."
P = "CS-FLOW-PROD"

U_APC = "cs.flow.prod.apc@example.com"     # every production role, only in APC
U_PLN = "cs.flow.prod.planner@example.com"  # Production User (planner) only in APC
U_DEF = "cs.flow.prod.def@example.com"     # every production role, only in the default company
U_ALL = "cs.flow.prod.all@example.com"     # every production role in both (default company first)
ROLES = ["Production Manager", "Production User", "Production Operator", "Store Manager", "Store Planner",
	"Store User", "Store Receiving User", "Plant Head", "QC Inspector", "QC Manager", "Stock User"]

RM, PM, BULK, SKU = f"{P}-RM", f"{P}-PM", f"{P}-BULK", f"{P}-SKU"
ITEMS = (RM, PM, BULK, SKU)
WH = {"main_warehouse": "Stores - APC", "wip_warehouse": "Work In Progress - APC",
      "fg_warehouse": "Finished Goods - APC", "fg_hold_warehouse": "QC Hold - APC",
      "rejected_warehouse": "Rejected - APC"}
S = frappe._dict()  # what the run created


class _Stop(Exception):
	pass


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)[:300]))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"[:300]))


def step(label, fn):
	"""A step of the chain: the rest of the chain needs it, so a failure stops the run."""
	try:
		out = fn()
	except Exception as e:
		R.append(("FAIL" if isinstance(e, AssertionError) else "ERROR", label,
			f"{type(e).__name__}: {frappe.utils.strip_html(str(e))}"[:400]))
		frappe.db.rollback()
		raise _Stop(label)
	R.append(("PASS", label, out if isinstance(out, str) else ""))
	return out


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, exc=(frappe.PermissionError, frappe.ValidationError)):
	try:
		fn()
	except exc:
		frappe.db.rollback()
		frappe.local.message_log = []
		return
	raise AssertionError("did not raise")


def _names(rows, key="name"):
	out = set()
	for r in rows or []:
		out.add(r.get(key) if isinstance(r, dict) else (r[0] if isinstance(r, list | tuple) else r))
	return out


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	if S:
		print("created:", {k: v for k, v in S.items() if v})
	frappe.db.commit()
	return R


def _wh_company(names):
	return set(frappe.get_all("Warehouse", {"name": ("in", list(names) or [""])}, pluck="company"))


def _ledger_in_apc(vouchers):
	"""Stock and GL rows of these vouchers exist and are all APC's."""
	sle = frappe.get_all("Stock Ledger Entry", {"voucher_no": ("in", vouchers), "is_cancelled": 0},
		["company", "warehouse"])
	gle = frappe.get_all("GL Entry", {"voucher_no": ("in", vouchers), "is_cancelled": 0}, pluck="company")
	_assert(sle, f"no stock ledger for {vouchers}")
	_assert({r.company for r in sle} == {APC}, {r.company for r in sle})
	_assert(_wh_company({r.warehouse for r in sle}) == {APC}, {r.warehouse for r in sle})
	_assert(not gle or set(gle) == {APC}, set(gle))


def _notified(doctype, name, since):
	return set(frappe.get_all("Notification Log", {"document_type": doctype, "document_name": name,
		"creation": (">=", since)}, pluck="for_user"))


# --- fixtures ------------------------------------------------------------------------------


def _item(code, group, uom, valuation, **extra):
	doc = frappe.get_doc(dict({
		"doctype": "Item", "item_code": code, "item_name": code, "item_group": group, "stock_uom": uom,
		"is_stock_item": 1, "include_item_in_manufacturing": 1, "valuation_rate": valuation,
		"custom_companies": [{"company": APC}], "gst_hsn_code": S.hsn,
		"item_defaults": [{"company": APC, "default_warehouse": WH["fg_warehouse"]}],
	}, **extra))
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _bom(item, rows, variation):
	from alpinos.production import material_type as MT

	doc = frappe.get_doc({
		"doctype": "BOM", "item": item, "company": APC, "quantity": 1, "is_active": 1, "is_default": 1,
		"currency": "INR", "rm_cost_as_per": "Valuation Rate", "custom_bom_variation_name": variation,
		"items": [{"item_code": c, "qty": q, "custom_process_stage": stage,
			"custom_material_type": {"RM": "RM", "PM": "PM"}.get(MT.item_type(c))} for c, q, stage in rows],
	})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _fixtures(A):
	frappe.set_user("Administrator")
	S.hsn = frappe.db.get_value("GST HSN Code", {"name": ("like", "1904%")}) or frappe.db.get_value("GST HSN Code", {})
	S.machine_type = frappe.get_doc({"doctype": "Machine Type", "machine_type_name": f"{P} Type",
		"is_active": 1}).insert(ignore_permissions=True).name
	_item(RM, "Raw Material", "Kg", 100)
	_item(PM, "Pouch", "Nos", 2)
	_item(BULK, "Combos", "Kg", 0)
	_item(SKU, "Finished Goods", "Nos", 0, has_batch_no=1, custom_pack_size_kg=0.5,
		custom_allowed_filling_categories=[{"filling_process_category": "Jar Filling"}])
	S.bom = _bom(BULK, [(RM, 50, "Base RM")], f"{P} bulk")
	S.sku_bom = _bom(SKU, [(BULK, 0.5, "Pouch Filling"), (PM, 1, "Pouch Filling")], f"{P} pack")
	tag = [{"company": APC}]
	S.oven = frappe.get_doc({"doctype": "Machine", "machine_name": f"{P} Oven", "machine_type": S.machine_type,
		"status": "Active", "custom_companies": tag}).insert(ignore_permissions=True).name
	S.line = frappe.get_doc({"doctype": "Machine", "machine_name": f"{P} Line 7", "machine_type": S.machine_type,
		"status": "Active", "filling_process_category": "Jar Filling", "custom_companies": tag}
		).insert(ignore_permissions=True).name
	S.bake = frappe.get_doc({"doctype": "Process Master", "process_code": "CS-FLOW-BAK",
		"process_name": "CS-FLOW Baking", "process_sequence": 901, "is_active": 1, "qc_required": 1,
		"allow_inward_entry": 1, "allow_machine_assignment": 1, "custom_companies": tag,
		"machine_types": [{"machine_type": S.machine_type}]}).insert(ignore_permissions=True).name
	S.fill_process = frappe.get_doc({"doctype": "Process Master", "process_code": "CS-FLOW-FIL",
		"process_name": "CS-FLOW Filling", "process_sequence": 902, "is_active": 1, "qc_required": 1,
		"allow_inward_entry": 1, "allow_machine_assignment": 0, "custom_companies": tag,
		"machine_types": [{"machine_type": S.machine_type}]}).insert(ignore_permissions=True).name
	# Production Settings > Warehouses by Company: a row for APC (the Single is not re-saved).
	S.settings_row = None
	if not frappe.db.exists("Production Company Warehouses", {"parent": "Production Settings", "company": APC}):
		row = frappe.get_doc(dict(WH, doctype="Production Company Warehouses", company=APC,
			parent="Production Settings", parenttype="Production Settings", parentfield="company_warehouses",
			idx=99))
		row.db_insert()
		S.settings_row = row.name
		frappe.clear_document_cache("Production Settings", "Production Settings")
	# RM (batch-tracked, as every RM item is) and PM in Stores - APC.
	S.rm_batch = frappe.get_doc({"doctype": "Batch", "batch_id": f"{P}-RM-B1", "item": RM}).insert(
		ignore_permissions=True).name
	se = frappe.get_doc({"doctype": "Stock Entry", "purpose": "Material Receipt",
		"stock_entry_type": "Material Receipt", "company": APC, "items": [
			{"item_code": RM, "qty": 100, "t_warehouse": WH["main_warehouse"], "basic_rate": 100,
			 "batch_no": S.rm_batch, "use_serial_batch_fields": 1},
			{"item_code": PM, "qty": 500, "t_warehouse": WH["main_warehouse"], "basic_rate": 2}]})
	se.insert(ignore_permissions=True)
	se.submit()
	S.receipt = se.name
	frappe.db.commit()


# --- cleanup -------------------------------------------------------------------------------


def _purge(doctype, names):
	names = [n for n in set(names or []) if n]
	if not names or not frappe.db.exists("DocType", doctype):
		return
	for df in frappe.get_meta(doctype).get_table_fields():
		frappe.db.delete(df.options, {"parent": ("in", names), "parenttype": doctype})
	frappe.db.delete(doctype, {"name": ("in", names)})
	for dt in ("Comment", "Version"):
		frappe.db.delete(dt, {"reference_doctype" if dt == "Comment" else "ref_doctype": doctype,
			"reference_name" if dt == "Comment" else "docname": ("in", names)})
	frappe.db.delete("Notification Log", {"document_type": doctype, "document_name": ("in", names)})
	queued = frappe.get_all("Email Queue", {"reference_doctype": doctype, "reference_name": ("in", names)},
		pluck="name")
	if queued:
		frappe.db.delete("Email Queue Recipient", {"parent": ("in", queued)})
		frappe.db.delete("Email Queue", {"name": ("in", queued)})


def _cleanup():
	"""Hard-delete everything the run made: own items, their stock / ledger rows, and every
	document of the chain (all of it is tied to the CS-FLOW-PROD items)."""
	frappe.set_user("Administrator")
	frappe.db.rollback()
	left = []
	items = [i for i in ITEMS if frappe.db.exists("Item", i)]
	pos = frappe.get_all("Production Order", {"fg_item": BULK}, pluck="name")
	wos = frappe.get_all("Work Order", {"production_item": BULK}, pluck="name")
	ses = list(set(frappe.get_all("Stock Entry Detail", {"item_code": ("in", list(ITEMS))}, pluck="parent")))
	try:
		vouchers = ses + wos
		bundles = frappe.get_all("Serial and Batch Bundle", {"voucher_no": ("in", vouchers or [""])}, pluck="name")
		_purge("Serial and Batch Bundle", bundles)
		for dt in ("Stock Ledger Entry", "GL Entry", "Payment Ledger Entry", "Repost Item Valuation"):
			frappe.db.delete(dt, {"voucher_no": ("in", vouchers or [""])})
		frappe.db.delete("Bin", {"item_code": ("in", list(ITEMS))})
		_purge("Stock Entry", ses)
		_purge("Material Request", frappe.get_all("Material Request Item", {"item_code": ("in", list(ITEMS))},
			pluck="parent"))
		_purge("Job Card", frappe.get_all("Job Card", {"work_order": ("in", wos or [""])}, pluck="name"))
		for dt, field, values in (
				("Final QC", "target_sku", [SKU]), ("Filling Inward", "bulk_item", [BULK]),
				("Filling Plan", "bulk_item", [BULK]), ("Production QC", "production_item", [BULK]),
				("Process Inward", "production_item", [BULK]), ("Production Run", "production_item", [BULK]),
				("Machine Run", "production_item", [BULK]), ("Production Yield Record", "parent_po", pos)):
			if frappe.db.exists("DocType", dt):
				_purge(dt, frappe.get_all(dt, {field: ("in", values or [""])}, pluck="name"))
		_purge("Work Order", wos)
		_purge("Production Order", pos)
		_purge("Batch", frappe.get_all("Batch", {"item": ("in", list(ITEMS))}, pluck="name"))
		_purge("BOM", frappe.get_all("BOM", {"item": ("in", [BULK, SKU])}, pluck="name"))
		_purge("Machine", frappe.get_all("Machine", {"machine_name": ("like", f"{P}%")}, pluck="name"))
		_purge("Process Master", frappe.get_all("Process Master", {"process_code": ("like", "CS-FLOW-%")},
			pluck="name"))
		_purge("Machine Type", frappe.get_all("Machine Type", {"machine_type_name": ("like", f"{P}%")},
			pluck="name"))
		_purge("Item", items)
		if S.get("settings_row"):
			frappe.db.delete("Production Company Warehouses", {"name": S.settings_row})
			frappe.clear_document_cache("Production Settings", "Production Settings")
	except Exception as e:
		left.append(f"cleanup error {type(e).__name__}: {e}")
	for user in (U_APC, U_PLN, U_DEF, U_ALL):
		cleanup_user(user)
	frappe.db.commit()
	for dt, filters in (("Item", {"name": ("like", f"{P}%")}), ("Production Order", {"fg_item": BULK}),
			("Work Order", {"production_item": BULK}), ("Stock Ledger Entry", {"item_code": ("like", f"{P}%")}),
			("Machine", {"machine_name": ("like", f"{P}%")}), ("Process Master", {"process_code": ("like", "CS-FLOW-%")})):
		if frappe.get_all(dt, filters, limit=1):
			left.append(dt)
	print("left in the database:", left or "nothing")


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	S.clear()
	frappe.set_user("Administrator")
	ensure_enabled()
	A = companies()[0]
	try:
		_cleanup_quiet()
		step("fixtures: APC items, BOMs, machines, processes, warehouses row, stock", lambda: _fixtures(A))
		make_user(U_APC, {APC: ROLES})
		make_user(U_PLN, {APC: ["Production User"]})
		make_user(U_DEF, {A: ROLES})
		make_user(U_ALL, {A: ROLES, APC: ROLES})
		_chain(A)
	except _Stop:
		pass
	finally:
		_report()
		_cleanup()
	return R


def _cleanup_quiet():
	import contextlib
	import io

	with contextlib.redirect_stdout(io.StringIO()):
		_cleanup()


def _chain(A):
	from alpinos.production import execution as EX
	from alpinos.production import execution_inward as EI
	from alpinos.production import filling_inward as FI
	from alpinos.production import filling_plan as FP
	from alpinos.production import final_qc as FQ
	from alpinos.production import material_issue as MI
	from alpinos.production import material_request as MRQ
	from alpinos.production import production_order_api as POA
	from alpinos.production import production_qc as PQC
	from alpinos.production import production_reports as REP
	from alpinos.production import store_planning as SP
	from alpinos.production import sub_order as SO

	today = nowdate()

	def denied(label, fn):
		"""The default company's user is refused."""
		check(f"{label}: refused to the default company's user", lambda: as_user(U_DEF, lambda: _raises(fn)))

	# 1. Production Order: the planner of APC writes it and sends it for approval.
	def create_po():
		out = as_user(U_PLN, lambda: POA.save_production_order({
			"production_type": "Own Production", "fg_item": BULK, "bom_no": S.bom, "batch_number": f"{P}-B1",
			"production_qty_kg": 50, "production_qty_pcs": 0, "production_start_date": today,
			"delivery_date": add_days(today, 7)}))
		S.po = out["name"]
		po = frappe.db.get_value("Production Order", S.po, ["company", "status", "total_batches"], as_dict=True)
		_assert(po.company == APC and S.po.startswith("PO-APC-"), (S.po, po))
		return S.po
	step("Production Order saved by APC's planner", create_po)
	step("... sent for approval (Pending Approval)", lambda: _assert(
		as_user(U_PLN, lambda: POA.submit_production_order(S.po))["status"] == "Pending Approval"))
	denied("approve APC's order", lambda: POA.approve_production_order(S.po))
	denied("open APC's order", lambda: POA.get_form_context(S.po))
	check("the default company's user does not list APC's order", lambda: _assert(
		S.po not in _names(as_user(U_DEF, lambda: POA.get_list(page_length=200))["data"])))

	def approve():
		out = as_user(U_APC, lambda: POA.approve_production_order(S.po))
		_assert(out["status"] == "Approved" and out["sub_orders"], out)
		S.sub = out["sub_orders"][0]
		wo = frappe.db.get_value("Work Order", S.sub, ["company", "fg_warehouse", "bom_no"], as_dict=True)
		_assert(wo.company == APC and _wh_company([wo.fg_warehouse]) == {APC} and wo.bom_no == S.bom, wo)
		return S.sub
	step("approved by APC's Production Manager; Sub PO in APC", approve)

	def send():
		since = frappe.utils.now()
		_assert(as_user(U_APC, lambda: POA.send_to_store(S.po))["status"] == "Sent To Store")
		told = _notified("Production Order", S.po, since)
		_assert(U_APC in told and U_DEF not in told and U_PLN not in told, told)
	step("sent to store; the store of APC is told, not the default company's", send)

	# 2. Store planning: the Baking process on APC's oven, today.
	check("store board in APC shows the Sub PO", lambda: _assert(
		S.sub in _names(as_user(U_APC, lambda: SP.get_board())["unplanned"])))
	check("store board of the default company does not", lambda: _assert(
		S.sub not in _names(as_user(U_DEF, lambda: SP.get_board())["unplanned"])))
	denied("plan APC's Sub PO", lambda: SP.save_planning(S.sub, S.bake, S.oven, today))
	step("planned on Baking / the APC oven", lambda: as_user(
		U_APC, lambda: SP.save_planning(S.sub, S.bake, S.oven, today)) and None)
	from alpinos.production import execution_common as X

	check("APC's Baking has no process before it (APC's own sequence)", lambda: _assert(
		X.previous_process(S.bake) is None and X.is_output_stage(S.bake)))
	check("the default company's sequence is unchanged", lambda: _assert(
		(X.previous_process("PRC-BAK") or {}).get("name") == "PRC-MIX" and X.is_output_stage("PRC-BAK")
		and not X.is_output_stage("PRC-MIX")))

	# 3. Material Request from Stores - APC to WIP - APC.
	def mr():
		since = frappe.utils.now()
		S.mr = as_user(U_APC, lambda: SP.generate_mr(S.sub))["material_request"]
		doc = frappe.get_doc("Material Request", S.mr)
		_assert(doc.company == APC and "-APC-" in S.mr, (S.mr, doc.company))
		_assert({r.from_warehouse for r in doc.items} == {WH["main_warehouse"]}
			and {r.warehouse for r in doc.items} == {WH["wip_warehouse"]}, [(r.from_warehouse, r.warehouse) for r in doc.items])
		told = _notified("Material Request", S.mr, since)
		_assert(U_APC in told and U_DEF not in told, told)
		return S.mr
	step("Material Request generated (APC warehouses, APC store told)", mr)
	denied("open APC's MR", lambda: MRQ.get_mr_context(S.mr))
	check("the default company's user does not list APC's MR", lambda: _assert(
		S.mr not in _names(as_user(U_DEF, lambda: MRQ.get_mr_list(page_length=200))["data"])))

	# 4. Material Issue to WIP - APC.
	def mi():
		ctx = as_user(U_APC, lambda: MI.mr_pending_rows(S.mr))
		_assert({r["s_warehouse"] for r in ctx["rows"]} == {WH["main_warehouse"]}, ctx["rows"])
		S.mi = as_user(U_APC, lambda: MI.save_mi({"material_request": S.mr, "items": ctx["rows"]}))["name"]
		as_user(U_APC, lambda: MI.submit_mi(S.mi))
		_assert(frappe.db.get_value("Stock Entry", S.mi, "company") == APC and "-APC-" in S.mi, S.mi)
		_ledger_in_apc([S.mi])
		return S.mi
	step("Material Issue submitted (stock Stores -> WIP, all APC)", mi)
	denied("issue against APC's MR", lambda: MI.save_mi({"material_request": S.mr, "items": []}))

	def mrt():
		from alpinos.production import material_constants as M
		from alpinos.production import material_return as MRT

		ctx = as_user(U_APC, lambda: MRT.issue_balance_rows(S.mi))
		rows = [dict(r, qty=1, reason=M.RETURN_REASONS[0]) for r in ctx["rows"] if r["item_code"] == RM]
		S.mrt = as_user(U_APC, lambda: MRT.save_mrt({"material_issue": S.mi, "items": rows}))["name"]
		as_user(U_APC, lambda: MRT.submit_mrt(S.mrt))
		_assert("-APC-" in S.mrt and frappe.db.get_value("Stock Entry", S.mrt, "company") == APC, S.mrt)
		_ledger_in_apc([S.mrt])
		return S.mrt
	step("Material Return of 1 KG RM (WIP -> Stores, all APC)", mrt)
	check("Sub PO is Ready to Run", lambda: _assert(
		frappe.db.get_value("Work Order", S.sub, "custom_execution_status") == "Ready to Run"))

	# 5. Shop floor.
	def start():
		cards = {c["key"]: c for c in as_user(U_APC, lambda: EX.get_floor())["cards"]}
		_assert(S.sub in cards and cards[S.sub]["can_start"], cards.get(S.sub))
		S.run = as_user(U_APC, lambda: EX.start_production(S.sub))["name"]
		_assert(frappe.db.get_value("Production Run", S.run, "company") == APC)
		return S.run
	step("production started on the shop floor (run in APC)", start)
	check("the default company's floor does not show it", lambda: _assert(
		S.sub not in {c["key"] for c in as_user(U_DEF, lambda: EX.get_floor())["cards"]}))
	denied("complete APC's run", lambda: EX.complete_production(S.run))
	step("production completed", lambda: as_user(U_APC, lambda: EX.complete_production(S.run)) and None)

	# 6. Process Inward: 45 KG baked, posted into the baked WIP of APC.
	def inward():
		since = frappe.utils.now()
		as_user(U_APC, lambda: EI.get_inward_context(production_run=S.run))
		S.inward = as_user(U_APC, lambda: EI.save_inward({"production_run": S.run, "total_batch": 1,
			"mixing_wastage_kg": 3, "baking_wastage_kg": 2, "actual_output_kg": 45}))["name"]
		out = as_user(U_APC, lambda: EI.submit_inward(S.inward, send_for_qc=1))
		S.pqc = out["production_qc"]
		doc = frappe.get_doc("Process Inward", S.inward)
		_assert(doc.company == APC and doc.status == "Pending QC" and cint(doc.stock_posted), (doc.company, doc.status))
		S.output_se = [a.stock_entry for a in doc.allocations if a.stock_entry]
		_ledger_in_apc(S.output_se)
		se = frappe.db.get_value("Stock Entry", S.output_se[0], ["purpose", "work_order"], as_dict=True)
		_assert(se.purpose == "Manufacture" and se.work_order == S.sub, se)
		_assert(frappe.db.get_value("Production QC", S.pqc, "company") == APC)
		told = _notified("Production QC", S.pqc, since)
		_assert(U_APC in told and U_DEF not in told, told)
		return f"{S.inward}, {S.output_se}, {S.pqc}"
	step("Process Inward submitted, sent for QC (stock + QC in APC)", inward)
	denied("open APC's inward", lambda: EI.get_inward_context(S.inward))
	denied("open APC's Production QC", lambda: PQC.get_qc_context(S.pqc))

	# 7. Production QC: 44 approved, 1 rejected to Rejected - APC.
	def pqc():
		since = frappe.utils.now()
		as_user(U_APC, lambda: PQC.send_for_filling({"name": S.pqc, "approved_kg": 44, "rejected_kg": 1,
			"rejection_reason": "Overbaked"}))
		doc = frappe.get_doc("Production QC", S.pqc)
		_assert(doc.docstatus == 1 and doc.stock_entries, doc.status)
		S.reject_se = [s.strip() for s in doc.stock_entries.split(",")]
		_ledger_in_apc(S.reject_se)
		_assert(WH["rejected_warehouse"] in frappe.get_all("Stock Ledger Entry",
			{"voucher_no": ("in", S.reject_se)}, pluck="warehouse"))
		_assert(flt(frappe.db.get_value("Work Order", S.sub, "custom_wip_qty")) == 44)
		told = _notified("Production QC", S.pqc, since)
		_assert(U_APC in told and U_DEF not in told, told)
		return ", ".join(S.reject_se)
	step("Production QC sent for filling (rejection moved inside APC)", pqc)

	# 8. Filling Plan on APC's line: 80 packs of 0.5 KG.
	def plan():
		S.plan = as_user(U_APC, lambda: FP.save_plan({"plan_date": today, "parent_po": S.po, "sub_order": S.sub,
			"filling_line": S.line, "rows": [{"target_sku": SKU, "planned_pcs": 80}]}))["name"]
		_assert(frappe.db.get_value("Filling Plan", S.plan, "company") == APC)
		return S.plan
	step("Filling Plan saved", plan)
	denied("open APC's filling plan", lambda: FP.get_plan_context(S.plan))
	check("the default company's plan list does not show it", lambda: _assert(
		S.plan not in _names(as_user(U_DEF, lambda: FP.get_plan_list())["data"])))

	# 9. Filling Inward: 80 packs into QC Hold - APC, the hopper emptied.
	def fill():
		since = frappe.utils.now()
		row = frappe.get_all("Filling Plan Row", {"parent": S.plan}, pluck="name")[0]
		out = as_user(U_APC, lambda: FI.submit_inward({"filling_plan": S.plan, "plan_row": row, "input_pcs": 80,
			"wastage_kg": 1, "submission_type": "Final Inward"}))
		S.fill, S.fg_batch = out["name"], out["fg_batch"]
		doc = frappe.get_doc("Filling Inward", S.fill)
		_assert(doc.company == APC and S.fg_batch, (doc.company, S.fg_batch))
		S.fill_se = [n for n in (doc.stock_entry, doc.writeoff_entry) if n]
		_ledger_in_apc(S.fill_se)
		_assert(WH["fg_hold_warehouse"] in frappe.get_all("Stock Ledger Entry",
			{"voucher_no": doc.stock_entry, "item_code": SKU}, pluck="warehouse"))
		_assert(frappe.db.get_value("Stock Ledger Entry", {"voucher_no": doc.stock_entry, "item_code": PM},
			"warehouse") in (WH["wip_warehouse"], WH["main_warehouse"]))
		told = _notified("Batch", S.fg_batch, since)
		_assert(U_APC in told and U_DEF not in told, told)
		return f"{S.fill}, batch {S.fg_batch}, {S.fill_se}"
	step("Filling Inward submitted (FG batch in QC Hold - APC)", fill)
	denied("reverse APC's filling inward", lambda: FI.reverse_inward(S.fill, "test"))

	# 10. Final QC by a member of both companies working in "All": stock moves in APC.
	def fqc():
		since = frappe.utils.now()
		set_active(U_ALL, ALL)
		info = as_user(U_ALL, lambda: FQ.get_batch_info(S.fg_batch))
		_assert(info["total_inward_pcs"] == 80, info["total_inward_pcs"])
		out = as_user(U_ALL, lambda: FQ.decide_qc({"fg_batch": S.fg_batch, "approved_pcs": 78, "rejected_pcs": 0,
			"sample_size": 2, "tests": [{"test_name": t, "test_result": "Pass"} for t in
				("Visual Check", "Seal Integrity", "Weight Check", "Lab Test")]}, "Approve Batch"))
		S.fqc = out["name"]
		doc = frappe.get_doc("Final QC", S.fqc)
		_assert(doc.company == APC and doc.qc_status == "Approved", (doc.company, doc.qc_status))
		S.fqc_se = [n for n in (doc.transfer_entry, doc.sample_entry) if n]
		_ledger_in_apc(S.fqc_se)
		_assert(WH["fg_warehouse"] in frappe.get_all("Stock Ledger Entry", {"voucher_no": doc.transfer_entry},
			pluck="warehouse"))
		told = _notified("Batch", S.fg_batch, since)
		_assert(U_APC in told and U_DEF not in told, told)
		return f"{S.fqc}, {S.fqc_se}"
	step("Final QC approved in All mode (FG Hold -> Finished Goods - APC)", fqc)
	denied("open APC's Final QC", lambda: FQ.get_qc_context(S.fqc))

	# 11. Lists, boards and reports: APC's user / the default company's / a member of both.
	lists = [
		("production order list", lambda: _names(POA.get_list(page_length=200)["data"]), lambda: S.po),
		("sub order list", lambda: _names(SO.get_sub_order_list(page_length=200)["data"]), lambda: S.sub),
		("MR list", lambda: _names(MRQ.get_mr_list(page_length=200)["data"]), lambda: S.mr),
		("MI list", lambda: _names(MI.get_mi_list(page_length=200)["data"]), lambda: S.mi),
		("Production QC list", lambda: _names(PQC.get_qc_list(page_length=200)["data"]), lambda: S.pqc),
		("filling plan list", lambda: _names(FP.get_plan_list(page_length=200)["data"]), lambda: S.plan),
		("Final QC list", lambda: _names(FQ.get_qc_list(page_length=200)["data"]), lambda: S.fqc),
		("Sub-PO report", lambda: _names(REP.run_report("sub_po", {})["rows"]), lambda: S.sub),
		("Parent PO report", lambda: _names(REP.run_report("parent_po", {})["rows"]), lambda: S.po),
	]
	for label, fn, name in lists:
		def apc_sees(fn=fn, name=name):
			_assert(name() in as_user(U_APC, fn), f"{name()} missing for APC's user")
			_assert(name() not in as_user(U_DEF, fn), f"{name()} shown to the default company's user")
		check(f"{label}: APC's user sees it, the default company's does not", apc_sees)
	set_active(U_ALL, A)
	for label, fn, name in lists:
		check(f"{label}: member of both, in the default company: hidden",
			lambda fn=fn, name=name: _assert(name() not in as_user(U_ALL, fn)))
	set_active(U_ALL, ALL)
	for label, fn, name in lists:
		check(f"{label}: member of both, All mode: shown",
			lambda fn=fn, name=name: _assert(name() in as_user(U_ALL, fn)))
	set_active(U_ALL, A)
