"""Recover a Workspace's block layout from before a migrate rearranged it.

	bench --site SITE execute alpinos.workspace_restore.history
	bench --site SITE execute alpinos.workspace_restore.show --kwargs "{'version':'<name>'}"
	bench --site SITE execute alpinos.workspace_restore.restore --kwargs "{'version':'<name>','apply':1}"

Five after_migrate hooks rebuild the Home workspace on every migrate: each overwrites its
Custom HTML Block and splices itself back in at a fixed index, then saves the workspace.
Anything anyone arranged by hand is overwritten, every time.

Workspace is version-tracked, so the layout that was there BEFORE the migrate is still on
record. A migrate shows up as a burst of Versions within the same second or two -- one per
patch -- and the OLDEST of that burst carries the layout as it stood before the migrate
started. `history` groups them so the burst is obvious; `show` prints a version's before
and after; `restore` writes the before back. Dry run by default.

This recovers the layout. It does not stop the next migrate doing it again.
"""

import json

import frappe
from frappe.utils import get_datetime

#: Versions this far apart or less are treated as one migrate burst.
BURST_SECONDS = 10


def _content_change(version_name):
	"""(before, after) for the workspace's `content`, or (None, None)."""
	raw = frappe.db.get_value("Version", version_name, "data") or "{}"
	try:
		data = json.loads(raw)
	except Exception:
		return None, None
	for field, old, new in data.get("changed") or []:
		if field == "content":
			return old, new
	return None, None


def _blocks(content):
	try:
		return json.loads(content or "[]")
	except Exception:
		return []


def _summarise(content):
	"""The block order, readable: what a person would recognise as 'the layout'."""
	out = []
	for b in _blocks(content):
		t = b.get("type") or "?"
		d = b.get("data") or {}
		label = d.get("custom_block_name") or d.get("chart_name") or d.get("label") or d.get("text") or ""
		out.append(f"{t}:{label}" if label else t)
	return out


def history(workspace="Home", limit=40):
	"""Versions that changed this workspace's layout, grouped into migrate bursts."""
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "Workspace", "docname": workspace},
		fields=["name", "creation", "owner"],
		order_by="creation desc",
		limit_page_length=int(limit),
	)
	rows = [r for r in rows if _content_change(r.name)[1] is not None]
	if not rows:
		print(f"No layout changes recorded for workspace '{workspace}'.")
		return []

	print(f"Layout changes on '{workspace}', newest first. "
	      f"A migrate is a burst of several within a second or two.\n")
	prev, burst = None, 0
	for r in rows:
		t = get_datetime(r.creation)
		if prev and (prev - t).total_seconds() > BURST_SECONDS:
			burst += 1
			print("   " + "-" * 60)
		before, _after = _content_change(r.name)
		print(f"   [{burst}] {r.name}  {r.creation}  {r.owner}")
		print(f"        before: {len(_blocks(before))} blocks")
		prev = t
	print("\nThe OLDEST line in a burst holds the layout from before that migrate.")
	print("Inspect it:  alpinos.workspace_restore.show --kwargs \"{'version':'<name>'}\"")
	return rows


def show(version):
	"""What this version changed the layout from, and to."""
	before, after = _content_change(version)
	if after is None:
		print(f"Version {version} did not change `content`.")
		return
	print(f"BEFORE ({len(_blocks(before))} blocks):")
	for b in _summarise(before):
		print(f"   {b}")
	print(f"\nAFTER ({len(_blocks(after))} blocks):")
	for b in _summarise(after):
		print(f"   {b}")


def restore(version, workspace="Home", apply=0):
	"""Write this version's BEFORE layout back onto the workspace. Dry run by default."""
	apply = int(apply)
	before, after = _content_change(version)
	if after is None:
		print(f"Version {version} did not change `content`; nothing to restore from.")
		return
	current = frappe.db.get_value("Workspace", workspace, "content")

	print(f"Current layout  : {len(_blocks(current))} blocks")
	for b in _summarise(current):
		print(f"   {b}")
	print(f"\nWould restore to: {len(_blocks(before))} blocks")
	for b in _summarise(before):
		print(f"   {b}")

	if _blocks(current) == _blocks(before):
		print("\nAlready identical. Nothing to do.")
		return
	if not apply:
		print("\nDry run. Re-run with apply:1 to write.")
		return

	frappe.db.set_value("Workspace", workspace, "content", before)
	frappe.db.commit()
	frappe.clear_cache()
	print(f"\nRestored '{workspace}'. Reload the browser to see it.")
	print("The next migrate will rearrange it again until the widget patches stop repositioning.")
