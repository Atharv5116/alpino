"""Company-wise access for production part B: shop floor, process inward, Production QC,
filling plans / inwards, Final QC, Production Orders and the Production Reports page.
Run on a TEST site (it turns the feature on):

	../env/bin/python /Users/hetvi/alpinos-wt/mrp_work/run.py alpinos-v16.localhost \
		alpinos.company_scope.prodb_scope_test.run

Fixtures: header-only copies of one record of each production doctype, once in company A
and once in company B (CS-PRODB-<KIND>-A / -B, linked to each other within a company), and
two users:
	cs.prodb.a@example.com   every production role, in A only
	cs.prodb.ab@example.com  every production role in A; only Production User + Plant Head in B
Everything is removed again at the end.
"""

import frappe
from frappe.utils import now_datetime, nowdate

from alpinos.company_scope.testing import (
	ALL,
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

U_A = "cs.prodb.a@example.com"
U_AB = "cs.prodb.ab@example.com"
ROLES = ["Production Manager", "Production User", "Production Operator", "QC Manager", "QC Inspector",
         "Plant Head"]
B_ROLES = ["Production User", "Plant Head"]
PREFIX = "CS-PRODB"
CO = {}

#: (kind, doctype) in creation order; deleted in reverse.
KINDS = (("PO", "Production Order"), ("WO", "Work Order"), ("RUN", "Production Run"),
         ("PINW", "Process Inward"), ("PQC", "Production QC"), ("FPL", "Filling Plan"),
         ("FIN", "Filling Inward"), ("FQC", "Final QC"), ("PYR", "Production Yield Record"),
         ("BATCH", "Batch"))


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


def n(kind, side):
	return f"{PREFIX}-{kind}-{side}"


# --- fixtures ------------------------------------------------------------------------------


def _template(doctype, filters=None):
	name = frappe.db.get_value(doctype, filters or {}, "name", order_by="creation asc")
	if not name:
		raise AssertionError(f"no {doctype} on this site to copy")
	return name


def _process():
	from alpinos.production import execution_common as X

	for p in X.active_processes():
		if not X.is_filling_process(p.name):
			return p.name
	raise AssertionError("no active non-filling Process Master")


def _make(side, company, process):
	today, now = nowdate(), now_datetime()
	po, wo, run, pinw, fpl, fin, batch = (n(k, side) for k in ("PO", "WO", "RUN", "PINW", "FPL", "FIN", "BATCH"))
	copy_header("Production Order", _template("Production Order"), po, company, status="Approved", docstatus=1,
	            creation_date=today)
	copy_header("Work Order", _template("Work Order", {"custom_parent_production_order": ["is", "set"]}), wo,
	            company, custom_parent_production_order=po, custom_execution_status="Assigned",
	            custom_assigned_process=process, custom_wip_qty=5, docstatus=0, custom_machine_run=None,
	            custom_current_run=None, custom_split_from=None)
	copy_header("Production Run", _template("Production Run"), run, company, sub_order=wo, member_sub_orders=wo,
	            parent_production_order=po, machine_run=None, machine=None, process_master=process,
	            status="Running", started_on=now, completed_on=None, process_inward=None)
	copy_header("Process Inward", _template("Process Inward"), pinw, company, production_run=run, sub_order=wo,
	            member_sub_orders=wo, parent_production_order=po, machine_run=None, machine=None,
	            process_master=process, posting_date=today, mixing_wastage_kg=1.5, docstatus=1,
	            status="Inward Logged", production_qc=None)
	copy_header("Production QC", _template("Production QC"), n("PQC", side), company, process_inward=pinw,
	            production_run=run, sub_order=wo, member_sub_orders=wo, parent_production_order=po,
	            machine_run=None, docstatus=0, status="Draft", stock_entries=None)
	copy_header("Filling Plan", _template("Filling Plan"), fpl, company, parent_po=po, sub_order=wo,
	            status="Planned", plan_date=today, rerouted_from=None, rerouted_to=None)
	copy_header("Filling Inward", _template("Filling Inward"), fin, company, filling_plan=fpl, parent_po=po,
	            sub_order=wo, fg_batch=batch, posting_date=today, docstatus=1, approval_status="Pending",
	            wastage_kg=0.5, stock_entry=None, writeoff_entry=None)
	copy_header("Final QC", _template("Final QC"), n("FQC", side), company, fg_batch=batch, filling_inward=fin,
	            sub_order=wo, parent_po=po, docstatus=1, qc_status="Approved", production_date=today,
	            rework_sub_order=None, transfer_entry=None, sample_entry=None)
	copy_header("Production Yield Record", _template("Production Yield Record"), n("PYR", side), company,
	            parent_po=po)
	copy_header("Batch", _template("Batch"), batch, company, batch_id=batch, custom_fg_status="FG-Hold",
	            custom_sub_production_order=wo, custom_parent_production_order=po, custom_filling_inward=fin,
	            disabled=0, parent_batch=None, reference_doctype=None, reference_name=None)


def _cleanup():
	frappe.set_user("Administrator")
	for _kind, doctype in reversed(KINDS):
		delete_copies(doctype, [f"{PREFIX}-{_kind}-{s}" for s in ("A", "B")])
	frappe.db.delete("Comment", {"reference_name": ["like", f"{PREFIX}-%"]})
	frappe.db.delete("Notification Log", {"document_name": ["like", f"{PREFIX}-%"]})
	for user in (U_A, U_AB):
		cleanup_user(user)
	frappe.db.commit()


# --- helpers -------------------------------------------------------------------------------


def _names(rows, key="name"):
	return {r.get(key) for r in rows or [] if r.get(key)}


def _mine(names):
	return {x for x in names if str(x).startswith(PREFIX)}


def _sees(names, expected, label=""):
	"""Of the fixture names, exactly `expected` (compared within the kinds expected)."""
	kinds = {x.rsplit("-", 1)[0] + "-" for x in expected}
	got = {x for x in _mine(names) if not kinds or any(x.startswith(k) for k in kinds)}
	_assert(got == set(expected), f"{label} expected {sorted(expected)}, got {sorted(got)}")


def _rep(report, filters=None, key="name"):
	from alpinos.production.production_reports import run_report

	return _names(run_report(report, filters or {})["rows"], key)


def _query(fn, filters=None, txt=PREFIX):
	return {r[0] for r in fn(doctype="Work Order", txt=txt, searchfield="name", start=0, page_len=50,
	                          filters=filters or {})}


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	frappe.set_user("Administrator")
	A, B, C = companies()
	CO.update(A=A, B=B)
	try:
		ensure_enabled()
		_cleanup()
		process = _process()
		_make("A", A, process)
		_make("B", B, process)
		make_user(U_A, {A: ROLES})
		make_user(U_AB, {A: ROLES, B: B_ROLES})
		frappe.db.commit()
		_lists(A, B)
		_reports(A, B, C)
		_views(A, B)
		_mutations(A, B)
		_queries(A, B)
	finally:
		_cleanup()
	return _report()


def _each_mode(label, fn, a_only, b_only, both):
	"""fn() -> names; checked for U_A in A, U_AB in B, U_AB in All, and Administrator."""
	check(f"{label}: user in A only sees A", lambda: _sees(as_user(U_A, fn), a_only, "A"))
	set_active(U_AB, CO["B"])
	check(f"{label}: switched to B sees B", lambda: _sees(as_user(U_AB, fn), b_only, "B"))
	set_active(U_AB, ALL)
	check(f"{label}: All mode sees both", lambda: _sees(as_user(U_AB, fn), both, "All"))
	set_active(U_AB, CO["A"])
	check(f"{label}: Administrator unchanged", lambda: _sees(fn(), both, "Admin"))


def _lists(A, B):
	from alpinos.production import execution, filling_inward, filling_plan, final_qc, production_order_api, production_qc

	def kinds(kind):
		return {n(kind, "A")}, {n(kind, "B")}, {n(kind, "A"), n(kind, "B")}

	_each_mode("Production Order list", lambda: _names(production_order_api.get_list(search=PREFIX)["data"]),
	           *kinds("PO"))
	_each_mode("Production QC list", lambda: _names(production_qc.get_qc_list(search=PREFIX)["data"]), *kinds("PQC"))
	_each_mode("Final QC list", lambda: _names(final_qc.get_qc_list(search=PREFIX)["data"]), *kinds("FQC"))
	_each_mode("Filling Plan list", lambda: _names(filling_plan.get_plan_list(search=PREFIX)["data"]), *kinds("FPL"))
	_each_mode("Filling calendar", lambda: _names(filling_plan.get_calendar(nowdate(), nowdate())["plans"]),
	           *kinds("FPL"))
	_each_mode("Filling Entry recent inwards", lambda: _names(filling_inward.get_entry_context()["recent"]),
	           *kinds("FIN"))
	_each_mode("Shop floor cards", lambda: _names(execution.get_floor(search=PREFIX)["cards"], "key"), *kinds("WO"))

	# Rule E: in All mode the B card is shown but read-only (only Production User / Plant Head in B).
	def floor_rights():
		cards = {c["key"]: c for c in execution.get_floor(search=PREFIX)["cards"]}
		return cards[n("WO", "A")]["can_pause"], cards[n("WO", "B")]["can_pause"]

	set_active(U_AB, ALL)
	check("Shop floor: actions only where the write role is held", lambda: _assert(
		as_user(U_AB, floor_rights) == (1, 0), f"got {as_user(U_AB, floor_rights)}"))
	set_active(U_AB, A)


def _reports(A, B, C):
	from alpinos.production.production_reports import get_report_index, production_summary_html

	for report, kind, key in (("parent_po", "PO", "name"), ("sub_po", "WO", "name"), ("yield", "PO", "parent"),
	                          ("loss", "PINW", "ref_name"), ("production_order", "FIN", "name")):
		_each_mode(f"Report {report}", lambda report=report, key=key: _rep(report, {}, key),
		           {n(kind, "A")}, {n(kind, "B")}, {n(kind, "A"), n(kind, "B")})

	set_active(U_AB, ALL)
	check("Report: company picked on the page narrows All mode", lambda: _sees(
		as_user(U_AB, lambda: _rep("parent_po", {"company": B})), {n("PO", "B")}))
	check("Report: a company the user is not in shows nothing", lambda: _sees(
		as_user(U_AB, lambda: _rep("parent_po", {"company": C})), set()))
	check("Report: user in A cannot pick B", lambda: _sees(
		as_user(U_A, lambda: _rep("parent_po", {"company": B})), set()))
	check("Report: Administrator picks B", lambda: _sees(_rep("parent_po", {"company": B}), {n("PO", "B")}))
	check("Report index offers the company filter", lambda: _assert(
		all(r["filters"][0] == "company" for r in get_report_index()["reports"])))

	set_active(U_AB, B)
	check("Summary print: header is the current company", lambda: _assert(
		B in as_user(U_AB, lambda: production_summary_html({})), "B not in header"))
	check("Summary print: header is the company picked", lambda: _assert(
		A in as_user(U_AB, lambda: production_summary_html({"company": A})), "A not in header"))
	set_active(U_AB, A)


def _views(A, B):
	from alpinos.production import execution, execution_inward, filling_plan, final_qc, production_order_api, production_qc

	opens = (
		("Production Order form", lambda side: production_order_api.get_form_context(n("PO", side))),
		("Production QC", lambda side: production_qc.get_qc_context(n("PQC", side))),
		("Final QC", lambda side: final_qc.get_qc_context(n("FQC", side))),
		("Final QC batch info", lambda side: final_qc.get_batch_info(n("BATCH", side))),
		("Filling Plan", lambda side: filling_plan.get_plan_context(n("FPL", side))),
		("Filling Plan WIP header", lambda side: filling_plan.get_wip_info(n("PO", side), n("WO", side))),
		("Process Inward", lambda side: execution_inward.get_inward_context(name=n("PINW", side))),
		("Production Run", lambda side: execution.get_run(n("RUN", side))),
	)
	set_active(U_AB, A)
	for label, fn in opens:
		check(f"{label}: B document while working in A asks to switch", lambda fn=fn: _raises(
			lambda: as_user(U_AB, lambda: fn("B")), contains="switch company"))
		check(f"{label}: user in A only cannot open B", lambda fn=fn: _raises(lambda: as_user(U_A, lambda: fn("B"))))
		check(f"{label}: user in A opens A", lambda fn=fn: as_user(U_A, lambda: fn("A")))
		check(f"{label}: Administrator opens B", lambda fn=fn: fn("B"))
	set_active(U_AB, B)
	for label, fn in opens:
		check(f"{label}: after switching to B it opens", lambda fn=fn: as_user(U_AB, lambda: fn("B")))
	# Rule E: the screen offers no write action in B, where the user only reads.
	check("Production QC in B: read-only for a reader there", lambda: _assert(
		as_user(U_AB, lambda: production_qc.get_qc_context(n("PQC", "B")))["can_write"] == 0))
	check("Filling Plan in B: read-only for a reader there", lambda: _assert(
		as_user(U_AB, lambda: filling_plan.get_plan_context(n("FPL", "B")))["can_write"] == 0))
	check("Process Inward in B: read-only for a reader there", lambda: _assert(
		as_user(U_AB, lambda: execution_inward.get_inward_context(name=n("PINW", "B")))["can_reverse"] == 0))
	set_active(U_AB, A)


def _mutations(A, B):
	from alpinos.production import (
		execution,
		filling_inward,
		filling_plan,
		final_qc,
		production_order_api,
		production_qc,
	)
	from alpinos.production import execution_common as X

	acts = (
		("pause production", lambda: execution.pause_production(n("RUN", "B"), reason=X.PAUSE_REASONS[0])),
		("delete a Filling Plan", lambda: filling_plan.delete_plan(n("FPL", "B"))),
		("approve filling wastage", lambda: filling_inward.approve_wastage(n("FIN", "B"))),
		("save a Production QC", lambda: production_qc.save_qc({"name": n("PQC", "B")})),
		("revoke a Final QC", lambda: final_qc.revoke_qc(n("FQC", "B"), "test")),
		("approve a Production Order", lambda: production_order_api.approve_production_order(n("PO", "B"))),
	)
	for label, fn in acts:
		check(f"user in A only cannot {label} in B", lambda fn=fn: _raises(lambda: as_user(U_A, fn)))
	# A member of B with only reading roles there: the write roles held in A do not count in B.
	set_active(U_AB, B)
	for label, fn in acts:
		if label == "approve filling wastage":
			continue  # Plant Head approves wastage, and U_AB is Plant Head in B
		check(f"reader in B cannot {label} in B", lambda fn=fn: _raises(lambda: as_user(U_AB, fn)))
	set_active(U_AB, A)
	check("refused actions changed nothing", lambda: _assert(
		frappe.db.get_value("Production Run", n("RUN", "B"), "status") == "Running"
		and frappe.db.exists("Filling Plan", n("FPL", "B"))
		and frappe.db.get_value("Filling Inward", n("FIN", "B"), "approval_status") == "Pending"
		and frappe.db.get_value("Final QC", n("FQC", "B"), "docstatus") == 1))


def _queries(A, B):
	from alpinos.production import filling, filling_plan, final_qc, production_order_api

	_each_mode("Filling plan Parent PO search", lambda: _query(filling_plan.parent_query),
	           {n("PO", "A")}, {n("PO", "B")}, {n("PO", "A"), n("PO", "B")})
	check("Filling plan Sub-PO search: B's parent finds nothing for a user in A", lambda: _assert(
		not as_user(U_A, lambda: _query(filling_plan.sub_order_query, {"parent_po": n("PO", "B")}))))
	check("Filling plan Sub-PO search: A's parent finds A's Sub-PO", lambda: _assert(
		as_user(U_A, lambda: _query(filling_plan.sub_order_query, {"parent_po": n("PO", "A")})) == {n("WO", "A")}))
	_each_mode("Final QC hold batch search", lambda: _query(final_qc.hold_batch_query),
	           {n("BATCH", "A")}, {n("BATCH", "B")}, {n("BATCH", "A"), n("BATCH", "B")})

	# Tagged masters: every local machine and BOM belongs to A only.
	line = frappe.db.get_value("Machine", {"filling_process_category": ["is", "set"], "status": "Active"},
	                           ["name", "filling_process_category", "custom_company_scope"], as_dict=True)
	if line and A in (line.custom_company_scope or ""):
		set_active(U_AB, B)
		check("Filling line search: an A-only line is not offered in B", lambda: _assert(
			line.name not in as_user(U_AB, lambda: _query(filling_plan.line_query, txt=""))))
		check("Machines for a category: none of A's in B", lambda: _assert(
			line.name not in {m.name for m in as_user(U_AB, lambda: filling.machines_for_category(
				line.filling_process_category))}))
		check("SKU / machine check: an A-only line is refused in B", lambda: _assert(
			not as_user(U_AB, lambda: filling.check_compatibility(line.name, "x"))["ok"]))
		set_active(U_AB, A)
		check("Filling line search: offered in A", lambda: _assert(
			line.name in as_user(U_A, lambda: _query(filling_plan.line_query, txt=""))))
		check("Category list counts only A's machines in A", lambda: _assert(
			{r["name"]: r["machine_count"] for r in as_user(U_A, filling.get_category_list)}.get(
				line.filling_process_category, 0) >= 1))
	bom = frappe.db.get_value("BOM", {"is_active": 1, "docstatus": ["<", 2], "company": A}, ["name", "item"],
	                          as_dict=True)
	if bom:
		def boms(user):
			return as_user(user, lambda: {r[0] for r in production_order_api.bom_for_item_query(
				doctype="BOM", txt="", searchfield="name", start=0, page_len=50, filters={"fg_item": bom.item})})

		check("BOM search: A's BOM offered in A", lambda: _assert(bom.name in boms(U_A)))
		set_active(U_AB, B)
		check("BOM search: A's BOM not offered in B", lambda: _assert(bom.name not in boms(U_AB)))
		check("BOM details: A's BOM while in B asks to switch", lambda: _raises(lambda: as_user(
			U_AB, lambda: production_order_api.bom_details(bom.item, bom.name)), contains="switch company"))
		set_active(U_AB, A)


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R
