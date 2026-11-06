"""Goods Return, Phase A (FSD Document 1, sections 1 and 2). TEST sites only.

Run:  bench --site <test site> execute alpinos.goods_return.goods_return_test.run

Covers the roles, the channel matrix of FSD 2.3.2 (create AND submit), the channel field
behaviour of 2.3.3, who sees which requests, the request rules (party, redistribution,
references, items, Supplementary), what stays locked after submit, cancel, numbering per
company, company-wise access and the company-scope lint.

Test users are made with company_scope.testing (committed, removed at the end); requests
and reasons are rolled back.
"""

import frappe
from frappe.utils import today

from alpinos.company_scope import testing as T
from alpinos.goods_return import (
	COORDINATOR, CUSTOMER_SITE_DISPOSAL, EXECUTIVE, REDISTRIBUTION, REQUEST, RETURN_TO_AHFPL,
)
from alpinos.goods_return import access

R = []
TAG = "grt" + frappe.generate_hash(length=5).lower()


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
	"""The error text fn() raises ("" when it went through), undoing only what fn() did."""
	sp = "grt_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	return ""


# ----------------------------------------------------------------------------- fixtures

# FSD 2.3.2, every row: (label, roles, Offline allowed, E-Commerce allowed).
# The FSD's "E-Commerce User" is E-Commerce Coordinator on Alpinos.
MATRIX = [
	("GRC + Sales Manager", [COORDINATOR, "Sales Manager"], True, False),
	("GRC + Sales Admin", [COORDINATOR, "Sales Admin"], True, False),
	("GRC + Sales User", [COORDINATOR, "Sales User"], True, False),
	("GRC + E-Commerce Manager", [COORDINATOR, "E-Commerce Manager"], False, True),
	("GRC + E-Commerce Admin", [COORDINATOR, "E-Commerce Admin"], False, True),
	("GRC + E-Commerce Coordinator", [COORDINATOR, "E-Commerce Coordinator"], False, True),
	("GRC + Sales User + E-Commerce Coordinator", [COORDINATOR, "Sales User", "E-Commerce Coordinator"], True, True),
	("GRC + Sales Manager + E-Commerce Admin", [COORDINATOR, "Sales Manager", "E-Commerce Admin"], True, True),
	("GRC only", [COORDINATOR], False, False),
	("Sales Manager only", ["Sales Manager"], False, False),
	("E-Commerce Manager only", ["E-Commerce Manager"], False, False),
]

F = frappe._dict()


def _fixtures():
	A, B, _C = T.companies()
	F.A, F.B = A, B

	# an Offline delivery whose customer is an offline buyer, preferably one with an MRP lot
	dns = frappe.db.sql(
		"""
		SELECT dn.name, dn.customer,
			(SELECT COUNT(*) FROM `tabDelivery Note Item` i WHERE i.parent = dn.name AND IFNULL(i.mrp_batch, '') != '') lots
		FROM `tabDelivery Note` dn LEFT JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id
		WHERE dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0 AND dn.company = %s
			AND IFNULL(so.custom_channel, '') IN ('', 'Offline')
		ORDER BY lots DESC, dn.creation
		""",
		A,
		as_dict=True,
	)
	dn = next((d for d in dns if access.customer_in_channel(d.customer, "Offline")), None)
	_assert(dn, "no submitted Offline Delivery Note with an offline buyer on this site")
	F.dn, F.off_customer = dn.name, dn.customer
	F.item = frappe.db.get_value("Delivery Note Item", {"parent": dn.name}, "item_code")
	F.other_dn = next((d.name for d in dns if d.customer != F.off_customer), None)
	F.off_customer2 = frappe.db.sql(
		"""SELECT m.customer FROM `tabBuyer Master` m JOIN tabCustomer c ON c.name = m.customer
		WHERE IFNULL(m.channel, '') IN ('', 'Offline') AND c.disabled = 0 AND m.customer != %s LIMIT 1""",
		F.off_customer,
	)[0][0]
	F.ecom_customer = frappe.db.sql(
		"""SELECT m.customer FROM `tabBuyer Master` m JOIN tabCustomer c ON c.name = m.customer
		WHERE m.channel = 'E-com' AND c.disabled = 0
		ORDER BY (IFNULL(m.is_parent, 0) = 1 OR IFNULL(m.parent_buyer, '') = '') DESC LIMIT 1"""
	)[0][0]

	F.reason = _reason(f"{TAG} Expired")
	F.reason2 = _reason(f"{TAG} Damaged")
	F.reason_off = _reason(f"{TAG} Old", enabled=0)

	users = {
		"off": [COORDINATOR, "Sales User"],
		"ecom": [COORDINATOR, "E-Commerce Admin"],
		"both": [COORDINATOR, "Sales Manager", "E-Commerce Coordinator"],
		"coord_only": [COORDINATOR],
		"wh_coord": [COORDINATOR, "Warehouse Manager"],
		"exe": [EXECUTIVE],
		"sales_user": ["Sales User"],
	}
	# every user is made here, before any request: making a user commits
	F.u = {}
	for key, roles in users.items():
		F.u[key] = T.make_user(f"{TAG}.{key}@example.com", {A: roles})
	F.extra_users = [T.make_user(f"{TAG}.m{i}@example.com", {A: roles}) for i, (_l, roles, _o, _e) in enumerate(MATRIX)]
	frappe.db.commit()


def _reason(name, enabled=1):
	frappe.get_doc({"doctype": "Goods Return Reason", "reason": name, "enabled": enabled}).insert(ignore_permissions=True)
	return name


def _cleanup():
	frappe.db.rollback()
	for email in (F.get("u") or {}).values():
		T.cleanup_user(email)
	for extra in F.get("extra_users") or []:
		T.cleanup_user(extra)
	for reason in (F.get("reason"), F.get("reason2"), F.get("reason_off")):
		if reason and frappe.db.exists("Goods Return Reason", reason):
			frappe.delete_doc("Goods Return Reason", reason, ignore_permissions=True, force=True)
	frappe.db.commit()


def _new(channel="Offline", customer=None, items=None, handling=RETURN_TO_AHFPL, company=None, **kw):
	doc = frappe.get_doc(
		{
			"doctype": REQUEST,
			"company": company or F.A,
			"posting_date": today(),
			"channel": channel,
			"customer": customer or (F.ecom_customer if channel == "E-com" else F.off_customer),
			"return_handling_type": handling,
			"items": items or [{"item_code": F.item, "expected_qty": 5, "return_reason": F.reason}],
			**kw,
		}
	)
	return doc


def _insert_as(user, **kw):
	return T.as_user(user, lambda: _new(**kw).insert())


def _admin_draft(**kw):
	return _new(**kw).insert()


# ----------------------------------------------------------------------------- checks


def _roles_and_permissions():
	for role in (COORDINATOR, EXECUTIVE):
		check(f"role {role} exists and is company-wise", lambda role=role: _assert(
			frappe.db.get_value("Role", role, "custom_company_scoped") == 1, frappe.db.get_value("Role", role, "custom_company_scoped")))
	perm = lambda role: frappe.db.get_value(
		"Custom DocPerm", {"parent": REQUEST, "role": role, "permlevel": 0},
		["read", "write", "create", "submit", "cancel"], as_dict=True) or {}
	check("Coordinator may create, write, submit and cancel requests", lambda: _assert(
		all(perm(COORDINATOR).get(p) for p in ("read", "write", "create", "submit", "cancel")), perm(COORDINATOR)))
	check("Executive may only read requests (Phase A)", lambda: _assert(
		perm(EXECUTIVE).get("read") and not any(perm(EXECUTIVE).get(p) for p in ("write", "create", "submit", "cancel")),
		perm(EXECUTIVE)))
	check("sidebar Alpino Sales & Dispatch lists the requests", lambda: _assert(frappe.db.exists(
		"Sidebar Item", {"parent": "Alpino Sales & Dispatch", "link_to": REQUEST}) or "Goods Return Request" in frappe.as_json(
		frappe.get_doc("Sidebar", "Alpino Sales & Dispatch").as_dict()), "no sidebar link"))


def _channel_matrix():
	"""FSD 2.3.2, every row, create and submit. E-Commerce User is E-Commerce Coordinator here."""
	for i, (label, roles, offline_ok, ecom_ok) in enumerate(MATRIX):
		user = F.extra_users[i]
		for channel, expected in (("Offline", offline_ok), ("E-com", ecom_ok)):
			def cell(user=user, channel=channel, expected=expected):
				created = {}

				def create():
					created["doc"] = _insert_as(user, channel=channel)

				err = refused(create)
				_assert((not err) == expected, f"create: expected {'allowed' if expected else 'refused'}, got {err or 'allowed'}")
				name = created["doc"].name if not err else _admin_draft(channel=channel).name
				err = refused(lambda: T.as_user(user, lambda: frappe.get_doc(REQUEST, name).submit()))
				_assert((not err) == expected, f"submit: expected {'allowed' if expected else 'refused'}, got {err or 'allowed'}")

			check(f"2.3.2 {label}: {channel} {'allowed' if expected else 'not allowed'}", cell)


def _channel_field():
	"""FSD 2.3.3: one channel locked and filled, two to choose, none blocked."""
	got = lambda key: T.as_user(F.u[key], lambda: access.get_request_access(F.A))
	check("2.3.3 Offline only: Offline, locked", lambda: _assert(
		(lambda a: a["channels"] == ["Offline"] and a["locked"] and a["default"] == "Offline")(got("off")), got("off")))
	check("2.3.3 E-Commerce only: E-com, locked", lambda: _assert(
		(lambda a: a["channels"] == ["E-com"] and a["locked"] and a["default"] == "E-com")(got("ecom")), got("ecom")))
	check("2.3.3 both channels: a choice, nothing preset", lambda: _assert(
		(lambda a: a["channels"] == ["Offline", "E-com"] and not a["locked"] and not a["default"])(got("both")), got("both")))
	check("2.3.3 no channel role: blocked", lambda: _assert(got("coord_only")["channels"] == [], got("coord_only")))
	check("Coordinator + Warehouse Manager (no sales role): blocked", lambda: _assert(
		got("wh_coord")["channels"] == [], got("wh_coord")))
	check("Coordinator + Warehouse Manager cannot save a request", lambda: _assert(
		refused(lambda: _insert_as(F.u["wh_coord"], channel="Offline")), "went through"))

	def switch_channel():
		doc = _insert_as(F.u["off"], channel="Offline")

		def change():
			d = frappe.get_doc(REQUEST, doc.name)
			d.channel = "E-com"
			d.customer = F.ecom_customer
			d.save()

		# refused either by the request's permission hook (an E-com request is not theirs to
		# write) or by the save rule; what matters is that the draft stays Offline
		err = refused(lambda: T.as_user(F.u["off"], change))
		_assert(err and frappe.db.get_value(REQUEST, doc.name, "channel") == "Offline", err or "went through")

	check("checked on save: an Offline-only user cannot move a draft to E-com", switch_channel)


def _visibility():
	off = _insert_as(F.u["off"], channel="Offline")
	T.as_user(F.u["off"], lambda: frappe.get_doc(REQUEST, off.name).submit())
	ecom = _insert_as(F.u["ecom"], channel="E-com")
	names = [off.name, ecom.name]
	listed = lambda user: set(T.as_user(user, lambda: frappe.get_list(REQUEST, {"name": ["in", names]}, pluck="name")))
	check("Offline Coordinator lists only Offline requests", lambda: _assert(listed(F.u["off"]) == {off.name}, listed(F.u["off"])))
	check("E-Commerce Coordinator lists only E-com requests", lambda: _assert(listed(F.u["ecom"]) == {ecom.name}, listed(F.u["ecom"])))
	check("two-channel Coordinator lists both", lambda: _assert(listed(F.u["both"]) == set(names), listed(F.u["both"])))
	check("Executive lists both channels", lambda: _assert(listed(F.u["exe"]) == set(names), listed(F.u["exe"])))
	check("Coordinator without a channel role lists none", lambda: _assert(
		listed(F.u["coord_only"]) == set(), listed(F.u["coord_only"])))
	check("a Sales User without the Coordinator role cannot list requests", lambda: _assert(
		refused(lambda: listed(F.u["sales_user"])) or not listed(F.u["sales_user"]), "listed"))
	check("Offline Coordinator cannot open the E-com request", lambda: _assert(
		not frappe.has_permission(REQUEST, "read", doc=ecom.name, user=F.u["off"]), "opened"))
	check("Executive can open it, read only", lambda: _assert(
		frappe.has_permission(REQUEST, "read", doc=ecom.name, user=F.u["exe"])
		and not frappe.has_permission(REQUEST, "write", doc=ecom.name, user=F.u["exe"]), "wrong rights"))
	check("Executive cannot raise a request", lambda: _assert(
		refused(lambda: _insert_as(F.u["exe"], channel="Offline")), "went through"))


def _rules():
	off = F.u["off"]
	check("returning party from the other channel is refused", lambda: _assert(
		"not a buyer in the Offline channel" in refused(lambda: _insert_as(off, channel="Offline", customer=F.ecom_customer)),
		"went through"))
	check("Buyer Master is filled from the returning party", lambda: _assert(
		_insert_as(off, channel="Offline").buyer_master == access.customer_in_channel(F.off_customer, "Offline")))
	check("redistribution without a destination is refused", lambda: _assert(
		refused(lambda: _insert_as(off, handling=REDISTRIBUTION)), "went through"))
	check("redistribution to the same customer is refused", lambda: _assert(
		"different" in refused(lambda: _insert_as(off, handling=REDISTRIBUTION, destination_customer=F.off_customer)),
		"went through"))
	check("redistribution to another customer goes through", lambda: _assert(
		_insert_as(off, handling=REDISTRIBUTION, destination_customer=F.off_customer2).destination_customer == F.off_customer2))
	check("a destination is dropped for other handling types", lambda: _assert(
		not _insert_as(off, handling=CUSTOMER_SITE_DISPOSAL, destination_customer=F.off_customer2).destination_customer))
	check("every handling type is accepted", lambda: [
		_insert_as(off, handling=h, **({"destination_customer": F.off_customer2} if h == REDISTRIBUTION else {}))
		for h in (RETURN_TO_AHFPL, CUSTOMER_SITE_DISPOSAL, REDISTRIBUTION)])
	if F.other_dn:
		check("a Delivery Note of another customer is refused", lambda: _assert(
			"not a delivery to" in refused(lambda: _insert_as(off, delivery_note=F.other_dn)), "went through"))
	check("the customer's own Delivery Note is accepted", lambda: _assert(
		_insert_as(off, delivery_note=F.dn).delivery_note == F.dn))

	def dn_items():
		r = T.as_user(off, lambda: access.get_delivery_note_items(F.dn))
		_assert(r["rows"] and r["customer"] == F.off_customer, r)
		lot = frappe.db.get_value("Delivery Note Item", {"parent": F.dn, "mrp_batch": ["is", "set"]}, ["name", "mrp_batch"], as_dict=True)
		if lot:
			row = next(x for x in r["rows"] if x["delivery_note_item"] == lot.name)
			_assert(row["mrp"] == frappe.db.get_value("MRP Batch", lot.mrp_batch, "mrp") and row["mrp_batch"] == lot.mrp_batch, row)

	check("Get Items from Delivery Note returns batch, MRP lot and quantity", dn_items)
	check("a user who cannot read the delivery gets no items", lambda: _assert(
		refused(lambda: T.as_user(F.u["coord_only"], lambda: access.get_delivery_note_items(F.dn))), "went through"))

	items = lambda *rows: [{"item_code": F.item, "expected_qty": 5, "return_reason": F.reason, **r} for r in rows]
	check("quantity 0 is refused", lambda: _assert(
		"more than 0" in refused(lambda: _insert_as(off, items=items({"expected_qty": 0}))), "went through"))
	check("a disabled reason is refused", lambda: _assert(
		"disabled" in refused(lambda: _insert_as(off, items=items({"return_reason": F.reason_off}))), "went through"))
	check("the same item, batch, MRP and reason twice is refused", lambda: _assert(
		"same item" in refused(lambda: _insert_as(off, items=items({"batch_code": "B1", "mrp": 100}, {"batch_code": "b1 ", "mrp": 100}))),
		"went through"))
	check("the same SKU under two reasons is allowed", lambda: _assert(
		_insert_as(off, items=items({}, {"return_reason": F.reason2})).total_expected_qty == 10))
	check("a user cannot make a Supplementary request", lambda: _assert(
		"system" in refused(lambda: _insert_as(off, request_type="Supplementary")), "went through"))
	check("UOM is filled from the item", lambda: _assert(
		_insert_as(off).items[0].uom == frappe.db.get_value("Item", F.item, "stock_uom")))


def _after_submit():
	off = F.u["off"]
	doc = _insert_as(off)
	T.as_user(off, lambda: frappe.get_doc(REQUEST, doc.name).submit())
	check("submitted request shows Submitted", lambda: _assert(frappe.db.get_value(REQUEST, doc.name, "status") == "Submitted"))

	def edit(field, value, child=False):
		def fn():
			d = frappe.get_doc(REQUEST, doc.name)
			if child:
				d.items[0].set(field, value)
			else:
				d.set(field, value)
			d.save()

		return lambda: T.as_user(off, fn)

	check("after submit the quantity cannot change", lambda: _assert(refused(edit("expected_qty", 1, child=True)), "changed"))
	check("after submit the returning party cannot change", lambda: _assert(refused(edit("customer", F.off_customer2)), "changed"))
	check("after submit the handling type cannot change", lambda: _assert(
		refused(edit("return_handling_type", CUSTOMER_SITE_DISPOSAL)), "changed"))
	check("after submit reverse logistics can be filled", lambda: (
		edit("transporter", "Test Transport")(),
		_assert(frappe.db.get_value(REQUEST, doc.name, "transporter") == "Test Transport")))
	check("an E-com Coordinator cannot update an Offline request", lambda: _assert(
		refused(lambda: T.as_user(F.u["ecom"], lambda: (lambda d: (d.set("docket_no", "X"), d.save()))(frappe.get_doc(REQUEST, doc.name)))),
		"changed"))
	check("the Coordinator can cancel it", lambda: (
		T.as_user(off, lambda: frappe.get_doc(REQUEST, doc.name).cancel()),
		_assert(frappe.db.get_value(REQUEST, doc.name, "status") == "Cancelled")))


def _numbering_and_company():
	from alpinos.purchase.naming import fy_short

	fy = fy_short(today())
	check(f"numbered GRR-{fy}-", lambda: _assert(_insert_as(F.u["off"]).name.startswith(f"GRR-{fy}-")))
	code = frappe.db.get_value("Company", F.B, "custom_series_code")
	apc = _admin_draft(company=F.B)
	if code:
		check(f"a {code} request is numbered GRR-{code}-{fy}-", lambda: _assert(apc.name.startswith(f"GRR-{code}-{fy}-"), apc.name))
	check(f"a user of {F.A} only cannot open a {F.B} request", lambda: _assert(
		not frappe.has_permission(REQUEST, "read", doc=apc.name, user=F.u["off"]), "opened"))
	check(f"nor list it", lambda: _assert(
		apc.name not in T.as_user(F.u["off"], lambda: frappe.get_list(REQUEST, {"name": apc.name}, pluck="name"))))


def _lint():
	from alpinos.company_scope import lint

	left = [m for m in lint.report() if m["file"].startswith(("goods_return/", "alpinos_development/doctype/goods_return"))]
	check("every goods return endpoint follows the company (lint)", lambda: _assert(not left, left))


def run():
	frappe.set_user("Administrator")
	T.ensure_enabled()
	try:
		check("fixtures", _fixtures)
		if R and R[-1][0] != "PASS":
			return _report()
		_roles_and_permissions()
		_channel_matrix()
		_channel_field()
		_visibility()
		_rules()
		_after_submit()
		_numbering_and_company()
		_lint()
	finally:
		frappe.set_user("Administrator")
		_cleanup()
	return _report()


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R
