"""The Production workspace.

Built from code and re-run on every migrate, exactly like the Goods Inward one, so the
workspace exists on any site this app is installed on -- staging, production, a fresh
bench -- without anyone creating it by hand in the desk.
"""

import hashlib
import json

import frappe

WORKSPACE = "Production"

SHORTCUTS = (
	# (label, type, link_to, doc_view)
	("Item Master", "Page", "item_master_list", ""),
	("BOM Master", "Page", "bom_master_list", ""),
	("Process Master", "Page", "process_master_list", ""),
	# The module's own screens, not the desk list: the desk grid shows raw TYP- ids where
	# these show the type name, the machine counts and the processes each type feeds.
	("Machine Master", "Page", "machine_list", ""),
	("Machine Type Master", "Page", "machine_type_list", ""),
	# 8.2 makes this the master trigger for filling, so it gets a shortcut of its own
	# rather than living only in the DocType links below.
	("Filling Process Category", "Page", "filling_category_list", ""),
	# The orders come before the New-something shortcuts: a production day starts on
	# the order list, not on a master.
	("Production Orders", "Page", "production_order_list", ""),
	("Sub Production Orders", "Page", "sub_order_list", ""),
	("New Production Order", "Page", "production_order_entry", ""),
	("New Item", "Page", "item_master_entry", ""),
	("New BOM", "Page", "bom_master_entry", ""),
	# Store Planning / Material Management (appended).
	("Store Planning Board", "Page", "store_planning_board", ""),
	("Material Requests", "Page", "material_request_list", ""),
	("Material Issues", "Page", "material_issue_list", ""),
	("Material Returns", "Page", "material_return_list", ""),
	("Production Settings", "DocType", "Production Settings", ""),
	# Phase 4+ (Execution / QC / Filling / Inventory / Dispatch / Reports), appended. A page
	# that does not exist yet is skipped and picked up on the next migrate.
	("Shop Floor", "Page", "production_floor", ""),
	("Production QC", "Page", "production_qc_list", ""),
	("Filling Planning", "Page", "filling_plan_list", ""),
	("Filling Calendar", "Page", "filling_calendar", ""),
	("Filling Entry", "Page", "filling_entry", ""),
	("Final QC", "Page", "final_qc_list", ""),
	("Inventory", "Page", "production_inventory", ""),
	("Stock Transfer", "Page", "production_transfer_list", ""),
	("Inventory Adjustment", "Page", "inventory_adjustment_list", ""),
	("Dispatch Tracking", "Page", "dispatch_tracking", ""),
	("Production Reports", "Page", "production_reports", ""),
	("Shift Type", "DocType", "Shift Type", "List"),
)

LINKS = (
	# (label, link_to, link_type)
	("Item", "Item", "DocType"),
	("BOM", "BOM", "DocType"),
	("Process Master", "Process Master", "DocType"),
	("Machine", "Machine", "DocType"),
	("Machine Type", "Machine Type", "DocType"),
	("Filling Process Category", "Filling Process Category", "DocType"),
	("Production Order", "Production Order", "DocType"),
	("Work Order", "Work Order", "DocType"),
	# Appended for Store Planning / Material Management.
	("Production Settings", "Production Settings", "DocType"),
	# Phase 4+ (appended).
	("Shift Type", "Shift Type", "DocType"),
)


def _block(kind, data, seed):
	"""One content block. The id is derived from the seed so re-running does not churn it."""
	return {
		"id": hashlib.md5(f"{kind}:{seed}".encode()).hexdigest()[:10],
		"type": kind,
		"data": data,
	}


def _workspace_content(ws):
	"""A workspace renders from `content`, not from its shortcut/link rows -- those only
	supply the data each block points at. An empty content is a blank page."""
	blocks = [
		_block("header", {"text": "<span class='h4'>Production</span>", "col": 12}, "hdr")
	]
	for shortcut in ws.shortcuts:
		blocks.append(
			_block("shortcut", {"shortcut_name": shortcut.label, "col": 3}, shortcut.label)
		)
	blocks.append(_block("spacer", {"col": 12}, "spacer"))
	for link in ws.links:
		if link.type == "Card Break":
			blocks.append(_block("card", {"card_name": link.label, "col": 4}, link.label))
	return json.dumps(blocks)


def setup_production_workspace():
	# Nothing to point at yet: the pages are created by the same migrate that calls this,
	# so a half-installed app must not leave a workspace full of dead shortcuts.
	if not frappe.db.exists("Page", "item_master_list"):
		return

	if frappe.db.exists("Workspace", WORKSPACE):
		ws = frappe.get_doc("Workspace", WORKSPACE)
	else:
		ws = frappe.new_doc("Workspace")
		ws.name = WORKSPACE
		ws.title = WORKSPACE
		ws.label = WORKSPACE

	ws.module = "Alpinos Development"
	ws.public = 1
	ws.icon = "setting-gear"
	ws.is_hidden = 0

	ws.set("shortcuts", [])
	for label, link_type, link_to, doc_view in SHORTCUTS:
		if link_type == "DocType" and not frappe.db.exists("DocType", link_to):
			continue
		if link_type == "Page" and not frappe.db.exists("Page", link_to):
			continue
		if link_type == "Report" and not frappe.db.exists("Report", link_to):
			continue
		ws.append("shortcuts", {
			"label": label,
			"type": link_type,
			"link_to": link_to,
			"doc_view": doc_view,
		})

	ws.set("links", [])
	present = [l for l in LINKS if frappe.db.exists("DocType", l[1])]
	ws.append("links", {
		"label": "Masters",
		"type": "Card Break",
		"link_count": len(present),
	})
	for label, link_to, link_type in present:
		ws.append("links", {
			"label": label,
			"type": "Link",
			"link_type": link_type,
			"link_to": link_to,
			"onboard": 0,
			"is_query_report": 0,
		})

	ws.content = _workspace_content(ws)
	ws.flags.ignore_permissions = True
	ws.flags.ignore_links = True
	ws.save(ignore_permissions=True)
	frappe.clear_cache()


def setup_page_access():
	"""Let the production roles open the master screens.

	A Page with no roles is admin-only in practice, so without this a Production Manager
	could read the doctypes and still be refused the screen that shows them.

	The Machine Type screens are listed here too, and deliberately so: BRD 2.1.1 bars a
	regular user from MANAGING types, not from seeing them. The DocPerm matrix
	(alpinos.production.roles) is what makes those two screens read-only for everyone but
	an Admin; locking the page itself would also hide the list they must select from.
	"""
	from alpinos.production import constants as C

	pages = (
		"item_master_list",
		"item_master_entry",
		"bom_master_list",
		"bom_master_entry",
		"process_master_list",
		"process_master_entry",
		"machine_list",
		"machine_entry",
		"machine_type_list",
		"machine_type_entry",
		"filling_category_list",
		"filling_category_entry",
		"production_order_list",
		"production_order_entry",
		"sub_order_list",
	)
	for page in pages:
		if not frappe.db.exists("Page", page):
			continue
		doc = frappe.get_doc("Page", page)
		have = {row.role for row in doc.roles}
		wanted = set(C.PRODUCTION_ROLES) | {"System Manager"}
		if wanted.issubset(have):
			continue
		for role in sorted(wanted - have):
			doc.append("roles", {"role": role})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)


def execute():
	setup_page_access()
	setup_production_workspace()


#: Store Planning / Material Management screens (appended). Opened by the store roles as
#: well as the production roles, so they get their own access list rather than joining the
#: masters' one above.
STORE_PAGES = (
	"store_planning_board",
	"material_request_list",
	"material_request_entry",
	"material_issue_list",
	"material_issue_entry",
	"material_return_list",
	"material_return_entry",
	"sub_order_view",
)


def setup_store_page_access():
	"""Let the store and production roles open the store screens. Only ever adds roles."""
	from alpinos.production import material_constants as M

	wanted = set(M.STORE_READ_ROLES)
	for page in STORE_PAGES:
		if not frappe.db.exists("Page", page):
			continue
		doc = frappe.get_doc("Page", page)
		have = {row.role for row in doc.roles}
		missing = sorted(r for r in wanted - have if frappe.db.exists("Role", r))
		if not missing:
			continue
		for role in missing:
			doc.append("roles", {"role": role})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)


# --- Phase 4+ screens (Execution / QC / Filling / Inventory / Dispatch / Reports) -----
# Appended. Each group of pages gets the roles that work on it; only ever adds roles, and
# a page or role that does not exist yet is skipped (picked up on the next migrate).

def _phase4_page_roles():
	from alpinos.production import constants as C
	from alpinos.production import material_constants as M
	from alpinos.production.roles import (
		ROLE_PLANT_HEAD,
		ROLE_PRODUCTION_OPERATOR,
		ROLE_QC_INSPECTOR,
		ROLE_QC_MANAGER,
	)

	base = set(C.PRODUCTION_ROLES) | {"System Manager", ROLE_PLANT_HEAD}
	floor = base | {ROLE_PRODUCTION_OPERATOR}
	qc = base | {ROLE_QC_INSPECTOR, ROLE_QC_MANAGER}
	store = base | set(M.STORE_MM_ROLES)
	reports = {C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, ROLE_PLANT_HEAD, "System Manager"}
	return {
		"production_floor": floor,
		"process_inward_entry": floor,
		"production_qc_list": qc,
		"production_qc_entry": qc,
		"filling_plan_list": floor,
		"filling_plan_entry": floor,
		"filling_calendar": floor,
		"filling_entry": floor,
		"final_qc_list": qc,
		"final_qc_entry": qc,
		"production_inventory": store,
		"production_transfer_list": store,
		"production_transfer_entry": store,
		"inventory_adjustment_list": store,
		"inventory_adjustment_entry": store,
		"dispatch_tracking": store,
		"production_reports": reports,
	}


PHASE4_PAGES = (
	"production_floor",
	"process_inward_entry",
	"production_qc_list",
	"production_qc_entry",
	"filling_plan_list",
	"filling_plan_entry",
	"filling_calendar",
	"filling_entry",
	"final_qc_list",
	"final_qc_entry",
	"production_inventory",
	"production_transfer_list",
	"production_transfer_entry",
	"inventory_adjustment_list",
	"inventory_adjustment_entry",
	"dispatch_tracking",
	"production_reports",
)


def setup_phase4_page_access():
	"""Let the right roles open the Phase 4+ screens. Only ever adds roles."""
	page_roles = _phase4_page_roles()
	for page in PHASE4_PAGES:
		if not frappe.db.exists("Page", page):
			continue
		try:
			doc = frappe.get_doc("Page", page)
			have = {row.role for row in doc.roles}
			missing = sorted(r for r in page_roles.get(page, set()) - have
			                 if frappe.db.exists("Role", r))
			if not missing:
				continue
			for role in missing:
				doc.append("roles", {"role": role})
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Phase 4 page access: {page}")
