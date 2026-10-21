"""Which Alpino sidebar an alpinos page opens in on the Frappe 16 desk.

Frappe 16 picks the sidebar for a page that no sidebar lists by its module, and every alpinos
page is in "Alpinos Development", the module of all the Alpino sidebars. So a Sales Order, Pick
List or Delivery Note opened by a link or a bookmark landed in "Alpino Goods Inward", which a
sales user sees as an empty sidebar. Entry and view pages need a document to open, so they
cannot simply be listed in a sidebar; instead this corrects Frappe's page -> sidebar map at
boot, and only to a sidebar the user can see. Frappe 15 has no such map, so it does nothing there.
"""

SALES = "Alpino Sales & Dispatch"
STOCK = "Alpino Stock"
GOODS_INWARD = "Alpino Goods Inward"
PRODUCTION = "Alpino Production"
HR = "Alpino HRMS"

# page-name prefixes, checked in order
_PREFIXES = (
	(GOODS_INWARD, ("purchase_",)),
	(HR, ("attendance_batch_", "screening")),
	(SALES, ("sales-order", "ecom-sales-order", "pick_list_", "delivery_note_", "dispatch", "post-delivery",
	         "invoice-", "offline-buyer")),
	(STOCK, ("stock-entry-import", "stock-reconciliation-import")),
	(PRODUCTION, ("production_", "sub_order_", "material_", "filling_", "final_qc_", "bom_master_", "item_master_",
	              "machine_", "process_", "inventory_adjustment_", "store_planning_")),
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
	HR: ("Home", "Approvals"),
	STOCK: (),
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

# Report views are URL items, which Frappe 16 shows to everyone; listed only for readers too.
_URL_NEEDS_READ = {
	"/desk/sales-order/view/report": "Sales Order",
	"/desk/pick-list/view/report": "Pick List",
	"/desk/delivery-note/view/report": "Delivery Note",
}

# Sidebar items the business shows to fewer roles than may open them (Changes(HP) #95, #96).
# Keyed by sidebar and the item's target (link_to, or url for a URL item). Hiding the item
# does not take the access away: the page or list still opens by link for whoever may read it.
_OFFLINE_ORDERS = ("Sales Manager", "Sales Admin", "Sales User", "Warehouse Manager", "Warehouse Admin")
_ECOM_ORDERS = ("E-Commerce Manager", "E-Commerce Admin", "E-Commerce Coordinator", "Warehouse Manager",
                "Warehouse Admin")
_ACCOUNTS = ("Accounts User", "Accounts Manager")
_SO_REPORT = ("Sales Manager", "Sales Admin", "E-Commerce Manager", "E-Commerce Admin")
_HR_TEAM = ("HR User", "HR Manager")
_ITEM_ROLES = {
	(SALES, "sales-order-entry-list"): _OFFLINE_ORDERS,
	(SALES, "ecom-sales-order-entry-list"): _ECOM_ORDERS,
	(SALES, "Accounts Format Report"): _ACCOUNTS,
	(SALES, "invoice-sync"): _ACCOUNTS,
	(SALES, "Invoice Sync Log"): _ACCOUNTS,
	(SALES, "/desk/sales-order/view/report"): _SO_REPORT,
	(HR, "Raven Workspace Member"): _HR_TEAM,
	(HR, "Leave Allocation"): _HR_TEAM,
	(HR, "Shift Assignment"): _HR_TEAM,
	(HR, "Attendance Summary"): _HR_TEAM,
}
# who sees every item a sidebar has, as Administrator does
_SEES_ALL = "System Manager"


# Frappe doctypes the Alpino pages send users into. Frappe 16 keeps a sidebar on screen only for
# its own app's entities, so the Data Import that Sales Order / Stock Entry / Stock Reconciliation
# Import open switched to Frappe's "Data" sidebar (Data Export, File, Naming, Logs...), which led
# users into the wrong tools. Claimed by an Alpino sidebar, the form stays in the Alpino sidebar
# the user came from; opened from Frappe's own Data sidebar it still stays there.
_ADOPTED_DOCTYPES = ("Data Import",)
_ADOPTING_SHELLS = (SALES, STOCK, PRODUCTION, GOODS_INWARD, HR)


def _item_allowed(shell, item, roles):
	import frappe

	if item.get("type") != "Link":
		return True
	link_type, target = item.get("link_type"), item.get("link_to")
	if link_type == "URL":
		target = item.get("url")
		if target in _URL_NEEDS_READ and not frappe.has_permission(_URL_NEEDS_READ[target], "read"):
			return False
	if link_type == "Page" and target in _PAGE_NEEDS_READ and not frappe.has_permission(_PAGE_NEEDS_READ[target], "read"):
		return False
	allowed = _ITEM_ROLES.get((shell, target))
	return not allowed or _SEES_ALL in roles or bool(roles.intersection(allowed))


def _drop_empty_sections(items):
	"""A section heading whose links were all filtered out would sit there with nothing under it."""
	kept = []
	for idx, item in enumerate(items):
		if item.get("type") == "Section Break":
			rest = items[idx + 1:]
			under = []
			for nxt in rest:
				if not nxt.get("child") or nxt.get("type") == "Section Break":
					break
				under.append(nxt)
			if not any(i.get("type") == "Link" for i in under):
				continue
		kept.append(item)
	return kept


def _drop_unreadable_links(bootinfo, visible):
	import frappe

	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	for shell in list(visible):
		if not shell.startswith("Alpino "):
			continue
		sidebar = visible[shell]
		items = [i for i in sidebar.get("items") or [] if _item_allowed(shell, i, roles)]
		items = _drop_empty_sections(items)
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
