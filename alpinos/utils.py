import frappe
from frappe.utils import flt
import math

def get_combined_items(doc):
	"""Explodes product bundles and groups items if combine_product_bundles is checked on the Buyer Master.

	Pricing rule: a plain (non-exploded) line reflects EXACTLY what the Sales Order
	stored — its own custom_customer_mrp / custom_flat_discount / custom_offer /
	custom_selling_price — so the printed PDF matches the on-screen Sales Order View
	and never silently re-prices a confirmed order from the (possibly since-edited)
	buyer catalog. Only exploded bundle components, which have no saved row of their
	own, are priced from the catalog as a fallback.
	"""
	obm_name = doc.get("custom_offline_buyer_master")
	if not obm_name and doc.get("customer"):
		obm_name = frappe.db.get_value("Buyer Master", {"customer": doc.customer}, "name")

	combine_product_bundles = True
	if obm_name:
		val = frappe.db.get_value("Buyer Master", obm_name, "combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

	if not combine_product_bundles:
		# Return items as they are
		return doc.items

	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
	from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor, _bundle_components
	from alpinos.pdf_tolerant import first_existing_file_url

	combined = {}

	def _pick_image(live_img, snapshot_img, variant_of):
		"""Choose a product image that actually exists, so a broken/missing primary
		falls back to another source. Order: current Item image -> the SO Item's own
		snapshot -> the variant's template Item image. Returns the first that resolves
		to a real file; if none do, the preferred URL (pdf_tolerant drops it if it's
		genuinely unreadable, so it never errors); '' when there's nothing to show."""
		cands = []
		for c in (live_img, snapshot_img):
			if c and c not in cands:
				cands.append(c)
		if variant_of:
			tmpl = frappe.db.get_value("Item", variant_of, "image")
			if tmpl and tmpl not in cands:
				cands.append(tmpl)
		if not cands:
			return ""
		return first_existing_file_url(cands) or cands[0]

	def add_item_to_combined(item_code, qty, parent_row, source_row=None):
		"""Add `qty` of `item_code` to the combined map.

		`source_row` is the saved Sales Order Item whose stored pricing is
		authoritative — passed for a plain line so the print shows exactly what the
		order was confirmed at. Left None for exploded bundle components, which have
		no saved row and are therefore priced from the buyer catalog as a fallback.
		"""
		# Fetch item UOM, name, CURRENT master image and variant parent safely
		res_item = frappe.db.get_value(
			"Item", item_code, ["item_name", "stock_uom", "valuation_rate", "image", "variant_of"], as_dict=True
		)
		item_name = res_item.get("item_name") if res_item else item_code
		uom = res_item.get("stock_uom") if res_item else "Nos"
		# Mirror the on-screen Sales Order View: prefer the live Item-master image so
		# pictures uploaded/changed after the order was placed still print; the SO Item's
		# custom_product_image is only a snapshot taken at creation (and may be empty).
		live_img = (res_item.get("image") if res_item else None) or None
		variant_of = res_item.get("variant_of") if res_item else None

		if source_row is not None:
			# Carry the values saved on the Sales Order Item verbatim.
			item_mrp = flt(source_row.get("custom_item_mrp") or 0) or (flt(res_item.get("valuation_rate")) if res_item else 0)
			mrp = flt(source_row.get("custom_customer_mrp") or 0)
			flat = flt(source_row.get("custom_flat_discount") or 0)
			offer = flt(source_row.get("custom_offer") or 0)
			add_disc = flt(source_row.get("custom_additional_discount") or 0)
			sp = flt(source_row.get("custom_selling_price") or source_row.get("rate") or 0)
			image = _pick_image(live_img, source_row.get("custom_product_image"), variant_of)
			# The saved row's own name/uom win (e-com & bundle rows may override the Item master).
			if source_row.get("item_name"):
				item_name = source_row.get("item_name")
			if source_row.get("uom"):
				uom = source_row.get("uom")
			# Authoritative net line total straight off the saved row. The discount may be
			# a Flat/Offer % OR baked into the selling price, so we take the stored amount
			# rather than recomputing from MRP (which would drop a price-based discount).
			line_amt = flt(source_row.get("amount"))
			if not line_amt:
				line_amt = flt(sp) * flt(qty)
		else:
			# Exploded bundle component: no saved price -> derive from the buyer catalog.
			mrp = 0
			flat = 0
			sp = 0
			res = get_offline_buyer_item_rate(doc.customer, item_code)
			if res and flt(res.get("mrp")) > 0:
				mrp = flt(res.get("mrp"))
				flat = flt(res.get("margin_percent"))
				sp = flt(res.get("rate"))
			else:
				res_mrp = get_customer_item_mrp(doc.customer, item_code)
				if res_mrp:
					mrp = flt(res_mrp)
				else:
					mrp = flt(frappe.db.get_value("Item", item_code, "valuation_rate") or 0)
				sp = mrp * (1 - flat / 100.0)
			item_mrp = flt(res_item.get("valuation_rate")) if res_item else 0
			offer = flt(parent_row.get("custom_offer") or 0)
			add_disc = flt(parent_row.get("custom_additional_discount") or 0)
			image = _pick_image(live_img, parent_row.get("custom_product_image"), variant_of)
			# Bundle component has no saved row -> net selling price x qty, less the
			# parent's offer / additional discount.
			line_amt = flt(sp) * flt(qty) * (100 - offer) / 100.0 * (100 - add_disc) / 100.0

		if item_code not in combined:
			combined[item_code] = {
				"item_code": item_code,
				"item_name": item_name,
				"uom": uom,
				"qty": 0.0,
				"amount": 0.0,
				"custom_item_mrp": item_mrp,
				"custom_customer_mrp": mrp,
				"custom_flat_discount": flat,
				"custom_offer": offer,
				"custom_additional_discount": add_disc,
				"custom_selling_price": sp,
				"custom_product_image": image,
			}
		combined[item_code]["qty"] += qty
		combined[item_code]["amount"] = flt(combined[item_code].get("amount") or 0) + flt(line_amt)

	for r in doc.items:
		packed = [p for p in (doc.get("packed_items") or []) if p.parent_detail_docname == r.name]
		if packed:
			for p in packed:
				add_item_to_combined(p.item_code, flt(p.qty), r)
		else:
			pb_name = frappe.db.get_value("Product Bundle", {"new_item_code": r.item_code}, "name")
			if pb_name:
				pb_items = frappe.db.get_all("Product Bundle Item", filters={"parent": pb_name}, fields=["item_code", "qty"])
				for p in pb_items:
					add_item_to_combined(p.item_code, flt(p.qty) * flt(r.qty), r)
			else:
				# Alpino bundles are defined via Item.custom_is_bundle + Product Bundle Mapping,
				# which can exist WITHOUT a native Product Bundle (and the SO may have no packed
				# items). Fall back to that mapping — the same source the pick list / DN use — so
				# the bundle still explodes when "Combine Product Bundles" is on.
				comps = _bundle_components(r.item_code)
				if comps:
					for c in comps:
						add_item_to_combined(c.get("item"), flt(c.get("base_qty")) * flt(r.qty), r)
				else:
					# Plain saved line: price it from the Sales Order Item itself.
					add_item_to_combined(r.item_code, flt(r.qty), r, source_row=r)

	# Convert back to a list of row-like dict objects (using frappe._dict to support dot notation in Jinja)
	result = []
	for idx, (code, item_dict) in enumerate(combined.items(), start=1):
		cf = flt(get_box_conversion_factor(code))
		item_dict["custom_box"] = math.ceil(item_dict["qty"] / cf) if cf else 0
		item_dict["idx"] = idx
		# Amount = the order's own stored net line total (accumulated above), NOT a
		# recompute from MRP x %s — the discount can live in the selling price, which a
		# MRP-based recompute would ignore and print at gross list value.
		item_dict["amount"] = flt(item_dict.get("amount") or 0, 2)
		item_dict["custom_item_tax"] = 0
		result.append(frappe._dict(item_dict))

	return result

# Expose to Jinja environment
jinja_methods = {
	"get_combined_items": get_combined_items
}
