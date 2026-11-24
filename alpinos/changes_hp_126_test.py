"""Changes(HP) #126, Quotation: Line Amount including GST, Cash Discount % shown as soon as it is
entered (the form's preview is the save's own pricing), full Billing / Shipping addresses in the
pickers and under the fields. TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.changes_hp_126_test.run
"""

import json

import frappe
from frappe.utils import flt

R = []
TAG = "HPS" + frappe.generate_hash(length=4).upper()
BUYER = "OBM-2026-00169"  # Approved, priced Buyer Catalog (also used by quotation_direct_test)
F = frappe._dict()


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.clear_cache()
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _draft():
	from alpinos.offline_sales import order_link as L

	buyer = frappe.get_doc("Buyer Master", BUYER)
	billing, shipping = L._addresses(buyer)
	items = [r.item_code for r in L.visible_items(buyer, limit=2)]
	rows = L._priced_rows(buyer, [{"item_code": i, "qty": 12} for i in items])
	q = frappe.new_doc("Quotation")
	q.update({"quotation_to": "Buyer Master", "party_name": BUYER, "company": L._company(buyer), "order_type": buyer.customer_type})
	ship = shipping[0]["address"] if shipping else billing[0]["address"]
	L._apply(q, buyer, L._header(buyer, {"billing_address": billing[0]["address"], "shipping_address": ship, "contact_person": "", "remarks": TAG}), rows)
	q.insert(ignore_permissions=True)
	return q


def _run():
	from alpinos.offline_sales import opportunity as OPP
	from alpinos.offline_sales import quotation as Q

	if not frappe.db.exists("Buyer Master", BUYER):
		R.append(("ERR ", "fixture", f"{BUYER} is not on this site"))
		return
	q = _draft()
	F.q = q.name

	def _incl_gst():
		_assert(len(q.items) >= 1, "no lines")
		for r in q.items:
			want = flt(flt(r.amount) + flt(r.custom_item_tax), 2)
			_assert(flt(r.custom_amount_incl_gst) == want, f"{r.item_code}: {r.custom_amount_incl_gst} vs {want}")
			paid = flt(r.custom_selling_price) * flt(r.qty) * (1 - flt(r.custom_additional_discount) / 100)
			_assert(abs(flt(r.custom_amount_incl_gst) - paid) <= 0.02, f"{r.item_code}: {r.custom_amount_incl_gst} vs Selling Price x Qty {paid}")
		total = sum(flt(r.custom_amount_incl_gst) for r in q.items)
		_assert(abs(total - (flt(q.net_total) + flt(q.total_taxes_and_charges))) <= 0.05, (total, q.net_total, q.total_taxes_and_charges))

	check("Line Amount incl. GST = Net Amount + the line's GST (= Selling Price x Qty); lines add up to Net Total + GST", _incl_gst)

	def _grid():
		meta = frappe.get_meta("Quotation Item")
		_assert(meta.get_field("custom_amount_incl_gst").in_list_view, "Line Amount incl. GST not in the grid")
		_assert(not meta.get_field("amount").in_list_view, "the net Amount is still a grid column")
		_assert(meta.get_field("custom_amount_incl_gst").read_only, "Line Amount incl. GST is editable")

	check("Items grid shows Line Amount incl. GST in place of the net Amount", _grid)

	def _cash_preview():
		base = flt(q.net_total) + flt(q.total_taxes_and_charges)
		d = q.as_dict(convert_dates_to_str=True)
		d["custom_cash_discount"] = 3
		p = Q.preview_totals(json.dumps(d, default=str))
		_assert(p, "no preview")
		disc = flt(base * 3 / 100, 2)
		_assert(abs(flt(p["custom_cash_discount_amount"]) - disc) <= 0.01, (p["custom_cash_discount_amount"], disc))
		_assert(abs(flt(p["grand_total"]) - (base - disc)) <= 0.02, (p["grand_total"], base - disc))
		stored = frappe.db.get_value("Quotation", q.name, ["custom_cash_discount", "grand_total"], as_dict=True)
		_assert(not flt(stored.custom_cash_discount) and flt(stored.grand_total) == flt(q.grand_total), f"preview wrote: {stored}")
		F.preview = p

	check("Cash Discount % entered: the preview shows the amount off the Grand Total; nothing is saved", _cash_preview)

	def _same_as_save():
		_assert(F.get("preview"), "no preview from the step before")
		d = frappe.get_doc("Quotation", q.name)
		d.custom_cash_discount = 3
		d.save(ignore_permissions=True)
		for f in ("custom_cash_discount_amount", "discount_amount", "net_total", "total_taxes_and_charges", "grand_total", "rounded_total"):
			_assert(flt(d.get(f)) == flt(F.preview[f]), f"{f}: saved {d.get(f)} vs preview {F.preview[f]}")

	check("Saved with that Cash Discount %: the same figures the form showed", _same_as_save)

	def _qty_preview():
		d = frappe.get_doc("Quotation", q.name)
		raw = d.as_dict(convert_dates_to_str=True)
		raw["items"][0]["qty"] = 20
		p = Q.preview_totals(json.dumps(raw, default=str))
		d.items[0].qty = 20
		d.save(ignore_permissions=True)
		line = next(x for x in p["items"] if x["idx"] == 1)
		_assert(flt(line["custom_amount_incl_gst"]) == flt(d.items[0].custom_amount_incl_gst), (line, d.items[0].custom_amount_incl_gst))
		_assert(flt(p["grand_total"]) == flt(d.grand_total), (p["grand_total"], d.grand_total))

	check("A quantity changed on the form: preview line and Grand Total = what the save stores", _qty_preview)

	def _not_for_finalized():
		d = q.as_dict(convert_dates_to_str=True)
		d["custom_quotation_status"] = "Finalized"
		d["docstatus"] = 1
		_assert(Q.preview_totals(json.dumps(d, default=str)) is None, "previewed a Finalized Quotation")

	check("No preview once the Quotation is Finalized (its values are locked)", _not_for_finalized)

	def _picker():
		d = frappe.get_doc("Quotation", q.name)
		rows = OPP.address_query("Address", "", "name", 0, 20, {"party_name": BUYER, "kind": "billing"})
		_assert(rows, "no billing addresses offered")
		addr = frappe.db.get_value("Address", rows[0][0], ["address_line1", "city", "pincode"], as_dict=True)
		for part in (addr.address_line1, addr.city, addr.pincode):
			if part:
				_assert(str(part).strip() in rows[0][1], f"'{part}' not in the option text '{rows[0][1]}'")
		text = OPP.address_text(BUYER, d.customer_address)
		_assert(text and (frappe.db.get_value("Address", d.customer_address, "address_line1") or "").strip() in text, text)

	check("Billing / Shipping pickers list the whole address; the picked one is shown in full", _picker)

	def _not_others():
		other = frappe.db.sql(
			"""SELECT a.name FROM `tabAddress` a WHERE a.name NOT IN (
			       SELECT dl.parent FROM `tabDynamic Link` dl WHERE dl.parenttype = 'Address' AND dl.link_name = %s)
			   LIMIT 1""",
			frappe.db.get_value("Buyer Master", BUYER, "customer"),
		)
		if other:
			_assert(OPP.address_text(BUYER, other[0][0]) == "", "another buyer's address was shown")
		user = f"{TAG.lower()}.none@example.com"
		frappe.get_doc({"doctype": "User", "email": user, "first_name": TAG, "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			_assert(OPP.address_text(BUYER, q.customer_address) == "", "shown to a user without access to the Buyer")
		finally:
			frappe.set_user("Administrator")

	check("No address for another buyer's address, or for a user without access to the Buyer", _not_others)
