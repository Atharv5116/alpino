"""A migrate ships a widget only when the app's copy of it changed.

Run:  bench --site alpinos.test execute alpinos.widget_content_test.run

Reported 09-10: the attendance calendar reverts on every deploy. The widget patch wrote its
Custom HTML Block unconditionally on each migrate, so an edit made through the UI survived
until the next one and no longer.

The two checks that carry the point are opposites, and both have to hold or the change is
worthless: a hand-edit must survive a migrate that ships nothing new, and a genuine change
to the app's files must still reach the site. Fixtures roll back.
"""

import frappe

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.widget_content import write_if_shipped_changed, _KEY

	name = "ZZ Test Widget " + frappe.generate_hash(length=5).upper()
	frappe.db.set_default(_KEY + name, None)

	def html_of():
		return frappe.db.get_value("Custom HTML Block", name, "html")

	def _first_migrate_creates_it():
		r = write_if_shipped_changed(name, html="<p>v1</p>", script="a()")
		_assert(r == "created", r)
		_assert(html_of() == "<p>v1</p>", html_of())

	check("a widget that does not exist yet is created", _first_migrate_creates_it)

	def _an_unchanged_migrate_writes_nothing():
		r = write_if_shipped_changed(name, html="<p>v1</p>", script="a()")
		_assert(r == "unchanged", r)

	check("a migrate shipping the same content writes nothing",
		_an_unchanged_migrate_writes_nothing)

	def _a_hand_edit_survives_an_unchanged_migrate():
		"""The reported fault, stated directly."""
		frappe.db.set_value("Custom HTML Block", name, "html", "<p>edited by hand</p>")
		r = write_if_shipped_changed(name, html="<p>v1</p>", script="a()")
		_assert(r == "unchanged", r)
		_assert(html_of() == "<p>edited by hand</p>",
			f"the migrate overwrote the edit: {html_of()!r}")

	check("an edit made through the UI survives a migrate that ships nothing new",
		_a_hand_edit_survives_an_unchanged_migrate)

	def _it_survives_repeated_migrates():
		"""Three deploys in a row, as the Version bursts show really happens."""
		for _ in range(3):
			write_if_shipped_changed(name, html="<p>v1</p>", script="a()")
		_assert(html_of() == "<p>edited by hand</p>",
			f"the edit was lost after repeated migrates: {html_of()!r}")

	check("the edit survives several migrates, not just the next one",
		_it_survives_repeated_migrates)

	def _a_real_change_still_ships():
		"""The other half: this must not become a way to never update a widget again."""
		r = write_if_shipped_changed(name, html="<p>v2</p>", script="a()")
		_assert(r == "updated", r)
		_assert(html_of() == "<p>v2</p>",
			f"a genuine app change did not reach the site: {html_of()!r}")

	check("a genuine change to the app's copy still reaches the site",
		_a_real_change_still_ships)

	def _the_script_counts_too():
		"""html unchanged, script changed -- the fingerprint has to notice."""
		r = write_if_shipped_changed(name, html="<p>v2</p>", script="b()")
		_assert(r == "updated", f"a script-only change was treated as unchanged: {r}")

	check("a change to the script alone is still shipped", _the_script_counts_too)

	def _a_missing_block_is_recreated():
		"""Deleted by hand, fingerprint still on record: the block must come back."""
		frappe.delete_doc("Custom HTML Block", name, force=True, ignore_permissions=True)
		r = write_if_shipped_changed(name, html="<p>v2</p>", script="b()")
		_assert(r == "created", f"a deleted block was not recreated: {r}")

	check("a block deleted by hand is recreated on the next migrate",
		_a_missing_block_is_recreated)

	def _forget_restores_the_apps_version():
		frappe.db.set_value("Custom HTML Block", name, "html", "<p>edited again</p>")
		frappe.db.set_default(_KEY + name, None)
		r = write_if_shipped_changed(name, html="<p>v2</p>", script="b()")
		_assert(r == "updated", r)
		_assert(html_of() == "<p>v2</p>",
			"forgetting the fingerprint should let the app's version through")

	check("forgetting the fingerprint lets the app's version overwrite an edit",
		_forget_restores_the_apps_version)
