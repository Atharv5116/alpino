"""The Opportunity ("Opportunity to Sales Order v1.0.0", Section 3; W4). TEST sites only.

Run:  bench --site <test site> execute alpinos.offline_sales.opportunity_test.run

Everything is rolled back: commits are disabled for the run, users / employees are written with
db_insert like the other buyer tests, and settings / masters touched are restored by the rollback.
"""

import json

import frappe
from frappe.utils import flt, today

R = []
TAG = "OPT" + frappe.generate_hash(length=4).upper()
F = frappe._dict()

API = "alpinos.offline_sales.opportunity"
M14 = "Quotation cannot be created because linked Buyer Approval & Buyer Catalog creation is pending."
M16 = "Quotation cannot be created because mandatory Buyer Catalog setup is pending."
M17 = "Quotation cannot be created because the linked Buyer is currently On Hold."
M18 = "This Buyer is currently On Hold and cannot be used for new sales transactions until approved by SM or SA."


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def refused(fn):
	"""The error text fn() raises ("" when it went through), undoing only what fn() did."""
	sp = "opt_" + frappe.generate_hash(length=6)
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


# ----------------------------------------------------------------------------- fixtures

_SEQ = [0]


def _letters(n):
	import random
	import string

	return "".join(random.choice(string.ascii_uppercase) for _ in range(n))


def gstin():
	_SEQ[0] += 1
	return f"24{_letters(5)}{3000 + _SEQ[0]:04d}{_letters(1)}1Z5"


def _person(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	emp = _insert(
		"Employee", name=f"{TAG}-{suffix.upper()}", employee_name=f"{TAG} {suffix.title()}", first_name=suffix,
		status="Active", company=F.company, date_of_joining="2026-01-01", user_id=user,
	)
	return frappe._dict(user=user, emp=emp)


def _items():
	from alpinos import item_mrp as IM

	rows = frappe.db.sql(
		"""SELECT i.name, i.valuation_rate,
			(SELECT COUNT(*) FROM `tabItem MRP` m WHERE m.parent = i.name AND m.active = 1 AND m.mrp > 0) AS active_mrps,
			(SELECT COUNT(*) FROM `tabItem MRP` m WHERE m.parent = i.name) AS mrp_rows,
			(SELECT conversion_factor FROM `tabUOM Conversion Detail` u WHERE u.parent = i.name AND u.uom = 'Box' LIMIT 1) AS box
		FROM tabItem i WHERE i.disabled = 0 AND i.is_sales_item = 1 AND i.has_variants = 0 ORDER BY i.name""",
		as_dict=True,
	)
	single = [r for r in rows if r.active_mrps == 1 and r.mrp_rows == 1]
	F.single = next((r.name for r in single if flt(r.box) > 1), None) or single[0].name
	F.single_mrp = IM.applicable(F.single).mrps[0]
	F.box = flt(next((r.box for r in rows if r.name == F.single), 0))
	F.single2 = next(r.name for r in single if r.name != F.single)
	F.multi = next(r.name for r in rows if r.active_mrps > 1)
	F.multi_mrps = IM.applicable(F.multi).mrps
	F.plain = next(r.name for r in rows if r.mrp_rows == 0 and flt(r.valuation_rate) > 0)
	F.plain_rate = flt(frappe.db.get_value("Item", F.plain, "valuation_rate"))
	F.freebie = next(r.name for r in rows if r.mrp_rows == 0 and r.name != F.plain)


def _fixtures():
	F.company = frappe.defaults.get_global_default("company")
	F.customer_type = frappe.db.sql(
		"SELECT customer_type FROM `tabBuyer Master` WHERE IFNULL(channel,'') != 'E-com' AND IFNULL(customer_type,'') != '' "
		"GROUP BY customer_type ORDER BY COUNT(*) DESC LIMIT 1"
	)[0][0]
	F.city = frappe.db.get_value("City", {"state": "Gujarat"}, "name")
	F.so1 = _person("so1", "Sales Officer")
	F.so2 = _person("so2", "Sales Officer")
	F.sm1 = _person("sm1", "Sales Manager")
	F.sa1 = _person("sa1", "Sales Admin")
	F.su = _person("su", "Sales User")
	frappe.clear_cache()
	settings = frappe.get_single("Offline Sales Settings")
	settings.set("default_primary_pocs", [{"employee": F.sm1.emp}])
	settings.assignment_scope_for_managers = 0
	settings.save(ignore_permissions=True)
	_items()
	frappe.db.set_value("Alpino Customer Type", F.customer_type, {"round_up": 1, "round_down": 0})

	F.ready = new_buyer("Administrator")  # Approved (a manager creates it)
	_catalog(F.ready)
	_assert(frappe.db.get_value("Buyer Master", F.ready.name, "buyer_catalog_status") == "Completed", "catalogue not completed")
	F.pending = new_buyer(F.so1.user)  # Pending Approval
	F.other = new_buyer("Administrator", sales_officers=[{"employee": F.so2.emp}])
	set_status(F.other.name, "Approved", "Completed")


def buyer_data(**kw):
	_SEQ[0] += 1
	n = _SEQ[0]
	data = {
		"doctype": "Buyer Master",
		"channel": "Offline",
		"customer_business_name": f"{TAG} Buyer {n}",
		"customer_type": F.customer_type,
		"gst_type": "Registered Business",
		"gst_no": gstin(),
		"level": "N/A",
		"payment_term": "Advance",
		"contact_person": "Ravi",
		"email": f"opt{n}@example.com",
		"contact_no": "9876543210",
		"secondary_poc": F.sa1.emp,
		"sales_officers": [{"employee": F.so1.emp}],
		"site_name": f"HQ {n}",
		"addresses": [
			{"site_name": f"HQ {n}", "address_line": f"{n} Ring Road", "state": "Gujarat", "city": F.city,
				"pincode": "380015", "country": "India", "is_primary": 1, "is_shipping": 0},
			{"site_name": f"Godown {n}", "address_line": f"Plot {n}", "state": "Gujarat", "city": F.city,
				"pincode": "382010", "country": "India", "is_primary": 0, "is_shipping": 1},
		],
	}
	data.update(kw)
	return data


def new_buyer(user="Administrator", **kw):
	from alpinos.sales_order_offline_buyer import sync_offline_buyer_master_addresses

	def _make():
		doc = frappe.get_doc(buyer_data(**kw))
		doc.insert()
		return doc

	doc = as_(user, _make)
	frappe.db.set_value("Buyer Master", doc.name, "round_off_per_unit", 0, update_modified=False)
	sync_offline_buyer_master_addresses(doc.customer)
	return frappe.get_doc("Buyer Master", doc.name)


def set_status(name, status, catalog=None):
	frappe.db.set_value("Buyer Master", name, "buyer_status", status, update_modified=False)
	if catalog:
		frappe.db.set_value("Buyer Master", name, "buyer_catalog_status", catalog, update_modified=False)


def _catalog(buyer):
	from alpinos import offline_buyer_api as api

	F.multi_rate = flt(F.multi_mrps[0] * 0.9, 2)  # the catalogue stores MRP x (1 - Flat %)
	record = api.create_record(f"{TAG} Catalogue {buyer.name}", offline_buyer_master=buyer.name)
	api.save_buyer_items(record, json.dumps([
		{"selected": 1, "item_code": F.single, "item_name": F.single, "mrp": F.single_mrp, "margin_percent": 20},
		{"selected": 1, "item_code": F.multi, "item_name": F.multi, "mrp": F.multi_mrps[0], "margin_percent": 10,
			},
	]))


def opp_doc(buyer, rows, **kw):
	from alpinos.sales_order_offline_buyer import site_address_options

	b = frappe.get_doc("Buyer Master", buyer)
	billing, shipping, every = site_address_options(b.customer, None)
	data = {
		"doctype": "Opportunity",
		"opportunity_from": "Buyer Master",
		"party_name": buyer,
		"company": F.company,
		"currency": frappe.get_cached_value("Company", F.company, "default_currency"),
		"transaction_date": today(),
		"custom_site_name": b.site_name,
		"custom_billing_address": (billing or every)[0],
		"customer_address": (shipping or every)[0],
		"custom_common_remark": "Deliver before Diwali",
		"items": [{"item_code": code, "qty": qty} for code, qty in rows],
	}
	data.update(kw)
	return data


def new_opp(user, buyer, rows=None, **kw):
	rows = rows if rows is not None else [(F.single, 10)]
	return as_(user, lambda: frappe.get_doc(opp_doc(buyer, rows, **kw)).insert())


def act(user, name, action, reason=None):
	from alpinos.offline_sales.opportunity import opportunity_action

	return as_(user, lambda: opportunity_action(name, action, reason))


def status(name):
	return frappe.db.get_value("Opportunity", name, "custom_opportunity_status")


def trail(name, action=None):
	filters = {"reference_doctype": "Opportunity", "reference_name": name}
	if action:
		filters["action"] = action
	return frappe.get_all(
		"Field Change Log", filters=filters,
		fields=["action", "field_label", "previous_value", "new_value", "reason", "user_role", "changed_by"],
		order_by="creation asc",
	)


def save_as(user, name, change):
	def _go():
		doc = frappe.get_doc("Opportunity", name)
		change(doc)
		doc.save()

	return refused(lambda: as_(user, _go))


def submitted(user=None, buyer=None, rows=None, **kw):
	doc = new_opp(user or F.so1.user, buyer or F.ready.name, rows, **kw)
	act(user or F.so1.user, doc.name, "submit")
	return doc.name


def converted(rows=None, **kw):
	from alpinos.offline_sales.opportunity import convert_to_quotation

	name = submitted(rows=rows, **kw)
	q = as_(F.so1.user, lambda: convert_to_quotation(name))["quotation"]
	return name, q


# ----------------------------------------------------------------------------- tests


def _run():
	_fixtures()
	_matrix()
	_creation()
	_pricing()
	_row_rules()
	_transitions()
	_lock()
	_convert()
	_engine()
	_scoping()
	_form_support()
	_legacy()


def _matrix():
	def perm(user, ptype):
		return as_(user, lambda: bool(frappe.has_permission("Opportunity", ptype)))

	def _so():
		_assert(perm(F.so1.user, "read") and perm(F.so1.user, "create") and perm(F.so1.user, "write"), "SO lacks read/create/write")
		_assert(not perm(F.so1.user, "delete"), "SO may delete an Opportunity")

	check("roles: a Sales Officer reads, creates and edits Opportunities, never deletes", _so)


def _creation():
	def _direct():
		doc = new_opp(F.so1.user, F.ready.name)
		_assert(doc.custom_opportunity_status == "Pending (Draft)", doc.custom_opportunity_status)
		_assert(doc.custom_opportunity_source == "Direct Opportunity", doc.custom_opportunity_source)
		_assert(doc.custom_created_by == F.so1.user and doc.custom_created_on, f"{doc.custom_created_by} {doc.custom_created_on}")
		_assert(not doc.custom_buyer_order_request_ref and not doc.custom_submitted_by, "system fields set on create")
		_assert(doc.name.startswith("OPP-2627-"), doc.name)
		rows = trail(doc.name, "Opportunity Created")
		_assert(rows and rows[0].user_role == "Sales Officer" and "Direct Opportunity" in rows[0].new_value, str(rows))

	check("3.1 / 6.1 a Direct Opportunity starts Pending (Draft): Source, Created By / On, OPP-2627-, audited", _direct)

	def _tamper():
		doc = new_opp(
			F.so1.user, F.ready.name, custom_opportunity_status="Won", custom_opportunity_source="Buyer Order Request Form",
			custom_buyer_order_request_ref="BOR-2627-99999", custom_submitted_by=F.sm1.user, custom_linked_quotation=None,
			custom_created_by=F.sm1.user,
		)
		_assert(doc.custom_opportunity_status == "Pending (Draft)", doc.custom_opportunity_status)
		_assert(doc.custom_opportunity_source == "Direct Opportunity" and not doc.custom_buyer_order_request_ref, "source kept")
		_assert(not doc.custom_submitted_by and doc.custom_created_by == F.so1.user, "stamps kept")

	check("3.1 Status, Source, BOR Ref and stamps sent by the client are ignored on create", _tamper)

	def _portal():
		def _go():
			doc = frappe.get_doc(opp_doc(
				F.ready.name, [(F.single, 4)], custom_opportunity_source="Buyer Order Request Form",
				custom_buyer_order_request_ref=f"BOR-2627-{TAG}", custom_request_contact_person="Asha",
				custom_source_display="Buyer Portal – Asha",
			))
			doc.flags.from_order_portal = True
			doc.insert(ignore_permissions=True)
			return doc

		doc = as_("Guest", _go)
		_assert(doc.custom_opportunity_source == "Buyer Order Request Form" and doc.custom_buyer_order_request_ref == f"BOR-2627-{TAG}",
			f"{doc.custom_opportunity_source} {doc.custom_buyer_order_request_ref}")
		_assert(doc.custom_opportunity_status == "Pending (Draft)" and not doc.custom_created_by, doc.custom_created_by)
		_assert(flt(doc.items[0].custom_selling_price) == flt(F.single_mrp * 0.8, 2), "portal row not priced from the catalogue")
		err = save_as(F.sm1.user, doc.name, lambda d: d.set("custom_buyer_order_request_ref", "BOR-2627-00001"))
		_assert("cannot be changed" in err, f"BOR Ref changed by a user: {err}")
		err = save_as(F.sm1.user, doc.name, lambda d: d.set("custom_opportunity_source", "Direct Opportunity"))
		_assert("cannot be changed" in err, f"Source changed by a user: {err}")

		def _portal_edit():
			d = frappe.get_doc("Opportunity", doc.name)
			d.custom_request_contact_person = "Asha P"
			d.flags.from_order_portal = True
			d.save(ignore_permissions=True)

		_assert(not refused(_portal_edit), "the portal could not update its own Draft")

	check("2 / 3.1 the portal (flag) sets Source + BOR Ref; nobody else can change them", _portal)

	def _gates():
		b = new_buyer("Administrator")
		set_status(b.name, "On Hold")
		err = refused(lambda: new_opp(F.so1.user, b.name))
		_assert(M18 in err, f"On Hold: {err}")
		for st in ("Inactive", "Cancelled"):
			set_status(b.name, st)
			err = refused(lambda: new_opp(F.so1.user, b.name))
			_assert(st in err, f"{st}: {err}")
		_assert(not refused(lambda: new_opp(F.so1.user, F.pending.name)), "Pending Approval buyer refused")
		set_status(b.name, "Approved", "Pending")
		_assert(not refused(lambda: new_opp(F.so1.user, b.name)), "Approved + Catalog Pending buyer refused")

	check("4 6.1 Create: Pending / Approved buyers yes; On Hold (doc message), Inactive, Cancelled no", _gates)

	def _assigned():
		err = refused(lambda: new_opp(F.so1.user, F.other.name))
		_assert("not assigned" in err, f"SO raised one for another officer's buyer: {err}")

	check("1 4.1 a Sales Officer cannot raise an Opportunity for a Buyer not assigned to them", _assigned)


def _pricing():
	def _catalogue():
		doc = new_opp(F.so1.user, F.ready.name, [(F.single, 10)])
		row = doc.items[0]
		sp = flt(F.single_mrp * 0.8, 2)
		_assert(flt(row.custom_mrp) == F.single_mrp and flt(row.custom_flat_discount) == 20, f"{row.custom_mrp} {row.custom_flat_discount}")
		_assert(flt(row.custom_selling_price) == sp and flt(row.custom_line_amount) == flt(10 * sp, 2), f"{row.custom_selling_price} {row.custom_line_amount}")
		_assert(flt(row.custom_offer) == 0 and flt(row.custom_additional_discount) == 0, "offer / additional not 0")
		_assert(flt(doc.total) == flt(row.custom_line_amount) and flt(doc.opportunity_amount) == flt(doc.total), f"total {doc.total}")
		gst = flt(frappe.db.get_value("Item", F.single, "custom_gst_percent"))
		_assert(abs(flt(row.amount) - flt(row.custom_line_amount) / (1 + gst / 100)) < 0.05, f"amount {row.amount} not before GST")

	check("3.2 catalogue SKU: MRP, Flat %, Selling Price, Line Amount = Qty x Selling Price, total", _catalogue)

	def _typed_ignored():
		d = opp_doc(F.ready.name, [(F.single, 5)])
		d["items"][0].update({"custom_mrp": 1, "custom_flat_discount": 99, "custom_selling_price": 1, "custom_offer": "50",
			"custom_additional_discount": 30, "custom_line_amount": 1, "custom_boxes": 99})
		doc = as_(F.so1.user, lambda: frappe.get_doc(d).insert())
		row = doc.items[0]
		_assert(flt(row.custom_mrp) == F.single_mrp and flt(row.custom_flat_discount) == 20, "typed MRP / Flat kept")
		_assert(flt(row.custom_selling_price) == flt(F.single_mrp * 0.8, 2) and flt(row.custom_additional_discount) == 0, "typed price kept")
		_assert(flt(row.custom_offer) == 0, "typed offer kept")
		frappe.db.set_value("Opportunity Item", row.name, "custom_selling_price", 1)
		save_as(F.sm1.user, doc.name, lambda x: x.set("custom_common_remark", "re-save"))
		_assert(flt(frappe.db.get_value("Opportunity Item", row.name, "custom_selling_price")) == flt(F.single_mrp * 0.8, 2), "not recomputed on save")

	check("3.2 commercial values typed by the client are recomputed on every Draft save", _typed_ignored)

	def _fallback():
		doc = new_opp(F.so1.user, F.ready.name, [(F.plain, 3)])
		row = doc.items[0]
		_assert(flt(row.custom_mrp) == F.plain_rate and flt(row.custom_flat_discount) == 0, f"{row.custom_mrp} {row.custom_flat_discount}")
		_assert(flt(row.custom_selling_price) == flt(F.plain_rate, 2) and flt(row.custom_line_amount) == flt(3 * F.plain_rate, 2), str(row.custom_selling_price))

	check("2 / 3.2 SKU not in the catalogue: Flat 0 %, Selling Price = MRP, never blocked", _fallback)

	def _multi():
		m1, m2 = F.multi_mrps[0], F.multi_mrps[1]
		doc = new_opp(F.so1.user, F.ready.name, [(F.multi, 2)])
		_assert(flt(doc.items[0].custom_mrp) == 0 and flt(doc.items[0].custom_selling_price) == 0, "a multi-MRP SKU got an MRP by itself")
		err = refused(lambda: act(F.so1.user, doc.name, "submit"))
		_assert("Select the MRP" in err, f"submit without MRP: {err}")
		d = opp_doc(F.ready.name, [(F.multi, 2), (F.multi, 1)])
		d["items"][0]["custom_mrp"] = m1
		d["items"][1]["custom_mrp"] = m2
		doc = as_(F.so1.user, lambda: frappe.get_doc(d).insert())
		a, b = doc.items
		_assert(flt(a.custom_mrp) == m1 and flt(a.custom_selling_price) == F.multi_rate and flt(a.custom_flat_discount) == 10, f"{a.custom_mrp} {a.custom_selling_price}")
		_assert(flt(b.custom_mrp) == m2 and flt(b.custom_selling_price) == flt(m2, 2) and flt(b.custom_flat_discount) == 0, f"{b.custom_mrp} {b.custom_selling_price}")
		d = opp_doc(F.ready.name, [(F.multi, 2)])
		d["items"][0]["custom_mrp"] = 1.23
		doc = as_(F.so1.user, lambda: frappe.get_doc(d).insert())
		_assert(flt(doc.items[0].custom_mrp) == 0, "an MRP outside the Item's MRPs was kept")

	check("3.2 Multiple MRP: chosen from the Item's MRPs only, priced at that MRP, required at Submit", _multi)

	def _box():
		if not F.box or F.box <= 1:
			raise AssertionError(f"{F.single} has no Box UOM on this site")
		qty = int(F.box * 2 + F.box / 2)
		doc = new_opp(F.so1.user, F.ready.name, [(F.single, qty)])
		_assert(flt(doc.items[0].qty) == qty, f"qty changed to {doc.items[0].qty}")
		_assert(flt(doc.items[0].custom_boxes) == 3, f"round up: {doc.items[0].custom_boxes}")
		frappe.db.set_value("Alpino Customer Type", F.customer_type, {"round_up": 0, "round_down": 1})
		save_as(F.so1.user, doc.name, lambda x: x.set("custom_common_remark", "boxes"))
		row = frappe.db.get_value("Opportunity Item", doc.items[0].name, ["qty", "custom_boxes"], as_dict=True)
		_assert(flt(row.qty) == qty and flt(row.custom_boxes) == 2, f"round down: {row}")
		frappe.db.set_value("Alpino Customer Type", F.customer_type, {"round_up": 1, "round_down": 0})

	check("3.2 Box from Quantity by the Customer Type's Round Up / Down; Quantity never changed", _box)


def _row_rules():
	from alpinos.offline_sales.opportunity import duplicate_sku_warning, get_duplicate_sku_warning

	def _zero():
		for qty in (0, -3):
			err = refused(lambda: new_opp(F.so1.user, F.ready.name, [(F.single, qty)]))
			_assert(f"Quantity for SKU [{F.single}] must be greater than zero." == err, f"{qty}: {err}")
		doc = new_opp(F.so1.user, F.ready.name)
		err = save_as(F.so1.user, doc.name, lambda d: d.items[0].set("qty", 0))
		_assert(f"Quantity for SKU [{F.single}] must be greater than zero." == err, f"save: {err}")
		err = refused(lambda: new_opp(F.so1.user, F.ready.name, custom_marketing_freebies=[{"item_code": F.freebie, "qty": 0}]))
		_assert("must be greater than zero" in err and "Marketing Freebies" in err, f"freebie: {err}")

	check("7.2 zero / negative quantity: the document's message, save blocked (freebies too)", _zero)

	def _inactive():
		frappe.db.set_value("Item", F.plain, "disabled", 1)
		try:
			err = refused(lambda: new_opp(F.so1.user, F.ready.name, [(F.plain, 2)]))
		finally:
			frappe.db.set_value("Item", F.plain, "disabled", 0)
		_assert("is not active" in err, err)

	check("3.2 an inactive SKU is refused", _inactive)

	def _duplicate():
		doc = frappe._dict(
			items=[frappe._dict(name="r1", idx=1, item_code=F.single), frappe._dict(name="r2", idx=2, item_code=F.single2),
				frappe._dict(name="r3", idx=3, item_code=F.single)],
			custom_marketing_freebies=[frappe._dict(name="f1", idx=1, item_code=F.freebie)],
			custom_scheme_item_table=[frappe._dict(name="s1", idx=2, item_code=F.single2)],
		)
		msg = duplicate_sku_warning(doc, "r3")
		_assert(msg == f"Warning: SKU [{F.single}] is already added in row 1. Are you sure you want to add a duplicate line?", msg)
		doc["items"][1].item_code = F.freebie
		_assert(f"SKU [{F.freebie}] is already added in row 1" in (duplicate_sku_warning(doc, "r2") or ""), "freebie match missed")
		doc["items"][1].item_code = F.single2
		doc["custom_marketing_freebies"][0].item_code = F.plain
		_assert(f"SKU [{F.single2}] is already added in row 2" in (duplicate_sku_warning(doc, "r2") or ""), "scheme match missed")
		doc["custom_scheme_item_table"][0].item_code = F.plain
		_assert(duplicate_sku_warning(doc, "r2") is None, "a unique SKU warned")
		payload = json.dumps({"items": [{"name": "a", "idx": 1, "item_code": F.single}, {"name": "b", "idx": 2, "item_code": F.single}]})
		_assert("row 1" in (as_(F.so1.user, lambda: get_duplicate_sku_warning(payload, "b")) or ""), "form call")
		ok = refused(lambda: new_opp(F.so1.user, F.ready.name, [(F.single, 1), (F.single, 2)]))
		_assert(not ok, f"a confirmed duplicate line was refused: {ok}")

	check("3.5 duplicate SKU: the soft warning (other row, Freebies, Scheme), the line may stay", _duplicate)


def _transitions():
	def _submit():
		doc = new_opp(F.so1.user, F.ready.name)
		r = act(F.so1.user, doc.name, "submit")
		row = frappe.db.get_value("Opportunity", doc.name, ["custom_opportunity_status", "custom_submitted_by", "custom_submitted_on"], as_dict=True)
		_assert(r["status"] == "Pending (Submitted)" and row.custom_opportunity_status == "Pending (Submitted)", str(row))
		_assert(row.custom_submitted_by == F.so1.user and row.custom_submitted_on, str(row))
		t = trail(doc.name, "Opportunity Submitted")
		_assert(t and t[0].previous_value == "Pending (Draft)" and t[0].new_value == "Pending (Submitted)", str(t))

	check("6.1 Submit: Draft -> Pending (Submitted), Submitted By / On stamped, audited", _submit)

	def _submit_checks():
		for kw, word in (
			({"custom_billing_address": None}, "Billing Address"),
			({"custom_site_name": ""}, "Site Name"),
			({"custom_scheme_item_table": [{"item_code": F.freebie, "qty": 1}]}, "enter the Scheme"),
		):
			doc = new_opp(F.so1.user, F.ready.name, **kw)
			err = refused(lambda: act(F.so1.user, doc.name, "submit"))
			_assert(word in err, f"{word}: {err}")
		doc = new_opp(F.so1.user, F.ready.name, [])
		_assert("at least one SKU" in refused(lambda: act(F.so1.user, doc.name, "submit")), "submitted with no Order Items")
		old = new_buyer("Administrator")
		set_status(old.name, "Approved", "Completed")
		# most buyers on the live data have no Site Name at all (master and address rows blank)
		frappe.db.set_value("Buyer Master", old.name, "site_name", None, update_modified=False)
		frappe.db.sql("UPDATE `tabBuyer Address` SET site_name = NULL WHERE parent = %s", old.name)
		doc = new_opp(F.so1.user, old.name, custom_site_name="")
		_assert(not refused(lambda: act(F.so1.user, doc.name, "submit")), "a buyer without sites needed a Site Name")

	check("6.1 Submit validates the form; Site Name only when the Buyer has sites", _submit_checks)

	def _submit_buyer():
		doc = new_opp(F.so1.user, F.pending.name)
		_assert(not refused(lambda: act(F.so1.user, doc.name, "submit")), "7.1 submission for a Pending buyer refused")
		b = new_buyer("Administrator")
		doc = new_opp(F.so1.user, b.name)
		set_status(b.name, "On Hold")
		_assert(M18 in refused(lambda: act(F.so1.user, doc.name, "submit")), "submit for an On Hold buyer allowed")

	check("7.1 / 4 6.1 Submit allowed for a Pending buyer, refused for an On Hold one", _submit_buyer)

	def _reasons():
		doc = new_opp(F.so1.user, F.ready.name)
		for action in ("hold", "lost", "cancel"):
			for blank in (None, "  "):
				err = refused(lambda: act(F.sm1.user, doc.name, action, blank))
				_assert("Enter the reason" in err, f"{action}: {err}")

	check("5 Action Reason Rule: Hold, Lost and Cancel need a reason", _reasons)

	def _hold_resume():
		doc = new_opp(F.so1.user, F.ready.name)
		act(F.sa1.user, doc.name, "hold", "Buyer asked to wait")
		row = frappe.db.get_value("Opportunity", doc.name, ["custom_opportunity_status", "custom_status_reason", "custom_status_before_hold"], as_dict=True)
		_assert(row.custom_opportunity_status == "Hold" and row.custom_status_reason == "Buyer asked to wait" and row.custom_status_before_hold == "Pending (Draft)", str(row))
		t = trail(doc.name, "Opportunity Put on Hold")
		_assert(t and t[0].reason == "Buyer asked to wait" and t[0].user_role == "Sales Admin", str(t))
		act(F.so1.user, doc.name, "resume")
		_assert(status(doc.name) == "Pending (Draft)", status(doc.name))
		_assert(not frappe.db.get_value("Opportunity", doc.name, "custom_status_reason"), "reason kept after resume")
		act(F.so1.user, doc.name, "submit")
		act(F.sm1.user, doc.name, "hold", "Stock check")
		act(F.sm1.user, doc.name, "resume")
		_assert(status(doc.name) == "Pending (Submitted)", f"resume from a submitted hold: {status(doc.name)}")
		_assert(trail(doc.name, "Opportunity Resumed"), "resume not audited")

	check("6.1 Hold (reason, audited) and Resume back to the status before Hold (Draft or Submitted)", _hold_resume)

	def _lost_cancel():
		a = new_opp(F.so1.user, F.ready.name)
		act(F.so1.user, a.name, "lost", "Price too high")
		_assert(status(a.name) == "Lost" and frappe.db.get_value("Opportunity", a.name, "custom_status_reason") == "Price too high", "Lost")
		_assert(trail(a.name, "Opportunity Marked Lost")[0].reason == "Price too high", "Lost reason not audited")
		b = submitted()
		act(F.sm1.user, b, "cancel", "Duplicate request")
		_assert(status(b) == "Cancelled", status(b))
		t = trail(b, "Opportunity Cancelled")
		_assert(t and t[0].previous_value == "Pending (Submitted)" and t[0].reason == "Duplicate request", str(t))

	check("6.1 Mark as Lost (Draft) and Cancel Opportunity (Submitted) with their reasons", _lost_cancel)

	def _refused():
		from alpinos.offline_sales.opportunity import convert_to_quotation

		draft = new_opp(F.so1.user, F.ready.name).name
		sub = submitted()
		lost = new_opp(F.so1.user, F.ready.name).name
		act(F.so1.user, lost, "lost", "x")
		hold = new_opp(F.so1.user, F.ready.name).name
		act(F.so1.user, hold, "hold", "x")
		conv, _q = converted()
		cases = [
			(sub, "submit"), (lost, "hold"), (lost, "cancel"), (lost, "resume"), (draft, "resume"), (hold, "submit"),
			(hold, "lost"), (conv, "lost"), (conv, "cancel"), (conv, "hold"), (conv, "submit"),
		]
		for name, action in cases:
			err = refused(lambda: act(F.sm1.user, name, action, "reason"))
			_assert("cannot be" in err, f"{status(name)} -> {action}: {err}")
		for name in (draft, hold, lost):
			err = refused(lambda: as_(F.sm1.user, lambda: convert_to_quotation(name)))
			_assert("Only a Pending (Submitted) Opportunity" in err, f"convert from {status(name)}: {err}")

	check("6.1 refused transitions: each action only from its statuses; Convert only from Submitted", _refused)

	def _plain_save():
		doc = new_opp(F.so1.user, F.ready.name)
		for field, value in (("custom_opportunity_status", "Won"), ("custom_submitted_by", F.so1.user), ("custom_status_reason", "x")):
			err = save_as(F.sm1.user, doc.name, lambda d: d.set(field, value))
			_assert("changes only through its actions" in err, f"{field}: {err}")

	check("6.1 the status and its stamps never change by a plain save", _plain_save)

	def _roles():
		doc = new_opp(F.so1.user, F.ready.name)
		_assert(as_(F.su.user, lambda: frappe.has_permission("Opportunity", "write", doc.name)), "Sales User cannot write (fixture)")
		err = refused(lambda: act(F.su.user, doc.name, "submit"))
		_assert("Only a Sales Officer, Sales Manager or Sales Admin" in err, err)
		for user in (F.so1.user, F.sm1.user, F.sa1.user):
			d = new_opp(F.so1.user, F.ready.name)
			_assert(not refused(lambda: act(user, d.name, "submit")), f"{user} could not submit")

	check("5 SO, SM and SA perform the actions; another role with write access does not", _roles)


def _lock():
	def _all_roles():
		name = submitted()
		frappe.db.set_value("Opportunity Item", {"parent": name}, "custom_row_remark", "")
		edits = {
			"header": lambda d: d.set("custom_common_remark", "changed"),
			"site": lambda d: d.set("custom_site_name", ""),
			"order row": lambda d: d.items[0].set("qty", 99),
			"new order row": lambda d: d.append("items", {"item_code": F.single2, "qty": 1}),
			"freebies": lambda d: d.append("custom_marketing_freebies", {"item_code": F.freebie, "qty": 1}),
			"scheme": lambda d: d.append("custom_scheme_item_table", {"item_code": F.freebie, "qty": 1, "scheme": "S1"}),
			"damage": lambda d: (d.set("custom_additional_units_damage", 1),
				d.append("custom_additional_units_damage_items", {"item_code": F.single, "qty": 1})),
			"remove row": lambda d: d.set("items", []),
		}
		for user in (F.so1.user, F.sm1.user, F.sa1.user):
			for what, change in edits.items():
				err = save_as(user, name, change)
				_assert("can no longer be changed" in err, f"{user} {what}: {err}")
		_assert(not save_as(F.sm1.user, name, lambda d: None), "an unchanged save of a submitted Opportunity was refused")

	check("3.1 lock: a submitted Opportunity's header and all four tables are read only for SO, SM, SA", _all_roles)

	def _other_statuses():
		doc = new_opp(F.so1.user, F.ready.name)
		act(F.so1.user, doc.name, "hold", "wait")
		_assert("can no longer be changed" in save_as(F.so1.user, doc.name, lambda d: d.set("custom_common_remark", "x")), "Hold editable")
		act(F.so1.user, doc.name, "resume")
		_assert(not save_as(F.so1.user, doc.name, lambda d: d.set("custom_common_remark", "x")), "Draft after Resume not editable")

	check("6.1 only Pending (Draft) is editable (Hold is locked until Resume)", _other_statuses)

	def _draft_saved():
		doc = new_opp(F.so1.user, F.ready.name)
		save_as(F.so1.user, doc.name, lambda d: (d.set("custom_common_remark", "Call before delivery"), d.items[0].set("qty", 12)))
		rows = trail(doc.name, "Opportunity Draft Saved")
		_assert(any(r.field_label == "Common Remark" and r.new_value == "Call before delivery" for r in rows), str(rows))
		_assert(any(r.field_label == "Items" and f"{F.single} x 12" in r.new_value for r in rows), str(rows))

	check("5 Save Draft: the changed fields are audited (Opportunity Draft Saved)", _draft_saved)


def _convert():
	from alpinos.offline_sales.opportunity import convert_to_quotation

	def convert(name, user=None):
		return as_(user or F.so1.user, lambda: convert_to_quotation(name))

	def _gates():
		name = submitted(buyer=F.pending.name)
		_assert(refused(lambda: convert(name)) == M14, f"pending: {refused(lambda: convert(name))}")
		set_status(F.pending.name, "Approved", "Pending")
		_assert(refused(lambda: convert(name)) == M16, f"catalogue pending: {refused(lambda: convert(name))}")
		set_status(F.pending.name, "On Hold")
		_assert(refused(lambda: convert(name)) == M17, f"on hold: {refused(lambda: convert(name))}")
		set_status(F.pending.name, "Pending Approval", "Pending")
		_assert(status(name) == "Pending (Submitted)", "a refused conversion changed the status")

	check("7.1 / 4 6.1 Convert refused with the doc's messages: Buyer pending, catalogue pending, On Hold", _gates)

	def _content():
		kw = {
			"custom_marketing_freebies": [{"item_code": F.freebie, "qty": 2}],
			"custom_scheme_item_table": [{"item_code": F.single2, "qty": 3, "scheme": "Diwali 10+1"}],
			"custom_additional_units_damage": 1,
			"custom_additional_units_damage_items": [{"item_code": F.single, "qty": 1, "remarks": "Broken in transit"}],
		}
		d = opp_doc(F.ready.name, [(F.single, int(F.box or 1) * 2), (F.plain, 4)], **kw)
		d["items"][0]["custom_row_remark"] = "Fresh batch only"
		doc = as_(F.so1.user, lambda: frappe.get_doc(d).insert())
		act(F.so1.user, doc.name, "submit")
		r = convert(doc.name)
		opp = frappe.get_doc("Opportunity", doc.name)
		q = frappe.get_doc("Quotation", r["quotation"])
		_assert(opp.custom_opportunity_status == "Converted to Quotation" and opp.custom_linked_quotation == q.name, opp.custom_opportunity_status)
		_assert(q.docstatus == 0 and q.opportunity == opp.name, f"{q.docstatus} {q.opportunity}")
		_assert(q.quotation_to == "Buyer Master" and q.party_name == F.ready.name and q.custom_buyer_master == F.ready.name, q.party_name)
		_assert(q.order_type == opp.custom_order_type and q.custom_site_name == opp.custom_site_name, f"{q.order_type} {q.custom_site_name}")
		_assert(q.customer_address == opp.custom_billing_address and q.shipping_address_name == opp.customer_address,
			f"{q.customer_address}/{q.shipping_address_name} vs {opp.custom_billing_address}/{opp.customer_address}")
		_assert(q.custom_opportunity_remark == "Deliver before Diwali", q.custom_opportunity_remark)
		got = [(i.item_code, flt(i.qty), flt(i.custom_mrp)) for i in q.items]
		want = [(i.item_code, flt(i.qty), flt(i.custom_mrp)) for i in opp.items]
		_assert(got == want, f"{got} != {want}")
		_assert(q.items[0].custom_remarks == "Fresh batch only", q.items[0].custom_remarks)
		_assert([(r.item_code, flt(r.qty)) for r in q.custom_marketing_freebies] == [(F.freebie, 2)], "freebies")
		_assert([(r.item_code, flt(r.qty), r.scheme) for r in q.custom_scheme_item_table] == [(F.single2, 3, "Diwali 10+1")], "scheme")
		_assert(q.custom_additional_units_damage == 1 and [(r.item_code, r.remarks) for r in q.custom_additional_units_damage_items]
			== [(F.single, "Broken in transit")], "damage")
		t = trail(opp.name, "Converted to Quotation")
		_assert(any(x.previous_value == "Pending (Submitted)" and x.new_value == "Converted to Quotation" for x in t), str(t))
		_assert(any(x.new_value == q.name for x in t), str(t))
		F.conv_opp, F.conv_q = opp.name, q.name

	check("5 / 6.1 Convert: a Draft Quotation with header, addresses, remark and all four tables; linked, audited", _content)

	def _one_quotation():
		_assert(F.get("conv_opp"), "no converted Opportunity from the step before")
		err = refused(lambda: convert(F.conv_opp))
		_assert(f"An active Quotation [{F.conv_q}] already exists for this Opportunity." in err, err)
		frappe.db.set_value("Opportunity", F.conv_opp, {"custom_opportunity_status": "Pending (Submitted)", "custom_linked_quotation": None})
		err = refused(lambda: convert(F.conv_opp))
		_assert(f"An active Quotation [{F.conv_q}] already exists" in err, f"unlinked active Quotation: {err}")
		frappe.db.set_value("Quotation", F.conv_q, "docstatus", 2)
		_assert(not refused(lambda: convert(F.conv_opp)), "a cancelled Quotation still blocked a new one")

	check("S5 one active Quotation per Opportunity (the doc's message); a cancelled one frees it", _one_quotation)

	def _standard_button():
		from alpinos.opportunity_make_quotation import make_quotation

		name = submitted()
		err = refused(lambda: as_(F.sm1.user, lambda: make_quotation(name)))
		_assert("Use Convert to Quotation" in err, err)

	check("5 ERPNext's own Create > Quotation is refused for a Buyer Opportunity", _standard_button)


def _engine():
	from alpinos.offline_sales.opportunity import apply_quotation_finalized, compare, quotation_result

	def rows(*pairs):
		return [frappe._dict(item_code=c, qty=q) for c, q in pairs]

	def _compare():
		opp = frappe._dict(items=rows((F.single, 10), (F.plain, 5)), custom_marketing_freebies=rows((F.freebie, 3)))
		cases = [
			(rows((F.single, 10), (F.plain, 5)), "Won", "equal"),
			(rows((F.single, 12), (F.plain, 6)), "Won", "more than requested"),
			(rows((F.single, 10)), "Partial", "missing SKU"),
			(rows((F.single, 9), (F.plain, 5)), "Partial", "lower quantity"),
			(rows((F.single, 6), (F.single, 4), (F.plain, 5)), "Won", "one SKU on two lines"),
		]
		for q_items, want, label in cases:
			got = compare(opp, frappe._dict(items=q_items)).result
			_assert(got == want, f"{label}: {got}")
		q = frappe._dict(items=rows((F.single, 10), (F.plain, 5)), custom_marketing_freebies=[],
			custom_scheme_item_table=rows((F.single2, 9)), custom_additional_units_damage_items=rows((F.single, 99)))
		_assert(compare(opp, q).result == "Won", "freebies / scheme / damage changed the result")
		opp2 = frappe._dict(items=rows((F.single, 10)), custom_scheme_item_table=rows((F.single2, 50)))
		_assert(compare(opp2, frappe._dict(items=rows((F.single, 10)))).result == "Won", "an Opportunity scheme row counted")
		short = compare(opp, frappe._dict(items=rows((F.single, 7)))).shortfalls
		_assert({s["item_code"] for s in short} == {F.single, F.plain}, str(short))

	check("6.2 comparison: all SKUs at >= quantity = Won; missing / lower = Partial; other tables excluded", _compare)

	def _won():
		name, q = converted([(F.single, 4)])
		r = as_(F.so1.user, lambda: quotation_result(q))
		_assert(r["opportunity"] == name and r["result"] == "Won" and not r["reason_required"], str(r))
		_assert(apply_quotation_finalized(q) == "Won", "not Won")
		_assert(status(name) == "Won" and not frappe.db.get_value("Opportunity", name, "custom_status_reason"), status(name))
		t = trail(name, "Opportunity Won")
		_assert(any(x.user_role == "System" and x.new_value == "Won" for x in t) and any(x.new_value == q for x in t), str(t))

	check("6.2 Won: set automatically, no reason, Done By System, the Quotation recorded", _won)

	def _partial():
		name, q = converted([(F.single, 4), (F.plain, 2)])
		qdoc = frappe.get_doc("Quotation", q)
		qdoc.items = [i for i in qdoc.items if i.item_code == F.single]
		r = as_(F.so1.user, lambda: quotation_result(qdoc.name))
		_assert(r["result"] == "Won", "quotation_result read an unsaved change")
		for blank in (None, " "):
			err = refused(lambda: as_(F.sm1.user, lambda: apply_quotation_finalized(qdoc, blank)))
			_assert("Enter the Partial Reason" in err and F.plain in err, err)
		_assert(status(name) == "Converted to Quotation", "a refused Partial changed the status")
		_assert(as_(F.sm1.user, lambda: apply_quotation_finalized(qdoc, "Buyer short of budget")) == "Partial", "not Partial")
		row = frappe.db.get_value("Opportunity", name, ["custom_opportunity_status", "custom_status_reason"], as_dict=True)
		_assert(row.custom_opportunity_status == "Partial" and row.custom_status_reason == "Buyer short of budget", str(row))
		t = trail(name, "Opportunity Partial")
		_assert(any(x.reason == "Buyer short of budget" and x.changed_by == F.sm1.user and x.user_role == "Sales Manager" for x in t), str(t))

	check("6.2 Partial: refused without a reason; with one, stored and audited with user and role", _partial)

	def _standalone():
		q = frappe._dict(name="X", opportunity=None, items=[])
		_assert(apply_quotation_finalized(q) is None, "a Standalone Quotation changed an Opportunity")
		name, qn = converted()
		frappe.db.set_value("Opportunity", name, "custom_linked_quotation", "OTHER")
		_assert(apply_quotation_finalized(qn) is None, "a Quotation that is not the linked one was applied")

	check("6.2 a Standalone (or unlinked) Quotation gives no Opportunity result", _standalone)


def _scoping():
	from alpinos.offline_sales.access import list_scope
	from alpinos.offline_sales.audit import get_trail

	def _so():
		mine = new_opp(F.so1.user, F.ready.name).name
		theirs = new_opp("Administrator", F.other.name).name
		seen = as_(F.so1.user, lambda: set(frappe.get_list("Opportunity", filters={"name": ("in", [mine, theirs])}, pluck="name")))
		_assert(seen == {mine}, f"SO1 sees {seen}")
		seen = as_(F.so2.user, lambda: set(frappe.get_list("Opportunity", filters={"name": ("in", [mine, theirs])}, pluck="name")))
		_assert(seen == {theirs}, f"SO2 sees {seen}")
		_assert(not as_(F.so2.user, lambda: frappe.has_permission("Opportunity", "read", mine)), "SO2 may open SO1's Opportunity")
		_assert(refused(lambda: act(F.so2.user, mine, "submit")), "SO2 acted on another officer's Opportunity")
		_assert(as_(F.sa1.user, lambda: frappe.has_permission("Opportunity", "read", theirs)), "SA narrowed")
		_assert(as_(F.so1.user, lambda: get_trail("Opportunity", mine)), "SO1 cannot read the trail")
		_assert(refused(lambda: as_(F.so2.user, lambda: get_trail("Opportunity", mine))), "SO2 read the trail of an Opportunity they cannot see")
		F.mine = mine

	check("1 4.1 a Sales Officer sees and acts on the Opportunities of their buyers only; the trail too", _so)

	def _sa_default():
		_assert(frappe.db.get_value("Opportunity", F.mine, "custom_secondary_poc") == F.sa1.emp, "Secondary POC not on the Opportunity")
		frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 1)
		try:
			scope = as_(F.sa1.user, list_scope)
			_assert(scope["secondary_poc_default"] == 1 and scope["employee"] == F.sa1.emp, str(scope))
		finally:
			frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 0)

		def _go():
			b = frappe.get_doc("Buyer Master", F.ready.name)
			b.secondary_poc = None
			b.save()

		as_(F.sm1.user, _go)
		_assert(not frappe.db.get_value("Opportunity", F.mine, "custom_secondary_poc"), "the Buyer's new Secondary POC did not follow")

	check("3.3 SA list default by Secondary POC (switch on); it follows the Buyer", _sa_default)


def _form_support():
	from alpinos.offline_sales import opportunity as O

	def _calls():
		ctx = as_(F.so1.user, lambda: O.buyer_context(F.pending.name))
		_assert(ctx["buyer_status"] == "Pending Approval" and ctx["convert_blocked_reason"] == M14, str(ctx))
		_assert(ctx["sites"] and ctx["default_site"] == F.pending.site_name and ctx["sales_officers"], str(ctx))
		addr = as_(F.so1.user, lambda: O.site_addresses(F.ready.name, F.ready.site_name))
		_assert(addr["billing"] and addr["shipping"], str(addr))
		billing = as_(F.so1.user, lambda: O.address_query("Address", "", "name", 0, 20, {"party_name": F.ready.name, "kind": "billing"}))
		shipping = as_(F.so1.user, lambda: O.address_query("Address", "", "name", 0, 20, {"party_name": F.ready.name, "kind": "shipping"}))
		_assert([b[0] for b in billing] == [addr["billing"]] and [s[0] for s in shipping] == [addr["shipping"]], f"{billing} {shipping}")
		v = as_(F.so1.user, lambda: O.line_values(F.ready.name, F.single, 10))
		_assert(flt(v["custom_selling_price"]) == flt(F.single_mrp * 0.8, 2) and flt(v["custom_line_amount"]) == flt(10 * v["custom_selling_price"], 2), str(v))
		v = as_(F.so1.user, lambda: O.line_values(F.ready.name, F.multi, 1))
		_assert(v["needs_mrp"] == 1 and len(v["mrp_options"]) > 1, str(v))
		name = submitted(buyer=F.pending.name)
		fa = as_(F.so1.user, lambda: O.form_actions(name))
		_assert(fa["convert"] == 1 and fa["convert_blocked_reason"] == M14 and set(fa["actions"]) == {"hold", "lost", "cancel"}, str(fa))
		draft = new_opp(F.so1.user, F.ready.name).name
		fa = as_(F.so1.user, lambda: O.form_actions(draft))
		_assert(set(fa["actions"]) == {"submit", "hold", "lost", "cancel"} and not fa["convert"], str(fa))
		fa = as_(F.su.user, lambda: O.form_actions(draft))
		_assert(not fa["actions"], "actions offered to a role outside SO / SM / SA")

	check("2 / 5 form calls: buyer context, site addresses, address pickers, line values, action buttons", _calls)


def _legacy():
	def _patch():
		from alpinos.patches.v2_0 import opportunity_workflow

		cases = {"Open": "Pending (Draft)", "Lost": "Lost", "Closed": "Cancelled", "Quotation": "Pending (Submitted)"}
		names = {}
		for erp_status in cases:
			names[erp_status] = _insert(
				"Opportunity", name=f"{TAG}-LEG-{erp_status}", opportunity_from="Customer", party_name=F.ready.customer,
				status=erp_status, company=F.company, transaction_date=today(), custom_opportunity_status=None,
			)
		opportunity_workflow.execute()
		for erp_status, want in cases.items():
			got = frappe.db.get_value("Opportunity", names[erp_status], ["custom_opportunity_status", "custom_opportunity_source"], as_dict=True)
			_assert(got.custom_opportunity_status == want and got.custom_opportunity_source == "Direct Opportunity", f"{erp_status}: {got}")

	check("migration: older Opportunities get Source and a status mapped from ERPNext's", _patch)
