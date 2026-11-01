"""Company-wise access for production part A: store planning, materials, sub orders, masters.

	bench --site <test site> execute alpinos.company_scope.proda_scope_test.run

All production data on the test site is in the default company (A). Header copies of a
Production Order, two Sub POs, an MR, an MI (with one row), an MRT, a BOM, a Production
Transfer, an Inventory Adjustment and a Delivery Note are put in company B, plus a Machine,
a Process Master and two Items tagged for A / B. A user with the production roles only in A
must not see or open B's; switched to B the same user (member of both) sees only B's, in
"All my companies" both, and Administrator always both. Every fixture is removed at the end.
"""

import frappe

from alpinos.company_scope import ALL
from alpinos.company_scope.testing import (
	as_user,
	cleanup_user,
	companies,
	copy_header,
	delete_copies,
	ensure_enabled,
	make_user,
	set_active,
)

R = []

U_A = "cs.proda.a@example.com"
U_AB = "cs.proda.ab@example.com"
U_MIX = "cs.proda.mix@example.com"
ROLES = ["Production Manager", "Production User", "Store Manager", "Store Planner", "Store User",
	"Plant Head", "Stock User"]

PO_B = "CS-PRODA-PO-B"
WO_B1 = "CS-PRODA-WO-B1"  # unplanned (copy of PO-003-A)
WO_B2 = "CS-PRODA-WO-B2"  # planned in October (copy of PO-001-A)
MR_B = "CS-PRODA-MR-B"
MI_B = "CS-PRODA-MI-B"
MRT_B = "CS-PRODA-MRT-B"
SED_B = "CS-PRODA-SED-B"
BOM_B = "CS-PRODA-BOM-B"
PTR_B = "CS-PRODA-PTR-B"
ADJ_A, ADJ_B = "CS-PRODA-ADJ-A", "CS-PRODA-ADJ-B"
DN_B = "CS-PRODA-DN-B"
M_B = "CS-PRODA-M-B"
PRC_B = "CS-PRODA-PRC-B"
ITEM_A, ITEM_B = "CS-PRODA-ITEM-A", "CS-PRODA-ITEM-B"

COPIES = (
	("Work Order", (WO_B1, WO_B2)), ("Production Order", (PO_B,)), ("Material Request", (MR_B,)),
	("Stock Entry", (MI_B, MRT_B)), ("Stock Entry Detail", (SED_B,)), ("BOM", (BOM_B,)),
	("Production Transfer", (PTR_B,)), ("Inventory Adjustment", (ADJ_A, ADJ_B)),
	("Delivery Note", (DN_B,)), ("Machine", (M_B,)), ("Process Master", (PRC_B,)),
	("Item", (ITEM_A, ITEM_B)),
)


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _raises(fn, exc=frappe.PermissionError, contains=None):
	try:
		fn()
	except exc as e:
		if contains and contains not in str(e):
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		return
	raise AssertionError("did not raise")


def _names(rows):
	out = set()
	for r in rows or []:
		if isinstance(r, dict):
			out.add(r.get("name"))
		elif isinstance(r, list | tuple):
			out.add(r[0])
		else:
			out.add(r)
	return out


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R


# --- fixtures ------------------------------------------------------------------------------


def _fixtures(A, B):
	from alpinos.production import material_type as MT

	copy_header("Production Order", "PO-003", PO_B, B)
	copy_header("Work Order", "PO-003-A", WO_B1, B, custom_parent_production_order=PO_B)
	copy_header("Work Order", "PO-001-A", WO_B2, B, custom_parent_production_order=PO_B)
	copy_header("Material Request", "MR-2026-00001", MR_B, B, custom_sub_production_order=WO_B1,
		custom_parent_production_order=PO_B)
	copy_header("Stock Entry", "MI-2026-00001", MI_B, B, custom_material_request=MR_B,
		custom_sub_production_order=WO_B1, work_order=None)
	row = frappe.db.get_value("Stock Entry Detail", {"parent": "MI-2026-00001"}, "*", as_dict=True)
	frappe.db.delete("Stock Entry Detail", {"name": SED_B})
	frappe.get_doc(dict(row, doctype="Stock Entry Detail", name=SED_B, parent=MI_B, mrp_batch=None,
		batch_no=None, serial_and_batch_bundle=None, custom_mr_item=None, material_request=None,
		material_request_item=None)).db_insert()
	copy_header("Stock Entry", "MRT-2026-00001", MRT_B, B, custom_material_issue=MI_B,
		custom_material_request=MR_B, custom_sub_production_order=WO_B1)
	copy_header("BOM", "BOM-0001", BOM_B, B, is_default=0)
	copy_header("Production Transfer", "PTR-2026-00001", PTR_B, B, stock_entry=None)
	copy_header("Delivery Note", "DN-26-00026", DN_B, B)
	for name, company in ((ADJ_A, A), (ADJ_B, B)):
		frappe.db.delete("Inventory Adjustment", {"name": name})
		frappe.get_doc({
			"doctype": "Inventory Adjustment", "name": name, "company": company,
			"posting_date": frappe.utils.nowdate(), "adjustment_type": "Add Stock",
			"reason_code": "Audit Correction", "admin_remarks": "company-scope test",
			"warehouse": frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}),
			"approval_status": "Draft", "docstatus": 0, "owner": "Administrator",
		}).db_insert()
	copy_header("Machine", "MAC-001", M_B, B, machine_name=M_B, custom_company_scope=f"|{B}|")
	copy_header("Process Master", "PRC-MIX", PRC_B, B, process_code=PRC_B, process_name=PRC_B,
		process_sequence=990, custom_company_scope=f"|{B}|")
	template = frappe.get_all("Item", {"item_group": ("in", MT.groups_of_type(MT.PM) or [""]),
		"is_stock_item": 1, "disabled": 0}, pluck="name", order_by="name", limit=1)[0]
	for name, company in ((ITEM_A, A), (ITEM_B, B)):
		copy_header("Item", template, name, company, item_code=name, item_name=name,
			custom_company_scope=f"|{company}|")
	frappe.db.commit()


def _cleanup():
	frappe.set_user("Administrator")
	for doctype, names in COPIES:
		delete_copies(doctype, names)
	for user in (U_A, U_AB, U_MIX):
		cleanup_user(user)
	frappe.db.commit()


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	frappe.set_user("Administrator")
	ensure_enabled()
	A, B, _C = companies()
	try:
		_fixtures(A, B)
		make_user(U_A, {A: ROLES})
		make_user(U_AB, {A: ROLES, B: ROLES})
		make_user(U_MIX, {A: ["Store Planner", "Store User", "Production User"], B: ["Production User"]})
		_run(A, B)
	finally:
		_cleanup()
	return _report()


def _run(A, B):
	from alpinos.alpinos_development.doctype.machine import machine as MACH
	from alpinos.alpinos_development.doctype.process_master import process_master as PM
	from alpinos.production import bom_api as BOM
	from alpinos.production import dispatch_rules as DR
	from alpinos.production import inventory_api as INV
	from alpinos.production import item_api as IA
	from alpinos.production import machine_api as MA
	from alpinos.production import material_issue as MI
	from alpinos.production import material_request as MRQ
	from alpinos.production import material_return as MRT
	from alpinos.production import material_type as MT
	from alpinos.production import process_api as PA
	from alpinos.production import store_planning as SP
	from alpinos.production import sub_order as SO
	from alpinos.production import sub_order_view as SOV

	def q(fn, *args):
		return lambda: _names(fn(*args))

	wh_b = frappe.db.get_value("Warehouse", {"company": B, "is_group": 0})

	# (label, names() as the current user, an A row, a B row)
	lists = [
		("sub order list", lambda: _names(SO.get_sub_order_list(page_length=200)["data"]), "PO-003-A", WO_B1),
		("store board cards", lambda: _names(SP.get_board(2026, 10)["cards"]), "PO-001-A", WO_B2),
		("store board unplanned", lambda: _names(SP.get_board(2026, 10)["unplanned"]), "PO-003-A", WO_B1),
		("unplanned options", q(SP.unplanned_options), "PO-003-A", WO_B1),
		("week MR candidates", lambda: set(SP.week_mr_candidates("2026-10-03")["sub_orders"]), "PO-001-A", WO_B2),
		("MR list", lambda: _names(MRQ.get_mr_list(page_length=200)["data"]), "MR-2026-00001", MR_B),
		("MI list", lambda: _names(MI.get_mi_list(page_length=200)["data"]), "MI-2026-00001", MI_B),
		("MRT list", lambda: _names(MRT.get_mrt_list(page_length=200)["data"]), "MRT-2026-00001", MRT_B),
		("BOM list", lambda: _names(BOM.get_list(page_length=200)["data"]), "BOM-0001", BOM_B),
		("transfer list", lambda: _names(INV.get_transfer_list(page_length=500)["rows"]), "PTR-2026-00001", PTR_B),
		("adjustment list", lambda: _names(INV.get_adjustment_list(page_length=500)["rows"]), ADJ_A, ADJ_B),
		("dispatch list", lambda: _names(DR.get_dispatch_list(page_length=500)["rows"]), "DN-26-00026", DN_B),
		("machine list", lambda: _names(MA.get_machine_list(page_length=200)["data"]), "MAC-001", M_B),
		("assignable machines", q(MACH.assignable_machines), "MAC-001", M_B),
		("machines for process", q(SO.machines_for_process, "PRC-MIX"), "MAC-001", M_B),
		("active processes", q(PM.active_processes), "PRC-MIX", PRC_B),
		("process list", lambda: _names(PA.get_list()), "PRC-MIX", PRC_B),
		("item list", lambda: _names(IA.get_list(search="CS-PRODA-ITEM", page_length=200)["data"]), ITEM_A, ITEM_B),
		("picker: MR sub order", q(MRQ.sub_order_query, "Work Order", "", "name", 0, 50, {}), "PO-003-A", WO_B1),
		("picker: MI request", q(MI.mr_query, "Material Request", "", "name", 0, 50, {}), "MR-2026-00001", MR_B),
		("picker: MRT issue", q(MRT.mi_query, "Stock Entry", "", "name", 0, 50, {}), None, MI_B),
		("picker: machine for process",
			q(SO.machine_query_for_process, "Machine", "", "name", 0, 50, {"process": "PRC-MIX"}), "MAC-001", M_B),
		("picker: item by type", q(MT.item_query, "Item", "CS-PRODA-ITEM", "name", 0, 50, {}), ITEM_A, ITEM_B),
		("picker: BOM component", q(BOM.component_item_query, "Item", "CS-PRODA-ITEM", "name", 0, 50, {}),
			ITEM_A, ITEM_B),
		("picker: items (no warehouse)", q(INV.items_at_warehouse, "Item", "CS-PRODA-ITEM", "name", 0, 50, {}),
			ITEM_A, ITEM_B),
	]

	# One document of B, opened from its page.
	views = [
		("sub order view", lambda: SOV.get_sub_order_view(WO_B1)),
		("planning popup", lambda: SP.get_planning_context(WO_B2)),
		("card summary", lambda: SP.get_sub_order_summary(WO_B2)),
		("merge candidates", lambda: SP.get_merge_candidates(WO_B2, "PRC-MIX")),
		("split dialog", lambda: SO.split_context(WO_B1)),
		("assign process dialog", lambda: SO.assign_process_context(WO_B1)),
		("MR context", lambda: MRQ.get_mr_context(MR_B)),
		("MR materials of a sub order", lambda: MRQ.sub_order_materials(WO_B1, wh_b)),
		("MI context", lambda: MI.get_mi_context(MI_B)),
		("MI rows of a request", lambda: MI.mr_pending_rows(MR_B)),
		("MRT context", lambda: MRT.get_mrt_context(MRT_B)),
		("MRT rows of an issue", lambda: MRT.issue_balance_rows(MI_B)),
		("BOM form", lambda: BOM.get_form_context(BOM_B)),
		("transfer form", lambda: INV.get_transfer_context(PTR_B)),
		("adjustment form", lambda: INV.get_adjustment_context(ADJ_B)),
		("dispatch detail", lambda: DR.get_dispatch_detail(DN_B)),
		("machine form", lambda: MA.get_machine_form_context(M_B)),
		("process form", lambda: PA.get_form_context(PRC_B)),
		("item form", lambda: IA.get_form_context(ITEM_B)),
	]

	# 1. In A only: A's rows, never B's; B's documents do not open.
	for label, fn, a_name, b_name in lists:
		def in_a(fn=fn, a_name=a_name, b_name=b_name):
			got = as_user(U_A, fn)
			_assert(b_name not in got, f"{b_name} leaked into A")
			_assert(not a_name or a_name in got, f"{a_name} missing")
		check(f"A only, {label}: A's rows, not B's", in_a)
	for label, fn in views:
		check(f"A only, {label}: B's document refused", lambda fn=fn: as_user(U_A, lambda: _raises(fn)))

	# 2. Member of A and B, working in A: B's documents ask to switch (or, tagged, are refused).
	set_active(U_AB, A)
	for label, fn in views:
		check(f"A of A+B, {label}: B's document refused", lambda fn=fn: as_user(U_AB, lambda: _raises(fn)))
	check("A of A+B, sub order view says switch", lambda: as_user(
		U_AB, lambda: _raises(lambda: SOV.get_sub_order_view(WO_B1), contains="switch company")))

	# 3. Switched to B: B's rows only; B's documents open.
	set_active(U_AB, B)
	for label, fn, a_name, b_name in lists:
		def in_b(fn=fn, a_name=a_name, b_name=b_name):
			got = as_user(U_AB, fn)
			_assert(b_name in got, f"{b_name} missing")
			_assert(not a_name or a_name not in got, f"{a_name} leaked into B")
		check(f"in B, {label}: B's rows, not A's", in_b)
	for label, fn in views:
		check(f"in B, {label}: B's document opens", lambda fn=fn: as_user(U_AB, fn))
	check("in B, a new Item defaults to B", lambda: _assert(
		as_user(U_AB, lambda: IA.get_form_context())["company"] == B))
	check("in B, the WIP dashboard has no A warehouse", lambda: _assert(
		not as_user(U_AB, lambda: INV.get_wip_dashboard())["warehouses"]))
	check("in B, the machine picker for a B sub order offers B's machine", lambda: _assert(
		M_B in as_user(U_AB, q(SO.machine_query_for_process, "Machine", "", "name", 0, 50,
			{"process": "PRC-MIX", "sub_order": WO_B1}))))

	# 4. All my companies: both.
	set_active(U_AB, ALL)
	for label, fn, a_name, b_name in lists:
		def in_all(fn=fn, a_name=a_name, b_name=b_name):
			got = as_user(U_AB, fn)
			_assert(b_name in got and (not a_name or a_name in got), f"got {sorted(got)[:8]}")
		check(f"All, {label}: both companies", in_all)
	check("All, machine picker for a B sub order offers only machines tagged for B", lambda: _assert(
		as_user(U_AB, q(SO.machine_query_for_process, "Machine", "", "name", 0, 50,
			{"process": "PRC-MIX", "sub_order": WO_B1})) == {M_B}))
	check("All, machines for a B sub order leave out A's", lambda: _assert(
		as_user(U_AB, q(SO.machines_for_process, "PRC-MIX", B)) == {M_B}))
	set_active(U_AB, A)

	# 5. Administrator is unchanged.
	for label, fn, a_name, b_name in lists:
		def admin(fn=fn, a_name=a_name, b_name=b_name):
			got = fn()
			_assert(b_name in got and (not a_name or a_name in got), f"got {sorted(got)[:8]}")
		check(f"Administrator, {label}: both companies", admin)
	check("Administrator opens B's sub order", lambda: SOV.get_sub_order_view(WO_B1))
	check("Administrator's WIP dashboard keeps the settings' floor", lambda: _assert(
		INV.get_wip_dashboard()["warehouses"]))

	# 6. Acting on B's documents from A is refused, and nothing changes.
	check("A only cannot plan B's sub order", lambda: as_user(
		U_A, lambda: _raises(lambda: SP.save_planning(WO_B1, "PRC-MIX", None, "2026-12-01"))))
	check("... and it stays unplanned", lambda: _assert(
		not frappe.db.get_value("Work Order", WO_B1, "custom_assigned_process")))
	check("A only cannot cancel B's planning", lambda: as_user(
		U_A, lambda: _raises(lambda: SP.cancel_planning(WO_B2, "test"))))
	check("A only cannot cancel B's MR", lambda: as_user(U_A, lambda: _raises(lambda: MRQ.cancel_mr(MR_B))))
	check("... and it stays submitted", lambda: _assert(
		frappe.db.get_value("Material Request", MR_B, "docstatus") == 1))
	check("A only cannot issue against B's MR", lambda: as_user(
		U_A, lambda: _raises(lambda: MI.save_mi({"material_request": MR_B, "items": []}))))
	check("A only cannot return against B's MI", lambda: as_user(
		U_A, lambda: _raises(lambda: MRT.save_mrt({"material_issue": MI_B, "items": []}))))
	check("A only cannot delete B's transfer", lambda: as_user(
		U_A, lambda: _raises(lambda: INV.delete_transfer(PTR_B))))
	check("... and it is still there", lambda: _assert(frappe.db.exists("Production Transfer", PTR_B)))
	check("A only cannot split B's sub order", lambda: as_user(
		U_A, lambda: _raises(lambda: SO.split_sub_order_action(WO_B1, 1))))

	# 7. Company-wise roles: Store Planner in A, only Production User in B.
	set_active(U_MIX, A)
	check("planner in A may plan A's sub order", lambda: _assert(
		as_user(U_MIX, lambda: SP.get_planning_context("PO-001-A"))["can_plan"] == 1))
	set_active(U_MIX, B)
	check("not a planner in B: B's popup offers no planning", lambda: _assert(
		as_user(U_MIX, lambda: SP.get_planning_context(WO_B2))["can_plan"] == 0))
	check("not a planner in B: planning B's sub order is refused", lambda: as_user(
		U_MIX, lambda: _raises(lambda: SP.save_planning(WO_B1, "PRC-MIX", None, "2026-12-01"),
			exc=frappe.ValidationError, contains="planning")))
	check("no store role in B: B's MR offers no submit / issue", lambda: _assert(
		not as_user(U_MIX, lambda: MRQ.get_mr_context(MR_B))["can_issue"]))

	# 8. Notifications go to the role holders of the document's company.
	from alpinos.production import notify as N

	sent = {}
	original = N.notify
	N.notify = lambda roles, subject, doctype=None, name=None, email=False, users=None: sent.update(
		{name: set(users or [])})
	try:
		MRQ.notify(("Store User",), B, "test", "Material Request", MR_B)
		MRQ.notify(("Store User",), A, "test", "Material Request", "MR-2026-00001")
	finally:
		N.notify = original
	check("an MR of B is announced to B's store users only", lambda: _assert(
		U_AB in sent[MR_B] and U_A not in sent[MR_B] and U_MIX not in sent[MR_B], sent.get(MR_B)))
	check("an MR of A is announced to A's store users", lambda: _assert(
		{U_A, U_AB, U_MIX} <= sent["MR-2026-00001"], sent.get("MR-2026-00001")))
