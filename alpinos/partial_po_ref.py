"""Changes(HP) #125: the Sales Order reference of each part of a Partial PO order.

When Partial PO is allowed (the order's own flag, set from the Buyer Master when it is made, else
the Buyer Master's) and the order has more than one submitted Pick List, the Accounts Format
Report shows each Pick List as its own part:

    1st Pick List  SOR-2627-05995
    2nd Pick List  SOR-2627-05995/2
    3rd Pick List  SOR-2627-05995/3 ...

The parts are numbered in the order the Pick Lists were made, so a part keeps its number once it
has been exported. The Invoice Mapping upload reads the same references back (parse) to find the
Pick List of each invoice. Only these references change: the Sales Order keeps its own name and
everything else about it.
"""

import re

import frappe
from frappe.utils import cint

_REF = re.compile(r"^(?P<so>.+?)/(?P<n>[0-9]+)$")


def parse(reference):
	"""("SOR-2627-05995", 2) for "SOR-2627-05995/2"; (reference, 1) for a plain one."""
	reference = (reference or "").strip()
	m = _REF.match(reference)
	if m and cint(m.group("n")) >= 2:
		return m.group("so").strip(), cint(m.group("n"))
	return reference, 1


def reference(so_name, n):
	return so_name if cint(n) <= 1 else f"{so_name}/{cint(n)}"


def partial_po_allowed(so_name):
	row = frappe.db.get_value(
		"Sales Order", so_name, ["custom_partial_order_allowed", "custom_offline_buyer_master"], as_dict=True
	) if frappe.db.has_column("Sales Order", "custom_partial_order_allowed") else None
	if not row:
		return False
	if cint(row.custom_partial_order_allowed):
		return True
	buyer = row.get("custom_offline_buyer_master")
	return bool(buyer and cint(frappe.db.get_value("Buyer Master", buyer, "partial_order_allowed")))


def pick_lists(so_name):
	"""The order's submitted Pick Lists in the order they were made (part 1, 2, 3 ...)."""
	return frappe.get_all(
		"Pick List",
		filters={"custom_sales_order_id": so_name, "docstatus": 1},
		fields=["name", "custom_dispatch_date", "custom_invoice_no"],
		order_by="creation asc, name asc",
	)


def part_numbers(so_name):
	"""{pick list: part number} when the order is reported in numbered parts, else {}."""
	parts = pick_lists(so_name)
	if len(parts) < 2 or not partial_po_allowed(so_name):
		return {}
	return {p.name: i for i, p in enumerate(parts, 1)}


def pick_list_of(so_name, n):
	"""The Pick List behind part `n` of the order, or None."""
	numbers = part_numbers(so_name)
	return next((pl for pl, i in numbers.items() if i == cint(n)), None)
