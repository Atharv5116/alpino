"""Ship a widget's content on the deploys that change it, and only those.

The widget patches run on every migrate and write their Custom HTML Block unconditionally:

	cal_block.html = cal_html
	cal_block.script = cal_script
	cal_block.save(ignore_permissions=True)

That is how an updated widget reaches a site, and it is also why an edit made through the
UI survives exactly until the next deploy. The two uses are in conflict only because the
patch cannot tell "the app shipped something new" from "the app shipped the same thing it
shipped last time".

So remember what was last shipped. On each migrate, compare the app's files against that
fingerprint:

  * no record, or the block is missing   -> write it, this is a new site or a new widget
  * fingerprint differs                  -> the app genuinely changed; write it, the deploy
                                            is meant to deliver that
  * fingerprint matches                  -> the app has nothing new to say, so leave the
                                            block alone and keep whatever is there

The fingerprint is of what the APP ships, never of what is in the database, which is the
part that makes this work: a hand-edit changes the block but not the fingerprint, so the
next migrate still compares equal and still leaves the edit alone.

Stored with frappe.db.set_default, so no schema change and nothing to migrate.
"""

import hashlib

import frappe

#: DefaultValue keys are global; prefix so these cannot collide with anything else.
_KEY = "alpinos_widget_shipped:"


def _fingerprint(*parts):
	h = hashlib.sha256()
	for p in parts:
		h.update((p or "").encode("utf-8"))
		h.update(b"\x00")          # so ("ab", "c") and ("a", "bc") differ
	return h.hexdigest()


def write_if_shipped_changed(block_name, html=None, script=None, style=None):
	"""Create or update a Custom HTML Block only when the app's own content changed.

	Returns "created", "updated" or "unchanged", which is what the caller logs.
	"""
	key = _KEY + block_name
	shipped = _fingerprint(html, script, style)
	last_shipped = frappe.db.get_default(key)
	exists = frappe.db.exists("Custom HTML Block", block_name)

	if exists and last_shipped == shipped:
		# Nothing new to deliver. Whatever is on the block stays, edits included.
		return "unchanged"

	values = {}
	if html is not None:
		values["html"] = html
	if script is not None:
		values["script"] = script
	if style is not None:
		values["style"] = style

	if exists:
		doc = frappe.get_doc("Custom HTML Block", block_name)
		for field, value in values.items():
			setattr(doc, field, value)
		doc.save(ignore_permissions=True)
		result = "updated"
	else:
		doc = frappe.get_doc(dict(doctype="Custom HTML Block", name=block_name, **values))
		doc.insert(ignore_permissions=True)
		result = "created"

	frappe.db.set_default(key, shipped)
	return result


def forget(block_name):
	"""Drop the remembered fingerprint, so the next migrate ships the app's version again.

	For the case where a block has been edited into a state somebody wants undone and the
	app's copy is the wanted one.

	  bench --site SITE execute alpinos.widget_content.forget --kwargs "{'block_name':'My Attendance Calendar'}"
	"""
	frappe.db.set_default(_KEY + block_name, None)
	frappe.db.commit()
	print(f"Forgot the shipped fingerprint for '{block_name}'. "
	      f"The next migrate will write the app's version over whatever is there.")
