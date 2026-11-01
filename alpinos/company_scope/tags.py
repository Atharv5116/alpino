"""Company tags on masters (Item, Customer, Supplier, Buyer Master, Price List, Machine,
Process Master): the Companies field, blank = every company.

custom_company_scope mirrors the tags as "|A|B|" so SQL and get_all can filter without a
join; it is rewritten on every save, never edited by hand.
"""

import frappe

from alpinos.company_scope import registry


def scope_string(companies):
	companies = sorted({c for c in companies if c})
	return "|" + "|".join(companies) + "|" if companies else ""


def sync_scope(doc, method=None):
	"""validate of a tagged master: dedupe the tags and refresh the mirror."""
	if not doc.meta.get_field(registry.TAG_FIELD):
		return
	seen, keep = set(), []
	for row in doc.get(registry.TAG_FIELD) or []:
		if row.company and row.company not in seen:
			seen.add(row.company)
			keep.append(row)
	doc.set(registry.TAG_FIELD, keep)
	doc.set(registry.SCOPE_FIELD, scope_string(seen))
	if doc.doctype == "Item":
		_item_defaults(doc, seen)


def _item_defaults(doc, companies):
	"""ERPNext keeps per-company defaults on Item Default rows; a newly tagged company gets one."""
	have = {r.company for r in doc.get("item_defaults") or []}
	for company in sorted(companies - have):
		doc.append("item_defaults", {"company": company})


def buyer_master_to_customer(doc, method=None):
	"""Buyer Master on_update: its Customer carries the same tags."""
	customer = doc.get("customer")
	if not customer or not frappe.db.exists("Customer", customer):
		return
	tags = [r.company for r in doc.get(registry.TAG_FIELD) or []]
	scope = scope_string(tags)
	current = frappe.db.get_value("Customer", customer, registry.SCOPE_FIELD) or ""
	if current == scope:
		return
	cust = frappe.get_doc("Customer", customer)
	cust.set(registry.TAG_FIELD, [{"company": c} for c in sorted(set(tags))])
	cust.flags.ignore_permissions = True
	cust.flags.ignore_mandatory = True
	cust.save()


def tag_all(doctype, company):
	"""Tag every untagged record of a master to one company (the go-live backfill)."""
	if registry.mode(doctype)[0] != registry.TAGGED:
		return 0
	names = frappe.get_all(doctype, filters={registry.SCOPE_FIELD: ["in", ["", None]]}, pluck="name")
	names += frappe.db.sql_list(
		f"select name from `tab{doctype}` where {registry.SCOPE_FIELD} is null"
	)
	names = sorted(set(names))
	if not names:
		return 0
	scope = scope_string([company])
	now = frappe.utils.now()
	for name in names:
		frappe.get_doc(
			{"doctype": registry.TAG_DOCTYPE, "parent": name, "parenttype": doctype,
			 "parentfield": registry.TAG_FIELD, "company": company, "idx": 1,
			 "owner": "Administrator", "modified_by": "Administrator", "creation": now, "modified": now}
		).db_insert()
	frappe.db.sql(
		f"update `tab{doctype}` set {registry.SCOPE_FIELD} = %s where name in %s", (scope, tuple(names))
	)
	return len(names)
