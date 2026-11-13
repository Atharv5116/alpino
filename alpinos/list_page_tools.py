"""Shared pieces of the Pick List and Delivery Note list pages.

  * total(): the record count behind the pager (Changes(HP) #111);
  * order_by(): a whitelisted server-side sort, so sorting covers every record (#111);
  * buyer_search_orders() / buyer_ids(): the Buyer ID (Buyer Master) of each row's Sales
    Order, searchable (Changes(HP) #64);
  * scope_to_assigned_buyers(): a Sales Officer sees only the documents of their assigned
    Buyers' orders (Changes(HP) #71). The pages read with frappe.get_all, which skips the
    permission hooks the desk list applies (buyer_assignment_visibility), so it is applied here.
"""

import frappe


def total(doctype, filters, or_filters=None):
	row = frappe.get_all(doctype, filters=filters, or_filters=or_filters or None, fields=[{"COUNT": "*", "as": "total"}])
	return int((row[0].get("total") if row else 0) or 0)


def order_by(sort_field, sort_dir, allowed, default="creation desc"):
	field = allowed.get(sort_field or "")
	if not field:
		return default
	direction = "asc" if (sort_dir or "").lower() == "asc" else "desc"
	return f"{field} {direction}, creation desc"


def buyer_search_orders(search):
	"""Sales Orders whose Buyer ID matches a search text (empty list when none)."""
	search = (search or "").strip()
	if not search:
		return []
	return frappe.get_all(
		"Sales Order",
		filters={"custom_offline_buyer_master": ["like", f"%{search}%"]},
		pluck="name",
		limit=5000,
	)


def buyer_ids(sales_orders):
	"""{sales order: Buyer ID} for the rows on one page."""
	names = [s for s in set(sales_orders or []) if s]
	if not names:
		return {}
	return dict(
		frappe.get_all(
			"Sales Order",
			filters={"name": ["in", names]},
			fields=["name", "custom_offline_buyer_master"],
			as_list=True,
		)
	)


def scope_to_assigned_buyers(filters, field="custom_sales_order_id"):
	"""Narrow `filters` to the orders of the user's assigned Buyers when assignment scopes them."""
	from alpinos import buyer_assignment_visibility as V

	if not V.is_downstream_scoped():
		return filters
	employee = V._employee_for(frappe.session.user)
	assigned = set()
	if employee:
		buyers = V._assigned_buyer_names(employee)
		if buyers:
			assigned = set(
				frappe.get_all("Sales Order", filters={V.SO_BUYER_FIELD: ["in", list(buyers)]}, pluck="name")
			)
	current = filters.get(field)
	if isinstance(current, (list, tuple)) and len(current) == 2 and current[0] == "in":
		assigned &= set(current[1] or [])
	elif isinstance(current, str) and current:
		assigned &= {current}
	filters[field] = ["in", sorted(assigned) or ["__no_match__"]]
	return filters
