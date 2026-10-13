"""Which Alpino sidebar an alpinos page opens in on the Frappe 16 desk.

Frappe 16 picks the sidebar for a page that no sidebar lists by its module, and every alpinos
page is in "Alpinos Development", the module of all four Alpino sidebars. So a Sales Order, Pick
List or Delivery Note opened by a link or a bookmark landed in "Alpino Goods Inward", which a
sales user sees as an empty sidebar. Entry and view pages need a document to open, so they
cannot simply be listed in a sidebar; instead this corrects Frappe's page -> sidebar map at
boot, and only to a sidebar the user can see. Frappe 15 has no such map, so it does nothing there.
"""

SALES = "Alpino Sales"
GOODS_INWARD = "Alpino Goods Inward"
PRODUCTION = "Alpino Production"
HR = "Alpino HR"

# page-name prefixes, checked in order
_PREFIXES = (
	(GOODS_INWARD, ("purchase_",)),
	(HR, ("attendance_batch_", "screening")),
	(SALES, ("sales-order", "ecom-sales-order", "pick_list_", "delivery_note_", "dispatch", "post-delivery",
	         "invoice-", "offline-buyer")),
	(PRODUCTION, ("production_", "sub_order_", "material_", "filling_", "final_qc_", "bom_master_", "item_master_",
	              "machine_", "process_", "inventory_adjustment_", "store_planning_", "stock-entry-import",
	              "stock-reconciliation-import")),
)


def shell_for(page):
	for shell, prefixes in _PREFIXES:
		if page.startswith(prefixes):
			return shell
	return None


def extend_bootinfo(bootinfo):
	import frappe

	pages = (bootinfo.get("canonical_shell") or {}).get("Page")
	visible = bootinfo.get("module_sidebars") or {}
	if not pages or not visible:
		return
	ours = set(frappe.get_all("Page", filters={"module": "Alpinos Development"}, pluck="name"))
	for page in pages:
		if page not in ours:
			continue
		shell = shell_for(page)
		if shell and shell in visible:
			pages[page] = shell
