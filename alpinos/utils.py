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

	combined = {}

	def add_item_to_combined(item_code, qty, parent_row, source_row=None):
		"""Add `qty` of `item_code` to the combined map.

		`source_row` is the saved Sales Order Item whose stored pricing is
		authoritative — passed for a plain line so the print shows exactly what the
		order was confirmed at. Left None for exploded bundle components, which have
		no saved row and are therefore priced from the buyer catalog as a fallback.
		"""
		# Fetch item UOM and name safely
		res_item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "valuation_rate"], as_dict=True)
		item_name = res_item.get("item_name") if res_item else item_code
		uom = res_item.get("stock_uom") if res_item else "Nos"

		if source_row is not None:
			# Carry the values saved on the Sales Order Item verbatim.
			item_mrp = flt(source_row.get("custom_item_mrp") or 0) or (flt(res_item.get("valuation_rate")) if res_item else 0)
			mrp = flt(source_row.get("custom_customer_mrp") or 0)
			flat = flt(source_row.get("custom_flat_discount") or 0)
			offer = flt(source_row.get("custom_offer") or 0)
			add_disc = flt(source_row.get("custom_additional_discount") or 0)
			sp = flt(source_row.get("custom_selling_price") or source_row.get("rate") or 0)
			image = source_row.get("custom_product_image")
			# The saved row's own name/uom win (e-com & bundle rows may override the Item master).
			if source_row.get("item_name"):
				item_name = source_row.get("item_name")
			if source_row.get("uom"):
				uom = source_row.get("uom")
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
			image = parent_row.get("custom_product_image")

		if item_code not in combined:
			combined[item_code] = {
				"item_code": item_code,
				"item_name": item_name,
				"uom": uom,
				"qty": 0.0,
				"custom_item_mrp": item_mrp,
				"custom_customer_mrp": mrp,
				"custom_flat_discount": flat,
				"custom_offer": offer,
				"custom_additional_discount": add_disc,
				"custom_selling_price": sp,
				"custom_product_image": image,
			}
		combined[item_code]["qty"] += qty

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
		# Line amount computed on the SAME basis the print format shows — MRP less the
		# flat and offer discounts — so this field agrees with the printed Amount column
		# and with the on-screen Sales Order View (no offer double-application).
		item_dict["amount"] = flt(
			flt(item_dict.get("custom_customer_mrp")) * flt(item_dict["qty"])
			* (1 - flt(item_dict.get("custom_flat_discount")) / 100.0)
			* (1 - flt(item_dict.get("custom_offer")) / 100.0),
			2,
		)
		item_dict["custom_item_tax"] = 0
		result.append(frappe._dict(item_dict))

	return result

# Expose to Jinja environment
jinja_methods = {
	"get_combined_items": get_combined_items
}
