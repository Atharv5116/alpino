# Update the Site Name on specific Sales Orders and cascade every site-derived
# field (billing/shipping GSTIN, billing/shipping address text, tax category +
# tax template) exactly the way selecting a site on the entry page does.
#
# Reuses the app's own derivation:
#   _gst_for_site                     -> site's GSTIN (owning Buyer Master)
#   get_customer_addresses_for_display-> the site's billing/shipping address rows
#   get_tax_template_for_sales_order  -> tax category + template from billing state
#
# Dry run by default: prints current -> new for every field and writes nothing.
# Draft orders are re-saved (validate/GST sync + tax rebuild run cleanly). Submitted
# orders are reported and skipped for now — changing their tax rows needs a separate
# decision (see the dry-run output).
#
#   bench --site <site> execute alpinos.so_update_site.run
#   bench --site <site> execute alpinos.so_update_site.run --kwargs "{'apply': 1}"

import frappe
from frappe.utils import cint

from alpinos.sales_order_offline_buyer import _gst_for_site, get_customer_addresses_for_display
from alpinos.sales_order_api import get_tax_template_for_sales_order

# Sales Order -> new Site Name (from "Sales Order (3).xlsx")
SITE_MAP = {
	"SOR-2627-00450": "BCPL - Kundli - Feeder Warehouse",
	"SOR-2627-00451": "BCPL - Kolkata K4 - Feeder Warehouse",
	"SOR-2627-00452": "BCPL - Dehradun - Feeder Warehouse",
	"SOR-2627-00453": "BCPL - Mumbai M10 - Feeder Warehouse",
	"SOR-2627-00454": "BCPL - Dasna D3 - Feeder Warehouse",
	"SOR-2627-00455": "BCPL - Noida N1 - Feeder Warehouse",
	"SOR-2627-00456": "BCPL - Surat S1 - Feeder Warehouse",
	"SOR-2627-00457": "BCPL - Ranchi R1 - Feeder Warehouse",
	"SOR-2627-00458": "BCPL - Lucknow L5 - Feeder Warehouse",
	"SOR-2627-00459": "BCPL - Patna P1 - Feeder Warehouse",
	"SOR-2627-00460": "BCPL - Rajpura R2 - Feeder Warehouse",
	"SOR-2627-00461": "BCPL - Kolkata K6 - Feeder Warehouse",
	"SOR-2627-00462": "BCPL - Jaipur J4 - Feeder Warehouse",
	"SOR-2627-00463": "BCPL - Varanasi V2 - Feeder Warehouse",
	"SOR-2627-00464": "BCPL - Vijayawada - Feeder Warehouse",
	"SOR-2627-00465": "BCPL - Farukhnagar F2 - Feeder Warehouse",
	"SOR-2627-00466": "BCPL - Mumbai M11 - Feeder Warehouse",
	"SOR-2627-00467": "BCPL - Jaipur J3 - Feeder Warehouse",
	"SOR-2627-00468": "BCPL - Hyderabad H3 - Feeder Warehouse",
	"SOR-2627-00469": "BCPL - Indore I2 - Feeder Warehouse",
	"SOR-2627-00470": "KIRA-Pudur_Hyd_MH_Dry",
}


def _derive(so, new_site):
	"""What the site change should cascade to — mirrors the entry page."""
	# Site-wise GST only — no fallback to the family parent's GSTIN (blank if unresolved).
	gstin = (_gst_for_site(new_site, "") or "").strip().upper()

	addrs = get_customer_addresses_for_display(so.customer, new_site) or []
	billing = next((a for a in addrs if a.get("is_primary")), addrs[0] if addrs else None)
	shipping = next((a for a in addrs if a.get("is_shipping")), billing)

	tax = get_tax_template_for_sales_order(
		so.customer, so.company,
		billing.get("name") if billing else None,
		shipping.get("name") if shipping else None,
	) or {}

	return {
		"n_addrs": len(addrs),
		"gstin": gstin,
		"billing_text": (billing.get("value") if billing else "") or "",
		"shipping_text": (shipping.get("value") if shipping else "") or "",
		"billing_name": billing.get("name") if billing else None,
		"shipping_name": shipping.get("name") if shipping else None,
		"tax_category": tax.get("tax_category"),
		"taxes_and_charges": tax.get("taxes_and_charges"),
	}


def _cut(v, n=44):
	return (str(v or "")[:n])


def run(apply=0):
	apply = cint(apply)
	drafts = submitted = missing = 0
	for so_name, new_site in SITE_MAP.items():
		if not frappe.db.exists("Sales Order", so_name):
			print("MISSING SO:", so_name)
			missing += 1
			continue
		so = frappe.get_doc("Sales Order", so_name)
		d = _derive(so, new_site)
		ds = {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(so.docstatus, so.docstatus)
		print(f"\n==== {so_name}  [{ds}]  customer={so.customer}")
		print(f"  site:      {_cut(so.get('custom_site_name'))!r} -> {new_site!r}")
		print(f"  GSTIN:     {_cut(so.get('custom_billing_gstin'))!r} -> {d['gstin']!r}   (addresses resolved: {d['n_addrs']})")
		print(f"  bill addr: {_cut(so.get('custom_billing_address_text'))!r} -> {_cut(d['billing_text'])!r}")
		print(f"  ship addr: {_cut(so.get('custom_shipping_address_text'))!r} -> {_cut(d['shipping_text'])!r}")
		print(f"  tax cat:   {_cut(so.get('tax_category'))!r} -> {_cut(d['tax_category'])!r}")
		print(f"  tax tmpl:  {_cut(so.get('taxes_and_charges'))!r} -> {_cut(d['taxes_and_charges'])!r}")
		if not d["n_addrs"]:
			print("  !! NO addresses resolved for this site under this customer — the site may")
			print("     belong to a different buyer/customer, or its Address isn't materialised yet.")

		if so.docstatus == 0:
			drafts += 1
			if apply:
				_apply_draft(so, new_site, d)
		elif so.docstatus == 1:
			submitted += 1

	print(f"\n{'APPLIED' if apply else 'DRY RUN'}: {len(SITE_MAP)} mapped | drafts {drafts} | submitted {submitted} | missing {missing}")
	if apply:
		frappe.db.commit()
	if submitted:
		print(f"NOTE: {submitted} order(s) are SUBMITTED and were NOT changed — changing their tax")
		print("rows needs a separate call; confirm after reviewing the dry run.")
	if not apply:
		print("Re-run with --kwargs \"{'apply': 1}\" to write the DRAFT orders.")


def _apply_draft(so, new_site, d):
	"""Draft order: set the cascaded fields and re-save (validate GST sync + tax
	template rebuild + totals recompute run the same as a manual edit)."""
	so.custom_site_name = new_site
	so.custom_billing_address_text = d["billing_text"]
	so.custom_shipping_address_text = d["shipping_text"]
	so.custom_billing_gstin = d["gstin"]
	so.custom_shipping_gstin = d["gstin"]
	so.tax_id = d["gstin"]
	if d["tax_category"]:
		so.tax_category = d["tax_category"]
	if d["taxes_and_charges"]:
		so.taxes_and_charges = d["taxes_and_charges"]
	so.flags.ignore_permissions = True
	so.save()
