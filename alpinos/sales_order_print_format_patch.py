import frappe

PF_NAME = "Sales Order"

# The items table must iterate get_combined_items(doc) — which explodes/merges product
# bundles per the buyer's "Combine Product Bundles" flag — instead of doc.items directly.
ANCHOR_LOOP = "{% for row in doc.items %}"
COMBINE_LOOP = "{% set combined_items = get_combined_items(doc) %}\n  {% for row in combined_items %}"

# Keep the "Items" count in the Total PCS summary consistent with the (possibly exploded) rows.
ANCHOR_COUNT = "{{ doc.items|length if doc.items else 0 }}"
COMBINE_COUNT = "{{ combined_items|length if combined_items else 0 }}"


def execute():
	"""Patch the 'Sales Order' print format to explode product bundles.

	Runs on every migrate but only rewrites the HTML when the helper call is
	missing, so it is safe/idempotent and leaves manual edits alone once patched.
	If the items loop can't be located unambiguously, it logs and skips rather
	than guessing.
	"""
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
