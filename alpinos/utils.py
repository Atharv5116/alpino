import frappe
from frappe.utils import flt
import math

def get_combined_items(doc):
	"""Explodes product bundles and groups items if combine_product_bundles is checked on the Offline Buyer Master."""
	obm_name = doc.get("custom_offline_buyer_master")
	if not obm_name and doc.get("customer"):
		obm_name = frappe.db.get_value("Offline Buyer Master", {"customer": doc.customer}, "name")
	
	combine_product_bundles = True
	if obm_name:
		val = frappe.db.get_value("Offline Buyer Master", obm_name, "combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

	if not combine_product_bundles:
		# Return items as they are
		return doc.items

	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
	from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor

	combined = {}
	
	def add_item_to_combined(item_code, qty, parent_row):
		# Fetch child pricing
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

		# Fetch item UOM and name safely
		res_item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
		item_name = res_item.get("item_name") if res_item else item_code
		uom = res_item.get("stock_uom") if res_item else "Nos"

		if item_code not in combined:
			combined[item_code] = {
				"item_code": item_code,
				"item_name": item_name,
				"uom": uom,
				"qty": 0.0,
				"custom_customer_mrp": mrp,
				"custom_flat_discount": flat,
				"custom_offer": flt(parent_row.get("custom_offer") or 0),
				"custom_additional_discount": flt(parent_row.get("custom_additional_discount") or 0),
				"custom_selling_price": sp,
				"custom_product_image": parent_row.get("custom_product_image"),
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
				add_item_to_combined(r.item_code, flt(r.qty), r)

	# Convert back to a list of row-like dict objects (using frappe._dict to support dot notation in Jinja)
	result = []
	for idx, (code, item_dict) in enumerate(combined.items(), start=1):
		cf = flt(get_box_conversion_factor(code))
		item_dict["custom_box"] = math.ceil(item_dict["qty"] / cf) if cf else 0
		item_dict["idx"] = idx
		result.append(frappe._dict(item_dict))

	return result

# Expose to Jinja environment
jinja_methods = {
	"get_combined_items": get_combined_items
}
