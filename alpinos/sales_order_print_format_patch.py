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

# Idempotent (original_source_line, patched_line) rewrites applied to the
# UI-authored "Sales Order" print format on every migrate:
#
# 1-3) Address / site: imported & e-com Sales Orders keep the buyer address as
#      FREE TEXT on the SO (custom_billing_address_text / custom_shipping_address_text)
#      and the site in custom_site_name — they have NO linked Address record and
#      usually no Buyer Master link, so the format's Address / Buyer Master reads
#      printed "Address N/A" and "—". Prefer the SO's own custom fields, falling
#      back to the original sources.
# 4)   Grand Total: show the rounded total (falls back to grand_total when rounding
#      is disabled) to match the amount customers expect on the printed order.
SALES_ORDER_PF_REWRITES = [
	(
		"{% set raw_bill = doc.address_display or '' %}",
		"{% set raw_bill = doc.get('custom_billing_address_text') or doc.address_display or '' %}",
	),
	(
		"{% set raw_ship = (ship_addr_doc.get_display() if ship_addr_doc else '') or doc.shipping_address or doc.address_display or '' %}",
		"{% set raw_ship = doc.get('custom_shipping_address_text') or (ship_addr_doc.get_display() if ship_addr_doc else '') or doc.shipping_address or doc.address_display or '' %}",
	),
	(
		"{% set site_name_obm = frappe.db.get_value('Buyer Master', doc.custom_offline_buyer_master, 'site_name') if doc.get('custom_offline_buyer_master') else '' %}",
		"{% set site_name_obm = doc.get('custom_site_name') or (frappe.db.get_value('Buyer Master', doc.custom_offline_buyer_master, 'site_name') if doc.get('custom_offline_buyer_master') else '') %}",
	),
	(
		"{{ frappe.utils.fmt_money(doc.grand_total or 0, currency=doc.currency) }}",
		"{{ frappe.utils.fmt_money(doc.rounded_total or doc.grand_total or 0, currency=doc.currency) }}",
	),
]


def _apply_sales_order_pf_rewrites():
	"""Apply SALES_ORDER_PF_REWRITES to the 'Sales Order' print format: prefer the
	SO's own free-text address / site fields (populated by Data Import and the e-com
	flow) and show the rounded grand total. Idempotent: each rewrite only fires
	while its original source line is still present, so manual re-edits and repeat
	migrates are left alone."""
	if not frappe.db.exists("Print Format", PF_NAME):
		return
	html = frappe.db.get_value("Print Format", PF_NAME, "html") or ""
	if not html:
		return
	changed = False
	diverged = []
	for old, new in SALES_ORDER_PF_REWRITES:
		if new in html:
			continue  # already patched
		if old in html:
			html = html.replace(old, new)
			changed = True
		else:
			# Neither the original source line nor the patched version is present —
			# the on-site format has drifted from what this patch expects, so the
			# fallback can't be injected by string match. Surface it rather than
			# silently leaving imported orders printing "Address N/A" / "—".
			diverged.append(old)
	if changed:
		frappe.db.set_value("Print Format", PF_NAME, "html", html)
		frappe.db.commit()
		frappe.logger("alpinos").info(
			"Patched '%s' print format: SO custom address/site fields + rounded total." % PF_NAME
		)
	if diverged:
		frappe.log_error(
			title="Sales Order print format: rewrite not applied",
			message="These source lines were not found (format edited on-site?):\n\n"
			+ "\n".join(diverged),
		)


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

	# Prefer the SO's own free-text address / site fields for imported & e-com orders,
	# and show the rounded grand total. Runs before the bundle-loop early-returns
	# below so it always applies.
	_apply_sales_order_pf_rewrites()

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
