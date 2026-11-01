"""Role Permissions Manager is where permissions are managed (decided 1 Nov 2026).

alpinos writes its role matrices (workflow_role_access, purchase.roles, production.roles,
phase4_permissions, salary_visibility, ...) on every migrate, which used to undo any change
made in Role Permissions Manager. Instead of changing each of those writers, every migrate
is wrapped:

    start()   first after_migrate step: remembers every Custom DocPerm row and page role;
    finish()  last after_migrate step: a row seeded by an earlier migrate goes back to what
              it was before this one (the writers' changes to it are undone), a seeded row
              someone deleted stays deleted, and a seeded row someone deleted that the
              writers put back is removed again. Rows seen for the first time are kept as the
              writers left them and recorded as seeded.

So code adds new permissions once (a new doctype, a new role), and from then on the row
belongs to Role Permissions Manager. The record is the Alpinos Permission Seed list.
"""

import frappe

SEED = "Alpinos Permission Seed"
_SKIP_COLUMNS = {"name", "owner", "creation", "modified", "modified_by", "idx", "docstatus", "parent",
	"parenttype", "parentfield", "role", "permlevel", "if_owner"}


def _rows():
	columns = [c for c in frappe.db.get_table_columns("Custom DocPerm") if c not in ("_user_tags", "_comments", "_assign", "_liked_by")]
	rows = {}
	for row in frappe.db.sql(f"select {', '.join('`'+c+'`' for c in columns)} from `tabCustom DocPerm`", as_dict=True):
		key = f"{row.parent}|{row.role}|{int(row.permlevel or 0)}|{int(row.if_owner or 0)}"
		rows[key] = row
	return rows


def _page_roles():
	return {
		f"Page:{r.parent}|{r.role}": r
		for r in frappe.db.sql(
			"""select name, parent, role from `tabHas Role` where parenttype = 'Page'
			and parent in (select name from tabPage where module = 'Alpinos Development')""",
			as_dict=True,
		)
	}


def _values(row):
	return {k: v for k, v in row.items() if k not in _SKIP_COLUMNS}


def start():
	if not frappe.db.table_exists(SEED):
		return
	frappe.flags.alpinos_perm_seed = {"perms": _rows(), "pages": _page_roles()}


def finish():
	snapshot = frappe.flags.get("alpinos_perm_seed")
	if not snapshot or not frappe.db.table_exists(SEED):
		return
	frappe.flags.alpinos_perm_seed = None
	seeded = set(frappe.get_all(SEED, pluck="seed_key"))
	before, after = snapshot["perms"], _rows()
	touched = set()
	restored = removed = 0
	for key in seeded:
		if key.startswith("Page:"):
			continue
		was, now = before.get(key), after.get(key)
		if was and now and _values(was) != _values(now):
			frappe.db.set_value("Custom DocPerm", now.name, _values(was), update_modified=False)
			touched.add(was.parent)
			restored += 1
		elif was and not now:
			doc = frappe.get_doc(dict(was, doctype="Custom DocPerm"))
			doc.db_insert()
			touched.add(was.parent)
			restored += 1
		elif now and not was:
			frappe.db.delete("Custom DocPerm", {"name": now.name})
			touched.add(now.parent)
			removed += 1
	pages_before, pages_after = snapshot["pages"], _page_roles()
	for key in seeded:
		if not key.startswith("Page:"):
			continue
		was, now = pages_before.get(key), pages_after.get(key)
		if now and not was:
			frappe.db.delete("Has Role", {"name": now.name})
			removed += 1
		elif was and not now:
			frappe.get_doc({"doctype": "Has Role", "parenttype": "Page", "parentfield": "roles",
				"parent": was.parent, "role": was.role}).db_insert()
			restored += 1
	for doctype in touched:
		frappe.clear_cache(doctype=doctype)
	_record(set(_rows()) | set(_page_roles()), seeded)
	if restored or removed:
		print(f"Role Permissions Manager kept: {restored} permission rows restored, {removed} removed rows kept removed")


def _record(keys, seeded):
	now = frappe.utils.now()
	for key in sorted(keys - seeded):
		parent, role, *rest = key.split("|")
		frappe.get_doc(
			{
				"doctype": SEED,
				"name": key,
				"seed_key": key,
				"document_type": parent,
				"role": role,
				"permlevel": int(rest[0]) if rest else 0,
				"if_owner": int(rest[1]) if len(rest) > 1 else 0,
				"owner": "Administrator",
				"creation": now,
				"modified": now,
				"modified_by": "Administrator",
			}
		).db_insert()
