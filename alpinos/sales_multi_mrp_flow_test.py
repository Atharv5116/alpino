"""Sales-side Multiple MRP, the flows around the rules (sales_multi_mrp_test covers the rules).

	bench --site <test site> execute alpinos.sales_multi_mrp_flow_test.run

GRN after QC with quarantine and its release, import through the Sales Order insert path, a
full e-com import, a draft edited from the entry screen, split Pick List rows, Delivery Note
and Accounts Format Report, the Pick List PDF file, older open orders, and the endpoints as
real (non-admin) users. Records stay on the site, prefixed PITEST / ECOMTEST.
"""

import frappe
from frappe.utils import add_days, cint, flt, today

from alpinos import item_mrp as IM
from alpinos import mrp_batch as MB
from alpinos.sales_multi_mrp_test import R, _assert, _fixtures, _report, check, refused


def run():
	R.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	try:
		_grn_and_quarantine()
		frappe.db.commit()
		_sales_flows()
	finally:
		frappe.flags.in_import = False
		frappe.set_user("Administrator")
	return _report()


# ---------------------------------------------------------------- purchase side


def _grn_and_quarantine():
	from alpinos.mrp_batch_test import _complete_qc, _fg_item, _receive_split
	from alpinos.purchase import constants as C
	from alpinos.purchase import e2e_test as H
	from alpinos.purchase import quarantine as Q

	H.COMPANY = H._company()
	H.SEQ = "SMF" + frappe.generate_hash(length=5).upper()
	wh = frappe.db.get_value("Warehouse", {"company": H.COMPANY, "is_group": 0, "name": ("like", "Stores%")}, "name") or H._warehouse()
	item = _fg_item(f"PITEST-SMF-{H.SEQ}")
	po = H.make_po(H.ensure_supplier(), [(item, 60, 80)], inward_type=C.INWARD_FG)
	inw = H.make_inward(po, po.items, invoice_no=f"PITEST-SMF-{H.SEQ}")
	inw.submit()
	inw = _receive_split(inw, wh, [(40, "F199", 199, add_days(today(), -20)), (20, "F210", 210, add_days(today(), -10))], line_qty=60)
	check("before QC and GRN the SKU has no MRP in its table", lambda: _assert(not IM.applicable(item).tracked, IM.applicable(item)))
	# QC: all of the 210 split held in quarantine, 10 of the 199 split held.
	qc = _complete_qc(inw, {"F199": (40, 0), "F210": (20, 0)}, quarantine={"F199": 10, "F210": 20})
	pr = frappe.get_doc("Purchase Receipt", frappe.db.get_value("Purchase Receipt", {"custom_purchase_inward": inw.name, "docstatus": 0}, "name"))
	pr.submit()
	rows = frappe.get_all(IM.CHILD, {"parent": item}, ["mrp", "source", "reference_name", "active"])
	check("GRN after QC: the MRP received into the store is added, source GRN", lambda: _assert(
		[(flt(r.mrp), r.source, r.reference_name) for r in rows] == [(199, "GRN", pr.name)], rows))
	check("the MRP held wholly in quarantine is not added yet", lambda: _assert(IM.applicable(item).mrps == [199], IM.applicable(item)))
	qdoc = frappe.db.get_value("Purchase QC", qc.name, "quarantine_document")
	held = [r.name for r in frappe.get_doc("Purchase Quarantine", qdoc).items]
	Q.release_items(qdoc, rows=frappe.as_json(held))
	check("releasing the quarantine adds 210 and sets Multiple MRP", lambda: _assert(
		IM.applicable(item).mrps == [199, 210] and cint(frappe.db.get_value("Item", item, IM.FLAG)) == 1,
		frappe.get_all(IM.CHILD, {"parent": item}, ["mrp", "source"])))
	check("the release row says Stock Entry", lambda: _assert(
		frappe.db.get_value(IM.CHILD, {"parent": item, "mrp": 210}, "source") == "Stock Entry"))


# ---------------------------------------------------------------- sales side


def _sales_flows():
	from alpinos import e2e_ecom_test as E
	from alpinos.alpinos_development.page.pick_list_entry import pick_list_entry as P
	from alpinos.sales_order_api import create_sales_order, get_pick_list_mapping_data, update_sales_order

	f = _fixtures()
	tag, wh, cust = f["tag"], f["warehouse"], f["cust_partial"]
	A, B = f["items"]
	MB.assign_existing_stock([
		{"item_code": A, "warehouse": wh, "batch_no": "ABC", "mrp": 599, "qty": 6, "expiry_date": add_days(today(), 100)},
		{"item_code": A, "warehouse": wh, "batch_no": "CDE", "mrp": 599, "qty": 6, "expiry_date": add_days(today(), 200)},
		{"item_code": A, "warehouse": wh, "batch_no": "XYZ", "mrp": 699, "qty": 20, "expiry_date": add_days(today(), 300)},
	])
	IM.register(B, 250, "Manual")
	frappe.db.commit()

	# ---- import through the Sales Order insert path (what Data Import does)
	base = create_sales_order(
		customer=cust, order_type=f["ctype"], company=f["company"],
		items=frappe.as_json([{"item_code": B, "qty": 2, "custom_customer_mrp": 250, "custom_selling_price": 225,
			"custom_flat_discount": 10, "custom_gst_percent": 0}]),
		dispatch_date=E.DISPATCH(), submit_now=0,
	)["name"]

	def imported(item_code, mrp, submit):
		doc = frappe.copy_doc(frappe.get_doc("Sales Order", base))
		doc.items[0].item_code = item_code
		doc.items[0].custom_customer_mrp = mrp
		doc.docstatus = 1 if submit else 0
		frappe.flags.in_import = True
		try:
			doc.insert()
		finally:
			frappe.flags.in_import = False
		return doc.name

	t = refused(lambda: imported(B, 300, 0))
	check("import (insert path): a draft row at another MRP is refused with the FRD message", lambda: _assert(
		"MRP mismatch for SKU" in t and "Please correct the import sheet" in t, t))
	t = refused(lambda: imported(A, 0, 1))
	check("import (insert path, submit after import): a blank MRP on a Multiple MRP SKU is refused", lambda: _assert("Select the MRP" in t, t))
	t = refused(lambda: imported(A, 699, 1))
	check("import (insert path): an applicable MRP goes in and submits", lambda: _assert(t == "", t))

	# ---- full e-com import
	from alpinos import ecom_sales_order_import as EI

	addr = frappe.get_all("Dynamic Link", {"link_doctype": "Customer", "link_name": cust, "parenttype": "Address"}, pluck="parent")
	sheet = [{"SKU": A, "Qty": 2, "MRP": 699, "Margin %": 10, "Site Name": "ECOMTEST Site", "Customer Type": f["ctype"],
		"PO Date": today(), "Dispatch Date": E.DISPATCH(), "Billing Address": addr[0] if addr else "", "Shipping Address": addr[-1] if addr else ""}]
	out = {}

	def go():
		out.update(EI._create_one_order(cust, f"PO-{tag}-EI", sheet))

	t = refused(go)
	so_ei = out.get("sales_order")
	check("e-com import with an applicable MRP creates the order at that MRP", lambda: _assert(
		so_ei and flt(frappe.db.get_value("Sales Order Item", {"parent": so_ei}, "custom_customer_mrp")) == 699, t or out))
	frappe.db.commit()

	# ---- a draft edited from the entry screen, then submitted
	# The imported order above already made this buyer's catalogue (submission writes it).
	existing = frappe.db.get_value("Buyer Items", {"buyer": cust}, "name")
	cat = frappe.get_doc("Buyer Items", existing) if existing else frappe.new_doc("Buyer Items")
	if not existing:
		cat.title, cat.buyer = f"{tag} Catalogue", cust
	check("the submitted import wrote its 699 price to the catalogue", lambda: _assert(
		existing and frappe.db.exists("Buyer Item", {"parent": existing, "item_code": A, "mrp": 699}), existing))
	cat.set("items", [r for r in cat.get("items") or [] if r.item_code != A])
	cat.append("items", {"item_code": A, "mrp": 599, "margin_percent": 30, "selling_rate": 419.30})
	cat.flags.ignore_permissions = cat.flags.ignore_mandatory = True
	cat.save() if existing else cat.insert()

	def catalogue():
		return sorted((flt(r.mrp), flt(r.selling_rate)) for r in frappe.get_all("Buyer Item", {"parent": cat.name, "item_code": A}, ["mrp", "selling_rate"]))

	line = [{"item_code": A, "qty": 2, "custom_customer_mrp": 699, "custom_selling_price": 520, "custom_flat_discount": 25.61, "custom_gst_percent": 0}]
	draft = create_sales_order(customer=cust, order_type=f["ctype"], company=f["company"], items=frappe.as_json(line),
		dispatch_date=E.DISPATCH(), submit_now=0)["name"]
	line[0]["custom_selling_price"] = 510
	update_sales_order(name=draft, customer=cust, order_type=f["ctype"], company=f["company"], items=frappe.as_json(line),
		dispatch_date=E.DISPATCH())
	check("saving and editing a draft leaves the catalogue alone", lambda: _assert(catalogue() == [(599, 419.30)], catalogue()))
	frappe.get_doc("Sales Order", draft).submit()
	check("submitting the edited draft adds the 699 price as last saved (510)", lambda: _assert(
		catalogue() == [(599, 419.30), (699, 510)], catalogue()))
	frappe.db.commit()

	# ---- split rows on one Pick List line, then Delivery Note and the report
	so = E._mk_ecom_so(f, cust, f"PO-{tag}-SPL", [(A, 10, 599, 10)])
	mapping = [l for l in get_pick_list_mapping_data(so)["locations"] if l.get("item_code") == A]
	header = frappe.as_json({"custom_qc_attended_by": "Administrator", "custom_dispatch_date": E.DISPATCH(),
		"custom_transporter": "ECOMTEST Transport", "custom_po_no": "ECOMTEST-PO"})
	blank = {"custom_box": 0, "batch_no": "", "custom_mfg_date": "", "custom_expiry_date": ""}
	pl = P.create_pick_list_as_draft(so, header, frappe.as_json([dict(blank, name=l.get("name"), item_code=A, qty=10,
		custom_batch_code="", custom_source_table="Items") for l in mapping]))
	doc = frappe.get_doc("Pick List", pl)
	first = doc.locations[0]
	first.qty = first.stock_qty = first.picked_qty = 6
	doc.append("locations", {k: first.get(k) for k in ("item_code", "item_name", "custom_ordered_qty", "warehouse", "sales_order",
		"sales_order_item", "conversion_factor", "custom_source_table", "uom", "stock_uom")} | {"qty": 4, "stock_qty": 4, "picked_qty": 4})
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	rows = frappe.get_all("Pick List Item", {"parent": pl, "item_code": A}, ["name", "qty"], order_by="idx")

	def save_rows(batches):
		# as split_pick_list_row leaves them: each part short of the ordered qty carries "[split]"
		return frappe.as_json([dict(blank, name=r.name, qty=flt(r.qty), custom_batch_code=b, mrp_batch="", custom_remark="[split]")
			for r, b in zip(rows, batches)])

	t = refused(lambda: P.save_pick_list_data(pl, header, save_rows(["ABC", "XYZ"])))
	check("split rows: the second part on a 699 batch is refused", lambda: _assert("Batch XYZ has MRP" in t, t))
	t = refused(lambda: P.save_pick_list_data(pl, header, save_rows(["ABC", "CDE"])))
	check("split rows: 6 on ABC and 4 on CDE, both 599, submit", lambda: _assert(t == "", t))
	picked = sorted((r.custom_batch_code, flt(r.qty), r.mrp_batch) for r in frappe.get_all("Pick List Item", {"parent": pl, "item_code": A}, ["custom_batch_code", "qty", "mrp_batch"]))
	lots = {r[2] for r in picked}
	check("each split row holds its own 599 lot", lambda: _assert(
		[(b, q) for b, q, _l in picked] == [("ABC", 6), ("CDE", 4)] and all(lot and lot.endswith(":599") for lot in lots), picked))
	frappe.db.commit()

	dn = E._mk_dn(pl)
	dn_rows = frappe.get_all("Delivery Note Item", {"parent": dn, "item_code": A}, ["mrp_batch", "qty"])
	check("the Delivery Note ships the two 599 lots", lambda: _assert(
		sorted((r.mrp_batch, flt(r.qty)) for r in dn_rows) == sorted((r[2], r[1]) for r in picked), dn_rows))
	check("the 699 stock is untouched", lambda: _assert(
		flt(MB.balances(A, wh).get(frappe.db.get_value(MB.DOCTYPE, {"item_code": A, "batch_no": "XYZ"}, "name"))) == 20))
	from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as AFR

	_c, data = AFR.execute({"sales_order": so, "show_all": 1})
	check("Accounts Format Report shows the order MRP 599 for the shipped order", lambda: _assert(
		{flt(r.get("alpino_mrp")) for r in data if r.get("alpino_mrp") is not None} == {599}, data[:2]))

	from alpinos import pick_list_print_format as PF

	PF.execute()
	# Local test sites are *.localhost, which this machine resolves only to ::1 while the dev
	# server listens on 127.0.0.1: wkhtmltopdf would wait on the asset URLs. A real site has a
	# real host name, so only the render here is pointed at 127.0.0.1.
	host = frappe.local.conf.get("host_name")
	if host and ".localhost" in host:
		frappe.local.conf.host_name = "http://127.0.0.1:" + host.rsplit(":", 1)[-1]
	try:
		pdf = frappe.get_print("Pick List", pl, print_format=PF.PF_NAME, as_pdf=True)
	finally:
		frappe.local.conf.host_name = host
	html = frappe.get_print("Pick List", pl, print_format=PF.PF_NAME)
	check("the Pick List PDF file renders, with the MRP line under the SKU", lambda: _assert(
		pdf[:4] == b"%PDF" and html.count("MRP: ₹ 599.00") == 2, (pdf[:8], html.count("MRP: ₹ 599.00"))))
	frappe.db.commit()

	# ---- orders taken before go-live, at an MRP the table no longer has
	old_b = E._mk_ecom_so(f, cust, f"PO-{tag}-OLDB", [(B, 5, 250, 10)])
	frappe.db.set_value("Sales Order Item", {"parent": old_b}, "custom_customer_mrp", 240)
	t = refused(lambda: E._mk_pl(old_b, f, {B: 5}))
	check("older order at 240, one-MRP SKU (table 250): its stock with no MRP still picks", lambda: _assert(t == "", t))
	old_a = E._mk_ecom_so(f, cust, f"PO-{tag}-OLDA", [(A, 2, 599, 10)])
	frappe.db.set_value("Sales Order Item", {"parent": old_a}, "custom_customer_mrp", 300)
	t = refused(lambda: E._mk_pl(old_a, f, {A: 2}))
	check("older order at 300, Multiple MRP SKU with no 300 stock: refused, nothing substituted", lambda: _assert(
		"Insufficient stock for SKU" in t and "₹ 300.00" in t and "Available Qty: 0" in t, t))
	frappe.db.commit()

	# ---- the new endpoints as real users
	_as_users(A, B, wh, cust)


def _users_with(roles, without=()):
	rows = frappe.db.sql(
		"""select distinct hr.parent from `tabHas Role` hr join `tabUser` u on u.name = hr.parent
		where hr.parenttype = 'User' and hr.role in %(roles)s and u.enabled = 1 and u.user_type = 'System User'
		and u.name not in ('Administrator', 'Guest')""",
		{"roles": tuple(roles)},
	)
	users = [r[0] for r in rows]
	if without:
		bad = set(frappe.db.sql_list("select parent from `tabHas Role` where parenttype='User' and role in %(r)s", {"r": tuple(without)}))
		users = [u for u in users if u not in bad]
	return users


def _as_users(A, B, wh, cust):
	from alpinos.ecom_sales_order_api import get_ecom_item_defaults
	from alpinos.mrp_batch_hooks import get_batch_code_options

	sales = next((u for u in _users_with(["Sales User", "Sales Manager"]) if frappe.has_permission("Sales Order", "create", user=u)), None)
	store = next((u for u in _users_with(["Warehouse Manager", "Warehouse Admin", "Stock User"], without=["Sales User", "Sales Manager", "System Manager"])
		if frappe.has_permission("Pick List", "read", user=u)), None)
	outsider = next((u for u in _users_with(["Employee"], without=["Sales User", "Sales Manager", "System Manager", "Accounts User", "Accounts Manager"])
		if not frappe.has_permission("Sales Order", "create", user=u) and not frappe.has_permission("Sales Order", "write", user=u)), None)
	check("found real UAT users to test with", lambda: _assert(sales and store and outsider, (sales, store, outsider)))
	if not (sales and store and outsider):
		return

	def as_user(user, fn):
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	opts = as_user(sales, lambda: IM.get_sales_mrp_options(A))
	check(f"a sales user ({sales}) gets the MRP list", lambda: _assert([m["mrp"] for m in opts["mrps"]] == [599, 699], opts))
	d = as_user(sales, lambda: get_ecom_item_defaults(cust, A, mrp=599))
	check("a sales user gets the e-com defaults at the chosen MRP", lambda: _assert(flt(d["mrp"]) == 599, d))
	line = frappe.db.get_value("Sales Order Item", {"item_code": A, "custom_customer_mrp": 599, "docstatus": 1}, "name")
	codes = as_user(store, lambda: get_batch_code_options(A, wh, sales_order_item=line))
	check(f"a warehouse user ({store}) gets batch suggestions for the order MRP", lambda: _assert(
		isinstance(codes, list) and "XYZ" not in codes, codes))
	t = refused(lambda: as_user(outsider, lambda: IM.get_sales_mrp_options(A)))
	check(f"a user without Sales Order rights ({outsider}) is refused the MRP list", lambda: _assert("permitted" in t.lower(), t))
