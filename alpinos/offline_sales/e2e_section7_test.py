"""Doc Section 7, "End-to-End Workflow for Existing Approved Buyer", as an automated flow (S7-R1).

The 14 steps with the doc's actors, run through the real actions (the same calls the screens
make), each asserting its status and its trail entry: Direct Opportunity -> Submit -> Convert to
Quotation -> commercial edit -> Partial payment term (Advance + Credit) -> Finalize (Opportunity
Won) -> Advance recorded with proof -> SO Eligibility Allowed -> Create Sales Order (Sales Officer
refused, duplicate refused) -> quantity change with a reason -> submit -> Buyer Catalog sync ->
fulfilment handoff. TEST sites only; everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.e2e_section7_test.run
"""

import json

import frappe
from frappe.utils import add_days, flt, today

R = []
TAG = "E2E" + frappe.generate_hash(length=4).upper()
F = frappe._dict()
BUYER = "OBM-2026-00002"  # 247 Nutrition: Sites with billing / shipping, priced catalogue


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
	sp = "e2e_" + frappe.generate_hash(length=6)
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


def trail(doctype, name, action=None):
	filters = {"reference_doctype": doctype, "reference_name": name}
	if action:
		filters["action"] = action
	return frappe.get_all("Field Change Log", filters=filters, fields=["action", "field_label", "previous_value", "new_value",
		"reason", "user_role", "changed_by", "item_code"], order_by="creation asc")


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	real_enqueue = frappe.enqueue
	frappe.enqueue = lambda *a, **k: None  # emails / PDFs after commit: not part of this flow
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


def _person(suffix, roles, assign=False):
	from alpinos.company_scope import sync

	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles + ["Employee"]):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	emp = _insert("Employee", name=f"{TAG}-{suffix.upper()}", employee_name=f"{TAG} {suffix}", first_name=suffix, status="Active",
		company=F.company, date_of_joining="2026-01-01", user_id=user)
	sync.ensure_membership(user, F.company, roles, is_default=True)
	sync.sync_user(user)
	if assign:
		_insert("Buyer Sales Officer", name=f"{TAG}-BSO-{suffix}", parent=BUYER, parenttype="Buyer Master",
			parentfield="sales_officers", employee=emp, idx=90)
	return user


def _fixtures():
	from alpinos import item_mrp as IM
	from alpinos.dispatch_report_api import _marketing_material_items

	F.company = frappe.defaults.get_global_default("company")
	frappe.db.set_value("Buyer Master", BUYER, {"buyer_status": "Approved", "buyer_catalog_status": "Completed"})
	F.customer = frappe.db.get_value("Buyer Master", BUYER, "customer")
	F.ravi = _person("ravi", ["Sales Officer"], assign=True)  # SO-1
	F.parth = _person("parth", ["Sales Manager"])  # SM-1
	# two catalogue SKUs with one active MRP each (the Sales Order submit checks the MRP)
	rows = frappe.db.sql(
		"""SELECT DISTINCT bil.item_code FROM `tabBuyer Item` bil JOIN `tabBuyer Items` bi ON bi.name = bil.parent
		WHERE bi.buyer = %s AND IFNULL(bi.docstatus, 0) < 2 AND bil.selling_rate > 0 ORDER BY bil.item_code""",
		F.customer, pluck=True,
	)
	single = [c for c in rows if IM.applicable(c).tracked and len(IM.applicable(c).mrps) == 1]
	_assert(len(single) >= 2, f"need two one-MRP catalogue SKUs for {BUYER}: {single}")
	F.sku1, F.sku2 = single[0], single[1]
	mm = sorted(_marketing_material_items())
	F.freebie = mm[0] if mm else None
	frappe.clear_cache()


def _run():
	_fixtures()
	from alpinos.offline_sales import opportunity as O
	from alpinos.offline_sales import quotation as Q
	from alpinos.offline_sales import quotation_payments as P
	from alpinos.offline_sales import so_handoff as H
	from alpinos.sales_order_offline_buyer import site_address_options

	from alpinos.sales_order_offline_buyer import get_customer_family_sites

	F.site = get_customer_family_sites(F.customer)[0]
	billing, shipping, every = site_address_options(F.customer, F.site)
	all_b, all_s, all_e = site_address_options(F.customer, None)
	billing, shipping = billing or all_b or every, shipping or all_s or every

	def s1():
		doc = frappe.get_doc({
			"doctype": "Opportunity", "opportunity_from": "Buyer Master", "party_name": BUYER, "company": F.company,
			"transaction_date": today(), "custom_site_name": F.site, "custom_billing_address": billing[0], "customer_address": shipping[0],
			"items": [{"item_code": F.sku1, "qty": 120}, {"item_code": F.sku2, "qty": 50}],
			"custom_marketing_freebies": [{"item_code": F.freebie, "qty": 100}] if F.freebie else [],
		})
		as_(F.ravi, lambda: doc.insert())
		F.opp = doc.name
		opp = frappe.get_doc("Opportunity", F.opp)
		_assert(opp.custom_opportunity_status == "Pending (Draft)" and opp.custom_opportunity_source == "Direct Opportunity", opp.custom_opportunity_status)
		_assert(trail("Opportunity", F.opp, "Opportunity Created"), "no 'Opportunity Created' row")

	check("1 Sales Officer creates a Direct Opportunity: Pending (Draft), trail Created", s1)

	def s2():
		as_(F.ravi, lambda: O.opportunity_action(F.opp, "submit"))
		opp = frappe.get_doc("Opportunity", F.opp)
		_assert(opp.custom_opportunity_status == "Pending (Submitted)" and opp.custom_submitted_by == F.ravi and opp.custom_submitted_on, opp.custom_opportunity_status)

		def _edit():
			d = frappe.get_doc("Opportunity", F.opp)
			d.items[0].qty = 999
			d.save()

		_assert(refused(lambda: as_(F.parth, _edit)), "a submitted Opportunity was edited")

	check("2 Submit: Submitted By / On stamped, Pending (Submitted), read-only for everyone", s2)

	def s3():
		r = as_(F.parth, lambda: O.convert_to_quotation(F.opp))
		F.qtn = r.get("quotation") if isinstance(r, dict) else r
		opp = frappe.get_doc("Opportunity", F.opp)
		q = frappe.get_doc("Quotation", F.qtn)
		_assert(opp.custom_opportunity_status == "Converted to Quotation" and opp.custom_linked_quotation == F.qtn, opp.custom_opportunity_status)
		_assert(q.opportunity == F.opp and q.custom_quotation_status == "Draft", (q.opportunity, q.custom_quotation_status))
		_assert(sorted((r.item_code, flt(r.qty)) for r in q.items) == sorted([(F.sku1, 120), (F.sku2, 50)]), "items not copied")
		if F.freebie:
			_assert([(r.item_code, flt(r.qty)) for r in q.custom_marketing_freebies] == [(F.freebie, 100)], "freebie not copied")

	check("3 Sales Manager converts: Draft Quotation with items and freebies, linked both ways", s3)

	def s4():
		def _edit():
			q = frappe.get_doc("Quotation", F.qtn)
			q.items[0].custom_selling_price = flt(flt(q.items[0].custom_selling_price) * 0.95, 2)
			q.save()

		as_(F.parth, _edit)
		F.grand_total = flt(frappe.db.get_value("Quotation", F.qtn, "grand_total"), 2)
		rows = [t for t in trail("Quotation", F.qtn) if "Commercial" in (t.action or "") or "Price" in (t.action or "")]
		_assert(rows, "no commercial edit row in the Quotation trail")

	check("4 commercial edit on the Quotation is in its trail", s4)

	def s5():
		half = flt(F.grand_total / 2, 2)

		def _term():
			q = frappe.get_doc("Quotation", F.qtn)
			q.custom_payment_term = "Partial"
			q.set("custom_payment_schedule", [
				{"payment_term": "Advance", "expected_payment_date": add_days(today(), 1), "expected_amount": half},
				{"payment_term": "Credit", "expected_payment_date": add_days(today(), 30), "expected_amount": flt(F.grand_total - half, 2)},
			])
			q.save()

		as_(F.parth, _term)
		q = frappe.get_doc("Quotation", F.qtn)
		_assert(flt(sum(flt(r.expected_amount) for r in q.custom_payment_schedule), 2) == F.grand_total, "schedule != Grand Total")

	check("5 Partial Payment Term: Advance + Credit rows that add up to the Grand Total", s5)

	def s6_7():
		as_(F.parth, lambda: Q.finalize(F.qtn))
		q = frappe.get_doc("Quotation", F.qtn)
		_assert(q.custom_quotation_status == "Finalized" and q.docstatus == 1 and q.custom_finalized_by == F.parth, q.custom_quotation_status)
		_assert(q.custom_payment_status == "Pending" and q.custom_so_eligibility == "Blocked", (q.custom_payment_status, q.custom_so_eligibility))
		opp = frappe.db.get_value("Opportunity", F.opp, "custom_opportunity_status")
		_assert(opp == "Won", f"Opportunity is {opp}, every requested SKU and quantity was quoted")

	check("6-7 Finalize: Finalized (no payment status mixed in), SO Eligibility Blocked; Opportunity Won", s6_7)

	def s8_9():
		f = frappe.get_doc({"doctype": "File", "file_name": f"{TAG}-receipt.png", "is_private": 1, "content": b"\x89PNG\r\n\x1a\n" + b"0" * 64,
			"attached_to_doctype": "Quotation", "attached_to_name": F.qtn})
		f.insert(ignore_permissions=True)
		advance = flt(frappe.get_doc("Quotation", F.qtn).custom_payment_schedule[0].expected_amount)
		as_(F.ravi, lambda: P.record_payment(F.qtn, received_amount=advance, received_date=today(), payment_proof=f.file_url,
			reference_utr="HDFCR92026091211029", remarks="50% Advance received", schedule_row=1))
		q = frappe.get_doc("Quotation", F.qtn)
		_assert(flt(q.custom_total_received) == advance and q.custom_payment_status == "Partially Received", (q.custom_total_received, q.custom_payment_status))
		_assert(q.custom_quotation_status == "Finalized", "a payment changed the Quotation Status")
		_assert(q.custom_payment_schedule[0].row_status == "Fully Received" and q.custom_payment_schedule[1].row_status == "Pending", "row statuses")
		_assert(q.custom_so_eligibility == "Allowed", f"SO Eligibility {q.custom_so_eligibility} after the Advance")

	check("8-9 Advance recorded with proof: Partially Received, Quotation stays Finalized, SO Eligibility Allowed", s8_9)

	def s10():
		_assert(not as_(F.ravi, lambda: H.can_create_sales_order(F.qtn))["allowed"], "a Sales Officer may create the Sales Order")
		from alpinos import quotation_api, sales_order_api

		payload = as_(F.parth, lambda: quotation_api.get_sales_order_entry_payload_from_quotation(F.qtn))
		F.so_items = [{"item_code": r["item_code"], "qty": r["qty"], "custom_customer_mrp": r["mrp"],
			"custom_selling_price": r.get("custom_selling_price"), "custom_flat_discount": r.get("flat_discount"),
			"custom_gst_percent": r.get("item_tax_percent")} for r in payload["items"]]
		args = dict(customer=payload["customer"], order_type=payload["order_type"], company=F.company, items=json.dumps(F.so_items),
			delivery_date=add_days(today(), 7), dispatch_date=add_days(today(), 1), billing_address=payload["billing_address"],
			shipping_address=payload["shipping_address"], site_name=payload.get("site_name") or "", from_quotation=F.qtn, submit_now=0,
			freebies=json.dumps(payload.get("freebies") or []))
		err = refused(lambda: as_(F.ravi, lambda: sales_order_api.create_sales_order(**args)))
		_assert(err, "a Sales Officer created a Sales Order from the Quotation")
		out = as_(F.parth, lambda: sales_order_api.create_sales_order(**args))
		F.so = out["name"]
		so = frappe.get_doc("Sales Order", F.so)
		_assert(so.custom_quotation == F.qtn and so.custom_opportunity == F.opp and so.docstatus == 0, (so.custom_quotation, so.custom_opportunity))
		q = frappe.db.get_value("Quotation", F.qtn, ["custom_quotation_status", "custom_linked_sales_order"], as_dict=True)
		_assert(q.custom_quotation_status == "Sales Order Created" and q.custom_linked_sales_order == F.so, q)
		dup = refused(lambda: as_(F.parth, lambda: sales_order_api.create_sales_order(**args)))
		_assert("already linked to Quotation" in dup, dup)
		F.args = args

	check("10 Create Sales Order: Sales Officer refused; SM creates a Draft linked to Quotation + Opportunity; duplicate refused", s10)

	def s11():
		from alpinos import sales_order_api

		items = [dict(r) for r in F.so_items]
		items[0]["qty"] = flt(items[0]["qty"]) - 5
		args = dict(F.args, items=json.dumps(items), name=F.so)
		args.pop("submit_now", None)
		err = refused(lambda: as_(F.parth, lambda: sales_order_api.update_sales_order(**args)))
		_assert("Reason for Change" in err, err)
		as_(F.parth, lambda: sales_order_api.update_sales_order(**args, change_reason="Buyer reduced the quantity"))
		rows = trail("Sales Order", F.so, "Sales Order Commercial Value Changed")
		_assert(rows and rows[0].reason == "Buyer reduced the quantity" and rows[0].field_label == "Quantity", rows)
		q_qty = frappe.db.get_value("Quotation Item", {"parent": F.qtn, "item_code": F.so_items[0]["item_code"]}, "qty")
		_assert(flt(q_qty) == flt(F.so_items[0]["qty"]), "the Quotation changed with the Sales Order")

	check("11 quantity change on the Draft needs a reason, is recorded, and leaves the Quotation as it was", s11)

	def s12_14():
		as_(F.parth, lambda: frappe.get_doc("Sales Order", F.so).submit())
		so = frappe.get_doc("Sales Order", F.so)
		_assert(so.docstatus == 1, "not submitted")
		_assert(trail("Sales Order", F.so, "Sales Order Submitted"), "no 'Sales Order Submitted' row")
		synced = frappe.db.sql("""SELECT bil.item_code FROM `tabBuyer Item` bil JOIN `tabBuyer Items` bi ON bi.name = bil.parent
			WHERE bi.buyer = %s AND bil.last_sales_order = %s""", (F.customer, F.so), pluck=True)
		_assert({F.sku1, F.sku2} <= set(synced), f"catalogue rows not synced from {F.so}: {synced}")
		handoff = trail("Sales Order", F.so, "Fulfillment Handoff")
		_assert(handoff and handoff[0].user_role == "System" and handoff[0].new_value == "Downstream Processing", handoff)

	check("12-14 submit: 'Sales Order Submitted', Buyer Catalog synced from the order, Fulfillment Handoff by System", s12_14)
