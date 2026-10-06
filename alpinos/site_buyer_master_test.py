"""The Sales Order PDF resolves its site inside the order's OWN buyer family.

Run:  bench --site alpinos.test execute alpinos.site_buyer_master_test.run

Site names are not unique -- "Maharashtra", "NW08" and the like are reused by different
buyers. The print format's lookup searched the whole table with LIMIT 1 and no ordering, so
it could return a stranger's Buyer Master. That record drives the Phone, Email, GST Type,
GSTIN and PAN printed on the Sales Order, which is how an order for a buyer with a real
contact number came out showing "Phone: 0" and "dummy@dummy.com" from somebody else.

Fixtures are rolled back.
"""

import frappe

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
	from alpinos.utils import site_buyer_master

	tag = "SBM" + frappe.generate_hash(length=4).upper()
	site = f"{tag} Maharashtra"          # the SAME site name on two unrelated buyers

	def _buyer(suffix, business, phone, email):
		cust = _insert("Customer", name=f"{tag}-C{suffix}", customer_name=business,
			customer_type="Company", disabled=0)
		bm = _insert("Buyer Master", name=f"{tag}-OBM-{suffix}",
			customer_business_name=business, channel="Offline", customer=cust,
			contact_no=phone, email=email)
		_insert("Buyer Address", name=f"{tag}-ADDR-{suffix}", parent=bm,
			parenttype="Buyer Master", parentfield="addresses", idx=1, site_name=site,
			address_line="1 Road", city="Mumbai", state="Maharashtra", pincode="400099",
			country="India", is_primary=1)
		return bm

	# "Ours" is the buyer the order is for. "Stranger" is an unrelated buyer that happens
	# to use the same site name, and carries the placeholder contact data.
	ours = _buyer("A", f"{tag} Gain Maximum", "8652392841", "annyparab88@example.com")
	stranger = _buyer("B", f"{tag} Hyuga Ventures", "0", "dummy@dummy.com")

	def _the_orders_own_buyer_is_returned():
		got = site_buyer_master(site, ours)
		_assert(got is not None, "nothing resolved at all")
		_assert(got.name == ours,
			f"the site resolved to {got.name}, which is not the buyer the order is for")

	check("the site resolves to the buyer the order is actually for",
		_the_orders_own_buyer_is_returned)

	def _the_printed_contact_belongs_to_that_buyer():
		got = site_buyer_master(site, ours)
		_assert(got.contact_no == "8652392841",
			f"the PDF would print {got.contact_no!r}, not this buyer's number")
		_assert(got.email == "annyparab88@example.com",
			f"the PDF would print {got.email!r}, not this buyer's email")

	check("the phone and email printed belong to that buyer",
		_the_printed_contact_belongs_to_that_buyer)

	def _a_strangers_record_is_never_returned():
		got = site_buyer_master(site, ours)
		_assert(got.name != stranger,
			"a different buyer's record was returned; its GSTIN and PAN would print too")

	check("an unrelated buyer sharing the site name is never returned",
		_a_strangers_record_is_never_returned)

	def _it_works_from_the_other_side_too():
		"""The same site, asked for on the stranger's own order, gives the stranger."""
		got = site_buyer_master(site, stranger)
		_assert(got.name == stranger,
			f"asked for {stranger}, got {got.name}")

	check("the same site asked from the other buyer's order gives that buyer",
		_it_works_from_the_other_side_too)

	def _an_unknown_site_falls_back_to_the_orders_buyer():
		got = site_buyer_master(f"{tag} No Such Site", ours)
		_assert(got is not None and got.name == ours,
			"an unmatched site should fall back to the order's own Buyer Master")

	check("an unmatched site falls back to the order's own Buyer Master",
		_an_unknown_site_falls_back_to_the_orders_buyer)

	def _no_site_at_all_still_resolves():
		got = site_buyer_master("", ours)
		_assert(got is not None and got.name == ours,
			"an order with no site name should still resolve to its own buyer")
		_assert(site_buyer_master("", None) is None,
			"nothing to go on should resolve to nothing, not raise")

	check("an order with no site name still resolves to its own buyer",
		_no_site_at_all_still_resolves)

	def _a_site_only_a_stranger_owns_does_not_leak():
		"""The case that separates the two guards.

		Here the order's own buyer does NOT own the site -- only an unrelated buyer does.
		Preferring the order's master is no help, because it is not among the owners at all;
		only searching inside the family keeps the stranger out. An unscoped lookup would
		hand back their record, and with it their GSTIN and PAN.
		"""
		lonely_cust = _insert("Customer", name=f"{tag}-C-L", customer_name=f"{tag} Lonely",
			customer_type="Company", disabled=0)
		lonely = _insert("Buyer Master", name=f"{tag}-OBM-L",
			customer_business_name=f"{tag} Lonely", channel="Offline", customer=lonely_cust,
			contact_no="9999999999", email="lonely@example.com")
		# `lonely` has no address row for `site` -- only `ours` and `stranger` do.
		got = site_buyer_master(site, lonely)
		_assert(got is not None, "nothing resolved")
		_assert(got.name == lonely,
			f"the site resolved to {got.name}; an unrelated buyer's record would be printed "
			"on this order, including their GSTIN and PAN")

	check("a site only an unrelated buyer owns never leaks onto this order",
		_a_site_only_a_stranger_owns_does_not_leak)
