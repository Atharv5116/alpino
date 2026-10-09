"""Recover a Workspace's block layout from before a migrate rearranged it.

	bench --site SITE execute alpinos.workspace_restore.history
	bench --site SITE execute alpinos.workspace_restore.show --kwargs "{'version':'<name>'}"
	bench --site SITE execute alpinos.workspace_restore.restore --kwargs "{'version':'<name>','apply':1}"

For the CONTENT of a widget (the calendar, the check-in box) rather than the layout:

	bench --site SITE execute alpinos.workspace_restore.block_history
	bench --site SITE execute alpinos.workspace_restore.block_show --kwargs "{'version':'<name>'}"
	bench --site SITE execute alpinos.workspace_restore.block_restore --kwargs "{'version':'<name>','apply':1}"

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


# ── Custom HTML Block: the content inside a widget ──────────────────────────
#
# The layout and the content are separate records, and the patches rewrite both. When the
# block ORDER comes back identical across a migrate but a widget still looks different, it
# is the Custom HTML Block that changed, not the workspace -- the calendar is one of these.

#: The fields a widget patch overwrites.
_BLOCK_FIELDS = ("html", "script", "style")


def _block_changes(version_name):
	"""{field: (before, after)} for a Custom HTML Block version."""
	raw = frappe.db.get_value("Version", version_name, "data") or "{}"
	try:
		data = json.loads(raw)
	except Exception:
		return {}
	out = {}
	for field, old, new in data.get("changed") or []:
		if field in _BLOCK_FIELDS:
			out[field] = (old or "", new or "")
	return out


def block_history(block=None, limit=40):
	"""Versions that changed a widget's content. Omit `block` to list every widget."""
	filters = {"ref_doctype": "Custom HTML Block"}
	if block:
		filters["docname"] = block
	rows = frappe.get_all(
		"Version", filters=filters, fields=["name", "docname", "creation", "owner"],
		order_by="creation desc", limit_page_length=int(limit),
	)
	rows = [r for r in rows if _block_changes(r.name)]
	if not rows:
		print("No content changes recorded" + (f" for '{block}'." if block else " for any widget."))
		return []
	print("Widget content changes, newest first.\n")
	for r in rows:
		ch = _block_changes(r.name)
		bits = ", ".join(
			f"{f} {len(b)}->{len(a)} chars" for f, (b, a) in sorted(ch.items())
		)
		print(f"   {r.name}  {r.creation}  {r.docname}")
		print(f"        {bits}")
	print("\nInspect:  alpinos.workspace_restore.block_show --kwargs \"{'version':'<name>'}\"")
	return rows


def block_show(version, context=3, max_lines=80):
	"""A unified diff of what this version changed, so the actual edit is visible."""
	import difflib

	ch = _block_changes(version)
	if not ch:
		print(f"Version {version} changed none of {_BLOCK_FIELDS}.")
		return
	docname = frappe.db.get_value("Version", version, "docname")
	print(f"{docname} -- version {version}\n")
	for field, (before, after) in sorted(ch.items()):
		print(f"=== {field}: {len(before)} -> {len(after)} chars")
		diff = list(difflib.unified_diff(
			before.splitlines(), after.splitlines(),
			fromfile="before", tofile="after", lineterm="", n=int(context),
		))
		if not diff:
			print("   (identical text, only the record was re-saved)")
		for line in diff[:int(max_lines)]:
			print("   " + line)
		if len(diff) > int(max_lines):
			print(f"   ... {len(diff) - int(max_lines)} more diff lines")
		print()


def block_restore(version, apply=0):
	"""Write this version's BEFORE content back onto the widget. Dry run by default."""
	apply = int(apply)
	ch = _block_changes(version)
	if not ch:
		print(f"Version {version} changed none of {_BLOCK_FIELDS}; nothing to restore.")
		return
	docname = frappe.db.get_value("Version", version, "docname")
	if not frappe.db.exists("Custom HTML Block", docname):
		print(f"Custom HTML Block '{docname}' no longer exists.")
		return

	pending = {}
	for field, (before, _after) in sorted(ch.items()):
		current = frappe.db.get_value("Custom HTML Block", docname, field) or ""
		if current == before:
			print(f"   {field}: already matches the restore point, leaving it")
		else:
			pending[field] = before
			print(f"   {field}: {len(current)} chars -> {len(before)} chars")
	if not pending:
		print("\nNothing to do.")
		return
	if not apply:
		print(f"\nDry run on '{docname}'. Re-run with apply:1 to write.")
		return

	doc = frappe.get_doc("Custom HTML Block", docname)
	for field, value in pending.items():
		setattr(doc, field, value)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache()
	print(f"\nRestored {', '.join(pending)} on '{docname}'. Hard-refresh the browser.")
	print("The next migrate will overwrite it again until the widget patches are changed.")
