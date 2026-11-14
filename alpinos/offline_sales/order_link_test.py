"""W3 Buyer Portal (doc Section 2): link lifecycle, token rules, product visibility, pricing,
submission and edit. TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.order_link_test.run
"""

import re

import frappe
from frappe.utils import add_days, cint, flt, today

from alpinos.offline_sales import order_link as L

R = []
TAG = "OLT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()
BUYER = "OBM-2026-00169"  # Approved, General Trade, priced Buyer Catalog, no Site Names


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
	sp = "olt_" + frappe.generate_hash(length=6)
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


def as_(user, fn):
	frappe.set_user(user)
	frappe.local.role_permissions = {}
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.role_permissions = {}


def _person(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	emp = _insert("Employee", name=f"{TAG}-{suffix.upper()}", employee_name=f"{TAG} {suffix}", first_name=suffix,
		status="Active", company=frappe.defaults.get_global_default("company"), date_of_joining="2026-01-01", user_id=user)
	return frappe._dict(user=user, emp=emp)


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	real_enqueue = frappe.enqueue
	frappe.enqueue = lambda *a, **k: F.setdefault("enqueued", []).append(k)
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.enqueue = real_enqueue
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)} {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")


def _run():
	F.sm = _person("sm", "Sales Manager", "Employee")
	F.so = _person("so", "Sales Officer", "Employee")
	_insert("Buyer Sales Officer", name=f"{TAG}-BSO", parent=BUYER, parenttype="Buyer Master", parentfield="sales_officers",
		employee=F.so.emp, idx=90)
	frappe.db.set_value("Buyer Master", BUYER, {
		L.TOKEN_FIELD: None, "order_link_url": None, L.STATUS_FIELD: L.NOT_GENERATED,
		"order_link_generated_on": None, "order_link_generated_by": None, "order_link_last_used_on": None,
		"email": f"{TAG.lower()}.buyer@example.com",
	})
	frappe.clear_cache()
	_link()
	_token_rules()
	_visibility_and_pricing()
	_submit_and_edit()


def _trail(action):
	return frappe.get_all("Field Change Log", filters={"reference_doctype": "Buyer Master", "reference_name": BUYER, "action": action},
		fields=["previous_value", "new_value", "changed_by"])


def _link():
	def _not_approved():
		frappe.db.set_value("Buyer Master", BUYER, "buyer_status", "Pending Approval")
		err = refused(lambda: as_(F.sm.user, lambda: L.generate_link(BUYER)))
		frappe.db.set_value("Buyer Master", BUYER, "buyer_status", "Approved")
		_assert("only for an Approved Buyer" in err, err)

	check("S2: no link for a Buyer that is not Approved", _not_approved)

	def _officer():
		err = refused(lambda: as_(F.so.user, lambda: L.generate_link(BUYER)))
		_assert("Sales Manager or Sales Admin" in err, err)

	check("S2: a Sales Officer cannot generate the link", _officer)

	def _generate():
		info = as_(F.sm.user, lambda: L.generate_link(BUYER))
		bm = frappe.db.get_value("Buyer Master", BUYER, [L.TOKEN_FIELD, L.STATUS_FIELD, "order_link_generated_by", "order_link_generated_on", "order_link_url"], as_dict=True)
		F.token = bm[L.TOKEN_FIELD]
		_assert(re.fullmatch(r"[0-9a-f]{64}", F.token or ""), bm)
		_assert(bm[L.STATUS_FIELD] == "Active" and bm.order_link_generated_by == F.sm.user and bm.order_link_generated_on, bm)
		_assert(bm.order_link_url.endswith(f"/order-request?token={F.token}") and info["url"] == bm.order_link_url, bm.order_link_url)
		_assert(_trail("Buyer Link Generated"), "no audit row")
		_assert("already exists" in refused(lambda: as_(F.sm.user, lambda: L.generate_link(BUYER))), "generated twice")

	check("S2: Generate gives a 64-character token, URL, status Active, Generated On/By, audit", _generate)

	def _officer_view():
		info = as_(F.so.user, lambda: L.link_info(BUYER))
		_assert(info["url"] and info["status"] == "Active" and not info["manager"], info)

	check("S2: the assigned Sales Officer may copy / open the link but not manage it", _officer_view)


def _token_rules():
	def _resolve_ok():
		_assert(L.resolve(F.token).name == BUYER)
		for bad in ("", "abc", F.token[:-1] + ("0" if F.token[-1] != "0" else "1"), F.token + "a"):
			_assert(_refuses(bad), f"accepted {bad[:10]}")

	check("S2: only the exact token opens the page", _resolve_ok)

	def _deactivate_activate():
		as_(F.sm.user, lambda: L.deactivate_link(BUYER))
		_assert(_refuses(F.token), "inactive link accepted")
		as_(F.sm.user, lambda: L.activate_link(BUYER))
		_assert(L.resolve(F.token).name == BUYER, "reactivated link refused")
		_assert(_trail("Buyer Link Deactivated") and _trail("Buyer Link Reactivated"), "audit rows")

	check("S2: Deactivate blocks the link at once; Activate opens the same link again", _deactivate_activate)

	def _regenerate():
		old = F.token
		as_(F.sm.user, lambda: L.regenerate_link(BUYER))
		F.token = frappe.db.get_value("Buyer Master", BUYER, L.TOKEN_FIELD)
		_assert(F.token != old and _refuses(old) and L.resolve(F.token).name == BUYER, "old token still works")
		rows = _trail("Buyer Link Regenerated (Old Token Deactivated)")
		_assert(rows and old not in (rows[0].previous_value or "") and old not in (rows[0].new_value or ""), "full token in the trail")

	check("S2: Regenerate supersedes the old link at once; the trail never holds a full token", _regenerate)

	def _states():
		for status in ("Expired", "Inactive"):
			frappe.db.set_value("Buyer Master", BUYER, L.STATUS_FIELD, status)
			_assert(_refuses(F.token), status)
		frappe.db.set_value("Buyer Master", BUYER, L.STATUS_FIELD, "Active")
		for bstatus in ("On Hold", "Inactive", "Cancelled", "Pending Approval"):
			frappe.db.set_value("Buyer Master", BUYER, "buyer_status", bstatus)
			_assert(_refuses(F.token), f"buyer {bstatus}")
		frappe.db.set_value("Buyer Master", BUYER, "buyer_status", "Approved")

	check("S2: Expired / Inactive link and Inactive / Cancelled / On Hold buyer are refused", _states)

	def _page_refusal():
		import os
		import runpy

		get_context = runpy.run_path(os.path.join(frappe.get_app_path("alpinos"), "www", "order-request.py"))["get_context"]
		for token in ("bad", F.token):
			frappe.form_dict.token = token
			ctx = frappe._dict()
			get_context(ctx)
			if token == "bad":
				_assert(ctx.refused and ctx.refused_message.startswith("This order request link is no longer active") and not ctx.get("page_data"), ctx)
			else:
				_assert(not ctx.refused and ctx.page_data, "valid link refused")
		frappe.form_dict.pop("token", None)

	check("S2: the refused page shows only the doc's message, no buyer data", _page_refusal)

	def _guest_calls():
		err = refused(lambda: as_("Guest", lambda: L.search_products("0" * 64, "")))
		_assert("no longer active" in err, err)
		items = as_("Guest", lambda: L.search_products(F.token, ""))
		_assert(items and all(set(i) >= {"item_code", "mrp", "selling_price"} for i in items), "guest search")

	check("S2: guest calls work without login and re-check the token every time", _guest_calls)


def _refuses(token):
	try:
		L.resolve(token)
		return False
	except L.LinkRefused:
		return True


def _visibility_and_pricing():
	from alpinos.production.material_type import FG, groups_of_type

	buyer = frappe.get_doc("Buyer Master", BUYER)
	fg = set(groups_of_type(FG))

	def _fg_only():
		items = L.visible_items(buyer, limit=2000)
		_assert(items, "nothing visible")
		groups = {frappe.db.get_value("Item", i.item_code, "item_group") for i in items}
		_assert(groups <= fg, f"non-FG groups {groups - fg}")
		_assert(not any(k for i in items for k in i if "stock" in k or "qty" in k), "stock leaked")

	check("S2: only active Finished Goods are offered, never stock", _fg_only)

	def _excluded():
		code = L.visible_items(buyer, limit=1)[0].item_code
		frappe.db.set_value("Item", code, "disabled", 1)
		_assert(code not in {i.item_code for i in L.visible_items(buyer, limit=2000)}, "disabled shown")
		frappe.db.set_value("Item", code, {"disabled": 0, "end_of_life": add_days(today(), -1)})
		_assert(code not in {i.item_code for i in L.visible_items(buyer, limit=2000)}, "end of life shown")
		frappe.db.set_value("Item", code, "end_of_life", None)
		other = frappe.db.get_value("Alpino Customer Type", {"name": ("!=", buyer.customer_type)}, "name")
		_insert("Item Allowed Customer Type", name=f"{TAG}-IACT", parent=code, parenttype="Item", parentfield="custom_allowed_customer_types",
			customer_type=other)
		_assert(code not in {i.item_code for i in L.visible_items(buyer, limit=2000)}, "other customer type shown")
		F.allowed_item = L.visible_items(buyer, limit=1)[0].item_code

	check("S2: disabled, end-of-life and other-customer-type items are hidden", _excluded)

	def _catalog_price():
		row = frappe.db.sql("""select bil.item_code, bil.selling_rate, bil.margin_percent from `tabBuyer Item` bil
			join `tabBuyer Items` bi on bi.name = bil.parent where bi.buyer = %s and ifnull(bi.docstatus,0) < 2 and bil.selling_rate > 0
			order by bi.modified desc limit 1""", buyer.customer, as_dict=True)[0]
		p = L.price(buyer.customer, row.item_code, 3)
		from alpinos.sales_order_offline_buyer import get_offline_buyer_item_rate
		from alpinos import item_mrp as IM

		info = IM.applicable(row.item_code)
		expect = get_offline_buyer_item_rate(buyer.customer, row.item_code, IM.q(info.mrps[-1]) if info.tracked and info.mrps else None)
		if expect and expect.get("rate") not in (None, ""):
			_assert(flt(p["selling_price"]) == flt(expect["rate"]) and flt(p["flat_discount"]) == flt(expect["margin_percent"]), (p, expect))
		_assert(flt(p["amount"]) == flt(3 * p["selling_price"], 2), p)

	check("S2: Buyer Catalog price is used where configured (same lookup as the Sales Order)", _catalog_price)

	def _fallback():
		catalog = set(frappe.db.sql_list("""select bil.item_code from `tabBuyer Item` bil join `tabBuyer Items` bi on bi.name = bil.parent
			where bi.buyer = %s""", buyer.customer))
		code = next((i.item_code for i in L.visible_items(buyer, limit=2000) if i.item_code not in catalog
			and not frappe.db.exists("Buyer Margin", {"parent": BUYER, "sku": i.item_code})), None)
		_assert(code, "no non-catalog item to test")
		p = L.price(buyer.customer, code, 10)
		_assert(flt(p["flat_discount"]) == 0 and flt(p["selling_price"]) == flt(p["mrp"]) and flt(p["amount"]) == flt(10 * p["mrp"], 2), p)
		F.fallback_item = code

	check("S2: an item without a Buyer Catalog price sells at MRP with 0% (never blocked)", _fallback)

	def _quote_rules():
		ok = L.quote_rows(F.token, [{"item_code": F.fallback_item, "qty": 2, "selling_price": 1, "mrp": 1, "amount": 1}])
		_assert(flt(ok["rows"][0]["selling_price"]) == flt(L.price(buyer.customer, F.fallback_item)["selling_price"]), "client price trusted")
		_assert(ok["sub_total"] == ok["net_total"] == flt(ok["rows"][0]["amount"]), ok)
		_assert(refused(lambda: L.quote_rows(F.token, [])) == L.MSG_NO_PRODUCTS, "empty rows")
		_assert("must be greater than zero" in refused(lambda: L.quote_rows(F.token, [{"item_code": F.fallback_item, "qty": 0}])), "zero")
		_assert("must be greater than zero" in refused(lambda: L.quote_rows(F.token, [{"item_code": F.fallback_item, "qty": 1.5}])), "fraction")
		_assert("not available for ordering" in refused(lambda: L.quote_rows(F.token, [{"item_code": "NOT-AN-ITEM", "qty": 1}])), "unknown sku")

	check("S2: page prices are recomputed on the server; qty must be a whole number > 0; unknown SKU refused", _quote_rules)


def _submit_and_edit():
	if not frappe.db.has_column("Opportunity", "custom_buyer_order_request_ref"):
		R.append(("ERR ", "S2: submission (needs the W4 Opportunity fields)", "Opportunity fields missing: build W4 first"))
		return
	buyer = frappe.get_doc("Buyer Master", BUYER)
	billing, shipping = L._addresses(buyer)

	def _data(qty=3):
		return {"billing_address": billing[0]["address"], "shipping_address": shipping[0]["address"], "contact_person": "Ravi",
			"remarks": "deliver before Friday", "rows": [{"item_code": F.fallback_item, "qty": qty}]}

	def _addresses_offered():
		_assert(billing and shipping, (billing, shipping))
		_assert(all("gstin" in b for b in billing), billing)

	check("S2: billing and shipping choices for a buyer without Site Names", _addresses_offered)

	def _nothing_on_empty():
		before = frappe.db.count("Opportunity")
		_assert(refused(lambda: as_("Guest", lambda: L.submit_request(F.token, {**_data(), "rows": []}))) == L.MSG_NO_PRODUCTS)
		_assert(frappe.db.count("Opportunity") == before, "an Opportunity was created")

	check("S2: zero products: nothing is created and the doc's message is shown", _nothing_on_empty)

	def _submit():
		r = as_("Guest", lambda: L.submit_request(F.token, _data()))
		F.bor = r["bor"]
		_assert(re.fullmatch(r"BOR-2627-\d{5}", F.bor), F.bor)
		opp = frappe.get_doc("Opportunity", {"custom_buyer_order_request_ref": F.bor})
		F.opp = opp.name
		_assert(opp.custom_opportunity_source == "Buyer Order Request Form" and opp.custom_opportunity_status == "Pending (Draft)", opp.custom_opportunity_status)
		_assert(opp.party_name == BUYER and opp.custom_billing_address == billing[0]["address"] and opp.customer_address == shipping[0]["address"], "header")
		_assert(opp.custom_request_contact_person == "Ravi" and opp.custom_common_remark == "deliver before Friday", "contact / remark")
		_assert(opp.custom_source_display == "Buyer Portal – Ravi", opp.custom_source_display)
		_assert(len(opp.items) == 1 and cint(opp.items[0].qty) == 3 and opp.items[0].item_code == F.fallback_item, "items")
		_assert(frappe.db.get_value("Buyer Master", BUYER, "order_link_last_used_on"), "Last Used On")
		_assert(frappe.get_all("Field Change Log", filters={"reference_doctype": "Opportunity", "reference_name": opp.name, "action": "Opportunity Created"}), "audit")
		_assert(any(k.get("opportunity") == opp.name for k in F.get("enqueued", [])), "notifications not queued")

	check("S2: a submission creates one Draft Opportunity with a BOR reference (as Guest)", _submit)

	def _second():
		r = as_("Guest", lambda: L.submit_request(F.token, _data(5)))
		_assert(r["bor"] != F.bor and frappe.db.count("Opportunity", {"custom_buyer_order_request_ref": ("in", [F.bor, r["bor"]])}) == 2, r)

	check("S2: a second submission the same day is a new BOR and a new Opportunity", _second)

	def _edit():
		d = as_("Guest", lambda: L.get_request(F.token, F.bor))
		_assert(d["rows"][0]["qty"] == 3, d)
		as_("Guest", lambda: L.update_request(F.token, F.bor, {**_data(7), "remarks": "changed"}))
		opp = frappe.get_doc("Opportunity", F.opp)
		_assert(opp.custom_buyer_order_request_ref == F.bor and cint(opp.items[0].qty) == 7 and opp.custom_common_remark == "changed", "not updated")
		_assert(frappe.db.count("Opportunity", {"custom_buyer_order_request_ref": F.bor}) == 1, "duplicated")
		_assert(frappe.get_all("Field Change Log", filters={"reference_doctype": "Opportunity", "reference_name": F.opp, "action": "Opportunity Updated"}), "edit audit")

	check("S2: editing while Draft keeps the same BOR and Opportunity, and is audited", _edit)

	def _locked():
		frappe.db.set_value("Opportunity", F.opp, "custom_opportunity_status", "Pending (Submitted)")
		err = refused(lambda: as_("Guest", lambda: L.update_request(F.token, F.bor, _data(9))))
		_assert("can no longer be changed" in err, err)
		other = frappe.db.get_value("Opportunity", {"party_name": ("!=", BUYER)}, "name")
		if other:
			frappe.db.set_value("Opportunity", other, "custom_buyer_order_request_ref", "BOR-2627-99999")
			_assert("no longer active" in refused(lambda: as_("Guest", lambda: L.get_request(F.token, "BOR-2627-99999"))), "another buyer's request")

	check("S2: no edit after the Opportunity leaves Draft; another buyer's request is never reachable", _locked)

	def _notifications():
		L.after_submit(F.opp)
		officers = frappe.get_all("Notification Log", filters={"document_type": "Opportunity", "document_name": F.opp, "for_user": F.so.user}, pluck="subject")
		_assert(officers and officers[0].startswith(f"New Buyer Order Request {F.bor} submitted by"), officers)
		mail = frappe.get_all("Email Queue", filters={"reference_doctype": "Opportunity", "reference_name": F.opp}, fields=["name"])
		_assert(mail, "no buyer email")

	check("S2: internal in-app notification to the assigned team; buyer email with the PDF", _notifications)

	def _ack():
		html = frappe.get_print("Opportunity", F.opp, L.ACK_PRINT_FORMAT)
		_assert(F.bor in html and L.MSG_ACK_FOOTER in html and F.fallback_item in html, "acknowledgement content")

	check("S2: acknowledgement shows the BOR reference, the products and the doc's footer", _ack)
