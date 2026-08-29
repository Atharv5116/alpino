import re

import frappe

PF_NAME = "Sales Order"

# iterate get_combined_items(doc) instead of doc.items so bundles explode/merge
ANCHOR_LOOP = "{% for row in doc.items %}"
COMBINE_LOOP = "{% set combined_items = get_combined_items(doc) %}\n  {% for row in combined_items %}"

# keep the Items count in the Total PCS summary consistent with the exploded rows
ANCHOR_COUNT = "{{ doc.items|length if doc.items else 0 }}"
COMBINE_COUNT = "{{ combined_items|length if combined_items else 0 }}"

# buyer master renamed "Offline Buyer Master" -> "Buyer Master" (2026-07-09);
# repair the stale name in every print format on migrate so PDF download doesn't crash
OLD_DOCTYPE = "Offline Buyer Master"
NEW_DOCTYPE = "Buyer Master"

# Idempotent (source_line, patched_line) rewrites for the "Sales Order" print format:
# 1-3) address/site: prefer the SO's own free-text fields (imported & e-com orders have
#      no linked Address/Buyer Master), falling back to the original sources.
# 4)   Grand Total: show the rounded total.
# 5)   Item Amount: print the stored GST-inclusive row.amount, not an MRP recompute.
# The totals footer is rewritten by _rewrite_so_totals_footer() below, not a tuple here.
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
	# resolve the Buyer Master site-wise (from the SO's site) instead of the family parent;
	# every buyer field reads obm_doc, so this one swap fixes them all.
	(
		"{% set obm_doc = frappe.get_doc('Buyer Master', doc.custom_offline_buyer_master) if doc.get('custom_offline_buyer_master') else None %}",
		"{% set obm_doc = site_buyer_master(doc.get('custom_site_name'), doc.get('custom_offline_buyer_master')) %}",
	),
	(
		"{{ frappe.utils.fmt_money(doc.grand_total or 0, currency=doc.currency) }}",
		"{{ frappe.utils.fmt_money(doc.rounded_total or doc.grand_total or 0, currency=doc.currency) }}",
	),
	(
		"{% set _mrp = frappe.utils.flt(row.custom_customer_mrp or 0) %}{% set _qty = frappe.utils.flt(row.qty or 0) %}{% set _flatpct = frappe.utils.flt(row.custom_flat_discount or 0) %}{% set _offerpct = frappe.utils.flt(row.custom_offer or 0) %}{% set _list = _mrp * _qty %}{% set _line_amt = frappe.utils.flt(_list * (100 - _flatpct) / 100.0 * (100 - _offerpct) / 100.0) %}{% set _amt_ns.sub = frappe.utils.flt(_amt_ns.sub) + _line_amt %}{{ frappe.utils.fmt_money(_line_amt, currency=doc.currency) }}",
		"{% set _line_amt = frappe.utils.flt(row.amount or 0) %}{% set _amt_ns.sub = frappe.utils.flt(_amt_ns.sub) + _line_amt %}{{ frappe.utils.fmt_money(_line_amt, currency=doc.currency) }}",
	),
]

# Totals footer: Sub Total (GST-inclusive) -> Cash Disc -> Grand Total, matching the reference PDF.
_FOOTER_NEW_BLOCK = (
	"<tr><td colspan='8' class='right bold'>Sub Total</td>"
	"<td class='right'>{{ frappe.utils.fmt_money(_amt_ns.sub, currency=doc.currency) }}</td></tr>\n    "
)

# already final when the Sub Total row is immediately followed by the Cash Disc row
_FOOTER_DONE = (
	"fmt_money(_amt_ns.sub, currency=doc.currency) }}</td></tr>\n    "
	"<tr><td colspan='8' class='right bold'>Cash Disc. (INR)</td>"
)

# from the Sub Total row up to (not including) the Cash Disc row; covers every prior variant
_FOOTER_RE = re.compile(
	r"<tr><td colspan='8' class='right bold'>Sub Total[^<]*</td>.*?"
	r"(?=<tr><td colspan='8' class='right bold'>Cash Disc\. \(INR\))",
	re.DOTALL,
)


def _rewrite_so_totals_footer():
	"""Rewrite the Sales Order totals footer to Sub Total (incl GST) -> Cash Disc -> Grand Total."""
	if not frappe.db.exists("Print Format", PF_NAME):
		return
	html = frappe.db.get_value("Print Format", PF_NAME, "html") or ""
	if not html or _FOOTER_DONE in html:
		return
	new_html, n = _FOOTER_RE.subn(_FOOTER_NEW_BLOCK, html, count=1)
	if n:
		frappe.db.set_value("Print Format", PF_NAME, "html", new_html)
		frappe.db.commit()
		frappe.logger("alpinos").info(
			"Patched '%s' totals footer: Sub Total (incl GST) -> Cash Disc -> Grand Total." % PF_NAME
		)


def _apply_sales_order_pf_rewrites():
	"""Apply SALES_ORDER_PF_REWRITES to the Sales Order print format (idempotent)."""
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
			# neither the source nor the patched line is present — format drifted on-site; surface it
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


_GST_EXCL_NOTE_MARKER = "alp-gst-excl-note"


def _inject_gst_exclusive_note():
	"""Prepend a GST-exclusive-buyer note to the Sales Order format (idempotent)."""
	if not frappe.db.exists("Print Format", PF_NAME):
		return
	html = frappe.db.get_value("Print Format", PF_NAME, "html") or ""
	if not html or _GST_EXCL_NOTE_MARKER in html:
		return
	note = (
		"{% if doc.custom_gst_exclusive_buyer %}"
		'<div class="' + _GST_EXCL_NOTE_MARKER + '" style="border:1px solid #ffe69c; '
		'background:#fff3cd; color:#664d03; padding:6px 10px; margin:0 0 8px 0; '
		'font-size:11px; font-weight:bold; border-radius:4px;">'
		"MRP is inclusive of GST. Selling Price, Amount and Grand Total are exclusive of GST."
		"</div>{% endif %}\n"
	)
	frappe.db.set_value("Print Format", PF_NAME, "html", note + html)
	frappe.logger("alpinos").info("Injected GST-exclusive note into '%s'." % PF_NAME)


# ── Selling Price column (BRD: add a Selling Price column after MRP) ──────────
_SP_MRP_TH = '<th class=\'right\' style="color: #000; font-weight: 800;">MRP</th>'
_SP_TH = '<th class=\'right\' style="color: #000; font-weight: 800;">Selling Price</th>'
_SP_MRP_TD = "<td class='right'>{{ frappe.utils.fmt_money(row.custom_customer_mrp or 0, currency=doc.currency) }}</td>"
_SP_TD = "<td class='right'>{{ frappe.utils.fmt_money(row.custom_selling_price or 0, currency=doc.currency) }}</td>"
# the 10th column needs its own <col> in the colgroup or the Amount column collapses;
# "col-selling" is only an idempotency marker.
_SP_COL_OLD = '<col class="col-mrp"><col class="col-flat">'
_SP_COL_NEW = '<col class="col-mrp"><col class="col-mrp col-selling"><col class="col-flat">'


def _add_selling_price_column():
	"""Add a Selling Price column after MRP, bumping the colspans and colgroup to match."""
	if not frappe.db.exists("Print Format", PF_NAME):
		return
	html = frappe.db.get_value("Print Format", PF_NAME, "html") or ""
	if not html:
		return
	changed = False

	# (1) header + body cell + colspans, only if the column isn't there yet
	if _SP_TH not in html:
		if _SP_MRP_TH not in html or _SP_MRP_TD not in html:
			frappe.log_error(
				title="Sales Order print format: Selling Price column skipped",
				message="MRP header/body cell not found — format edited on-site?",
			)
		else:
			html = html.replace(_SP_MRP_TH, _SP_MRP_TH + _SP_TH, 1)  # header cell after MRP
			html = html.replace(_SP_MRP_TD, _SP_MRP_TD + _SP_TD, 1)  # body cell after MRP
			html = html.replace(
				"<tr><th colspan='9' class='center bg-grey'",
				"<tr><th colspan='10' class='center bg-grey'",
			)
			html = html.replace("colspan='8' class='right bold'", "colspan='9' class='right bold'")
			changed = True

	# (2) matching <col> in the colgroup; also repairs formats left with a 9-col colgroup
	if "col-selling" not in html and _SP_COL_OLD in html:
		html = html.replace(_SP_COL_OLD, _SP_COL_NEW, 1)
		changed = True

	if changed:
		frappe.db.set_value("Print Format", PF_NAME, "html", html)
		frappe.db.commit()
		frappe.logger("alpinos").info("Patched Selling Price column / colgroup on '%s'." % PF_NAME)


def execute():
	"""Patch the Sales Order print format on migrate (bundles, address/site, totals, columns)."""
	_fix_renamed_doctype_refs()
	frappe.db.commit()  # persist the doctype-name repair regardless of the bundle path below

	# address/site fields + rounded total; runs before the bundle-loop early-returns
	_apply_sales_order_pf_rewrites()

	# GST-exclusive buyer note
	_inject_gst_exclusive_note()

	# Selling Price column after MRP
	_add_selling_price_column()

	# collapse the totals footer (handled separately from the tuple rewrites)
	_rewrite_so_totals_footer()

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
