"""Sections 12 and 13: cancel a Draft Sales Order, and duplicate one.

Run:  bench --site alpinos.test execute alpinos.sales_order_actions_test.run

From "Buyer Master & Sales Order - Required Changes" (03-10-2026). The two things the
document is firm about are that the cancellation is captured in the trail with its previous
and new status, and that duplicating leaves the original untouched. Fixtures roll back.
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


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


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
		frappe.clear_cache()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import buyer_assignment as BA
	from alpinos import sales_order_actions as X

	tag = "SAC" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company")
	item = frappe.db.get_value("Item", {"disabled": 0}, "name")
	customer = _insert("Customer", name=f"{tag}-CUST", customer_name=f"{tag} Customer",
		customer_type="Company", disabled=0)
	wh = frappe.db.get_value("Warehouse", {"is_group": 0}, ["name", "company"], as_dict=True)
	warehouse = wh.name if wh else None
	if wh:
		company = wh.company      # the site default did not match any warehouse
	_assert(customer and item and warehouse,
		"this site has no customer, item or warehouse to build an order from")

	user = f"{tag.lower()}.officer@example.com"
	_insert("User", name=user, email=user, first_name="Officer",
		user_type="System User", enabled=1)
	_insert("Has Role", name=f"{tag}-HR", parent=user, parenttype="User",
		parentfield="roles", role=BA.SALES_OFFICER_ROLE)
	officer = _insert("Employee", name=f"{tag}-EMP", employee_name=f"{tag} Officer",
		status="Active", company=company, date_of_joining="2026-01-01", user_id=user)

	outsider = f"{tag.lower()}.outsider@example.com"
	_insert("User", name=outsider, email=outsider, first_name="Out",
		user_type="System User", enabled=1)
	_insert("Has Role", name=f"{tag}-HR2", parent=outsider, parenttype="User",
		parentfield="roles", role=BA.SALES_OFFICER_ROLE)
	_insert("Employee", name=f"{tag}-EMP2", employee_name=f"{tag} Out", status="Active",
		company=company, date_of_joining="2026-01-01", user_id=outsider)

	buyer = _insert("Buyer Master", name=f"{tag}-OBM", customer_business_name=f"{tag} Party",
		channel="Offline", customer=customer, gst_type="Unregistered Business")
	_insert("Buyer Sales Officer", name=f"{tag}-BSO", parent=buyer, parenttype="Buyer Master",
		parentfield="sales_officers", employee=officer, idx=1)
	# Every Sales Order must name a Site that is mapped on the Buyer Master.
	site = f"{tag} Site"
	_insert("Buyer Address", name=f"{tag}-ADDR", parent=buyer, parenttype="Buyer Master",
		parentfield="addresses", idx=1, site_name=site, address_line="1 Test Road",
		city="Ahmedabad", state="Gujarat", pincode="380001", country="India",
		is_primary=1, is_shipping=1, address_label="Main")

	def _draft(suffix, docstatus=0):
		doc = frappe.get_doc({
			"doctype": "Sales Order", "company": company, "customer": customer,
			"transaction_date": today(), "delivery_date": today(),
			"custom_offline_buyer_master": buyer, "custom_workflow_status": "Draft",
			"set_warehouse": warehouse,
			# The app refuses a Registered Business order with no billing GSTIN.
			"custom_billing_gstin": "24AAACC1206D1ZM",
			"custom_shipping_gstin": "24AAACC1206D1ZM",
			# Every order must name its Site; the parent buyer is not a fallback.
			"custom_site_name": site,
			"order_type": frappe.db.get_value("Alpino Customer Type", {}, "name") or "Sales",
			"custom_dispatch_date": today(),
			"items": [{"item_code": item, "qty": 5, "rate": 10, "delivery_date": today(),
			           "conversion_factor": 1, "warehouse": warehouse}],
		})
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_validate = True
		doc.flags.ignore_permissions = True
		doc.name = f"SAC-{tag}-{suffix}"
		doc.insert(ignore_permissions=True)
		if docstatus:
			frappe.db.set_value("Sales Order", doc.name, "docstatus", docstatus, update_modified=False)
		return doc.name

	draft = _draft("D1")

	def _the_assigned_officer_may_cancel_a_draft():
		frappe.set_user(user)
		try:
			out = X.cancel_draft_sales_order(draft, reason="Buyer withdrew the order")
		finally:
			frappe.set_user("Administrator")
		_assert(out["new_status"] == "Cancelled", out)
		_assert(out["previous_status"] == "Draft", out)
		_assert(frappe.db.get_value("Sales Order", draft, "custom_workflow_status") == "Cancelled",
			"the order was not actually cancelled")

	check("§12 an assigned Sales Officer may cancel a Draft",
		_the_assigned_officer_may_cancel_a_draft)

	def _the_trail_records_everything_the_document_lists():
		row = frappe.db.get_value(
			"Field Change Log",
			{"reference_name": draft, "action": "Cancelled"},
			["reference_name", "previous_value", "new_value", "changed_by", "user_role",
			 "reason", "changed_on"], as_dict=True,
		)
		_assert(row, "the cancellation left no trail entry")
		_assert(row.previous_value == "Draft" and row.new_value == "Cancelled",
			f"the trail does not carry both statuses: {row}")
		_assert(row.changed_by == user, f"wrong user recorded: {row.changed_by}")
		_assert(row.user_role == BA.SALES_OFFICER_ROLE,
			f"the role was not recorded: {row.user_role!r}")
		_assert("withdrew" in (row.reason or ""), f"the reason was not kept: {row.reason!r}")
		_assert(row.changed_on, "no timestamp")

	check("§12 the trail records SO, who, role, time, previous and new status, and reason",
		_the_trail_records_everything_the_document_lists)

	def _an_unassigned_officer_is_refused():
		other = _draft("D2")
		frappe.set_user(outsider)
		try:
			X.cancel_draft_sales_order(other, reason="not mine")
		except frappe.PermissionError:
			return
		finally:
			frappe.set_user("Administrator")
		raise AssertionError("an officer assigned to another Buyer cancelled this order")

	check("§12 an officer not assigned to the Buyer is refused",
		_an_unassigned_officer_is_refused)

	def _a_submitted_order_cannot_be_cancelled_this_way():
		submitted = _draft("S1", docstatus=1)
		try:
			X.cancel_draft_sales_order(submitted, reason="too late")
		except frappe.ValidationError:
			return
		raise AssertionError("a submitted order was cancelled through the draft path")

	check("§12 a submitted order is not cancellable through the Draft path",
		_a_submitted_order_cannot_be_cancelled_this_way)

	def _duplicating_produces_a_new_draft():
		src = _draft("D3")
		out = X.duplicate_sales_order(src)
		new = out["sales_order"]
		_assert(new != src, "the duplicate is the same record")
		_assert(frappe.db.get_value("Sales Order", new, "docstatus") == 0,
			"the duplicate is not a Draft")
		_assert(frappe.db.get_value("Sales Order", new, "custom_workflow_status") == "Draft",
			"the duplicate did not start at Draft")
		_assert(frappe.db.count("Sales Order Item", {"parent": new}) ==
			frappe.db.count("Sales Order Item", {"parent": src}),
			"the duplicate did not carry the lines")

	check("§13 duplicating produces a new Draft carrying the lines",
		_duplicating_produces_a_new_draft)

	def _the_original_is_untouched_by_duplication():
		src = _draft("D4")
		before = frappe.db.get_value(
			"Sales Order", src,
			["docstatus", "custom_workflow_status", "transaction_date"], as_dict=True)
		X.duplicate_sales_order(src)
		after = frappe.db.get_value(
			"Sales Order", src,
			["docstatus", "custom_workflow_status", "transaction_date"], as_dict=True)
		_assert(dict(before) == dict(after), f"the original changed: {before} -> {after}")

	check("§13 the original is left exactly as it was", _the_original_is_untouched_by_duplication)

	def _a_submitted_order_may_be_duplicated():
		src = _draft("S2", docstatus=1)
		out = X.duplicate_sales_order(src)
		_assert(frappe.db.get_value("Sales Order", out["sales_order"], "docstatus") == 0,
			"duplicating a submitted order did not produce a Draft")

	check("§13 a submitted order may be duplicated into a Draft",
		_a_submitted_order_may_be_duplicated)

	def _the_copy_does_not_inherit_the_originals_invoice():
		src = _draft("D5")
		frappe.db.set_value("Sales Order", src, "custom_invoice_no", "INV-ORIGINAL",
			update_modified=False)
		out = X.duplicate_sales_order(src)
		_assert(not frappe.db.get_value("Sales Order", out["sales_order"], "custom_invoice_no"),
			"the duplicate inherited the original's invoice number")

	check("§13 the copy does not inherit the original's invoice number",
		_the_copy_does_not_inherit_the_originals_invoice)
