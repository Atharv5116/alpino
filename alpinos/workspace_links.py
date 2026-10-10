"""Drop workspace rows that point at something which no longer exists, before a save.

A Workspace validates every link on save, so one dead shortcut makes the whole workspace
unsavable -- and the Home widgets re-save Home on every migrate. On this site that has
happened twice: a "Bad POS" shortcut to another app's page, and on Frappe v16 the
Leaderboard page, which v16 removed. Either one stopped every after_migrate step after it.

Hooked on Workspace before_validate, so it covers alpinos's own saves and anyone else's.
It only ever removes a row whose target is missing (the save would fail on it anyway),
together with the layout block that showed it; nothing that resolves is touched.
"""

import json

import frappe

# child table -> (type field or fixed doctype, name field, content block type, block key)
_TABLES = {
	"shortcuts": ("type", "link_to", "shortcut", "shortcut_name"),
	"links": ("link_type", "link_to", None, None),
	"charts": ("=Dashboard Chart", "chart_name", "chart", "chart_name"),
	"number_cards": ("=Number Card", "number_card_name", "number_card", "number_card_name"),
	"quick_lists": ("=DocType", "document_type", "quick_list", "quick_list_name"),
	"custom_blocks": ("=Custom HTML Block", "custom_block_name", "custom_block", "custom_block_name"),
}
_LINKABLE = {"DocType", "Report", "Page", "Dashboard", "Dashboard Chart", "Number Card", "Custom HTML Block"}


def _target_doctype(row, type_spec):
	if type_spec.startswith("="):
		return type_spec[1:]
	return row.get(type_spec)


def prune_dead_links(doc, method=None):
	removed_blocks = set()
	for table, (type_spec, name_field, block_type, block_key) in _TABLES.items():
		keep = []
		for row in doc.get(table) or []:
			target_doctype = _target_doctype(row, type_spec)
			target = row.get(name_field)
			if target and target_doctype in _LINKABLE and not frappe.db.exists(target_doctype, target):
				if block_type:
					removed_blocks.add((block_type, block_key, row.get("label") or target))
				frappe.log_error(
					title=f"Workspace {doc.name}: dropped a dead {table[:-1].replace('_', ' ')}",
					message=f"{target_doctype} {target!r} no longer exists (row label {row.get('label')!r}).",
				)
				continue
			keep.append(row)
		if len(keep) != len(doc.get(table) or []):
			doc.set(table, keep)

	if removed_blocks and doc.content:
		try:
			blocks = json.loads(doc.content)
		except ValueError:
			return

		def is_removed(block):
			data = block.get("data") or {}
			return any(
				block.get("type") == block_type and data.get(key) == name
				for block_type, key, name in removed_blocks
			)

		blocks = [b for b in blocks if not is_removed(b)]
		doc.content = json.dumps(blocks)
