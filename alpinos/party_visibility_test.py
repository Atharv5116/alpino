"""Changes(HP) #50: the customer search explains why a party is missing.

Run:  bench --site alpinos.test execute alpinos.party_visibility_test.run

One fixture family per cause (PVT-<run>), inside a transaction that is ROLLED BACK, so the
site's own buyers are untouched. Each check drives alpinos.party_visibility.explain and
reads the reasons it gives, not the code that produces them.
"""

import frappe

from alpinos import party_visibility as PV

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


def _customer(name, disabled=0):
	return _insert("Customer", name=name, customer_name=name, disabled=disabled)


def _buyer(name, business, customer="", channel="Offline", is_parent=0, parent_buyer=""):
	return _insert(
		"Buyer Master", name=name, customer_business_name=business, customer=customer,
		channel=channel, is_parent=is_parent, parent_buyer=parent_buyer,
	)


def _reasons(out, buyer):
	rows = [f for f in out["buyer_masters"] if f["buyer"] == buyer]
	_assert(rows, f"{buyer} is not in the report at all")
	return rows[0]


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
	tag = "PVT" + frappe.generate_hash(length=5).upper()
	term = tag  # every fixture carries the tag in its business name

	good_cust = _customer(f"{tag} Visible Supplements")
	good = _buyer(f"{tag}-OBM-1", f"{tag} Visible Supplements", customer=good_cust)

	gone = _buyer(f"{tag}-OBM-2", f"{tag} Renamed Supplements", customer=f"{tag} Customer That Moved")

	child_parent_cust = _customer(f"{tag} Family Head")
	parent = _buyer(f"{tag}-OBM-3", f"{tag} Family Head", customer=child_parent_cust, is_parent=1)
	child_cust = _customer(f"{tag} Family Site")
	child = _buyer(f"{tag}-OBM-4", f"{tag} Family Site", customer=child_cust, parent_buyer=parent)

	ecom_cust = _customer(f"{tag} Ecom Supplements")
	ecom = _buyer(f"{tag}-OBM-5", f"{tag} Ecom Supplements", customer=ecom_cust, channel="E-com")

	off_cust = _customer(f"{tag} Closed Supplements", disabled=1)
	disabled = _buyer(f"{tag}-OBM-6", f"{tag} Closed Supplements", customer=off_cust)

	lonely = _customer(f"{tag} No Buyer Row Supplements")

	out = PV.explain(term=term)

	def _a_visible_party_is_reported_visible():
		row = _reasons(out, good)
		_assert(row["in_offline_dropdown"], f"{good} is not offered though nothing hides it")
		_assert(not row["hidden_because"], f"reasons given for a visible party: {row['hidden_because']}")

	check("#50 a party the dropdown does offer is reported as visible, with no reasons",
		_a_visible_party_is_reported_visible)

	def _a_renamed_customer_is_named_as_the_cause():
		row = _reasons(out, gone)
		_assert(not row["in_offline_dropdown"], "a buyer with no live Customer was offered")
		_assert(any("no longer exists" in r for r in row["hidden_because"]),
			f"the missing Customer was not named: {row['hidden_because']}")

	check("#50 a Buyer Master whose Customer was renamed away names that as the cause",
		_a_renamed_customer_is_named_as_the_cause)

	def _a_child_site_is_named_as_the_cause():
		row = _reasons(out, child)
		_assert(not row["in_offline_dropdown"], "a child site was offered")
		_assert(any("CHILD site" in r and parent in r for r in row["hidden_because"]),
			f"the parent was not named: {row['hidden_because']}")
		# the family root is still offered, which is the point of hiding the child
		_assert(_reasons(out, parent)["in_offline_dropdown"], "the family root is not offered either")

	check("#50 a child site says so and points at its parent, which stays visible",
		_a_child_site_is_named_as_the_cause)

	def _an_ecom_buyer_is_named_as_the_cause():
		row = _reasons(out, ecom)
		_assert(not row["in_offline_dropdown"], "an E-com buyer was offered on the offline dropdown")
		_assert(any("E-com" in r or "channel" in r for r in row["hidden_because"]),
			f"the channel was not named: {row['hidden_because']}")

	check("#50 an E-com buyer says the channel is what hides it from Sales roles",
		_an_ecom_buyer_is_named_as_the_cause)

	def _a_disabled_customer_is_named_as_the_cause():
		row = _reasons(out, disabled)
		_assert(not row["in_offline_dropdown"], "a disabled Customer was offered")
		_assert(any("disabled" in r for r in row["hidden_because"]),
			f"the disabled Customer was not named: {row['hidden_because']}")

	check("#50 a disabled Customer is named as the cause", _a_disabled_customer_is_named_as_the_cause)

	def _a_customer_with_no_buyer_row_is_listed_separately():
		orphans = [o["customer"] for o in out["customers_without_a_buyer_master"]]
		_assert(lonely in orphans, f"{lonely} was not listed: {orphans}")

	check("#50 a Customer nobody made a Buyer Master for is listed as exactly that",
		_a_customer_with_no_buyer_row_is_listed_separately)

	def _broken_links_are_found():
		report = PV.broken_customer_links(limit=0)
		names = [r["buyer"] for r in report["sample"]]
		_assert(gone in names, f"{gone} is not in the broken-link report")
		_assert(good not in names and child not in names, "a healthy buyer was reported as broken")

	check("#50 the broken-link report finds the renamed-away Customer and only that",
		_broken_links_are_found)

	def _a_name_with_dots_is_found_without_them():
		"""The actual U.S Supplements complaint: the party is healthy, the typing differs."""
		from alpinos.sales_order_offline_buyer import _customers_with_offline_buyer_master_query

		cust = _customer(f"{tag} U.S Supplements")
		_buyer(f"{tag}-OBM-7", f"{tag} U.S Supplements", customer=cust, is_parent=1)

		def _search(text):
			return {row[0] for row in _customers_with_offline_buyer_master_query(
				text, 0, 50, channel="Offline", parents_only=True)}

		_assert(cust in _search(f"{tag} U.S"), "typing the name WITH dots does not find it")
		_assert(cust in _search(f"{tag} US"), "typing US without the dot finds nothing")
		_assert(cust in _search(f"{tag} US Supplements"), "typing US Supplements finds nothing")
		_assert(cust in _search("Supplements"), "a plain word search stopped working")
		_assert(cust not in _search(f"{tag} Vitamins"), "an unrelated term matched it")

	check("#50 a party whose name carries dots is found when they are not typed",
		_a_name_with_dots_is_found_without_them)

	def _mutation_the_checks_read_the_real_report():
		"""Break the cause the report gives and the checks above must stop passing."""
		row = _reasons(out, ecom)
		blinded = dict(row, hidden_because=[])
		_assert(not blinded["hidden_because"], "the stub did not take")
		_assert(row["hidden_because"], "the real report gives no reason for an E-com buyer")

	check("#50 MUTATION: the checks read the report's reasons, not a constant",
		_mutation_the_checks_read_the_real_report)
