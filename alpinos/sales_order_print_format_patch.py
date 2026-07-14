import frappe

PF_NAME = "Sales Order"

# The items table must iterate get_combined_items(doc) — which explodes/merges product
# bundles per the buyer's "Combine Product Bundles" flag — instead of doc.items directly.
ANCHOR_LOOP = "{% for row in doc.items %}"
COMBINE_LOOP = "{% set combined_items = get_combined_items(doc) %}\n  {% for row in combined_items %}"

# Keep the "Items" count in the Total PCS summary consistent with the (possibly exploded) rows.
ANCHOR_COUNT = "{{ doc.items|length if doc.items else 0 }}"
COMBINE_COUNT = "{{ combined_items|length if combined_items else 0 }}"

# The buyer master was renamed "Offline Buyer Master" -> "Buyer Master" (2026-07-09),
# but UI-authored print-format Jinja still called get_doc/get_value on the old name.
# On PDF download that raises PrintFormatError: "No module named
# ...offline_buyer_master" (get_doc imports the now-missing controller module).
# Idempotently repair the stale name in every print format on migrate.
OLD_DOCTYPE = "Offline Buyer Master"
NEW_DOCTYPE = "Buyer Master"


def _fix_renamed_doctype_refs():
	for name in frappe.get_all(
		"Print Format", filters={"html": ["like", "%" + OLD_DOCTYPE + "%"]}, pluck="name"
	):
		html = frappe.db.get_value("Print Format", name, "html") or ""
		if OLD_DOCTYPE in html:
			frappe.db.set_value(
				"Print Format", name, "html", html.replace(OLD_DOCTYPE, NEW_DOCTYPE)
			)
			frappe.logger("alpinos").info(
				"Print format '%s': repaired stale '%s' reference." % (name, OLD_DOCTYPE)
			)


def execute():
	"""Patch the 'Sales Order' print format to explode product bundles, and repair
	the renamed buyer-master doctype reference in all print formats.

	Runs on every migrate but only rewrites HTML when needed, so it is
	safe/idempotent and leaves manual edits alone once patched. If the items loop
	can't be located unambiguously, it logs and skips rather than guessing.
	"""
	_fix_renamed_doctype_refs()
	frappe.db.commit()  # persist the doctype-name repair regardless of the bundle path below

	if not frappe.db.exists("Print Format", PF_NAME):
		return

	html = frappe.db.get_value("Print Format", PF_NAME, "html") or ""
	if not html or "get_combined_items(doc)" in html:
		return  # empty, or already patched

	if html.count(ANCHOR_LOOP) != 1:
		frappe.log_error(
			title="Sales Order print format: bundle-split patch skipped",
			message="Expected exactly one {0!r} in the HTML, found {1}.".format(
				ANCHOR_LOOP, html.count(ANCHOR_LOOP)
			),
		)
		return

	html = html.replace(ANCHOR_LOOP, COMBINE_LOOP)
	html = html.replace(ANCHOR_COUNT, COMBINE_COUNT)  # no-op if the summary line differs

	frappe.db.set_value("Print Format", PF_NAME, "html", html)
	frappe.db.commit()
	frappe.logger("alpinos").info("Patched '%s' print format to explode product bundles." % PF_NAME)
