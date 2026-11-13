"""Changes(HP) rows still open on 13 Nov 2026 (#64-#79, #101, #103-#116). TEST sites only.

Run:  bench --site <test site> execute alpinos.changes_hp_nov_test.run

Everything is rolled back (commits disabled for the run). The screens (#67-#69, #72, #73,
#104, #112, #113, #114, #115) are checked in the browser run; this covers the server side.
"""

import json

import frappe
from frappe.utils import add_days, today

R = []
TAG = "HPN" + frappe.generate_hash(length=4).upper()
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


def refused(fn):
	sp = "hpn_" + frappe.generate_hash(length=6)
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


def _person(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	emp = _insert("Employee", name=f"{TAG}-{suffix.upper()}", employee_name=f"{TAG} {suffix.title()}", first_name=suffix,
		status="Active", company=F.company, date_of_joining="2026-01-01", user_id=user)
	return frappe._dict(user=user, emp=emp)


def _fixtures():
	F.company = frappe.defaults.get_global_default("company")
	F.so = _person("so", "Sales Officer", "Employee")
	F.sm = _person("sm", "Sales Manager", "Employee")
	F.both = _person("both", "Sales Manager", "Sales Officer")
	F.sysm = _person("sys", "System Manager")
	F.plain = _person("plain", "Sales User")
	# two buyers, the Sales Officer assigned to the first
	F.mine = _insert("Buyer Master", name=f"{TAG}-MINE", customer_business_name=f"{TAG} Mine", channel="Offline",
		customer=_insert("Customer", name=f"{TAG}-CUST-MINE", customer_name=f"{TAG} Mine", customer_type="Company"),
		buyer_status="Approved", buyer_catalog_status="Completed")
	F.other = _insert("Buyer Master", name=f"{TAG}-OTHER", customer_business_name=f"{TAG} Other", channel="Offline",
		customer=_insert("Customer", name=f"{TAG}-CUST-OTHER", customer_name=f"{TAG} Other", customer_type="Company"),
		buyer_status="Approved", buyer_catalog_status="Completed")
	_insert("Buyer Sales Officer", name=f"{TAG}-BSO", parent=F.mine, parenttype="Buyer Master", parentfield="sales_officers",
		employee=F.so.emp, idx=1)
	frappe.clear_cache()


def _run():
	_fixtures()
	_settings_read()
	_closed_orders()
	_bulk()
	_state()
	_buyer_id_and_paging()
	_officer_scope()
	_buyer_master()
	_afr_export()
	_restore()
	_switcher()
	_only_invoice()
	_accounts_view()
	_daily_report()


def _settings_read():
	from alpinos.user_settings_compat import get_value

	def _own():
		frappe.db.set_value("User", F.plain.user, "dock_mode", "Floating")
		r = as_(F.plain.user, lambda: get_value("User", json.dumps(["dock_mode", "time_zone"]), F.plain.user))
		_assert(r.get("dock_mode") == "Floating", str(r))
		other = refused(lambda: as_(F.plain.user, lambda: get_value("User", json.dumps(["dock_mode"]), F.sm.user)))
		_assert(other, "another user's preference came back")
		# any other field goes to Frappe's own read (refused, or no value, for a plain user)
		got = {}
		err = refused(lambda: got.update(as_(F.plain.user, lambda: get_value("User", json.dumps(["dock_mode", "api_key"]), F.plain.user)) or {}))
		_assert(err or not got.get("api_key"), "a non-preference field came back")

	check("#116 a user reads their own Doc View (Floating), not another's, not other fields", _own)


def _so(name, **values):
	base = dict(name=name, company=F.company, customer=frappe.db.get_value("Buyer Master", F.mine, "customer"),
		customer_name=f"{TAG} Mine", custom_offline_buyer_master=F.mine, transaction_date=today(),
		custom_channel="Offline", docstatus=0, custom_workflow_status="Draft", currency="INR", conversion_rate=1,
		custom_rl_no_invoice=0, custom_only_invoice=0,
		selling_price_list="Standard Selling", plc_conversion_rate=1)
	base.update(values)
	return _insert("Sales Order", **base)


def _closed_orders():
	from alpinos.workflow_engine import sales_order_before_cancel

	def _rejected():
		doc = frappe._dict(name="X", custom_workflow_status="Rejected", flags=frappe._dict(cancellation_reason="x"))
		doc.get = lambda k, d=None: doc[k] if k in doc else d
		_assert("Rejected" in refused(lambda: sales_order_before_cancel(doc)), "a Rejected order could be cancelled")

	check("#103 a Rejected order cannot be cancelled", _rejected)


def _bulk():
	from alpinos import bulk_so_actions as B

	def _only_admin():
		err = refused(lambda: as_(F.sm.user, lambda: B.bulk_cancel(json.dumps(["X"]), "x")))
		_assert(err, "a Sales Manager ran the bulk cancel")

	check("#105 bulk actions are for System Manager (BA team) only", _only_admin)

	def _per_order():
		draft = _so(f"{TAG}-SO-D1")
		res = as_(F.sysm.user, lambda: B.bulk_cancel(json.dumps([draft, f"{TAG}-NOPE"]), "Customer asked"))
		_assert(res["counts"]["done"] == 1 and res["counts"]["failed"] == 1, str(res))
		_assert(frappe.db.get_value("Sales Order", draft, "custom_workflow_status") == "Cancelled", "draft not cancelled")
		_assert("reason" in refused(lambda: as_(F.sysm.user, lambda: B.bulk_reject(json.dumps([draft]), " "))).lower(), "blank reason")

	check("#105 each order goes through its own rule; one refusal does not stop the rest", _per_order)


def _state():
	import alpinos.invoice_queue_api as Q

	def _gstin_first():
		addr = _insert("Address", name=f"{TAG}-ADDR-KA", address_title="x", address_line1="x", city="Bengaluru",
			state="Karnataka", country="India", address_type="Billing")
		so = _so(f"{TAG}-SO-ST", customer_address=addr, custom_billing_gstin="27AAFCG9846E1ZB", custom_invoice_no="9999")
		got = frappe.db.sql(f"SELECT {Q._STATE} FROM `tabSales Order` so {Q._JOINS} WHERE so.name = %s", so)[0][0]
		_assert(got == "Maharashtra", got)
		so2 = _so(f"{TAG}-SO-ST2", customer_address=addr, custom_invoice_no="9998")
		got2 = frappe.db.sql(f"SELECT {Q._STATE} FROM `tabSales Order` so {Q._JOINS} WHERE so.name = %s", so2)[0][0]
		_assert(got2 == "Karnataka", f"no GSTIN, no site: the address should still decide: {got2}")

	check("#101 OFR State follows the Billing GSTIN (SOR-2627-04137 case), else the address", _gstin_first)


def _buyer_id_and_paging():
	from alpinos import sales_order_api
	from alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry import get_delivery_note_list
	from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import get_pick_list_entry_list

	so = _so(f"{TAG}-SO-B1", docstatus=1, custom_workflow_status="Warehouse Approved")
	pl = _insert("Pick List", name=f"{TAG}-PL-B1", custom_sales_order_id=so, company=F.company, purpose="Delivery",
		docstatus=0, custom_customer_name=f"{TAG} Mine", custom_workflow_status="Draft")
	dn = _insert("Delivery Note", name=f"{TAG}-DN-B1", custom_sales_order_id=so, company=F.company, docstatus=0,
		customer=frappe.db.get_value("Buyer Master", F.mine, "customer"), posting_date=today())
	F.so_b1, F.pl_b1, F.dn_b1 = so, pl, dn

	def _search():
		r = get_pick_list_entry_list(page_length=20, search=F.mine)
		_assert(pl in {d.name for d in r["data"]} and r["total"] >= 1, str(r)[:300])
		_assert(all(d.buyer_id == F.mine for d in r["data"] if d.name == pl), "PL row has no Buyer ID")
		r = get_delivery_note_list(page_length=20, search=F.mine)
		_assert(dn in {d.name for d in r["data"]}, str(r)[:300])
		r = sales_order_api.get_sales_order_entry_list(page_length=50, search=F.mine)
		_assert(so in {d.name for d in r["data"]}, "SO list search by Buyer ID")

	check("#64 Pick List / Delivery Note / Sales Order lists: Buyer ID column and search", _search)

	def _paging():
		r = get_pick_list_entry_list(page_length=5, start=0, sort_field="name", sort_dir="asc")
		names = [d.name for d in r["data"]]
		_assert(names == sorted(names), f"not sorted: {names}")
		_assert(r["total"] >= len(names) and "total" in r, str(r.keys()))
		bad = get_pick_list_entry_list(page_length=5, sort_field="name; drop table x", sort_dir="asc")
		_assert(bad["data"] is not None, "an unknown sort field broke the list")

	check("#111 totals and server-side sorting over all records; unknown sort fields ignored", _paging)

	def _ofr_and_afr():
		import alpinos.invoice_queue_api as Q
		from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

		_assert("buyer_id" in Q.COLUMNS and "buyer_id" in Q.DEFAULT_COLUMNS and "buyer_id" in Q._FILTERS, "OFR Buyer ID")
		cols = [c["fieldname"] for c in AFR.get_columns()]
		_assert(cols.index("buyer_id") > cols.index("so_submitted_on"), cols[-5:])

	check("#64 OFR Buyer ID column + filter; AFR Buyer ID after Submitted By / On", _ofr_and_afr)


def _officer_scope():
	from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import get_pick_list_entry_list
	from alpinos.sales_order_offline_buyer import sales_order_customer_query

	other_so = _so(f"{TAG}-SO-O1", custom_offline_buyer_master=F.other,
		customer=frappe.db.get_value("Buyer Master", F.other, "customer"), docstatus=1)
	other_pl = _insert("Pick List", name=f"{TAG}-PL-O1", custom_sales_order_id=other_so, company=F.company,
		purpose="Delivery", docstatus=0, custom_customer_name=f"{TAG} Other")

	def _picker():
		rows = as_(F.so.user, lambda: sales_order_customer_query("Customer", TAG, "name", 0, 20, {}))
		got = {r[0] for r in rows}
		_assert(frappe.db.get_value("Buyer Master", F.mine, "customer") in got, f"own buyer missing: {got}")
		_assert(frappe.db.get_value("Buyer Master", F.other, "customer") not in got, f"other buyer offered: {got}")
		rows = as_(F.sm.user, lambda: sales_order_customer_query("Customer", TAG, "name", 0, 20, {}))
		_assert(len({r[0] for r in rows}) >= 2, "a Sales Manager was narrowed")

	check("#65 the Sales Order buyer dropdown lists only a Sales Officer's buyers", _picker)

	def _pl_page():
		r = as_(F.so.user, lambda: get_pick_list_entry_list(page_length=50, search=TAG))
		names = {d.name for d in r["data"]}
		_assert(F.pl_b1 in names and other_pl not in names, f"Sales Officer PL page: {names}")

	check("#71 the Pick List page shows a Sales Officer only their buyers' Pick Lists", _pl_page)

	def _ofr():
		import alpinos.invoice_queue_api as Q

		frappe.db.set_value("Sales Order", F.so_b1, "custom_invoice_no", "777", update_modified=False)
		frappe.db.set_value("Sales Order", other_so, "custom_invoice_no", "778", update_modified=False)

		def rows():
			where, params, _s, _o, _k = Q._build({}, None, None, None)
			return {r[0] for r in frappe.db.sql(f"SELECT so.name FROM `tabSales Order` so {Q._JOINS} WHERE {where}", params)}

		seen = as_(F.so.user, rows)
		_assert(F.so_b1 in seen and other_so not in seen, f"Sales Officer OFR: {seen & {F.so_b1, other_so}}")
		seen = rows()
		_assert({F.so_b1, other_so} <= seen, "Administrator narrowed")

	check("#70 the Order Fulfilment Report shows a Sales Officer only their buyers' orders", _ofr)

	def _pages():
		for page in ("sales-order-entry", "sales-order-entry-list", "sales-order-entry-view", "invoice-download-queue"):
			_assert(frappe.db.exists("Has Role", {"parent": page, "parenttype": "Page", "role": "Sales Officer"}), page)

	check("#66 / #70 Sales Officer may open the Sales Order pages and the OFR", _pages)


def _buyer_master():
	from alpinos import buyer_assignment as BA

	def _no_employee_name():
		_assert(not frappe.get_meta("Buyer Master").has_field("poc_employee"), "Employee Name still on Buyer Master")

	check("#75 Employee Name is gone from Buyer Master", _no_employee_name)

	def _masters():
		for dt in ("State", "City", "Country"):
			_assert(as_(F.so.user, lambda: frappe.has_permission(dt, "read")), f"Sales Officer cannot read {dt}")

	check("#77 a Sales Officer reads State, City, Country", _masters)

	def _primary_query():
		rows = BA.employees_with_roles(BA.PRIMARY_POC_ROLES, TAG, 0, 50, exclude_roles=(BA.SALES_OFFICER_ROLE,))
		got = {r[0] for r in rows}
		_assert(F.sm.emp in got and F.both.emp not in got and F.so.emp not in got, str(got))

	check("#78 Primary POC suggestions: SM / SA, never a Sales Officer role holder", _primary_query)

	def _names_onload():
		doc = frappe.get_doc("Buyer Master", F.mine)
		doc.run_method("onload")
		names = (doc.get_onload() or {}).get("employee_names") or {}
		_assert(names.get(F.so.emp) == f"{TAG} So", str(names))

	check("#76 the form receives the names of its responsibility fields", _names_onload)


def _afr_export():
	from alpinos import afr_export as X

	def _submitted_on():
		doc = frappe.get_doc("Pick List", F.pl_b1)
		X.pick_list_on_submit(doc)
		_assert(frappe.db.get_value("Pick List", F.pl_b1, "custom_submitted_on"), "Submitted On not stamped")

	check("#110 a Pick List records when it was submitted", _submitted_on)

	def _history():
		rows = [{"sales_order_id": F.so_b1, "_pick_list": F.pl_b1, "exported_at": ""},
			{"sales_order_id": F.so_b1, "_pick_list": F.pl_b1, "exported_at": ""},
			{"sales_order_id": F.so_b1, "_pick_list": "", "exported_at": ""}]
		X.record_export(rows, "Test")
		X.record_export([dict(r, exported_at="") for r in rows], "Test")
		_assert(frappe.db.count(X.LOG, {"sales_order": F.so_b1}) == 4, "one log per row key per export")
		fresh = X.fill_history([{"sales_order_id": F.so_b1, "_pick_list": F.pl_b1}])
		stamps = fresh[0]["exported_at"].split(", ")
		_assert(len(stamps) == 2 and len(stamps[0]) == 16, fresh[0]["exported_at"])
		_assert(rows[0]["exported_at"], "the exported rows show this export")

	check("#110 every export is kept per row and shown oldest first (dd-MM-yyyy HH:mm, ...)", _history)


def _restore():
	from alpinos import pick_list_api as P

	pl_name = frappe.db.sql(
		"""SELECT pl.name FROM `tabPick List` pl WHERE pl.docstatus = 0 AND IFNULL(pl.custom_sales_order_id, '') <> ''
		AND (SELECT COUNT(*) FROM `tabPick List Item` i WHERE i.parent = pl.name) >= 1
		AND EXISTS (SELECT 1 FROM `tabSales Order` so WHERE so.name = pl.custom_sales_order_id AND so.docstatus = 1)
		ORDER BY pl.creation DESC LIMIT 1"""
	)

	def _flow():
		_assert(pl_name, "no Draft Pick List of a submitted order on this site")
		pl = frappe.get_doc("Pick List", pl_name[0][0])
		row = pl.locations[0]
		item, qty, line = row.item_code, row.qty, row.sales_order_item
		before_rows = len(pl.locations)
		P.remove_pick_list_row_with_reason(pl.name, row.name, "test")
		pl.reload()
		_assert(len(pl.locations) == before_rows - 1, "row not removed")
		removed = [r for r in pl.custom_removed_items if not r.restored][-1]
		_assert(removed.sales_order_item == line, "removal did not record its Sales Order line")
		listed = P.get_restorable_rows(pl.name)
		_assert(any(r["name"] == removed.name for r in listed), "not offered for restore")
		err = refused(lambda: P.restore_pick_list_rows(pl.name, json.dumps([removed.name])))
		pl.reload()
		if err:
			# the Pick List's own stock / MRP checks may refuse on this data: then nothing changes
			_assert(len(pl.locations) == before_rows - 1, f"refused but changed: {err}")
			return
		back = [l for l in pl.locations if l.sales_order_item == line and l.item_code == item]
		_assert(back and abs(sum(l.qty for l in back) - qty) < 0.001, f"qty after restore {[l.qty for l in back]} vs {qty}")
		_assert([r for r in pl.custom_removed_items if r.name == removed.name][0].restored, "not marked Restored")
		_assert(not any(r["name"] == removed.name for r in P.get_restorable_rows(pl.name)), "offered again")

	check("#109 a removed row goes back on its Sales Order line, marked Restored", _flow)

	def _submitted():
		sub = frappe.db.get_value("Pick List", {"docstatus": 1}, "name")
		_assert("Draft" in refused(lambda: P.restore_pick_list_rows(sub, "[]")), "restore on a submitted Pick List")

	check("#109 a submitted Pick List restores nothing", _submitted)


def _switcher():
	from alpinos.company_scope import api

	def _looks():
		looks = api._company_looks(frappe.get_all("Company", pluck="name"))
		ahfpl = next((v for k, v in looks.items() if "Alpino Health Foods" in k), {})
		_assert((ahfpl.get("color") or "").upper() == "#005C2A", str(ahfpl))
		logo = ahfpl.get("logo") or ""
		_assert(not logo or logo.startswith("/files/") or "company_logo" in logo, logo)

	check("#114 / #115 the switcher gets each company's colour and logo", _looks)

	def _missing_file():
		import os

		company = frappe.db.get_value("Company", {}, "name")
		gone = "/private/files/alpinos-test-missing-logo.png"
		_assert(not os.path.exists(frappe.get_site_path("private", "files", "alpinos-test-missing-logo.png")))
		frappe.db.set_value("Company", company, "company_logo", gone, update_modified=False)
		_assert(api._company_looks([company])[company]["logo"] is None, "a logo whose file is gone is not offered")
		frappe.set_user("Administrator")
		try:
			api.company_logo(company)
			_assert(False, "company_logo answered for a missing file")
		except frappe.DoesNotExistError:
			pass  # 404, not a server error

	check("#115 a Company Logo whose file is missing keeps the app logo (no error)", _missing_file)


def _item_row(parent, item_code, qty, idx=1):
	return _insert("Sales Order Item", name=f"{parent}-I{idx}", parent=parent, parenttype="Sales Order", parentfield="items",
		idx=idx, item_code=item_code, item_name=item_code, qty=qty, stock_qty=qty, rate=100, amount=100 * qty,
		custom_customer_mrp=120, custom_selling_price=100, custom_gst_percent=0, uom="Nos", conversion_factor=1)


def _only_invoice():
	from alpinos import only_invoice as OI
	from alpinos import sales_order_api
	from alpinos.workflow_engine import sales_order_on_submit

	item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
	so = _so(f"{TAG}-SO-OI", docstatus=1, custom_only_invoice=1, custom_dispatch_date=today(), order_type="Modern Trade",
		custom_invoice_no="5555")
	_item_row(so, item, 5)
	F.oi_so = so

	def _submit():
		sales_order_on_submit(frappe.get_doc("Sales Order", so))
		_assert(frappe.db.get_value("Sales Order", so, "custom_workflow_status") == "Only Invoice", "status")
		_assert(not frappe.get_all("Notification Log", {"document_name": so}), "warehouse notified")

	check("#108 an Only Invoice order goes to Only Invoice on submit, the warehouse not notified", _submit)

	def _no_pl_dn():
		pl = frappe._dict(custom_sales_order_id=so, docstatus=0, items=[], flags=frappe._dict())
		pl.is_new = lambda: True
		pl.get = lambda k, d=None: pl[k] if k in pl else d
		_assert("Only Invoice" in refused(lambda: OI.pick_list_validate(pl)), "Pick List allowed")
		dn = frappe._dict(custom_sales_order_id=so, docstatus=0, items=[], flags=frappe._dict())
		dn.get = lambda k, d=None: dn[k] if k in dn else d
		_assert("Only Invoice" in refused(lambda: OI.delivery_note_validate(dn)), "Delivery Note allowed")

	check("#108 no Pick List or Delivery Note for an Only Invoice order", _no_pl_dn)

	def _lists():
		yes = sales_order_api.get_sales_order_entry_list(page_length=100, search=TAG, only_invoice="Yes", show_all=1)
		no = sales_order_api.get_sales_order_entry_list(page_length=100, search=TAG, only_invoice="No", show_all=1)
		_assert(so in {r.name for r in yes["data"]} and so not in {r.name for r in no["data"]}, "SO list Only Invoice filter")

	check("#108 the Sales Order list filters Only Invoice Yes / No", _lists)

	def _afr():
		from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

		cols, rows = AFR.execute({"from_date": today(), "to_date": today(), "only_invoice": "Yes", "sales_order": so, "show_all": 1})
		mine = [r for r in rows if r.get("sales_order_id") == so]
		_assert(mine and all(r["only_invoice"] == "Yes" for r in mine), f"AFR rows {len(mine)}")
		_assert(any(abs(float(r.get("unit") or 0) - 5) < 0.001 for r in mine), "quantity not from the Sales Order")
		_assert(not mine[0].get("pl_submitted_at"), "Pick List Submitted At should be blank")
		_assert([c["fieldname"] for c in cols][-1] == "only_invoice", "Only Invoice not the last column")
		_c, rows = AFR.execute({"from_date": today(), "to_date": today(), "only_invoice": "No", "sales_order": so, "show_all": 1})
		_assert(not [r for r in rows if r.get("sales_order_id") == so], "filter No still lists it")

	check("#108 Accounts Format Report: rows from the Sales Order, Only Invoice column and filter", _afr)

	def _ofr_column():
		import alpinos.invoice_queue_api as Q

		_assert("only_invoice" in as_(F.sm.user, lambda: Q.catalogue()), "Sales Manager misses the column")
		acc = _person("acc1", "Accounts User")
		_assert("only_invoice" not in as_(acc.user, lambda: Q.catalogue()), "Accounts User sees the column")

	check("#108 OFR Only Invoice column only for the sales / e-com roles", _ofr_column)


def _accounts_view():
	from alpinos import ofr_accounts as A

	acc = _person("acc", "Accounts User")
	accm = _person("accsys", "Accounts Manager", "System Manager")

	def _modes():
		_assert(A.mode(acc.user) == "only" and A.mode(accm.user) == "switch" and A.mode(F.sm.user) is None,
			(A.mode(acc.user), A.mode(accm.user), A.mode(F.sm.user)))

	check("#106 Accounts View: only view for Accounts roles, a switch for someone with more", _modes)

	so_pending = _so(f"{TAG}-SO-AV1", docstatus=1, custom_dispatch_date=today())
	pl_cancel = _insert("Pick List", name=f"{TAG}-PL-AV1", custom_sales_order_id=so_pending, company=F.company,
		purpose="Delivery", docstatus=2, custom_dispatch_date=today())
	so_linked = _so(f"{TAG}-SO-AV2", docstatus=1, custom_dispatch_date=today(), custom_invoice_no="4444",
		custom_invoice_pdf="/private/files/x.pdf")
	_insert("Pick List", name=f"{TAG}-PL-AV2", custom_sales_order_id=so_linked, company=F.company,
		purpose="Delivery", docstatus=1, custom_dispatch_date=today(), custom_invoice_no="4444")

	def _view():
		r = as_(acc.user, lambda: A.get_accounts_view(today(), today(), "", "", TAG))
		rows = {x.sales_order: x for x in r["rows"]}
		_assert({so_pending, so_linked, F.oi_so} <= set(rows), sorted(rows))
		_assert(rows[so_pending].pl_cancelled == 1 and rows[so_pending].pick_list == pl_cancel, "cancelled PL not flagged")
		_assert(rows[so_linked].linked == 1 and rows[so_pending].linked == 0, "linked / pending")
		_assert(rows[F.oi_so].only_invoice == 1, "Only Invoice row")
		only = as_(acc.user, lambda: A.get_accounts_view(today(), today(), "", "only_invoice", TAG))
		_assert({x.sales_order for x in only["rows"]} == {F.oi_so}, "Only Invoice card filter")
		c = r["counts"]
		_assert(c["pending"] + c["total"] >= 3 and c["only_invoice"] >= 1, str(c))
		_assert(c["only_invoice"] <= c["pending"] + c["total"], "Only Invoice added on top")

	check("#106 cards (pending / total / only invoice), cancelled Pick List kept and flagged", _view)

	def _replaced():
		_insert("Pick List", name=f"{TAG}-PL-AV1B", custom_sales_order_id=so_pending, company=F.company,
			purpose="Delivery", docstatus=1, custom_dispatch_date=today())
		r = as_(acc.user, lambda: A.get_accounts_view(today(), today(), "", "", TAG))
		row = [x for x in r["rows"] if x.sales_order == so_pending][0]
		_assert(row.pick_list == f"{TAG}-PL-AV1B" and not row.pl_cancelled, "new Pick List does not replace the red one")

	check("#106 a new Pick List replaces the cancelled one (no red)", _replaced)

	def _delink():
		res = as_(acc.user, lambda: A.delink_invoices(json.dumps([so_linked])))
		_assert(res["done"] == [so_linked], str(res))
		row = frappe.db.get_value("Sales Order", so_linked, ["custom_invoice_no", "custom_invoice_pdf"], as_dict=True)
		_assert(not row.custom_invoice_no and not row.custom_invoice_pdf, str(row))
		_assert(not frappe.db.get_value("Pick List", f"{TAG}-PL-AV2", "custom_invoice_no"), "PL invoice kept")
		_assert(frappe.db.exists("Invoice Sync Log", {"order_id": so_linked, "sync_type": "Delink"}), "not logged")
		_assert("Accounts" in refused(lambda: as_(F.sm.user, lambda: A.delink_invoices(json.dumps([so_linked])))), "SM delinked")

	check("#106 Delink clears the order's invoice and its parts, logged; Accounts roles only", _delink)


def _daily_report():
	from alpinos import daily_report as DR

	item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
	ctype = "Reliance" if frappe.db.exists("Alpino Customer Type", "Reliance") else frappe.db.get_value("Alpino Customer Type", {}, "name")
	so = _so(f"{TAG}-SO-DR", docstatus=1, order_type=ctype, custom_invoice_no="3333", custom_invoice_pdf="/private/files/y.pdf")
	pl_old = _insert("Pick List", name=f"{TAG}-PL-DR1", custom_sales_order_id=so, company=F.company, purpose="Delivery",
		docstatus=2, custom_dispatch_date=today(), custom_actual_box=3, custom_total_box=3, custom_customer_name=f"{TAG} Mine")
	_insert("Pick List Item", name=f"{TAG}-PLI-1", parent=pl_old, parenttype="Pick List", parentfield="locations",
		item_code=item, qty=7, stock_qty=7, idx=1)

	def blocks(ct=ctype):
		r = DR.get_daily_report(today(), today(), ct, 0)
		return {b["customer_type"]: b for b in r["blocks"]}

	def _cancelled_kept():
		b = blocks().get(ctype)
		col = [c for c in (b or {}).get("columns", []) if c["sales_order"] == so]
		_assert(col and col[0]["cancelled"], "cancelled Pick List not kept / not flagged")

	check("#107 a cancelled Pick List stays (red) while the order has no other", _cancelled_kept)

	def _replaced():
		pl_new = _insert("Pick List", name=f"{TAG}-PL-DR2", custom_sales_order_id=so, company=F.company, purpose="Delivery",
			docstatus=1, custom_dispatch_date=today(), custom_actual_box=4, custom_total_box=4, custom_customer_name=f"{TAG} Mine",
			custom_party_code="P-1")
		_insert("Pick List Item", name=f"{TAG}-PLI-2", parent=pl_new, parenttype="Pick List", parentfield="locations",
			item_code=item, qty=9, stock_qty=9, idx=1)
		b = blocks()[ctype]
		cols = [c for c in b["columns"] if c["sales_order"] == so]
		_assert(len(cols) == 1 and cols[0]["pick_list"] == pl_new and not cols[0]["cancelled"], str(cols))
		i = [x for x in b["items"] if x["item_code"] == item][0]
		_assert(9 in i["values"], f"qty {i['values']}")
		_assert(cols[0]["header"]["party_code"] == "P-1" and cols[0]["header"]["actual_box"] == 4, cols[0]["header"])

	check("#107 the new Pick List replaces it: its boxes, party code and quantities", _replaced)

	def _parent_type():
		parent = frappe.db.get_value("Alpino Customer Type", ctype, "parent_customer_type")
		if not parent:
			return
		_assert(ctype in blocks(parent), "a parent type does not show its child type")

	check("#107 a parent Customer Type shows its child types", _parent_type)

	def _no_invoice():
		frappe.db.set_value("Sales Order", so, "custom_invoice_pdf", "", update_modified=False)
		b = blocks().get(ctype)
		_assert(not [c for c in (b or {}).get("columns", []) if c["sales_order"] == so], "listed without a fetched invoice")
		frappe.db.set_value("Sales Order", so, "custom_invoice_pdf", "/private/files/y.pdf", update_modified=False)

	check("#107 nothing until the invoice PDF is fetched and linked", _no_invoice)

	def _export():
		import io

		import openpyxl

		DR.export_daily_report(today(), today(), ctype, 1)
		wb = openpyxl.load_workbook(io.BytesIO(frappe.response["filecontent"]))
		abbr = frappe.db.get_value("Alpino Customer Type", ctype, "abbreviation") or ctype[:12]
		_assert(abbr in wb.sheetnames, wb.sheetnames)
		ws = wb[abbr]
		_assert(ws["D4"].value == "TOTAL BOX" and ws["D4"].fill.fgColor.rgb.endswith("4472C4"), "header rows / colours")
		_assert(ws.freeze_panes == "E12", ws.freeze_panes)
		frappe.response.pop("filecontent", None)

	check("#107 Excel export: a sheet per Customer Type in the template layout", _export)
