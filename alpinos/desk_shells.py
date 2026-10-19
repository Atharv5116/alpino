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


# The workspaces each Alpino sidebar stands for. Frappe 16 derives a sidebar's workspaces from its
# module, so all four listed both Production and Goods Inward, and it opens a workspace in the
# first sidebar listing it: the Production dock entry landed in Goods Inward, and the HR entry's
# Home (module Setup) landed in the Setup sidebar (Company, Users...) instead of Alpino HR.
_SHELL_WORKSPACES = {
	SALES: (),
	GOODS_INWARD: ("Goods Inward",),
	PRODUCTION: ("Production",),
	HR: ("Home",),
}


# Pages with no roles of their own, which Frappe 16 therefore lists for every user although
# the page itself refuses anyone who cannot read its documents (an employee clicking the Alpino
# tile landed on "You are not permitted to view Pick Lists"). Listed only for readers.
_PAGE_NEEDS_READ = {
	"pick_list_list": "Pick List",
	"delivery_note_entry_list": "Delivery Note",
	"sales-order-import": "Sales Order",
	"stock-entry-import": "Stock Entry",
	"stock-reconciliation-import": "Stock Reconciliation",
}


# Frappe doctypes the Alpino pages send users into. Frappe 16 keeps a sidebar on screen only for
# its own app's entities, so the Data Import that Sales Order / Stock Entry / Stock Reconciliation
# Import open switched to Frappe's "Data" sidebar (Data Export, File, Naming, Logs...), which led
# users into the wrong tools. Claimed by an Alpino sidebar, the form stays in the Alpino sidebar
# the user came from; opened from Frappe's own Data sidebar it still stays there.
_ADOPTED_DOCTYPES = ("Data Import",)
_ADOPTING_SHELLS = (SALES, PRODUCTION, GOODS_INWARD, HR)


def _drop_unreadable_links(bootinfo, visible):
	import frappe

	for shell in list(visible):
		if not shell.startswith("Alpino "):
			continue
		sidebar = visible[shell]
		items = [
			i for i in sidebar.get("items") or []
			if not (i.get("link_type") == "Page" and i.get("link_to") in _PAGE_NEEDS_READ
			        and not frappe.has_permission(_PAGE_NEEDS_READ[i["link_to"]], "read"))
		]
		sidebar["items"] = items
		if any(i.get("type") == "Link" for i in items):
			continue
		# nothing left to open: drop the sidebar and its dock entry instead of showing it empty
		del visible[shell]
		for app in bootinfo.get("app_data") or []:
			if app.get("dock"):
				app["dock"] = [e for e in app["dock"] if e.get("link_to") != shell]
		for app, entries in (bootinfo.get("dock") or {}).items():
			bootinfo["dock"][app] = [e for e in entries if e.get("link_to") != shell]


def extend_bootinfo(bootinfo):
	import frappe

	visible = bootinfo.get("module_sidebars") or {}
	if not visible:
		return
	_drop_unreadable_links(bootinfo, visible)

	# every workspace this user can open already appears in some sidebar's list
	reachable = set()
	for sidebar in visible.values():
		reachable.update(sidebar.get("workspaces") or ())
	for shell, workspaces in _SHELL_WORKSPACES.items():
		sidebar = visible.get(shell)
		if sidebar is not None and "workspaces" in sidebar:
			sidebar["workspaces"] = [w for w in workspaces if w in reachable]

	canonical = bootinfo.get("canonical_shell") or {}
	doctypes = canonical.get("DocType")
	adopting = next((shell for shell in _ADOPTING_SHELLS if shell in visible), None)
	if doctypes is not None and adopting:
		for doctype in _ADOPTED_DOCTYPES:
			doctypes[doctype] = adopting

	pages = canonical.get("Page")
	if not pages:
		return
	ours = set(frappe.get_all("Page", filters={"module": "Alpinos Development"}, pluck="name"))
	for page in pages:
		if page not in ours:
			continue
		shell = shell_for(page)
		if shell and shell in visible:
			pages[page] = shell
