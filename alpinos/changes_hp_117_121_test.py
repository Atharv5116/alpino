"""Changes(HP) rows of 16 Nov 2026 (#117-#121), server side. TEST sites only.

Run:  bench --site <test site> execute alpinos.changes_hp_117_121_test.run

Everything is rolled back (commits disabled for the run). The screens (#117 button label,
#118 typing in GST No., #119 the GST Type change on the form, #120 / #121 the Edit and
Duplicate pages) are checked in the browser run; this covers what the server decides.
"""

import frappe
from frappe.utils import flt, today

from alpinos.offline_sales import offline_sales_test as OST

R = []
TAG = "HPQ" + frappe.generate_hash(length=4).upper()


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


def refused(fn):
	sp = "hpq_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	finally:
		frappe.set_user("Administrator")
	return ""


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


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
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _run():
	OST._fixtures()  # people, customer type, city; rolled back with the run
	_line_percent()
	_payloads()
	_gst_type_change()


# ----------------------------------------------------------------------------- #121


def _line_percent():
	from alpinos.sales_order_api import line_percent

	def _cases():
		_assert(line_percent(0, 265.33, 419) == 36.68, line_percent(0, 265.33, 419))
		_assert(line_percent(None, 240, 300) == 20, "blank stored")
		_assert(line_percent(10, 90, 100) == 10, "a stored percentage is kept")
		_assert(line_percent(0, 419, 419) == 0, "at MRP")
		_assert(line_percent(0, 500, 419) == 0, "above MRP")
		_assert(line_percent(0, 0, 419) == 0, "no price")
		_assert(line_percent(0, 50, 0) == 0, "no MRP")

	check("#121 the percentage a Selling Price means, only where none is stored and it sells below MRP", _cases)


# ----------------------------------------------------------------------------- #120 / #121 payloads


def _order(name, channel, **values):
	F = OST.F
	customer = _insert("Customer", name=f"{name}-C", customer_name=f"{name} C", customer_type="Company")
	base = dict(name=name, company=F.company, customer=customer, customer_name=f"{name} C", transaction_date=today(),
		custom_channel=channel, docstatus=0, custom_workflow_status="Draft", currency="INR", conversion_rate=1,
		selling_price_list="Standard Selling", plc_conversion_rate=1, order_type="Modern Trade")
	base.update(values)
	return _insert("Sales Order", **base)


def _line(parent, idx, item_code, mrp, selling_price, **values):
	return _insert("Sales Order Item", name=f"{parent}-I{idx}", parent=parent, parenttype="Sales Order", parentfield="items",
		idx=idx, item_code=item_code, item_name=item_code, qty=2, stock_qty=2, rate=selling_price, amount=2 * selling_price,
		custom_customer_mrp=mrp, custom_selling_price=selling_price, uom="Nos", conversion_factor=1, **values)


def _payloads():
	from alpinos.ecom_sales_order_api import get_ecom_so_entry_payload
	from alpinos.sales_order_api import get_so_entry_payload

	items = frappe.get_all("Item", filters={"disabled": 0, "is_stock_item": 1}, pluck="name", limit=3)

	# what Sales Order Import leaves: the PO in po_no only, Selling Price without a percentage
	ecom = _order(f"{TAG}-E", "E-com", po_no="IMP-PO-1")
	_line(ecom, 1, items[0], 419, 265.33, custom_margin_percent=0)
	_line(ecom, 2, items[1], 200, 180, custom_margin_percent=12.5)

	def _ecom():
		p = get_ecom_so_entry_payload(ecom)
		_assert(p["po_number"] == "IMP-PO-1", p["po_number"])
		got = {r["item_code"]: (r["margin_percent"], r["custom_selling_price"]) for r in p["items"]}
		_assert(got[items[0]] == (36.68, 265.33), got[items[0]])
		_assert(got[items[1]] == (12.5, 180), "a stored margin changed: " + str(got[items[1]]))

	check("#120 #121 e-com Edit / Duplicate: PO Number from po_no, Margin % from the Selling Price, price as stored", _ecom)

	mt = _order(f"{TAG}-M", "Offline", po_no="IMP-PO-2")
	_line(mt, 1, items[0], 300, 240, custom_flat_discount=0)
	_line(mt, 2, items[1], 300, 216, custom_flat_discount=0, custom_offer="10")
	_line(mt, 3, items[2], 300, 270, custom_flat_discount=10)

	def _offline():
		p = get_so_entry_payload(mt)
		_assert(p["po_no"] == "IMP-PO-2" and p["ecom"]["po_number"] == "IMP-PO-2", (p["po_no"], p["ecom"]["po_number"]))
		got = {r["item_code"]: (flt(r["flat_discount"]), flt(r["custom_selling_price"])) for r in p["items"]}
		_assert(got[items[0]] == (20, 240), got[items[0]])
		_assert(got[items[1]][0] == 0, "an Offer line had its Flat Discount derived: " + str(got[items[1]]))
		_assert(got[items[2]] == (10, 270), got[items[2]])

	check("#120 #121 offline Edit / Duplicate: MT PO Number from po_no, Flat Discount % from the price (not with an Offer)", _offline)

	both = _order(f"{TAG}-B", "E-com", po_no="OLD-PO", custom_po_number="PAGE-PO")

	def _page_po_wins():
		_assert(get_ecom_so_entry_payload(both)["po_number"] == "PAGE-PO", "the page's PO Number lost")
		_assert(get_so_entry_payload(both)["ecom"]["po_number"] == "PAGE-PO", "the page's PO Number lost (offline payload)")

	check("#120 an order saved from the page keeps its own PO Number", _page_po_wins)


# ----------------------------------------------------------------------------- #119 (and #118's check on save)


def _gst_type_change():
	def _new_unregistered():
		b = OST.new_buyer(gst_type="Unregistered Business", gst_no="27ABCDE", pan_no=OST.pan(), pan_attachment="/files/pan.pdf")
		_assert(not frappe.db.get_value("Buyer Master", b.name, "gst_no"), "the leftover GST No. was kept")

	check("#119 a new Unregistered buyer saves with its PAN; a GST No. left in the form is dropped", _new_unregistered)

	def _changed_type():
		b = OST.new_buyer()
		doc = frappe.get_doc("Buyer Master", b.name)
		doc.gst_type = "Unregistered Business"
		doc.gst_no = "24ABC"  # half a number, left behind in the hidden field
		doc.pan_no = OST.pan()
		doc.pan_attachment = "/files/pan.pdf"
		doc.save()
		_assert(not frappe.db.get_value("Buyer Master", b.name, "gst_no"), "GST No. kept after the change to Unregistered")
		_assert(frappe.db.get_value("Buyer Master", b.name, "gst_type") == "Unregistered Business", "type")

	check("#119 Registered -> Unregistered clears the GST No. and saves without a GST No. error", _changed_type)

	def _registered_still_checked():
		err = refused(lambda: OST.new_buyer(gst_no="24ABC"))
		_assert("Invalid GSTIN" in err, "a short GST No. on a Registered buyer was accepted: " + err)

	check("#118 a Registered buyer's GST No. is still checked on save", _registered_still_checked)

	def _legacy_kept():
		b = OST.new_buyer()
		gst = frappe.db.get_value("Buyer Master", b.name, "gst_no")
		frappe.db.set_value("Buyer Master", b.name, {"gst_type": "Unregistered Business", "pan_no": OST.pan(),
			"pan_attachment": "/files/pan.pdf"}, update_modified=False)
		doc = frappe.get_doc("Buyer Master", b.name)
		doc.contact_person = "Ravi K"
		doc.save()
		_assert(frappe.db.get_value("Buyer Master", b.name, "gst_no") == gst, "an older buyer's GST No. was removed")

	check("#119 an older Unregistered buyer that still has a GST No. keeps it when saved unchanged", _legacy_kept)
