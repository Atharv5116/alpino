"""W7, Sales Order side (doc Section 6): Quotation-only switch, Sales Officer refusal, one active
order per Quotation, links kept, Billing GSTIN, catalogue Last Order Date. TEST sites only;
everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.so_handoff_test.run
"""

import frappe
from frappe.utils import add_days, flt, today

from alpinos.offline_sales import so_handoff as H

R = []
TAG = "SHT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()


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


def refused(fn):
	sp = "sht_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	finally:
		frappe.set_user("Administrator")
	return ""


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def run():
	R.clear()
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
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)} {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")


def _source():
	"""A recent submitted Offline order of an Approved buyer with a completed catalogue."""
	return frappe.db.sql(
		"""
		SELECT so.name FROM `tabSales Order` so
		JOIN `tabBuyer Master` bm ON bm.customer = so.customer
		WHERE so.docstatus = 1 AND IFNULL(so.custom_channel, '') IN ('', 'Offline')
			AND bm.buyer_status = 'Approved' AND bm.buyer_catalog_status = 'Completed'
			AND IFNULL(so.custom_billing_gstin, '') != ''
			AND NOT EXISTS (SELECT 1 FROM `tabSales Order Item` i WHERE i.parent = so.name AND (
				IFNULL(i.custom_customer_mrp, 0) = 0
				OR (EXISTS (SELECT 1 FROM `tabItem MRP` m WHERE m.parent = i.item_code)
					AND NOT EXISTS (SELECT 1 FROM `tabItem MRP` m WHERE m.parent = i.item_code AND m.active = 1
						AND ROUND(m.mrp, 2) = ROUND(i.custom_customer_mrp, 2)))))
			AND (IFNULL(so.custom_site_name, '') = '' OR EXISTS (SELECT 1 FROM `tabBuyer Address` ba
				WHERE ba.parent = bm.name AND ba.site_name = so.custom_site_name) OR bm.site_name = so.custom_site_name)
		ORDER BY so.creation DESC LIMIT 1
		""",
		pluck=True,
	)[0]


def _new_order(quotation=None, user="Administrator", insert=True):
	src = frappe.get_doc("Sales Order", F.src)
	so = frappe.copy_doc(src)
	so.transaction_date = today()
	so.delivery_date = add_days(today(), 7)
	if so.meta.has_field("custom_dispatch_date"):
		so.custom_dispatch_date = add_days(today(), 1)
	for row in so.items:
		row.delivery_date = so.delivery_date
	so.custom_workflow_status = "Draft"
	so.set("payment_schedule", [])
	so.payment_terms_template = None
	so.custom_quotation = quotation
	so.custom_opportunity = None
	if not insert:
		return so
	frappe.set_user(user)
	try:
		so.insert()
	finally:
		frappe.set_user("Administrator")
	return so


def _person(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	return user


def _run():
	F.src = _source()
	src = frappe.get_doc("Sales Order", F.src)
	F.customer = src.customer
	F.quotation = _insert("Quotation", name=f"{TAG}-Q1", quotation_to="Customer", party_name=src.customer, company=src.company,
		transaction_date=today(), docstatus=1, opportunity=None)
	F.quotation2 = _insert("Quotation", name=f"{TAG}-Q2", quotation_to="Customer", party_name=src.customer, company=src.company,
		transaction_date=today(), docstatus=1)
	F.officer = _person("so", "Sales Officer", "Employee")
	from alpinos.company_scope import sync

	sync.ensure_membership(F.officer, src.company, ["Sales Officer"], is_default=True)
	sync.sync_user(F.officer)
	emp = _insert("Employee", name=f"{TAG}-SO", employee_name=f"{TAG} so", first_name="so", status="Active",
		company=src.company, date_of_joining="2026-01-01", user_id=F.officer)
	_insert("Buyer Sales Officer", name=f"{TAG}-BSO", parenttype="Buyer Master", parentfield="sales_officers", idx=90,
		parent=frappe.db.get_value("Buyer Master", {"customer": src.customer}, "name"), employee=emp)
	frappe.clear_cache()
	frappe.db.set_single_value("Offline Sales Settings", "quotation_required_for_sales_order", 0)

	def _switch_off():
		so = _new_order()
		_assert(so.name and not so.custom_quotation, "a direct order was refused with the switch OFF")

	check("S6: switch OFF (deploy default): a direct Offline Sales Order is created as before", _switch_off)

	def _switch_on():
		frappe.db.set_single_value("Offline Sales Settings", "quotation_required_for_sales_order", 1)
		err = refused(lambda: _new_order())
		_assert(err == H.MSG_QUOTATION_ONLY, err)
		so = _new_order(F.quotation)
		_assert(so.custom_quotation == F.quotation, "a Quotation-sourced order was refused")
		F.first = so.name
		frappe.db.set_single_value("Offline Sales Settings", "quotation_required_for_sales_order", 0)

	check("S6: switch ON: an order without a Quotation is refused; from a Quotation it is created", _switch_on)

	def _officer():
		err = refused(lambda: _new_order(F.quotation2, user=F.officer))
		_assert(err == H.MSG_SO_CANNOT_CREATE, err)

	check("S6: a Sales Officer cannot create a Sales Order from a Quotation", _officer)

	def _one_active():
		err = refused(lambda: _new_order(F.quotation))
		_assert(err == H.MSG_DUPLICATE.format(F.first, F.quotation), err)
		frappe.db.set_value("Sales Order", F.first, "custom_workflow_status", "Cancelled")
		so = _new_order(F.quotation)
		_assert(so.name, "replacement refused after the first order was cancelled")
		F.second = so.name

	check("S6: one active Sales Order per Quotation; a cancelled one frees the Quotation", _one_active)

	def _opportunity_link():
		opp = frappe.db.get_value("Opportunity", {}, "name")
		if not opp:
			return
		frappe.db.set_value("Quotation", F.quotation2, "opportunity", opp)
		so = _new_order(F.quotation2)
		_assert(so.custom_opportunity == opp, so.custom_opportunity)

	check("S6: the order carries the Quotation's Opportunity (blank for a Standalone Quotation)", _opportunity_link)

	def _links_locked():
		so = frappe.get_doc("Sales Order", F.second)
		other = frappe.db.get_value("Customer", {"name": ("!=", so.customer)}, "name")
		so.customer = other
		err = refused(lambda: so.save())
		_assert("cannot be changed" in err, err)

	check("S6: an order from a Quotation keeps its Customer and links", _links_locked)

	def _gstin():
		frappe.db.savepoint("sht_gstin")
		try:
			_gstin_case()
		finally:
			frappe.db.rollback(save_point="sht_gstin")

	def _gstin_case():
		bm = frappe.db.get_value("Buyer Master", {"customer": F.customer}, ["name", "gst_type", "gst_no"], as_dict=True)
		frappe.db.set_value("Buyer Master", bm.name, "gst_type", "Registered Business")
		from alpinos.sales_order_offline_buyer import buyer_family_masters

		for m in buyer_family_masters(F.customer):
			frappe.db.set_value("Buyer Master", m.name, "gst_no", None)
		frappe.db.set_value("Sales Order", F.second, "custom_workflow_status", "Cancelled")
		so = _new_order(F.quotation, insert=False)
		so.custom_billing_gstin = None
		err = refused(lambda: so.insert())
		_assert(err.startswith("Billing GSTIN is missing on selected Billing Address"), err)

	check("S6: Registered Business buyer without a Billing GSTIN: the doc's message, the order is not created", _gstin)

	def _stamp():
		frappe.db.set_value("Sales Order", F.first, "custom_workflow_status", "Draft")
		so = frappe.get_doc("Sales Order", F.first)
		so.submit()
		rows = frappe.db.sql(
			"""SELECT bil.item_code, bil.last_order_date, bil.last_sales_order FROM `tabBuyer Item` bil
			JOIN `tabBuyer Items` bi ON bi.name = bil.parent WHERE bi.buyer = %s AND bil.last_sales_order = %s""",
			(so.customer, so.name), as_dict=True,
		)
		priced = {r.item_code for r in so.items if flt(r.custom_selling_price) > 0}
		_assert(priced and priced <= {r.item_code for r in rows}, f"{priced} vs {rows}")
		_assert(all(str(r.last_order_date) == str(so.transaction_date) for r in rows), rows)

	check("S6 8.3: on submission each synced catalogue row records Last Order Date and Linked Sales Order", _stamp)

	def _draft_no_sync():
		so = _new_order()
		touched = frappe.db.count("Buyer Item", {"last_sales_order": so.name})
		_assert(touched == 0, "a Draft order wrote to the catalogue")

	check("S6: a Draft order never changes the Buyer Catalog", _draft_no_sync)

	def _officer_direct():
		frappe.db.set_single_value("Offline Sales Settings", "quotation_required_for_sales_order", 0)
		so = _new_order(user=F.officer)
		_assert(so.name and so.docstatus == 0, "an assigned Sales Officer could not save a direct draft order")

	check("amendment: switch OFF, an assigned Sales Officer saves a direct draft order (reads its masters)", _officer_direct)
