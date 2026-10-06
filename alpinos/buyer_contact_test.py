"""The Sales Order PDF takes the buyer's phone and email from the Buyer Master.

Run:  bench --site alpinos.test execute alpinos.buyer_contact_test.run

SOR-2627-04011 printed "0" and "dummy@dummy.com" for a buyer whose Buyer Master held a real
number and whose own contact fields were NULL -- neither source this app reads could produce
those values, so the live format had been edited to read somewhere else. Both cells are now
rewritten on migrate to one helper, so every site answers the same way and a later hand-edit
is undone on the next migrate.

Fixtures roll back.
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
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.utils import buyer_contact

	tag = "BCT" + frappe.generate_hash(length=4).upper()
	company = frappe.db.get_value("Warehouse", {"is_group": 0}, "company")
	customer = _insert("Customer", name=f"{tag}-CUST", customer_name=f"{tag} Co",
		customer_type="Company", disabled=0)
	site = f"{tag} Site"

	buyer = _insert("Buyer Master", name=f"{tag}-OBM", customer_business_name=f"{tag} Chain",
		channel="Offline", customer=customer, contact_no="8652392841",
		email="real.buyer@example.com")
	_insert("Buyer Address", name=f"{tag}-ADDR", parent=buyer, parenttype="Buyer Master",
		parentfield="addresses", idx=1, site_name=site, address_line="1 Road",
		city="Mumbai", state="Maharashtra", pincode="400099", country="India",
		is_primary=1, is_shipping=1, address_label="Main")

	def _order(suffix, **kw):
		return _insert("Sales Order", name=f"SOBCT-{tag}-{suffix}", docstatus=1,
			company=company, customer=customer, transaction_date=today(),
			custom_site_name=site, custom_offline_buyer_master=buyer, **kw)

	def _the_buyer_master_supplies_both():
		out = buyer_contact(frappe.get_doc("Sales Order", _order("A")))
		_assert(out["phone"] == "8652392841", f"phone came from elsewhere: {out}")
		_assert(out["email"] == "real.buyer@example.com", f"email came from elsewhere: {out}")
		_assert(out["source"] == buyer, f"the source is not the Buyer Master: {out['source']}")

	check("the buyer's phone and email come from the Buyer Master",
		_the_buyer_master_supplies_both)

	def _the_order_fields_do_not_win_over_the_master():
		"""The order carrying its own contact must not override a Buyer Master that has one."""
		so = _order("B", contact_mobile="0", contact_email="dummy@dummy.com")
		out = buyer_contact(frappe.get_doc("Sales Order", so))
		_assert(out["phone"] == "8652392841",
			f"the order's placeholder beat the Buyer Master: {out['phone']}")
		_assert(out["email"] == "real.buyer@example.com",
			f"the order's placeholder beat the Buyer Master: {out['email']}")

	check("a placeholder on the order never beats a real Buyer Master value",
		_the_order_fields_do_not_win_over_the_master)

	def _the_order_is_the_fallback_when_the_master_is_blank():
		blank = _insert("Buyer Master", name=f"{tag}-OBM2",
			customer_business_name=f"{tag} Blank", channel="Offline", customer=customer)
		so = _insert("Sales Order", name=f"SOBCT-{tag}-C", docstatus=1, company=company,
			customer=customer, transaction_date=today(), custom_offline_buyer_master=blank,
			contact_mobile="9999900000", contact_email="fallback@example.com")
		out = buyer_contact(frappe.get_doc("Sales Order", so))
		_assert(out["phone"] == "9999900000", f"the fallback did not apply: {out}")
		_assert(out["email"] == "fallback@example.com", f"the fallback did not apply: {out}")

	check("the order's own contact is the fallback when the master has none",
		_the_order_is_the_fallback_when_the_master_is_blank)

	def _nothing_anywhere_gives_a_dash():
		so = _insert("Sales Order", name=f"SOBCT-{tag}-D", docstatus=1, company=company,
			customer=customer, transaction_date=today())
		out = buyer_contact(frappe.get_doc("Sales Order", so))
		_assert(out["phone"] == "—" and out["email"] == "—",
			f"expected an em-dash on both: {out}")

	check("with nothing on file both read as an em-dash", _nothing_anywhere_gives_a_dash)

	def _it_never_raises():
		"""A print must not fail over a contact lookup."""
		for bad in (frappe._dict(), frappe._dict(custom_site_name="nope",
				custom_offline_buyer_master="NOT-A-BUYER")):
			out = buyer_contact(bad)
			_assert("phone" in out and "email" in out, f"returned nothing usable: {out}")

	check("a missing or broken buyer never raises out of the helper", _it_never_raises)

	def _the_format_calls_the_helper_for_the_buyer_cells_only():
		html = frappe.db.get_value("Print Format", "Sales Order", "html") or ""
		_assert("buyer_contact(doc).phone" in html, "the Phone cell does not call the helper")
		_assert("buyer_contact(doc).email" in html, "the Email cell does not call the helper")
		# The company's own phone/email in the header must be untouched.
		_assert("company.phone_no" in html,
			"the company's phone in the header was rewritten; only the buyer's cells should move")
		_assert("company.email" in html,
			"the company's email in the header was rewritten")

	check("the format calls the helper for the buyer cells and leaves the company header alone",
		_the_format_calls_the_helper_for_the_buyer_cells_only)

	def _the_rewrite_is_idempotent():
		from alpinos.sales_order_print_format_patch import _rewrite_buyer_contact

		before = frappe.db.get_value("Print Format", "Sales Order", "html") or ""
		_rewrite_buyer_contact()
		after = frappe.db.get_value("Print Format", "Sales Order", "html") or ""
		_assert(before == after, "running the patch again changed the format")
		_assert(after.count("buyer_contact(doc).phone") == 1,
			f"the helper call was duplicated: {after.count('buyer_contact(doc).phone')}")

	check("running the migrate patch again changes nothing", _the_rewrite_is_idempotent)
