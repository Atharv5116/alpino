"""Shared pieces of the Pick List and Delivery Note list pages (Changes(HP) #111).

  * total(): the record count behind the pager;
  * order_by(): a whitelisted server-side sort, so sorting covers every record.
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
