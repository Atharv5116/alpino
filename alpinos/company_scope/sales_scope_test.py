"""Company-wise access on the sales / dispatch pages and APIs. Run on a TEST site:

	bench --site <test site> execute alpinos.company_scope.sales_scope_test.run

Header-only copies of a Sales Order, Pick List and Delivery Note are made in company A
(the default) and in company B; users holding sales / warehouse roles in A only, in A and
B, and a DN / PL picker in B only, call the endpoints. Everything is removed at the end.
"""

import frappe

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

U_A = "cs.sales.a@example.com"
U_AB = "cs.sales.ab@example.com"
U_PICK_B = "cs.sales.pickb@example.com"
ROLES = ["Sales Manager", "Warehouse Manager", "Accounts User"]

SO_A, SO_B = "CS-SALES-SO-A", "CS-SALES-SO-B"
PL_A, PL_B = "CS-SALES-PL-A", "CS-SALES-PL-B"
DN_A, DN_B = "CS-SALES-DN-A", "CS-SALES-DN-B"
DISPATCH_DAY = "2031-01-15"


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


def _raises(fn, contains=None):
	"""fn() must raise (a PermissionError / ValidationError from frappe.throw)."""
	try:
		fn()
	except Exception as e:
		if contains and contains.lower() not in str(e).lower():
			raise AssertionError(f"raised, but '{contains}' not in: {e}")
		frappe.clear_messages()
		return
	raise AssertionError("did not raise")


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R


# --- fixtures ------------------------------------------------------------------------------


def _template(doctype, filters):
	name = frappe.db.get_value(doctype, filters, "name", order_by="modified desc")
	if not name:
		raise RuntimeError(f"No {doctype} to copy on this site")
	return name


def _make_copies(A, B):
	so_t = _template("Sales Order", {"docstatus": 1, "name": ["not like", "CS-%"]})
	pl_t = _template("Pick List", {"docstatus": 1, "name": ["not like", "CS-%"]})
	dn_t = _template("Delivery Note", {"is_return": 0, "name": ["not like", "CS-%"]})
	for company, so, pl, dn in ((A, SO_A, PL_A, DN_A), (B, SO_B, PL_B, DN_B)):
		copy_header(
			"Sales Order", so_t, so, company, docstatus=1, custom_invoice_no=f"{so}-INV",
			custom_appointment_required=1, custom_channel="Offline", custom_workflow_status="Forced Completed",
		)
		copy_header(
			"Pick List", pl_t, pl, company, docstatus=1, custom_sales_order_id=so,
			custom_dispatch_date=DISPATCH_DAY, custom_invoice_no=None, custom_assigned_to=None,
		)
		copy_header(
			"Delivery Note", dn_t, dn, company, docstatus=0, custom_sales_order_id=so,
			custom_lr_gr_no=None, custom_invoice_no=None, is_return=0, custom_assigned_to=None,
		)
	frappe.db.commit()


def _cleanup():
	frappe.set_user("Administrator")
	delete_copies("Delivery Note", [DN_A, DN_B])
	delete_copies("Pick List", [PL_A, PL_B])
	delete_copies("Sales Order", [SO_A, SO_B])
	for user in (U_A, U_AB, U_PICK_B):
		cleanup_user(user)
	frappe.db.commit()


# --- the run -------------------------------------------------------------------------------


def run():
	R.clear()
	frappe.set_user("Administrator")
	A, B, _C = companies()
	try:
		_cleanup()
		ensure_enabled()
		_make_copies(A, B)
		make_user(U_A, {A: ROLES})
		make_user(U_AB, {A: ROLES, B: ROLES}, active_company=A)
		make_user(U_PICK_B, {B: ["DN User", "PL User"]})
		_run(A, B)
	finally:
		_cleanup()
	return _report()


def _lists():
	"""name -> fn() returning the CS-SALES names an endpoint lists."""
	from alpinos import invoice_queue_api, post_delivery_api, sales_order_api
	from alpinos.alpinos_development.page.delivery_note_entry import delivery_note_entry
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry
	from alpinos.alpinos_development.report.pending_invoice_downloads import pending_invoice_downloads
	from alpinos.dispatch_report_api import _pick_lists_dispatched_on

	def so_list():
		rows = sales_order_api.get_sales_order_entry_list(search="CS-SALES-SO", page_length=100)["data"]
		return {r.name for r in rows}

	def pl_list():
		rows = pick_list_entry.get_pick_list_entry_list(search="CS-SALES-PL", page_length=100)["data"]
		return {r.name for r in rows}

	def dn_list():
		rows = delivery_note_entry.get_delivery_note_list(search="CS-SALES-DN", page_length=100)["data"]
		return {r.name for r in rows}

	def invoice_queue():
		rows = invoice_queue_api.get_rows(filters={"sales_order": "CS-SALES-SO"})["rows"]
		return {r["sales_order"] for r in rows}

	def invoice_queue_all():
		return set(invoice_queue_api.get_all_sales_orders(filters={"sales_order": "CS-SALES-SO"}))

	def post_delivery():
		rows = post_delivery_api.get_post_delivery_queue(search="CS-SALES-DN")["data"]
		return {r["delivery_note"] for r in rows}

	def dispatch_day():
		return {n for n in _pick_lists_dispatched_on(DISPATCH_DAY) if n.startswith("CS-SALES")}

	def pending_invoices():
		_cols, rows = pending_invoice_downloads.execute({"sales_order": "CS-SALES-SO"})
		return {r.sales_order for r in rows}

	def qty_flow():
		from alpinos.qty_flow_report import _pairs_so_pl

		out = set()
		for pl in (PL_A, PL_B):
			out |= {down for _up, down, *_rest in _pairs_so_pl(frappe._dict(down_id=pl))}
		return out

	return {
		"Sales Order list": (so_list, SO_A, SO_B),
		"Pick List list": (pl_list, PL_A, PL_B),
		"Delivery Note list": (dn_list, DN_A, DN_B),
		"Order Fulfilment rows": (invoice_queue, SO_A, SO_B),
		"Order Fulfilment select-all": (invoice_queue_all, SO_A, SO_B),
		"Post Dispatch queue": (post_delivery, DN_A, DN_B),
		"Dispatch Report pick lists": (dispatch_day, PL_A, PL_B),
		"Pending Invoice Downloads report": (pending_invoices, SO_A, SO_B),
		"SO to Pick List report": (qty_flow, PL_A, PL_B),
	}


def _run(A, B):
	lists = _lists()

	# 1. Lists: A only / switch to B / All / Administrator.
	for label, (fn, in_a, in_b) in lists.items():

		def a_only(fn=fn, in_a=in_a, in_b=in_b):
			got = as_user(U_A, fn)
			_assert(in_a in got and in_b not in got, f"got {sorted(got)}")

		def switched(fn=fn, in_a=in_a, in_b=in_b):
			set_active(U_AB, B)
			try:
				got = as_user(U_AB, fn)
			finally:
				set_active(U_AB, A)
			_assert(in_b in got and in_a not in got, f"got {sorted(got)}")

		def all_mode(fn=fn, in_a=in_a, in_b=in_b):
			set_active(U_AB, ALL)
			try:
				got = as_user(U_AB, fn)
			finally:
				set_active(U_AB, A)
			_assert({in_a, in_b} <= got, f"got {sorted(got)}")

		def admin(fn=fn, in_a=in_a, in_b=in_b):
			got = fn()
			_assert({in_a, in_b} <= got, f"got {sorted(got)}")

		check(f"{label}: user in A sees A's, not B's", a_only)
		check(f"{label}: switched to B shows B's only", switched)
		check(f"{label}: All mode shows both", all_mode)
		check(f"{label}: Administrator sees both", admin)

	# 2. One-document views: a B document opened while working in A.
	from alpinos import sales_order_api, sales_order_invoices, sales_order_trail
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry

	check("SO activity trail: B's order from A asks to switch", lambda: as_user(
		U_AB, lambda: _raises(lambda: sales_order_trail.get_activity_trail(SO_B), contains="switch")))
	check("SO activity trail: not a member of B, refused", lambda: as_user(
		U_A, lambda: _raises(lambda: sales_order_trail.get_activity_trail(SO_B))))

	def trail_in_b():
		set_active(U_AB, B)
		try:
			as_user(U_AB, lambda: sales_order_trail.get_activity_trail(SO_B))
		finally:
			set_active(U_AB, A)

	check("SO activity trail: opens after switching to B", trail_in_b)
	check("SO invoices popup: B's order from A refused", lambda: as_user(
		U_AB, lambda: _raises(lambda: sales_order_invoices.get_sales_order_invoices(SO_B))))
	check("SO pick-list status: B's order from A refused", lambda: as_user(
		U_AB, lambda: _raises(lambda: sales_order_api.get_so_pick_list_status(SO_B))))
	check("Pick List page: B's pick list from A refused", lambda: as_user(
		U_AB, lambda: _raises(lambda: pick_list_entry.get_pick_list_data(PL_B))))
	check("Administrator opens B's order trail", lambda: sales_order_trail.get_activity_trail(SO_B))

	# 3. Mutations and role gates follow the document's company.
	from alpinos import invoice_queue_api, workflow_engine

	check("Approve B's order without a role in B: refused", lambda: as_user(
		U_A, lambda: _raises(lambda: workflow_engine.approve_sales_order(SO_B), contains="not permitted")))
	check("Approve B's order with Warehouse Manager in B: past the role gate", lambda: as_user(
		U_AB, lambda: _raises(lambda: workflow_engine.approve_sales_order(SO_B), contains="Pending Warehouse")))
	check("Download of B's invoice from an A-only user: refused", lambda: as_user(
		U_A, lambda: _raises(lambda: invoice_queue_api.assert_orders_in_channel([SO_B]), contains="company")))
	check("Download of A's invoice: allowed", lambda: as_user(
		U_A, lambda: invoice_queue_api.assert_orders_in_channel([SO_A])))

	# 4. New documents take the active company; a company the user is not in is not used.
	def resolve(user, preferred):
		return as_user(user, lambda: sales_order_api._resolve_company(preferred))

	check("New SO company: A-only user asking for B gets A", lambda: _assert(resolve(U_A, B) == A, resolve(U_A, B)))

	def resolve_in_b():
		set_active(U_AB, B)
		try:
			got = resolve(U_AB, "")
		finally:
			set_active(U_AB, A)
		_assert(got == B, got)

	check("New SO company: blank follows the active company (B)", resolve_in_b)
	check("New SO company: member may pick B explicitly", lambda: _assert(resolve(U_AB, B) == B))
	check("New SO company: Administrator unchanged (default company)", lambda: _assert(
		sales_order_api._resolve_company("") == A))

	# 5. Assignee pickers: only holders of the role in the company.
	from alpinos import pick_list_api, workflow_role_access

	def dn_users(user):
		return as_user(user, lambda: workflow_role_access.get_dn_assignable_users())

	def dn_query(user):
		return {r[0] for r in as_user(user, lambda: workflow_role_access.dn_assigned_to_query(
			"User", "cs.sales", "name", 0, 50, {}))}

	def pl_query(user):
		return {r[0] for r in as_user(user, lambda: pick_list_api.warehouse_user_query(
			"User", "cs.sales", "name", 0, 50, {}))}

	check("DN assignee list in A leaves out B's DN User", lambda: _assert(U_PICK_B not in dn_users(U_A)))
	check("DN Assigned To search in A leaves out B's DN User", lambda: _assert(U_PICK_B not in dn_query(U_A)))
	check("PL Assigned To search in A leaves out B's PL User", lambda: _assert(U_PICK_B not in pl_query(U_A)))

	def pickers_in_b():
		set_active(U_AB, B)
		try:
			_assert(U_PICK_B in dn_users(U_AB), "dn list")
			_assert(U_PICK_B in dn_query(U_AB), "dn query")
			_assert(U_PICK_B in pl_query(U_AB), "pl query")
		finally:
			set_active(U_AB, A)

	check("Pickers after switching to B offer B's DN / PL user", pickers_in_b)
	def picker_for_document():
		set_active(U_AB, ALL)
		try:
			for_b = {r[0] for r in as_user(U_AB, lambda: workflow_role_access.dn_assigned_to_query(
				"User", "cs.sales", "name", 0, 50, {"company": B}))}
			for_a = {r[0] for r in as_user(U_AB, lambda: workflow_role_access.dn_assigned_to_query(
				"User", "cs.sales", "name", 0, 50, {"company": A}))}
		finally:
			set_active(U_AB, A)
		_assert(U_PICK_B in for_b and U_PICK_B not in for_a, f"B {sorted(for_b)} / A {sorted(for_a)}")

	check("All mode: DN picker follows the document's company (filters.company)", picker_for_document)
	check("Administrator's pickers unchanged", lambda: _assert(
		U_PICK_B in workflow_role_access.get_dn_assignable_users()
		and U_PICK_B in {r[0] for r in pick_list_api.warehouse_user_query("User", "cs.sales", "name", 0, 50, {})}))
