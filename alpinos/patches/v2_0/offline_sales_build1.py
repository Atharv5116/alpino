"""Offline Sales build 1 (alpinos.offline_sales): starting values for the new Buyer Master fields
and the one permission row that existed before the build.

  * Every existing buyer is Approved with its Buyer Catalog counted as Completed, so nothing
    being sold today is stopped by the new readiness gate.
  * Buyer Master / Sales Officer goes from read only to read, create, write (the server limits
    which fields and when). It runs here, before company_scope.perm_seed snapshots the rows,
    because that row is already seeded and after_migrate writers cannot move a seeded row.
"""

import frappe


def execute():
	if not frappe.db.has_column("Buyer Master", "buyer_status"):
		return
	frappe.db.sql("UPDATE `tabBuyer Master` SET buyer_status = 'Approved' WHERE IFNULL(buyer_status, '') = ''")
	frappe.db.sql(
		"UPDATE `tabBuyer Master` SET buyer_catalog_status = 'Completed' WHERE IFNULL(buyer_catalog_status, '') = ''"
	)

	if frappe.db.exists("Role", "Sales Officer"):
		from alpinos.purchase.roles import _grant

		_grant("Buyer Master", "Sales Officer", "CREATE_EDIT")
		frappe.clear_cache(doctype="Buyer Master")
