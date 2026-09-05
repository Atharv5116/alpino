"""Regression tests for changing the party on a Sales Order (run on a TEST site).

Run:  cd ~/frappe-bench/sites && ~/frappe-bench/env/bin/python -c \
        "import frappe; frappe.init(site='alpinos.test'); frappe.connect(); \
         from alpinos import sales_order_party_test as t; t.run()"

The case these pin down: apply_site_addresses drops an address the Site never offered and
re-resolves it, but it only ran for a NEW order. Changing the customer on an existing one
therefore left the PREVIOUS customer's billing address on the document, where it would
print on the invoice.
"""

import frappe
from frappe.utils import add_days, today

R = []


def _check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)[:110]))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:100]}"))


def _address_owner(address):
	rows = frappe.db.sql(
		"""select link_name from `tabDynamic Link`
		   where parenttype='Address' and link_doctype='Customer' and parent=%s""",
		(address,),
	)
	return rows[0][0] if rows else None


def _order_and_other_customer():
	"""A draft order with a resolved billing address, plus a different customer that
	actually has one of its own (so a correct re-resolve is possible)."""
	so = frappe.db.get_value(
		"Sales Order", {"docstatus": 0, "customer_address": ("is", "set")}, "name"
	)
	if not so:
		return None, None
	current = frappe.db.get_value("Sales Order", so, "customer")
	rows = frappe.db.sql(
		"""select link_name from `tabDynamic Link`
		   where parenttype='Address' and link_doctype='Customer' and link_name != %s
		   group by link_name limit 1""",
		(current,),
	)
	return so, (rows[0][0] if rows else None)


def run():
	R.clear()
	frappe.set_user("Administrator")

	so, other = _order_and_other_customer()
	if not so or not other:
		print("SKIPPED: no draft Sales Order with an address, or no second addressed customer")
		return R

	def _load():
		doc = frappe.get_doc("Sales Order", so)
		if not doc.get("custom_dispatch_date"):
			doc.custom_dispatch_date = add_days(today(), 2)
		doc.flags.ignore_permissions = True
		return doc

	state = {}

	def changing_customer_reresolves_the_address():
		doc = _load()
		state["old_customer"] = doc.customer
		state["old_address"] = doc.customer_address
		doc.customer = other
		doc.save()
		doc.reload()
		assert doc.customer_address != state["old_address"], (
			"the previous customer's billing address survived the switch"
		)
		owner = _address_owner(doc.customer_address)
		assert owner == other, (
			f"billing address belongs to {owner!r}, not the new customer {other!r}"
		)

	def address_is_stable_on_an_unrelated_save():
		"""The re-resolve must be triggered by the party changing, not by every save."""
		doc = frappe.get_doc("Sales Order", so)
		before = doc.customer_address
		doc.po_no = "PARTYTEST-" + frappe.generate_hash(length=4)
		doc.flags.ignore_permissions = True
		doc.save()
		doc.reload()
		assert doc.customer_address == before, (
			f"an unrelated edit churned the address: {before!r} -> {doc.customer_address!r}"
		)

	def helper_is_quiet_for_a_new_doc():
		from alpinos.sales_order_offline_buyer import _party_or_site_changed

		fresh = frappe.new_doc("Sales Order")
		assert not _party_or_site_changed(fresh), (
			"_party_or_site_changed must be False on a new doc, which has no baseline"
		)

	_check("changing the customer re-resolves the billing address", changing_customer_reresolves_the_address)
	_check("an unrelated save does not churn the address", address_is_stable_on_an_unrelated_save)
	_check("the change-detector is quiet for a new document", helper_is_quiet_for_a_new_doc)

	frappe.db.rollback()

	width = max(len(r[1]) for r in R)
	print("=" * (width + 12))
	print("Sales Order — changing the party")
	print("=" * (width + 12))
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 12))
	print(f"{passed}/{len(R)} passed")
	return R
