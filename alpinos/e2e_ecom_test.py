"""
End-to-end script test for the E-Com Sales Order feature set on a TEST site.

Run:  bench --site alpinos.test execute alpinos.e2e_ecom_test.run

Covers:
  1. E-Com SO create API (channel, flags, PO fields) + validations
     (duplicate PO / future PO date / bad GSTIN / margin range / MRP>0)
  2. MT-offline ecom_fields passthrough (channel stays Offline)
  3. Partial dispatch: 2 rounds, cumulative over-dispatch guard, remaining map,
     partial statuses, auto-Complete on full dispatch
  4. Forced close: at-PL-submission path + lock (no new PL) + Forced Completed;
     single-PL lock for non-partial orders
  5. Post Delivery: queue, start (transport/GRN seeding), GRN validations,
     status roll-up + reflect onto DN/SO, fill rate
  6. Notifications: Notification Log rows created for a test recipient

All records are prefixed ECOMTEST. Data persists on the test site (inspectable);
re-runs create a fresh set via a hash suffix.
"""

import frappe
from frappe.utils import add_days, flt, today

R = []  # results

def DISPATCH():
	return add_days(today(), 1)


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def expect_throw(label, fn, fragment=None):
	try:
		fn()
		R.append(("FAIL", label, "expected an exception, none raised"))
	except Exception as e:
		msg = str(e)
		if fragment and fragment.lower() not in msg.lower():
			R.append(("FAIL", label, f"threw, but message lacked '{fragment}': {msg[:160]}"))
		else:
			R.append(("PASS", label, ""))


def so_status(so):
	return frappe.db.get_value("Sales Order", so, "custom_workflow_status")


# ---------------------------------------------------------------------------
def _fixtures(tag):
	"""Create isolated test masters; return a dict of names."""
	f = {}
	# Customer type with no min-expiry (skips expiry validation).
	ct = f"ECOMTEST TYPE {tag}"
	if not frappe.db.exists("Alpino Customer Type", ct):
		frappe.get_doc({"doctype": "Alpino Customer Type", "name": ct, "customer_type": ct,
		                "channel": "E-com" if frappe.db.exists("Channel", "E-com") else None}).insert(ignore_permissions=True)
	f["ctype"] = ct

	# Items (plain stock items, no batch, no Box UOM).
	f["items"] = []
	for i in (1, 2):
		code = f"ECOMTEST-ITEM-{tag}-{i}"
		if not frappe.db.exists("Item", code):
			frappe.get_doc({
				"doctype": "Item", "item_code": code, "item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": frappe.db.get_value("UOM", {}, "name", order_by="creation asc") or "Nos",
				"is_stock_item": 1, "custom_gst_percent": 0,
			}).insert(ignore_permissions=True)
		f["items"].append(code)

	# Any State/City for the buyer address (create minimal ones if the site has none).
	def _any(doctype, payload):
		name = frappe.db.get_value(doctype, {}, "name")
		if name:
			return name
		d = frappe.get_doc({"doctype": doctype, **payload})
		d.flags.ignore_permissions = True
		d.flags.ignore_mandatory = True
		d.insert()
		return d.name

	state = _any("State", {"state": "ECOMTEST State", "state_name": "ECOMTEST State", "name": "ECOMTEST State"})
	city = _any("City", {"city": "ECOMTEST City", "city_name": "ECOMTEST City", "name": "ECOMTEST City", "state": state})

	# Customers + Buyer Masters (one partial-allowed e-com, one partial-off).
	def mk_buyer(suffix, partial):
		cust = f"ECOMTEST-CUST-{tag}-{suffix}"
		if not frappe.db.exists("Customer", cust):
			# Group/territory must be explicit — sites without Selling Settings
			# defaults (e.g. UAT) otherwise create a group-less Customer, and
			# ERPNext's price-list lookup crashes on Customer Group None.
			frappe.get_doc({
				"doctype": "Customer", "customer_name": cust,
				"custom_order_type": ct,
				"customer_group": frappe.db.get_single_value("Selling Settings", "customer_group")
					or frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
					or "All Customer Groups",
				"territory": frappe.db.get_single_value("Selling Settings", "territory")
					or frappe.db.get_value("Territory", {"is_group": 0}, "name")
					or "All Territories",
			}).insert(ignore_permissions=True)
		cust_name = frappe.db.get_value("Customer", {"customer_name": cust}, "name")
		if not frappe.db.exists("Buyer Master", {"customer": cust_name}):
			frappe.get_doc({
				"doctype": "Buyer Master",
				"customer_business_name": cust, "customer": cust_name,
				"customer_type": ct, "channel": "E-com",
				"appointment_required": 1, "grn_available": 1,
				"partial_order_allowed": partial, "gst_exclusive_buyer": 0,
				"gst_no": "24AAACC1206D1ZM", "site_name": "ECOMTEST Site",
				"gst_type": "Registered Business", "level": "N/A",
				"email": "ecomtest@example.com", "contact_no": "9999999999",
				"contact_person": "ECOMTEST Person",
				"addresses": [{
					"is_primary": 1, "is_shipping": 1,
					"site_name": "ECOMTEST Site",
					"address_line": "ECOMTEST Street 1",
					"pincode": "395003",
					"state": state, "city": city,
					"country": frappe.db.get_default("country")
						or frappe.db.get_value("Country", {}, "name"),
				}],
			}).insert(ignore_permissions=True)
		# Buyer Master hooks rename the Customer (GST suffix) — re-fetch the name.
		return frappe.db.get_value("Customer", {"customer_name": cust}, "name")

	f["cust_partial"] = mk_buyer("P", 1)
	f["cust_single"] = mk_buyer("S", 0)

	# Stock: material receipt into the company's default warehouse.
	from alpinos.sales_order_api import _resolve_company, _resolve_default_warehouse
	company = _resolve_company(None)
	wh = _resolve_default_warehouse(company)
	assert wh, "no default warehouse resolved"
	f["company"], f["warehouse"] = company, wh
	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
		"purpose": "Material Receipt", "company": company, "to_warehouse": wh,
		"items": [{"item_code": it, "qty": 1000, "t_warehouse": wh,
		           "basic_rate": 10, "allow_zero_valuation_rate": 1} for it in f["items"]],
	})
	se.flags.ignore_permissions = True
	se.insert()
	se.submit()

	# Notification recipient (Sales+Warehouse+ECOM roles).
	email = f"ecomtest-{tag.lower()}@example.com"
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({"doctype": "User", "email": email, "first_name": "ECOMTEST",
		                    "send_welcome_email": 0, "enabled": 1})
		u.flags.ignore_permissions = True
		u.insert()
	roles = ["Sales Manager", "Warehouse Manager", "Warehouse Admin",
	         "E-Commerce Coordinator", "E-Commerce Manager"]
	u = frappe.get_doc("User", email)
	have = {r.role for r in u.roles}
	for role in roles:
		if role not in have and frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.flags.ignore_permissions = True
	u.save()
	f["notify_user"] = email
	frappe.db.commit()
	return f


def _mk_ecom_so(f, cust, po, items_spec):
	"""Create + submit an e-com SO via the real API. items_spec: [(item, qty, mrp, margin)]"""
	from alpinos.ecom_sales_order_api import create_ecom_sales_order
	items = [{"item_code": it, "qty": q, "custom_customer_mrp": mrp,
	          "custom_selling_price": flt(mrp * (1 - m / 100.0), 2),
	          "margin_percent": m, "custom_gst_percent": 0, "warehouse": f["warehouse"]}
	         for (it, q, mrp, m) in items_spec]
	out = create_ecom_sales_order(
		customer=cust, order_type=f["ctype"], company=f["company"],
		items=frappe.as_json(items),
		flags=frappe.as_json({"appointment_required": 1, "grn_available": 1,
		                      "partial_order_allowed": frappe.db.get_value("Buyer Master", {"customer": cust}, "partial_order_allowed"),
		                      "gst_exclusive_buyer": 0}),
		po_number=po, po_date=today(), dispatch_date=DISPATCH(),
		billing_gstin="24AAACC1206D1ZM", shipping_gstin="24AAACC1206D1ZM",
		billing_address="ECOMTEST billing addr", shipping_address="ECOMTEST shipping addr",
		site_name="ECOMTEST Site", submit_now=1,
	)
	return out["name"]


def _mk_pl(so, f, qtys, short_action=None, reason=None, future_date=None, qc_user=None):
	"""Create+submit a PL via the real page API. qtys: {item_code: qty}."""
	from alpinos.sales_order_api import get_pick_list_mapping_data
	from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import (
		create_and_submit_pick_list,
	)
	mapping = get_pick_list_mapping_data(so)
	items = []
	for loc in mapping["locations"]:
		it = loc.get("item_code")
		if it not in qtys:
			continue
		items.append({"name": loc.get("name"), "item_code": it, "qty": qtys[it],
		              "custom_box": 0, "custom_batch_code": "", "batch_no": "",
		              "custom_mfg_date": "", "custom_expiry_date": "",
		              "custom_source_table": "Items",
		              "custom_remark": reason or "ECOMTEST"})
	header = {"custom_qc_attended_by": qc_user or frappe.db.get_value("User", {"email": ["like", "ecomtest-%"]}, "name") or "Administrator",
	          "custom_dispatch_date": DISPATCH()}
	return create_and_submit_pick_list(
		so_name=so, header=frappe.as_json(header), items=frappe.as_json(items),
		short_pick_action=short_action, short_pick_reason=reason,
		future_dispatch_date=future_date,
	)


def _mk_dn(pl):
	"""Create the DN from a PL and submit it with the fields our features read."""
	from alpinos.pick_list_api import create_delivery_note_from_pick_list
	res = create_delivery_note_from_pick_list(pl)
	dn_name = res.get("name") if isinstance(res, dict) else res
	dn = frappe.get_doc("Delivery Note", dn_name)
	dn.custom_transporter_name = "ECOMTEST Transport"
	dn.custom_lr_gr_no = "LR-ECOMTEST-1"
	dn.custom_dispatch_date = DISPATCH()
	dn.custom_delivery_date = DISPATCH()
	dn.flags.ignore_mandatory = True
	dn.flags.ignore_permissions = True
	dn.save()
	dn.reload()
	dn.flags.ignore_mandatory = True
	dn.submit()
	return dn_name


# ---------------------------------------------------------------------------
def run():
	frappe.flags.in_test = False
	tag = frappe.generate_hash(length=5).upper()
	print(f"\n=== ECOM E2E TEST (tag {tag}) on site {frappe.local.site} ===\n")
	f = _fixtures(tag)
	it1, it2 = f["items"]

	notif_before = frappe.db.count("Notification Log", {"for_user": f["notify_user"]})

	# ------------------------------------------------------------ Feature 1
	so1 = _mk_ecom_so(f, f["cust_partial"], f"PO-{tag}-1", [(it1, 30, 100, 10), (it2, 20, 50, 20)])
	check("E-Com SO created + submitted", lambda: None)
	check("channel = E-com", lambda: (lambda v: (v == "E-com") or (_ for _ in ()).throw(AssertionError(v)))(frappe.db.get_value("Sales Order", so1, "custom_channel")))
	check("flags stored (appointment/grn/partial)", lambda: (
		(lambda d: (d.custom_appointment_required == 1 and d.custom_grn_available == 1 and d.custom_partial_order_allowed == 1)
		 or (_ for _ in ()).throw(AssertionError(str(d))))
		(frappe.db.get_value("Sales Order", so1,
			["custom_appointment_required", "custom_grn_available", "custom_partial_order_allowed"], as_dict=True))))
	check("PO fields stored", lambda: (
		(lambda d: (d.custom_po_number == f"PO-{tag}-1" and str(d.custom_po_date) == today())
		 or (_ for _ in ()).throw(AssertionError(str(d))))
		(frappe.db.get_value("Sales Order", so1, ["custom_po_number", "custom_po_date"], as_dict=True))))

	expect_throw("duplicate PO/customer blocked",
		lambda: _mk_ecom_so(f, f["cust_partial"], f"PO-{tag}-1", [(it1, 5, 100, 10)]),
		"already exists")
	expect_throw("future PO date blocked", lambda: __import__("alpinos.ecom_sales_order_api", fromlist=["create_ecom_sales_order"]).create_ecom_sales_order(
		customer=f["cust_partial"], order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": it1, "qty": 1, "custom_customer_mrp": 100, "custom_selling_price": 90, "margin_percent": 10}]),
		po_number=f"PO-{tag}-FUT", po_date=add_days(today(), 2), dispatch_date=DISPATCH(),
		billing_address="x", shipping_address="x", submit_now=0), "future")
	expect_throw("bad GSTIN blocked", lambda: __import__("alpinos.ecom_sales_order_api", fromlist=["create_ecom_sales_order"]).create_ecom_sales_order(
		customer=f["cust_partial"], order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": it1, "qty": 1, "custom_customer_mrp": 100, "custom_selling_price": 90, "margin_percent": 10}]),
		po_number=f"PO-{tag}-GST", po_date=today(), dispatch_date=DISPATCH(),
		billing_gstin="BADGSTIN123", billing_address="x", shipping_address="x", submit_now=0), "GSTIN")
	expect_throw("margin > 90 blocked", lambda: __import__("alpinos.ecom_sales_order_api", fromlist=["create_ecom_sales_order"]).create_ecom_sales_order(
		customer=f["cust_partial"], order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": it1, "qty": 1, "custom_customer_mrp": 100, "custom_selling_price": 5, "margin_percent": 95}]),
		po_number=f"PO-{tag}-MGN", po_date=today(), dispatch_date=DISPATCH(),
		billing_address="x", shipping_address="x", submit_now=0), "Margin")
	expect_throw("MRP 0 blocked (e-com)", lambda: __import__("alpinos.ecom_sales_order_api", fromlist=["create_ecom_sales_order"]).create_ecom_sales_order(
		customer=f["cust_partial"], order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": it1, "qty": 1, "custom_customer_mrp": 0, "custom_selling_price": 0, "margin_percent": 10}]),
		po_number=f"PO-{tag}-MRP", po_date=today(), dispatch_date=DISPATCH(),
		billing_address="x", shipping_address="x", submit_now=0), "MRP")

	from alpinos.ecom_sales_order_api import get_ecom_buyer_for_customer
	check("buyer lookup returns flags + GSTIN", lambda: (
		(lambda d: (d["appointment_required"] == 1 and d["billing"]["gstin"])
		 or (_ for _ in ()).throw(AssertionError(str(d))))
		(get_ecom_buyer_for_customer(f["cust_partial"]))))

	# ------------------------------------------------------------ Feature 2
	from alpinos.sales_order_api import create_sales_order
	so_mt = create_sales_order(
		customer=f["cust_partial"], order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": it1, "qty": 4, "custom_customer_mrp": 100,
		                       "custom_selling_price": 90, "custom_gst_percent": 0}]),
		dispatch_date=DISPATCH(), submit_now=0,
		ecom_fields=frappe.as_json({"flags": {"appointment_required": 1, "grn_available": 0,
		                                      "partial_order_allowed": 0, "gst_exclusive_buyer": 1},
		                            "po_number": f"PO-{tag}-MT", "po_date": today(),
		                            "billing_gstin": "24AAACC1206D1ZM"}))["name"]
	check("MT-offline: channel stays Offline + flags applied", lambda: (
		(lambda d: (d.custom_channel == "Offline" and d.custom_gst_exclusive_buyer == 1 and d.custom_po_number == f"PO-{tag}-MT")
		 or (_ for _ in ()).throw(AssertionError(str(d))))
		(frappe.db.get_value("Sales Order", so_mt,
			["custom_channel", "custom_gst_exclusive_buyer", "custom_po_number"], as_dict=True))))

	# ------------------------------------------------------------ Feature 3
	from alpinos import partial_dispatch as pd

	pl1 = _mk_pl(so1, f, {it1: 20, it2: 20}, short_action="Partial", reason="Stock Shortage",
	             future_date=add_days(today(), 2))
	check("partial round 1: SO -> Partial Ready For Dispatch",
		lambda: (so_status(so1) == "Partial Ready For Dispatch") or (_ for _ in ()).throw(AssertionError(so_status(so1))))
	check("partial round 1: PL -> Partial Ready To Dispatch",
		lambda: (frappe.db.get_value("Pick List", pl1, "custom_workflow_status") == "Partial Ready To Dispatch")
		or (_ for _ in ()).throw(AssertionError("wrong PL status")))
	check("future dispatch date recorded on SO", lambda: (
		(str(frappe.db.get_value("Sales Order", so1, "custom_dispatch_date")) == add_days(today(), 2))
		or (_ for _ in ()).throw(AssertionError("dispatch date not rescheduled"))))

	dn1 = _mk_dn(pl1)
	check("partial round 1: DN submit -> SO Partial Dispatched",
		lambda: (so_status(so1) == "Partial Dispatched") or (_ for _ in ()).throw(AssertionError(so_status(so1))))
	check("remaining map = {it1: 10}", lambda: (
		(lambda r: (flt(r.get(it1)) == 10 and flt(r.get(it2)) == 0)
		 or (_ for _ in ()).throw(AssertionError(str(r))))
		(pd.remaining_qty_by_sku(so1))))

	expect_throw("cumulative over-dispatch blocked (15 > remaining 10)",
		lambda: _mk_pl(so1, f, {it1: 15}), "exceed")

	pl2 = _mk_pl(so1, f, {it1: 10}, reason="ECOMTEST round2")
	dn2 = _mk_dn(pl2)
	check("auto-Complete when cumulative dispatched == ordered",
		lambda: (so_status(so1) == "Completed") or (_ for _ in ()).throw(AssertionError(so_status(so1))))

	# ------------------------------------------------------------ Feature 4
	so3 = _mk_ecom_so(f, f["cust_partial"], f"PO-{tag}-3", [(it1, 30, 100, 10)])
	pl3 = _mk_pl(so3, f, {it1: 20}, short_action="Forced Close", reason="Stock Shortage")
	check("forced close at PL submission: flag + reason set", lambda: (
		(lambda d: (d.custom_force_closed == 1 and d.custom_force_close_reason == "Stock Shortage")
		 or (_ for _ in ()).throw(AssertionError(str(d))))
		(frappe.db.get_value("Sales Order", so3, ["custom_force_closed", "custom_force_close_reason"], as_dict=True))))
	check("forced close: SO -> Forced Ready For Dispatch",
		lambda: (so_status(so3) == "Forced Ready For Dispatch") or (_ for _ in ()).throw(AssertionError(so_status(so3))))
	expect_throw("new PL blocked after force close", lambda: _mk_pl(so3, f, {it1: 10}), "Force Closed")
	dn3 = _mk_dn(pl3)
	check("forced DN submit -> SO Forced Dispatched",
		lambda: (so_status(so3) == "Forced Dispatched") or (_ for _ in ()).throw(AssertionError(so_status(so3))))
	from alpinos.forced_close import confirm_forced_completion
	confirm_forced_completion(so3)
	check("confirm -> Forced Completed (terminal)",
		lambda: (so_status(so3) == "Forced Completed") or (_ for _ in ()).throw(AssertionError(so_status(so3))))

	# Single-PL lock (partial off).
	so4 = _mk_ecom_so(f, f["cust_single"], f"PO-{tag}-4", [(it1, 10, 100, 10)])
	_mk_pl(so4, f, {it1: 10})
	expect_throw("second PL blocked when partial not allowed",
		lambda: _mk_pl(so4, f, {it1: 1}), "only one Pick List")

	# ------------------------------------------------------------ Feature 5
	from alpinos.post_delivery_api import get_post_delivery_queue, start_post_delivery
	q = get_post_delivery_queue(search=so3)
	check("post delivery queue lists the forced DN", lambda: (
		any(r.get("delivery_note") == dn3 for r in q["data"])
		or (_ for _ in ()).throw(AssertionError(frappe.as_json(q["data"])))))

	pd_name = start_post_delivery(dn3)["name"]
	pdoc = frappe.get_doc("Post Delivery", pd_name)
	check("post delivery seeded (transport + GRN rows + qty)", lambda: (
		(pdoc.transporter == "ECOMTEST Transport" and flt(pdoc.dispatched_qty) == 20
		 and len(pdoc.grn_items) == 1 and flt(pdoc.grn_items[0].dispatched_qty) == 20)
		or (_ for _ in ()).throw(AssertionError(f"{pdoc.transporter}/{pdoc.dispatched_qty}/{len(pdoc.grn_items)}"))))

	def _bad_grn():
		p = frappe.get_doc("Post Delivery", pd_name)
		p.grn_items[0].grn_qty = 25  # > dispatched 20
		p.save(ignore_permissions=True)
	expect_throw("GRN qty > dispatched blocked", _bad_grn, "GRN Qty")

	def _bad_reject():
		p = frappe.get_doc("Post Delivery", pd_name)
		p.reload()
		p.grn_items[0].grn_qty = 15
		p.grn_items[0].grn_rejected_qty = 5
		p.grn_items[0].rejection_reason = ""
		p.save(ignore_permissions=True)
	expect_throw("rejected qty without reason blocked", _bad_reject, "Rejection Reason")

	def _good_pd():
		p = frappe.get_doc("Post Delivery", pd_name)
		p.reload()
		p.asn_status = "Accepted"
		p.asn_id = f"ASN-{tag}"
		p.appointment_status = "Completed"
		p.appointment_id = f"APT-{tag}"
		p.grn_status = "Completed"
		p.grn_items[0].grn_qty = 18
		p.grn_items[0].grn_rejected_qty = 2
		p.grn_items[0].rejection_reason = "Damage"
		p.save(ignore_permissions=True)
	_good_pd()
	pdoc = frappe.get_doc("Post Delivery", pd_name)
	check("post delivery rolls up to Completed + ASN stamped", lambda: (
		(pdoc.post_delivery_status == "Completed" and pdoc.asn_uploaded_by)
		or (_ for _ in ()).throw(AssertionError(f"{pdoc.post_delivery_status}/{pdoc.asn_uploaded_by}"))))
	check("fill rate = 66.67 (20/30)", lambda: (
		abs(flt(pdoc.fill_rate) - 66.67) < 0.1
		or (_ for _ in ()).throw(AssertionError(str(pdoc.fill_rate)))))
	check("status reflected onto DN + SO", lambda: (
		(frappe.db.get_value("Delivery Note", dn3, "custom_post_delivery_status") == "Completed"
		 and frappe.db.get_value("Sales Order", so3, "custom_grn_status") == "Completed")
		or (_ for _ in ()).throw(AssertionError("reflect fields not set"))))

	# ------------------------------------------------------------ Feature 6
	notif_after = frappe.db.count("Notification Log", {"for_user": f["notify_user"]})
	check(f"notifications delivered to test user ({notif_after - notif_before} logs)",
		lambda: (notif_after > notif_before) or (_ for _ in ()).throw(AssertionError("no Notification Log rows created")))

	frappe.db.commit()

	# ------------------------------------------------------------ Report
	print(f"\n{'='*72}")
	passed = sum(1 for s, _, _ in R if s == "PASS")
	print(f"RESULT: {passed}/{len(R)} passed\n")
	for status, label, detail in R:
		mark = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥"}[status]
		print(f"  {mark} {label}" + (f"\n      -> {detail}" if detail else ""))
	print(f"{'='*72}")
	print(f"Test docs (tag {tag}): SO {so1}, {so_mt}, {so3}, {so4}; PD {pd_name}\n")
