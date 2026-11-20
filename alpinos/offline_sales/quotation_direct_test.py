"""The Opportunity is skipped (Hetvi, 20 Nov 2026): the Quotation is the entry. Checks the
Quotation layout (only the document's fields, tabs Details | Items | Payment | Activity), a
Draft for a buyer not ready yet, and the Payment Section's Quotation Grand Total. TEST sites
only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.quotation_direct_test.run
"""

import frappe
from frappe.utils import flt

R = []
TAG = "QDT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()
BUYER = "OBM-2026-00169"  # Approved, priced Buyer Catalog, no Site Names


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
	sp = "qdt_" + frappe.generate_hash(length=6)
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


def as_(user, fn):
	frappe.set_user(user)
	frappe.local.role_permissions = {}
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.role_permissions = {}


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
	real_enqueue = frappe.enqueue
	frappe.enqueue = lambda *a, **k: None
	try:
		_layout()
		_not_ready_buyer()
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


def _visible():
	"""{tab: [field labels]} as the form shows them (hidden tabs / sections / fields left out)."""
	tab, sec_hidden, out = "Details", False, {}
	for d in frappe.get_meta("Quotation", cached=False).fields:
		if d.fieldtype == "Tab Break":
			tab, sec_hidden = (None if d.hidden else d.label), False
			continue
		if d.fieldtype == "Section Break":
			sec_hidden = bool(d.hidden)
			continue
		if tab is None or sec_hidden or d.hidden or d.fieldtype == "Column Break":
			continue
		out.setdefault(tab, []).append(d.fieldname)
	return out


def _layout():
	v = _visible()

	def _tabs():
		_assert(list(v) == ["Details", "Items", "Payment", "Activity"], list(v))

	check("Layout: tabs Details | Items | Payment | Activity, as the Opportunity's", _tabs)

	def _details():
		want = [
			"custom_quotation_status", "custom_quotation_source", "custom_buyer_order_request_ref", "custom_request_contact_person",
			"custom_source_display", "party_name", "order_type", "custom_site_name", "customer_address", "custom_billing_gstin",
			"shipping_address_name", "custom_quotation_remarks", "transaction_date", "custom_responsible_sales_officer",
		]
		_assert(v["Details"][: len(want)] == want, v["Details"])
		for gone in ("naming_series", "quotation_to", "valid_till", "company", "custom_buyer_master", "custom_order_no", "custom_opportunity_remark"):
			_assert(gone not in v["Details"], f"{gone} still shown")

	check("Layout: Details shows the header of Section 5, 5 and the request fields only", _details)

	def _items():
		for f in ("items", "custom_marketing_freebies", "custom_scheme_item_table", "custom_additional_units_damage",
				"total", "net_total", "custom_cash_discount", "custom_cash_discount_amount", "total_taxes_and_charges", "grand_total"):
			_assert(f in v["Items"], f"{f} missing from Items")
		for gone in ("scan_barcode", "last_scanned_warehouse", "total_qty", "tax_category", "taxes_and_charges", "taxes",
				"shipping_rule", "incoterm", "rounded_total", "disable_rounded_total", "in_words", "base_grand_total"):
			_assert(gone not in v["Items"], f"{gone} still shown")
		labels = {f: frappe.get_meta("Quotation").get_label(f) for f in ("total", "net_total", "total_taxes_and_charges", "grand_total", "custom_scheme_item_table")}
		_assert(labels == {"total": "Total", "net_total": "Net Total", "total_taxes_and_charges": "Taxes & Charges",
			"grand_total": "Grand Total", "custom_scheme_item_table": "Scheme Items"}, labels)

	check("Layout: Items = the four item tables and the Sales Order-style summary (6.1-6.5)", _items)

	def _grid():
		cols = [d.fieldname for d in frappe.get_meta("Quotation Item").fields if d.in_list_view and not d.hidden]
		_assert(cols == ["item_code", "item_name", "qty", "custom_boxes", "custom_mrp", "custom_selling_price", "custom_flat_discount",
			"custom_offer", "custom_additional_discount", "amount"], cols)
		_assert(frappe.get_meta("Quotation Item").get_label("amount") == "Line Amount", "Line Amount")

	check("Layout: Order Items columns as 6.1 (Additional Discount % and Line Amount included)", _grid)

	def _payment():
		for f in ("custom_payment_term", "custom_credit_days", "custom_payment_schedule", "custom_payment_receipts",
				"custom_payment_grand_total", "custom_total_received", "custom_total_pending", "custom_payment_status", "custom_so_eligibility"):
			_assert(f in v["Payment"], f"{f} missing from Payment")
		for gone in ("custom_payment_mode", "custom_advance_amount", "payment_terms_template", "payment_schedule"):
			_assert(all(gone not in fields for fields in v.values()), f"{gone} still shown")

	check("Layout: Payment = term, schedule, payments and the summary with the Grand Total (8-16)", _payment)

	def _hidden_tabs():
		shown = {f for fields in v.values() for f in fields}
		for gone in ("address_display", "contact_person", "tc_name", "letter_head", "opportunity", "status"):
			_assert(gone not in shown, f"{gone} still shown")
		_assert(frappe.get_meta("Quotation").get_field("quotation_to").default == "Buyer Master", "Quotation To default")

	check("Layout: ERPNext's Address & Contact / Terms / More Info tabs are hidden; Quotation To defaults to Buyer Master", _hidden_tabs)


def _not_ready_buyer():
	from alpinos.offline_sales import quotation as Q
	from alpinos.offline_sales import order_link as L

	user = f"{TAG.lower()}.sm@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} SM", user_type="System User", enabled=1)
	_insert("Has Role", name=f"{TAG}-HR", parent=user, parenttype="User", parentfield="roles", role="Sales Manager")
	buyer = frappe.get_doc("Buyer Master", BUYER)
	frappe.db.set_value("Buyer Master", BUYER, "buyer_status", "Pending Approval", update_modified=False)
	billing, shipping = L._addresses(buyer)
	item = L.visible_items(buyer, limit=1)[0].item_code
	rows = L._priced_rows(buyer, [{"item_code": item, "qty": 2}])

	def _draft():
		q = frappe.new_doc("Quotation")
		q.update({"quotation_to": "Buyer Master", "party_name": BUYER, "company": L._company(buyer), "order_type": buyer.customer_type})
		L._apply(q, buyer, L._header(buyer, {"billing_address": billing[0]["address"], "shipping_address": shipping[0]["address"],
			"contact_person": "", "remarks": ""}), rows)
		q.insert(ignore_permissions=True)
		F.q = q.name
		_assert(q.custom_quotation_status == "Draft" and q.custom_quotation_source == "Direct Quotation", (q.custom_quotation_status, q.custom_quotation_source))
		_assert(flt(q.custom_payment_grand_total) == flt(q.grand_total) and flt(q.grand_total) > 0, (q.custom_payment_grand_total, q.grand_total))

	check("A Draft Quotation saves for a buyer still Pending Approval (Payment shows its Grand Total)", _draft)

	def _held():
		_assert(F.get("q"), "no Draft from the step before")
		ctx = as_(user, lambda: Q.form_actions(F.q))
		_assert("Buyer Approval & Buyer Catalog creation is pending" in (ctx.get("buyer_not_ready") or ""), ctx.get("buyer_not_ready"))
		err = refused(lambda: as_(user, lambda: Q.start_negotiation(F.q)))
		_assert("cannot be moved to Negotiation because linked Buyer Approval" in err, err)
		_assert("cannot be finalized because linked Buyer Approval" in " ".join(Q.finalize_errors(frappe.get_doc("Quotation", F.q))), "Finalize not held")
		frappe.db.set_value("Buyer Master", BUYER, {"buyer_status": "Approved", "buyer_catalog_status": "Pending"}, update_modified=False)
		err = refused(lambda: as_(user, lambda: Q.start_negotiation(F.q)))
		_assert("mandatory Buyer Catalog setup is pending" in err, err)
		frappe.db.set_value("Buyer Master", BUYER, "buyer_catalog_status", "Completed", update_modified=False)
		_assert(not as_(user, lambda: Q.form_actions(F.q)).get("buyer_not_ready"), "still held when ready")
		_assert(as_(user, lambda: Q.start_negotiation(F.q))["status"] == "Negotiation", "Start Negotiation once ready")

	check("Start Negotiation / Finalize wait for the approval and the Buyer Catalog, with the reason on the form", _held)

	def _request_keeps_buyer():
		frappe.db.set_value("Quotation", F.q, {"custom_quotation_source": "Buyer Order Request Form", "custom_buyer_order_request_ref": "BOR-2627-77777",
			"custom_quotation_status": "Draft"}, update_modified=False)
		other = frappe.db.get_value("Buyer Master", {"name": ("!=", BUYER), "buyer_status": "Approved", "customer": ("is", "set")}, "name")

		def _change():
			q = frappe.get_doc("Quotation", F.q)
			q.party_name = other
			q.save(ignore_permissions=True)

		err = refused(_change)
		_assert("order request BOR-2627-77777 of its Buyer" in err, err)

	check("A buyer's order request keeps its Customer", _request_keeps_buyer)
