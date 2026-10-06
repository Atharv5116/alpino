import frappe
from frappe.utils import flt
import math

def _doc_tax_rate(doc):
	"""Combined On-Net-Total tax rate on the order (0 for GST-exclusive buyers)."""
	return flt(
		sum(
			flt(t.get("rate"))
			for t in (doc.get("taxes") or [])
			if t.get("charge_type") == "On Net Total"
		)
	)


def _inclusive_line_amount(row, doc_tax_rate=0.0):
	"""GST-inclusive line total for a saved Sales Order Item."""
	net = flt(row.get("amount"))
	tax = flt(row.get("custom_item_tax"))
	if tax:
		return flt(net + tax, 2)

	sp = flt(row.get("custom_selling_price"))
	if sp:
		add_disc = flt(row.get("custom_additional_discount"))
		base = flt(sp * flt(row.get("qty")) * (100 - add_disc) / 100.0, 2)
	else:
		base = net

	if doc_tax_rate and not flt(row.get("custom_gst_percent")):
		return flt(base * (100 + doc_tax_rate) / 100.0, 2)
	return base


def get_combined_items(doc):
	"""Explode product bundles and optionally group items (per Buyer Master combine_product_bundles)."""
	obm_name = doc.get("custom_offline_buyer_master")
	if not obm_name and doc.get("customer"):
		obm_name = frappe.db.get_value("Buyer Master", {"customer": doc.customer}, "name")

	combine_product_bundles = True
	if obm_name:
		val = frappe.db.get_value("Buyer Master", obm_name, "combine_product_bundles")
		if val is not None:
			combine_product_bundles = bool(val)

	doc_tax_rate = _doc_tax_rate(doc)

	if not combine_product_bundles:
		# Copy rows but swap in the GST-inclusive Amount (saved row.amount is net).
		return [
			frappe._dict(dict(r.as_dict(), amount=_inclusive_line_amount(r, doc_tax_rate)))
			for r in doc.items
		]

	from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
	from alpinos.sales_order_api import get_customer_item_mrp, get_box_conversion_factor, _bundle_components
	from alpinos.pdf_tolerant import first_existing_file_url

	combined = {}

	def _pick_image(live_img, snapshot_img, variant_of):
		"""First product image that resolves to a real file; '' when there's nothing to show."""
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
		"""Add qty of item_code to the combined map (source_row = saved row, else catalog fallback)."""
		res_item = frappe.db.get_value(
			"Item", item_code,
			["item_name", "stock_uom", "valuation_rate", "image", "variant_of"],
			as_dict=True,
		)
		item_name = res_item.get("item_name") if res_item else item_code
		uom = res_item.get("stock_uom") if res_item else "Nos"
		# Prefer the live Item-master image; the SO Item snapshot is only a fallback.
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
			line_amt = _inclusive_line_amount(source_row, doc_tax_rate)
		else:
			# Exploded bundle component: no saved price, derive from the buyer catalog.
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
			# No saved row: net selling price x qty, less the parent's offer/additional discount.
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
				# Fall back to Item.custom_is_bundle + Product Bundle Mapping (no native Product Bundle).
				comps = _bundle_components(r.item_code)
				if comps:
					for c in comps:
						add_item_to_combined(c.get("item"), flt(c.get("base_qty")) * flt(r.qty), r)
				else:
					# Plain saved line: price it from the Sales Order Item itself.
					add_item_to_combined(r.item_code, flt(r.qty), r, source_row=r)

	# Back to a list of _dict rows for Jinja.
	result = []
	for idx, (code, item_dict) in enumerate(combined.items(), start=1):
		cf = flt(get_box_conversion_factor(code))
		item_dict["custom_box"] = math.ceil(item_dict["qty"] / cf) if cf else 0
		item_dict["idx"] = idx
		# Amount = accumulated selling price x qty, GST-inclusive.
		item_dict["amount"] = flt(item_dict.get("amount") or 0, 2)
		item_dict["custom_item_tax"] = 0
		result.append(frappe._dict(item_dict))

	return result

def sku_sort_key(sku_no):
	"""Natural ascending sort key for an Item's SKU No; blanks sort last."""
	v = (sku_no or "").strip()
	if not v:
		return (2, 0, "")
	if v.isdigit():
		return (0, int(v), "")
	return (1, 0, v.lower())


def sort_locations_by_sku(locations):
	"""Pick List location rows sorted ascending by the Item's SKU No (read from Item master)."""
	rows = list(locations or [])
	cache = {}

	def _sku(row):
		code = row.get("item_code") if hasattr(row, "get") else getattr(row, "item_code", None)
		if not code:
			return ""
		if code not in cache:
			cache[code] = frappe.db.get_value("Item", code, "custom_sku_no") or ""
		return cache[code]

	return sorted(rows, key=lambda r: sku_sort_key(_sku(r)))


def pack_size(item_code):
	"""Units-per-box for a SKU as int; '' when unknown."""
	try:
		from alpinos.sales_order_api import get_box_conversion_factor
		f = flt(get_box_conversion_factor(item_code))
		return int(f) if f else ""
	except Exception:
		return ""


def available_stock(item_code):
	"""Total available stock for a SKU across warehouses; '' when unknown."""
	try:
		res = frappe.db.sql("SELECT SUM(actual_qty) FROM `tabBin` WHERE item_code=%s", item_code)
		v = flt(res[0][0]) if res and res[0][0] is not None else 0.0
		return int(v) if v == int(v) else round(v, 2)
	except Exception:
		return ""


def site_buyer_master(site_name, fallback=None):
	"""The Buyer Master that owns this site, WITHIN the order's own buyer family.

	The site is resolved inside the family of `fallback` -- the buyer the order is actually
	for -- and never across the whole table. Site names are not unique: "Maharashtra",
	"NW08" and the like are reused by different buyers, and a bare lookup with LIMIT 1
	returned whichever row the database happened to hand back first. That put a STRANGER'S
	record on the Sales Order PDF, which prints its contact number, email, GST Type, GSTIN
	and PAN -- so one buyer's tax identifiers could appear on another buyer's order.

	With no family to search, or no owner inside it, the order's own Buyer Master is used.
	"""
	name = None
	site_name = (site_name or "").strip()
	if site_name and fallback:
		try:
			from alpinos.sales_order_offline_buyer import (
				_masters_owning_site,
				masters_for_customer_business,
			)

			customer = frappe.db.get_value("Buyer Master", fallback, "customer")
			family = masters_for_customer_business(customer) if customer else []
			# The order's own master always counts as part of its family.
			family = list(set(family or []) | {fallback})
			owners = _masters_owning_site(family, site_name)
			if owners:
				# Prefer the order's own master when it owns the site too, so a buyer with
				# several masters on one site reports the one the order was raised against.
				name = fallback if fallback in owners else sorted(owners)[0]
		except Exception:
			# Never let a print fail over this; the order's own master is a safe answer.
			frappe.log_error(frappe.get_traceback(), "site_buyer_master lookup failed")
	name = name or fallback
	if name and frappe.db.exists("Buyer Master", name):
		return frappe.get_doc("Buyer Master", name)
	return None


def buyer_contact(doc):
	"""{phone, email} for a Sales Order, from the Buyer Master that owns its Site.

	One place for the rule, so a print format carries no logic of its own and every format
	answers the same way. Resolution:

	  1. the Buyer Master owning the order's Site, within the order's own buyer family
	  2. the order's own Buyer Master
	  3. the Sales Order's contact_mobile / contact_email
	  4. an em-dash

	Deliberately never reads the Address or Contact record. Those carry their own phone and
	email, they are commonly left on placeholder values, and taking them is how a PDF ends
	up printing "0" and "dummy@dummy.com" for a buyer whose real number is on file.
	"""
	dash = "\u2014"
	out = {"phone": dash, "email": dash, "source": "none"}
	try:
		obm = site_buyer_master(doc.get("custom_site_name"), doc.get("custom_offline_buyer_master"))
		if obm:
			phone = (obm.get("contact_no") or "").strip()
			email = (obm.get("email") or "").strip()
			if phone:
				out["phone"], out["source"] = phone, obm.name
			if email:
				out["email"] = email
				out["source"] = obm.name
		if out["phone"] == dash and (doc.get("contact_mobile") or "").strip():
			out["phone"], out["source"] = doc.get("contact_mobile").strip(), "sales order"
		if out["email"] == dash and (doc.get("contact_email") or "").strip():
			out["email"], out["source"] = doc.get("contact_email").strip(), "sales order"
	except Exception:
		# A print must never fail over a contact lookup.
		frappe.log_error(frappe.get_traceback(), "buyer_contact lookup failed")
	return out


jinja_methods = {
	"get_combined_items": get_combined_items,
	"pack_size": pack_size,
	"available_stock": available_stock,
	"sort_locations_by_sku": sort_locations_by_sku,
	"site_buyer_master": site_buyer_master,
	"buyer_contact": buyer_contact,
}
