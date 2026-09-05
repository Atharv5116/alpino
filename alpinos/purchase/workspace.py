"""Desk entry point for the Purchase Inward module (task 292 / 303).

Both list screens are custom Pages. Granting Has Role lets a user OPEN them, but nothing
put them anywhere a user could find: there was no Workspace Link or Workspace Shortcut
anywhere pointing at purchase_inward_list or purchase_qc_list, so the awesome bar found
the plain DocType list instead of the BRD screen and the purpose-built pages were
reachable only by typing the URL.

Re-run on every migrate; idempotent.
"""

import frappe

#: NOT "Purchase Inward": a Workspace and a DocType of the same name both resolve to
#: /app/purchase-inward, and the collision left the desk landing on the DocType's
#: new-document route with an empty body. The card inside is still labelled Purchase
#: Inward — a card name is not a route.
WORKSPACE = "Goods Inward"

#: The colliding workspace an earlier build created. Removed on migrate.
LEGACY_WORKSPACE = "Purchase Inward"

SHORTCUTS = (
	# (label, type, link_to, doc_view)
	("Purchase Inward", "Page", "purchase_inward_list", ""),
	("Purchase QC", "Page", "purchase_qc_list", ""),
	("New Inward", "Page", "purchase_inward_entry", ""),
	("Purchase Orders", "DocType", "Purchase Order", "List"),
	("GRN", "DocType", "Purchase Receipt", "List"),
)

LINKS = (
	("Purchase Inward", "Purchase Inward", "DocType"),
	("Purchase QC", "Purchase QC", "DocType"),
	("Purchase Inward Settings", "Purchase Inward Settings", "DocType"),
)


# Screen-level access for the two BRD entry pages. It must not be NARROWER than the list
# pages that link to them (both grant C.ALL_PURCHASE_ROLES): a role that can open the list,
# click a row, and then be refused the entry screen is a dead end. What each role may
# actually DO inside is still governed by the DocPerm matrix in purchase.roles and by the
# per-section rules, not by this.
ENTRY_PAGES = ("purchase_inward_entry", "purchase_qc_entry")


def setup_entry_page_access():
	"""Grant every module role the two entry screens. Idempotent.

	Inserted as Has Role rows rather than through page.save(), which in developer_mode
	rewrites the tracked page JSON on disk.
	"""
	from alpinos.purchase import constants as C

	roles = tuple(C.ALL_PURCHASE_ROLES) + ("System Manager",)
	for page in ENTRY_PAGES:
		if not frappe.db.exists("Page", page):
			continue
		for role in roles:
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists(
				"Has Role", {"parenttype": "Page", "parent": page, "role": role}
			):
				continue
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parenttype": "Page",
					"parentfield": "roles",
					"parent": page,
					"role": role,
				}
			).insert(ignore_permissions=True)
	frappe.clear_cache()


def setup_purchase_workspace():
	if not frappe.db.exists("Page", "purchase_inward_list"):
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
	ws.icon = "stock"
	ws.is_hidden = 0

	ws.set("shortcuts", [])
	for label, link_type, link_to, doc_view in SHORTCUTS:
		if link_type == "DocType" and not frappe.db.exists("DocType", link_to):
			continue
		if link_type == "Page" and not frappe.db.exists("Page", link_to):
			continue
		ws.append("shortcuts", {
			"label": label,
			"type": link_type,
			"link_to": link_to,
			"doc_view": doc_view,
		})

	ws.set("links", [])
	ws.append("links", {
		"label": "Purchase Inward",
		"type": "Card Break",
		"link_count": len([l for l in LINKS if frappe.db.exists("DocType", l[1])]),
	})
	for label, link_to, link_type in LINKS:
		if not frappe.db.exists("DocType", link_to):
			continue
		ws.append("links", {
			"label": label,
			"type": "Link",
			"link_type": link_type,
			"link_to": link_to,
			"onboard": 0,
			"is_query_report": 0,
		})

	# A workspace renders from `content`, NOT from the shortcuts/links rows: those rows
	# only supply the data each block points at. Leaving content empty is what produced a
	# blank page with nothing but the Edit / + New buttons.
	ws.content = _workspace_content(ws)

	ws.flags.ignore_permissions = True
	ws.flags.ignore_links = True
	ws.save(ignore_permissions=True)

	_drop_legacy_workspace()
	frappe.clear_cache()


def _block(kind, data, seed):
	"""One content block. The id is derived from the seed so re-running does not churn it."""
	import hashlib

	return {
		"id": hashlib.md5(f"{kind}:{seed}".encode()).hexdigest()[:10],
		"type": kind,
		"data": data,
	}


def _workspace_content(ws):
	"""Header, the shortcut row, then the link card — the layout the desk actually draws."""
	import json

	blocks = [
		_block("header", {"text": "<span class='h4'>Goods Inward</span>", "col": 12}, "hdr"),
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


def _drop_legacy_workspace():
	"""Remove the same-named workspace that collided with the DocType route."""
	if frappe.db.exists("Workspace", LEGACY_WORKSPACE):
		frappe.delete_doc("Workspace", LEGACY_WORKSPACE, ignore_permissions=True, force=True)


def execute():
	setup_entry_page_access()
	setup_purchase_workspace()
