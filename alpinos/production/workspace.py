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
