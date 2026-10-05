"""Changes(HP) #59: Pick Lists and Delivery Notes in bulk.

Run:  bench --site alpinos.test execute alpinos.bulk_dispatch_test.run

The orders are cloned from a real submitted Sales Order of the site, the way
dn_so_total_test does it, so the Pick List mapping has genuine items, warehouses and
conversion factors to work with rather than a hand-built skeleton that maps to nothing.

What matters most here is that one bad record does not take the batch down with it, and
that a bulk run produces the same Pick List the entry page would. Fixtures roll back.
"""

import frappe
from frappe.utils import today

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _template_so():
	rows = frappe.db.sql(
		"""
		SELECT so.name
		FROM `tabSales Order` so
		WHERE so.docstatus = 1
			AND EXISTS (SELECT 1 FROM `tabSales Order Item` i WHERE i.parent = so.name AND i.qty > 0)
		ORDER BY so.creation DESC LIMIT 1
		"""
	)
	return rows[0][0] if rows else None


def _clone_so(template, name):
	"""A fresh submitted Sales Order carrying the template's first line."""
	src = frappe.get_doc("Sales Order", template)
	data = src.as_dict()
	for key in ("name", "creation", "modified", "owner", "modified_by", "amended_from", "naming_series"):
		data.pop(key, None)
	for key in ("items", "taxes", "packed_items"):
		data.pop(key, None)
	doc = frappe.get_doc(dict(data, doctype="Sales Order"))
	doc.name = name
	doc.docstatus = 1
	doc.status = "To Deliver and Bill"
	doc.per_delivered = 0
	doc.transaction_date = today()
	doc.delivery_date = today()
	# The template may itself be force closed or part-dispatched; the clone starts clean.
	doc.custom_force_closed = 0
	doc.custom_force_close_reason = None
	doc.custom_workflow_status = None
	doc.db_insert()

	item_data = src.items[0].as_dict()
	for key in ("name", "creation", "modified", "owner", "modified_by"):
		item_data.pop(key, None)
	item = frappe.get_doc(dict(item_data, doctype="Sales Order Item"))
	item.name = f"{name}-I1"
	item.parent = name
	item.parenttype = "Sales Order"
	item.parentfield = "items"
	item.idx = 1
	item.docstatus = 1
	item.qty = item.stock_qty = 5
	item.conversion_factor = 1
	item.delivered_qty = 0
	item.returned_qty = 0
	item.billed_amt = 0
	item.db_insert()
	return name


def _run():
	from alpinos import bulk_dispatch as B

	template = _template_so()
	if not template:
		RES.append(("ERROR", "fixtures", "no submitted Sales Order on this site to clone"))
		return

	tag = "BLK" + frappe.generate_hash(length=4).upper()
	so_a = _clone_so(template, f"SOBLK-{tag}-A")
	so_b = _clone_so(template, f"SOBLK-{tag}-B")

	def _a_non_warehouse_user_is_refused():
		user = f"{tag.lower()}.nobody@example.com"
		doc = frappe.get_doc({"doctype": "User", "email": user, "first_name": "No",
			"user_type": "System User", "enabled": 1})
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_validate = True
		doc.db_insert()
		frappe.set_user(user)
		try:
			B.bulk_create_pick_lists([so_a])
		except frappe.PermissionError:
			return
		finally:
			frappe.set_user("Administrator")
		raise AssertionError("a user with no warehouse role ran a bulk create")

	check("#59 only Warehouse Admin / Manager may run a bulk action",
		_a_non_warehouse_user_is_refused)

	def _two_orders_become_two_draft_pick_lists():
		out = B.bulk_create_pick_lists([so_a, so_b])
		_assert(out["counts"]["done"] == 2, f"created {out['counts']}: {out}")
		for row in out["done"]:
			pl = row["pick_list"]
			_assert(frappe.db.get_value("Pick List", pl, "docstatus") == 0,
				f"{pl} is not a draft")
			_assert(frappe.db.get_value("Pick List", pl, "custom_sales_order_id") == row["name"],
				f"{pl} is not linked to its order")
			_assert(frappe.db.count("Pick List Item", {"parent": pl}) > 0,
				f"{pl} has no lines; the mapping produced nothing")

	check("#59 a bulk run creates one Draft Pick List per order, with its lines",
		_two_orders_become_two_draft_pick_lists)

	def _an_order_that_already_has_one_is_skipped_not_duplicated():
		out = B.bulk_create_pick_lists([so_a])
		_assert(out["counts"]["done"] == 0 and out["counts"]["skipped"] == 1,
			f"a second run duplicated the Pick List: {out['counts']}")
		_assert("already exists" in out["skipped"][0]["reason"], out["skipped"][0])

	check("#59 an order that already has a Pick List is skipped, never duplicated",
		_an_order_that_already_has_one_is_skipped_not_duplicated)

	def _a_bad_record_does_not_stop_the_batch():
		so_c = _clone_so(template, f"SOBLK-{tag}-C")
		out = B.bulk_create_pick_lists(["SOBLK-DOES-NOT-EXIST", so_c])
		_assert(out["counts"]["done"] == 1,
			f"the good order did not go through alongside the bad one: {out['counts']}")
		_assert(out["counts"]["skipped"] == 1, out)
		_assert(out["done"][0]["name"] == so_c, out["done"])

	check("#59 one unusable record does not stop the rest of the batch",
		_a_bad_record_does_not_stop_the_batch)

	def _an_unsubmitted_order_is_skipped():
		draft = _clone_so(template, f"SOBLK-{tag}-D")
		frappe.db.set_value("Sales Order", draft, "docstatus", 0, update_modified=False)
		out = B.bulk_create_pick_lists([draft])
		_assert(out["counts"]["skipped"] == 1, out)
		_assert("not submitted" in out["skipped"][0]["reason"], out["skipped"][0])

	check("#59 a draft Sales Order is skipped with a reason", _an_unsubmitted_order_is_skipped)

	def _a_pick_list_that_is_not_ready_is_reported_not_crashed():
		"""PO No. is typed on the Pick List, so a bulk create cannot supply it."""
		pl = frappe.db.get_value("Pick List", {"custom_sales_order_id": so_b, "docstatus": 0}, "name")
		_assert(pl, "no draft Pick List for this check")
		out = B.bulk_submit_pick_lists([pl])
		_assert(out["counts"]["failed"] == 0,
			f"a missing mandatory field was reported as a failure: {out['failed']}")
		_assert(out["counts"]["skipped"] == 1, out["counts"])
		_assert("PO No" in out["skipped"][0]["reason"],
			f"the skip does not say why: {out['skipped'][0]}")

	check("#59 a Pick List that is not ready is skipped with the rule's own words",
		_a_pick_list_that_is_not_ready_is_reported_not_crashed)

	def _bulk_submit_moves_drafts_to_submitted():
		pl = frappe.db.get_value("Pick List", {"custom_sales_order_id": so_b, "docstatus": 0}, "name")
		_assert(pl, "no draft Pick List to submit")
		# Fill what a picker fills on the form before submitting.
		frappe.db.set_value("Pick List", pl, "custom_po_no", f"PO-{tag}", update_modified=False)
		out = B.bulk_submit_pick_lists([pl])
		if out["counts"]["failed"]:
			raise AssertionError(f"submit failed: {out['failed']}")
		_assert(out["counts"]["done"] == 1, out["counts"])
		_assert(frappe.db.get_value("Pick List", pl, "docstatus") == 1, f"{pl} is still a draft")

	check("#59 bulk submit moves a Draft Pick List to Submitted",
		_bulk_submit_moves_drafts_to_submitted)

	def _submitting_an_already_submitted_one_is_skipped():
		pl = frappe.db.get_value("Pick List", {"custom_sales_order_id": so_b, "docstatus": 1}, "name")
		_assert(pl, "no submitted Pick List to re-submit")
		out = B.bulk_submit_pick_lists([pl])
		_assert(out["counts"]["skipped"] == 1, out)
		_assert("already submitted" in out["skipped"][0]["reason"], out["skipped"][0])

	check("#59 an already-submitted Pick List is skipped, not re-submitted",
		_submitting_an_already_submitted_one_is_skipped)

	def _a_submitted_pick_list_becomes_a_draft_delivery_note():
		pl = frappe.db.get_value("Pick List", {"custom_sales_order_id": so_b, "docstatus": 1}, "name")
		_assert(pl, "no submitted Pick List to turn into a Delivery Note")
		out = B.bulk_create_delivery_notes([pl])
		if out["counts"]["failed"]:
			raise AssertionError(f"delivery note creation failed: {out['failed']}")
		_assert(out["counts"]["done"] == 1, out["counts"])
		dn = out["done"][0]["delivery_note"]
		_assert(frappe.db.get_value("Delivery Note", dn, "docstatus") == 0,
			f"{dn} is not a draft; #59 asks for Draft Delivery Notes")

		# And a second run must find it rather than make another.
		again = B.bulk_create_delivery_notes([pl])
		_assert(again["counts"]["skipped"] == 1,
			f"a second run created another Delivery Note: {again['counts']}")

	check("#59 a submitted Pick List becomes one Draft Delivery Note, never two",
		_a_submitted_pick_list_becomes_a_draft_delivery_note)

	def _a_draft_pick_list_cannot_make_a_delivery_note():
		pl = frappe.db.get_value("Pick List", {"custom_sales_order_id": so_a, "docstatus": 0}, "name")
		_assert(pl, "no draft Pick List for this check")
		out = B.bulk_create_delivery_notes([pl])
		_assert(out["counts"]["skipped"] == 1, out)
		_assert("not submitted" in out["skipped"][0]["reason"], out["skipped"][0])

	check("#59 a Draft Pick List is skipped for Delivery Note creation",
		_a_draft_pick_list_cannot_make_a_delivery_note)

	def _the_preview_reports_before_anything_runs():
		out = B.bulk_action_preview(sales_orders=[so_a])
		row = out["pick_lists_to_create"][0]
		_assert(row["existing_pick_list"], f"the preview missed the existing Pick List: {row}")
		_assert(row["eligible"] is False, f"the preview calls a done order eligible: {row}")

	check("#59 the preview reports what a run would do, without running it",
		_the_preview_reports_before_anything_runs)
