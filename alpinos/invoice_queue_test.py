"""Invoice Download Queue: page access, channel rules, columns, filters, sorting, export,
downloads and saved views.

Run:  bench --site alpinos.test execute alpinos.invoice_queue_test.run

Everything runs against its own fixture orders (tagged IQT-<run>) inside one
transaction that is ROLLED BACK at the end, so the site is left exactly as it was.
The fixtures are written straight to the tables: this suite tests what the queue
reads, not how an order is created.

A role lock that only hides a filter on screen is not a lock, so the access checks
drive the SERVER entry points as a real user holding just that role.
"""

import frappe
from frappe.utils import add_days, cint, flt, today

from alpinos import invoice_queue_api as Q

R = []

SPEC_ROLES = (
	"E-Commerce Admin", "E-Commerce Coordinator", "E-Commerce Manager",
	"Sales Manager", "Sales Admin", "Sales User",
	"Warehouse Admin", "Warehouse Manager", "Accounts User",
)


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def expect_throw(label, fn, fragment=None, exc=None):
	try:
		fn()
		R.append(("FAIL", label, "expected an exception, none raised"))
	except Exception as e:
		msg = str(e) or str(getattr(frappe.flags, "error_message", "") or "")
		if exc and not isinstance(e, exc):
			R.append(("FAIL", label, f"raised {type(e).__name__}, expected {exc.__name__}: {msg[:160]}"))
		elif fragment and fragment.lower() not in msg.lower():
			R.append(("FAIL", label, f"threw, but lacked {fragment!r}: {msg[:160]}"))
		else:
			R.append(("PASS", label, ""))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


# ------------------------------------------------------------------- fixtures


def _user(email, roles):
	"""A user holding exactly `roles` (rolled back with everything else)."""
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User",
		}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	u.set("roles", [])
	for role in roles:
		u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
	frappe.clear_cache(user=email)
	return email


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.db_insert()
	return doc


class Fixture:
	def __init__(self):
		self.tag = "IQT-" + frappe.generate_hash(length=6).upper()
		t = self.tag
		self.day = today()

		# Two owners whose names sort the OPPOSITE way to their logins.
		self.owner_z = f"z-{t.lower()}@example.com"
		self.owner_a = f"a-{t.lower()}@example.com"
		_insert("User", name=self.owner_z, email=self.owner_z, first_name="Abe", full_name="Abe Owner",
			user_type="System User", enabled=1)
		_insert("User", name=self.owner_a, email=self.owner_a, first_name="Zed", full_name="Zed Owner",
			user_type="System User", enabled=1)

		self.addr = _insert("Address", name=f"{t}-ADDR", address_title=t, address_type="Shipping",
			address_line1="1 Test Road", city="Pune", state="Maharashtra", country="India").name

		self.cust_e = f"{t}-CUST-E"
		self.cust_o = f"{t}-CUST-O"
		self.cust_g = f"{t}-CUST-G"
		self.cust_shared = f"{t}-CUST-S"

		self.ecom = self._so("01", "E-com", self.cust_e, owner=self.owner_a)
		self.offline = self._so("02", "Offline", self.cust_o, owner=self.owner_z)
		self.gt = self._so("03", "General Trade", self.cust_g)
		self.shared_e = self._so("04", "E-com", self.cust_shared)
		self.shared_o = self._so("05", "Offline", self.cust_shared)
		self.all = [self.ecom, self.offline, self.gt, self.shared_e, self.shared_o]

		# Dispatch Date lives on the Pick List, and differs from the order's own field.
		self.pl_date = add_days(self.day, 3)
		_insert("Pick List", name=f"{t}-PL-1", docstatus=1, custom_sales_order_id=self.ecom,
			custom_dispatch_date=self.pl_date, custom_transporter="T1", custom_po_no="PLPO-1",
			custom_total_box=2, custom_gross_weight=10.5)
		_insert("Pick List", name=f"{t}-PL-2", docstatus=1, custom_sales_order_id=self.ecom,
			custom_dispatch_date=add_days(self.day, 1), custom_transporter="T2", custom_po_no="PLPO-1",
			custom_total_box=1, custom_gross_weight=4.5)
		# Two notes on one order, so a summed dynamic column has something to add.
		_insert("Delivery Note", name=f"{t}-DN-1", docstatus=1, is_return=0,
			custom_sales_order_id=self.ecom, grand_total=100, custom_lr_gr_no="LR-1")
		_insert("Delivery Note", name=f"{t}-DN-2", docstatus=1, is_return=0,
			custom_sales_order_id=self.ecom, grand_total=50, custom_lr_gr_no="LR-2")
		if frappe.db.exists("DocType", "Post Dispatch"):
			_insert("Post Dispatch", name=f"{t}-PD-1", sales_order=self.ecom,
				post_delivery_status="In Progress")

		# Combos. BUNDLE = 1 x A + 1 x B, so 2 units per combo.
		self.bundle = f"{t}-BUNDLE"
		self.plain = f"{t}-PLAIN"
		self.comp_a = f"{t}-A"
		self.comp_b = f"{t}-B"
		_insert("Product Bundle", name=self.bundle, new_item_code=self.bundle)
		_insert("Product Bundle Item", parent=self.bundle, parenttype="Product Bundle",
			parentfield="items", item_code=self.comp_a, qty=1, idx=1)
		_insert("Product Bundle Item", parent=self.bundle, parenttype="Product Bundle",
			parentfield="items", item_code=self.comp_b, qty=1, idx=2)

		# Order 20 combos + 10 plain. Dispatched: 15 A + 5 B = 20 units = 10 combos
		# (the sheet's rule), and 4 plain. The scarcest-component rule would say 5 combos.
		self.combo_partial = self._so("06", "Offline", self.cust_o, items=[(self.bundle, 20), (self.plain, 10)])
		dn = _insert("Delivery Note", name=f"{t}-DN-3", docstatus=1, is_return=0,
			custom_sales_order_id=self.combo_partial, grand_total=0)
		self._dn_item(dn.name, self.bundle, 5, 1)
		self._dn_item(dn.name, self.plain, 4, 2)
		self._packed(dn.name, self.bundle, self.comp_a, 15, 1)
		self._packed(dn.name, self.bundle, self.comp_b, 5, 2)

		# Fully dispatched combo order: nothing may be reported as undispatched.
		self.combo_full = self._so("07", "Offline", self.cust_o, items=[(self.bundle, 4)])
		dn = _insert("Delivery Note", name=f"{t}-DN-4", docstatus=1, is_return=0,
			custom_sales_order_id=self.combo_full, grand_total=0)
		self._dn_item(dn.name, self.bundle, 4, 1)
		self._packed(dn.name, self.bundle, self.comp_a, 4, 1)
		self._packed(dn.name, self.bundle, self.comp_b, 4, 2)
		self.all += [self.combo_partial, self.combo_full]

	def _so(self, n, channel, customer, owner=None, items=None):
		name = f"{self.tag}-SO-{n}"
		_insert("Sales Order", name=name, docstatus=1, custom_channel=channel,
			custom_invoice_no=f"{self.tag}-INV-{n}", customer=customer, customer_name=customer,
			transaction_date=self.day, custom_dispatch_date=self.day, grand_total=1000,
			custom_total_invoice_value=900, order_type="Sales", shipping_address_name=self.addr,
			company=frappe.defaults.get_global_default("company"))
		# db_insert stamps the session user as owner, so the owner is set afterwards.
		frappe.db.set_value("Sales Order", name, "owner", owner or "Administrator", update_modified=False)
		for idx, (code, qty) in enumerate(items or [(f"{self.tag}-ITEM", 1)], start=1):
			_insert("Sales Order Item", parent=name, parenttype="Sales Order", parentfield="items",
				item_code=code, item_name=code, qty=qty, idx=idx)
		return name

	def _dn_item(self, dn, code, qty, idx):
		_insert("Delivery Note Item", parent=dn, parenttype="Delivery Note", parentfield="items",
			item_code=code, item_name=code, qty=qty, idx=idx)

	def _packed(self, dn, parent_item, code, qty, idx):
		_insert("Packed Item", parent=dn, parenttype="Delivery Note", parentfield="packed_items",
			parent_item=parent_item, item_code=code, qty=qty, idx=idx)

	def f(self, **extra):
		"""Filters scoped to this run's orders."""
		return dict(sales_order=self.tag, **extra)


def _as(user, fn):
	frappe.set_user(user)
	frappe.local.idq_catalogue = None
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.idq_catalogue = None


def _names(rows):
	return {r["sales_order"] for r in rows}


# ------------------------------------------------------------------------ run


def run():
	R.clear()
	frappe.set_user("Administrator")
	# Some code under test commits (the invoice ZIP marks orders downloaded). A commit in
	# the middle would make the fixtures permanent, so commits are ignored while it runs.
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *args, **kwargs: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		# Nothing this suite wrote survives it, including the role changes.
		frappe.db.rollback()
		for email in list(_TOUCHED_USERS):
			frappe.clear_cache(user=email)
		_TOUCHED_USERS.clear()
		frappe.set_user("Administrator")
		frappe.local.idq_catalogue = None

	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


_TOUCHED_USERS = set()


def _role_user(slug, roles):
	email = f"iqtest.{slug}@example.com"
	_TOUCHED_USERS.add(email)
	return _user(email, roles)


def _run():
	fx = Fixture()

	users = {role: _role_user(role.lower().replace(" ", "").replace("-", ""), [role]) for role in SPEC_ROLES}
	ecom_user = users["E-Commerce Coordinator"]
	sales_user = users["Sales User"]
	wh_user = users["Warehouse Manager"]
	mixed_user = _role_user("mixed", ["E-Commerce Manager", "Sales Manager"])

	# ------------------------------------------------------------ page access
	from alpinos.workflow_role_access import _setup_page_access

	_setup_page_access()

	def _every_spec_role_can_open_and_load():
		refused = []
		for role, user in users.items():
			ok_page = _as(user, lambda: frappe.get_doc("Page", Q.PAGE_ROUTE).is_permitted())
			if not ok_page:
				refused.append(f"{role}: page")
				continue
			try:
				_as(user, lambda: Q.get_rows(filters=fx.f(), page_length=5))
			except Exception as e:
				refused.append(f"{role}: rows ({type(e).__name__})")
		_assert(not refused, "refused: " + "; ".join(refused))

	check("all nine roles in the spec can open the page and load it", _every_spec_role_can_open_and_load)

	def _page_is_not_open_to_everyone():
		nobody = _role_user("nobody", ["Stock User"])
		_assert(not _as(nobody, lambda: frappe.get_doc("Page", Q.PAGE_ROUTE).is_permitted()),
			"a user with none of the roles can open the page")

	check("the page is not opened to roles outside the spec", _page_is_not_open_to_everyone)

	# ---------------------------------------------------------------- the lock
	check(
		"E-Commerce roles are locked to E-com",
		lambda: _assert(
			_as(ecom_user, Q.resolve_access) == {
				"channels": ["E-com"], "locked": True, "default": "E-com", "group": "ecom"},
			_as(ecom_user, Q.resolve_access)),
	)

	def _sales_locked_to_offline_family():
		a = _as(sales_user, Q.resolve_access)
		_assert(a["locked"] and a["default"] == "Offline", a)
		_assert(set(a["channels"]) == {"Offline", "General Trade"}, a)
		g = _as(sales_user, Q.get_access)
		_assert(g["selectable"] == ["Offline"], f"a locked user should have one option: {g['selectable']}")

	check("Sales roles are locked to Offline, General Trade included", _sales_locked_to_offline_family)

	def _unrestricted_roles():
		for role in ("Warehouse Admin", "Warehouse Manager", "Accounts User"):
			a = _as(users[role], Q.resolve_access)
			_assert(a["channels"] is None and not a["locked"], f"{role}: {a}")

	check("Warehouse and Accounts roles see every channel, unlocked", _unrestricted_roles)

	def _sales_user_sees_general_trade():
		# Exactly what the page sends: the locked default, "Offline".
		for filters in (fx.f(channel="Offline"), fx.f()):
			got = _names(_as(sales_user, lambda: Q.get_rows(filters=filters, page_length=500)["rows"]))
			_assert(fx.gt in got, f"General Trade order hidden from a Sales user ({filters})")
			_assert(fx.offline in got, "Offline order missing")
			_assert(fx.ecom not in got and fx.shared_e not in got, "E-com order served to a Sales user")

	check("a Sales user sees Offline AND General Trade orders, never E-com", _sales_user_sees_general_trade)

	def _ecom_user_sees_only_ecom():
		got = _names(_as(ecom_user, lambda: Q.get_rows(filters=fx.f(), page_length=500)["rows"]))
		_assert(got == {fx.ecom, fx.shared_e}, f"E-com user got {sorted(got)}")

	check("an E-Commerce user sees only E-com orders", _ecom_user_sees_only_ecom)

	expect_throw(
		"an E-Commerce user asking for Offline is refused, not ignored",
		lambda: _as(ecom_user, lambda: Q.get_rows(filters=fx.f(channel="Offline"))),
		"do not have access",
	)
	expect_throw(
		"a Sales user asking for E-com is refused",
		lambda: _as(sales_user, lambda: Q.get_rows(filters=fx.f(channel="E-com"))),
		"do not have access",
	)

	def _mixed_roles_see_both_and_can_choose():
		a = _as(mixed_user, Q.resolve_access)
		_assert(not a["locked"], f"a user with both restricted groups is locked: {a}")
		got = _names(_as(mixed_user, lambda: Q.get_rows(filters=fx.f(), page_length=500)["rows"]))
		_assert({fx.ecom, fx.offline, fx.gt}.issubset(got), f"mixed user got {sorted(got)}")
		only = _names(_as(mixed_user, lambda: Q.get_rows(filters=fx.f(channel="E-com"), page_length=500)["rows"]))
		_assert(only == {fx.ecom, fx.shared_e}, f"mixed user choosing E-com got {sorted(only)}")

	check("E-Commerce + Sales roles together see both channels and may choose", _mixed_roles_see_both_and_can_choose)

	def _offline_means_the_family_for_everyone():
		off = _names(_as(wh_user, lambda: Q.get_rows(filters=fx.f(channel="Offline"), page_length=500)["rows"]))
		_assert(fx.gt in off and fx.offline in off and fx.ecom not in off, sorted(off))
		gt = _names(_as(wh_user, lambda: Q.get_rows(filters=fx.f(channel="General Trade"), page_length=500)["rows"]))
		_assert(gt == {fx.gt}, f"General Trade alone got {sorted(gt)}")

	check("choosing Offline includes General Trade; General Trade alone narrows", _offline_means_the_family_for_everyone)

	# ------------------------------------------------------------- customers
	def _customer_list_follows_channel():
		sales = {r["value"] for r in _as(sales_user, lambda: Q.get_customers(search=fx.tag, limit=500))}
		_assert(fx.cust_g in sales and fx.cust_o in sales, f"Sales customers missing: {sorted(sales)}")
		_assert(fx.cust_e not in sales, "an E-com-only customer offered to a Sales user")
		link = [r[0] for r in _as(wh_user, lambda: Q.customer_link_query(
			"Customer", fx.tag, "name", 0, 50, {"channel": "E-com"}))]
		_assert(set(link) == {fx.cust_e, fx.cust_shared}, f"E-com link query offered {link}")

	check("the Customer dropdown follows the channel and the role", _customer_list_follows_channel)

	def _customer_cleared_only_when_outside_channel():
		_assert(Q.customer_in_channel(fx.cust_e, "Offline") is False, "E-com-only customer kept under Offline")
		_assert(Q.customer_in_channel(fx.cust_shared, "Offline") is True, "a customer in both channels was dropped")
		_assert(Q.customer_in_channel(fx.cust_g, "Offline") is True, "a General Trade customer dropped under Offline")

	check("changing Channel clears only a customer who is not in it", _customer_cleared_only_when_outside_channel)

	# ------------------------------------------------------- report columns
	def _dispatch_date_is_the_pick_lists():
		row = [r for r in Q.get_rows(filters=fx.f(), page_length=500)["rows"] if r["sales_order"] == fx.ecom][0]
		_assert(str(row["dispatch_date"]) == str(fx.pl_date),
			f"Dispatch Date {row['dispatch_date']} is not the Pick List's {fx.pl_date}")
		hit = _names(Q.get_rows(filters=fx.f(dispatch_date_from=fx.pl_date, dispatch_date_to=fx.pl_date))["rows"])
		_assert(hit == {fx.ecom}, f"Dispatch Date filter on the Pick List date got {sorted(hit)}")
		miss = _names(Q.get_rows(filters=fx.f(dispatch_date_from=fx.day, dispatch_date_to=fx.day))["rows"])
		_assert(fx.ecom not in miss, "the filter still matched the order's own dispatch date")

	check("Dispatch Date (column and filter) comes from the Pick List", _dispatch_date_is_the_pick_lists)

	def _pick_list_and_note_columns():
		row = [r for r in Q.get_rows(filters=fx.f(), page_length=500)["rows"] if r["sales_order"] == fx.ecom][0]
		_assert(row["transporter"] in ("T1", "T2") and row["pl_po_no"] == "PLPO-1", row)
		_assert(flt(row["total_box"]) == 3 and flt(row["weight"]) == 15, f"box/weight not summed: {row}")
		_assert(set((row["lr_number"] or "").split(", ")) == {"LR-1", "LR-2"}, row["lr_number"])
		_assert(row["state"] == "Maharashtra", row["state"])

	check("PL PO No, Transporter, Box, Weight, LR No. and State come from their documents", _pick_list_and_note_columns)

	def _undispatched_counts_units_per_the_sheet():
		rows = {r["sales_order"]: r for r in Q.get_rows(
			filters=fx.f(), columns=["sales_order", "undispatched"], page_length=500)["rows"]}
		want = f"{fx.bundle} (10), {fx.plain} (6)"
		_assert(rows[fx.combo_partial]["undispatched"] == want,
			f"partial combo: {rows[fx.combo_partial]['undispatched']!r}, expected {want!r}")
		_assert(rows[fx.combo_full]["undispatched"] == "",
			f"a fully dispatched combo order reports {rows[fx.combo_full]['undispatched']!r}")

	check("Undispatched counts combos in individual units (20 units of a 2-unit combo = 10)",
		_undispatched_counts_units_per_the_sheet)

	# ------------------------------------------------------ dynamic columns
	def _fields_from_all_four_documents():
		cat = Q.catalogue()
		for prefix, doctype in (("so", "Sales Order"), ("pl", "Pick List"), ("dn", "Delivery Note"),
		                        ("pd", "Post Dispatch")):
			if not frappe.db.exists("DocType", doctype):
				continue
			_assert(any(k.startswith(prefix + ":") for k in cat), f"no {doctype} fields offered")
		_assert("po_date" in cat, "PO Date is not available")

	check("fields from Sales Order, Pick List, Delivery Note and Post Dispatch can be added",
		_fields_from_all_four_documents)

	def _dynamic_values_roll_up():
		cols = ["sales_order", "pl:custom_transporter", "dn:grand_total"]
		if frappe.db.exists("DocType", "Post Dispatch"):
			cols.append("pd:post_delivery_status")
		row = [r for r in Q.get_rows(filters=fx.f(), columns=cols, page_length=500)["rows"]
		       if r["sales_order"] == fx.ecom][0]
		_assert(row["pl:custom_transporter"] == "T1, T2", row)
		_assert(flt(row["dn:grand_total"]) == 150, f"two notes not added: {row['dn:grand_total']}")
		if "pd:post_delivery_status" in cols:
			_assert(row["pd:post_delivery_status"] == "In Progress", row)

	check("a document field rolls up per order (text listed, amounts added)", _dynamic_values_roll_up)

	def _dynamic_columns_follow_read_access():
		for user in list(users.values()) + [mixed_user]:
			def probe():
				cat = Q.catalogue()
				for prefix, doctype in (("pl", "Pick List"), ("dn", "Delivery Note"), ("pd", "Post Dispatch")):
					if not frappe.db.exists("DocType", doctype):
						continue
					offered = any(k.startswith(prefix + ":") for k in cat)
					allowed = bool(frappe.has_permission(doctype, "read"))
					_assert(offered == allowed, f"{frappe.session.user}: {doctype} fields offered={offered}, read={allowed}")
			_as(user, probe)

	check("document fields are offered only to users who may read that document",
		_dynamic_columns_follow_read_access)

	def _crafted_columns_are_dropped():
		out = Q.get_rows(filters=fx.f(), columns=[
			"sales_order", "customer_name", "so.custom_invoice_pdf", "../etc",
			"pl:name` FROM tabUser; --", "so:custom_invoice_pdf"])
		_assert(out["columns"] == ["sales_order", "customer_name"], out["columns"])

	check("a column outside the user's catalogue is dropped, not queried", _crafted_columns_are_dropped)

	def _download_is_not_a_column():
		cat = {c["key"] for c in Q.get_columns()["available"]}
		_assert("download" not in cat, "Download is offered as a data column")

	check("Download is an action, never a data column", _download_is_not_a_column)

	# ------------------------------------------------------------- sorting
	def _sort_both_ways_on_any_column():
		for key in ("order_date", "customer_name", "pl:custom_transporter"):
			asc = [r.get(key) for r in Q.get_rows(filters=fx.f(), columns=["sales_order", key],
				sort_field=key, sort_dir="asc", page_length=500)["rows"]]
			desc = [r.get(key) for r in Q.get_rows(filters=fx.f(), columns=["sales_order", key],
				sort_field=key, sort_dir="desc", page_length=500)["rows"]]
			norm = lambda xs: [str(x or "") for x in xs]
			_assert(norm(asc) == sorted(norm(asc)), f"{key} ascending is not ascending: {asc}")
			_assert(norm(desc) == sorted(norm(desc), reverse=True), f"{key} descending: {desc}")

	check("sorting works both ways, on report and document columns", _sort_both_ways_on_any_column)

	def _owner_sorts_by_the_name_shown():
		rows = Q.get_rows(filters=fx.f(), columns=["sales_order", "owner_name"], sort_field="owner_name",
			sort_dir="asc", page_length=500)["rows"]
		names = [r["owner_name"] for r in rows if r["sales_order"] in (fx.ecom, fx.offline)]
		_assert(names == ["Abe Owner", "Zed Owner"], f"owner order {names}")

	check("Owner sorts by the person's name, not their login", _owner_sorts_by_the_name_shown)

	def _unsortable_column_falls_back():
		out = Q.get_rows(filters=fx.f(), sort_field="undispatched", page_length=5)
		_assert(out["rows"] is not None, "a computed column broke the sort")

	check("sorting on a computed column falls back instead of failing", _unsortable_column_falls_back)

	# -------------------------------------------------------------- export
	def _export_is_every_row_in_screen_order():
		cols = ["customer_name", "channel", "invoice_id"]
		original = Q.MAX_PAGE_LENGTH
		Q.MAX_PAGE_LENGTH = 2  # smaller than the fixture set, so a paged export would show
		try:
			page = Q.get_rows(filters=fx.f(), columns=cols, page_length=500)
			out = Q.export_rows(filters=fx.f(), columns=cols, sort_field="invoice_id", sort_dir="asc")
		finally:
			Q.MAX_PAGE_LENGTH = original
		_assert(len(page["rows"]) == 2, "fixture smaller than the page cap; the check proves nothing")
		_assert(len(out["rows"]) == len(fx.all), f"export has {len(out['rows'])} of {len(fx.all)} rows")
		_assert(out["header"] == ["Customer", "Channel", "Invoice Number"], out["header"])
		invs = [r[2] for r in out["rows"]]
		_assert(invs == sorted(invs), "export ignored the sort")

	check("export has every filtered row, only the on-screen columns, in order and sorted",
		_export_is_every_row_in_screen_order)

	def _export_obeys_the_lock():
		out = _as(ecom_user, lambda: Q.export_rows(filters=fx.f()))
		_assert("Download" not in out["header"], "the Download action reached the export")
		idx = out["header"].index("Channel")
		_assert({r[idx] for r in out["rows"]} == {"E-com"}, "the export leaked another channel")

	check("export obeys the channel lock and omits the Download column", _export_obeys_the_lock)

	# ------------------------------------------------------------ downloads
	expect_throw(
		"a download URL for an order outside the user's channel is refused (ZIP)",
		lambda: _as(ecom_user, lambda: Q.download_invoices_zip(frappe.as_json([fx.offline]))),
		"do not have access",
		exc=frappe.PermissionError,
	)

	def _bundle_url_refused():
		from alpinos.sales_order_api import download_order_bundle

		return _as(sales_user, lambda: download_order_bundle(frappe.as_json([fx.ecom]), parts="so"))

	expect_throw(
		"a download URL for an order outside the user's channel is refused (SO / PL / INV)",
		_bundle_url_refused, "do not have access", exc=frappe.PermissionError,
	)

	check(
		"an order inside the channel passes the download check",
		lambda: _as(sales_user, lambda: Q.assert_orders_in_channel([fx.offline, fx.gt])),
	)

	def _download_all_spans_pages_and_obeys_the_lock():
		page = Q.get_rows(filters=fx.f(), page_length=1)
		everything = Q.get_all_sales_orders(filters=fx.f())
		_assert(len(everything) == page["total"] == len(fx.all), f"{len(everything)} vs {page['total']}")
		mine = set(_as(ecom_user, lambda: Q.get_all_sales_orders(filters=fx.f())))
		_assert(mine == {fx.ecom, fx.shared_e}, f"E-com user's download set {sorted(mine)}")

	check("Download All / select-all span every page and obey the lock", _download_all_spans_pages_and_obeys_the_lock)

	# ---------------------------------------------------------- saved views
	def _view_round_trips():
		Q.save_view("IQTest View", columns=["sales_order", "pl:custom_transporter", "invoice_id"],
			filters={"customer_type": "Sales", "bogus": "x"}, sort_field="order_date", sort_dir="asc",
			is_default=1)
		v = [x for x in Q.list_views() if x["view_name"] == "IQTest View"][0]
		_assert(v["columns"] == ["sales_order", "pl:custom_transporter", "invoice_id"], v["columns"])
		_assert(v["filters"] == {"customer_type": "Sales"}, f"unknown filter key kept: {v['filters']}")
		_assert(v["sort_dir"] == "asc" and cint(v["is_default"]) == 1, v)

	check("a saved view round-trips columns, order, filters and sort", _view_round_trips)

	def _saving_the_same_name_replaces():
		Q.save_view("IQTest View", columns=["sales_order"], filters={})
		after = [v for v in Q.list_views() if v["view_name"] == "IQTest View"]
		_assert(len(after) == 1 and after[0]["columns"] == ["sales_order"], after)

	check("saving the same name replaces rather than piling up", _saving_the_same_name_replaces)

	def _views_are_per_user():
		theirs = _as(sales_user, lambda: {v["view_name"] for v in Q.list_views()})
		_assert("IQTest View" not in theirs, "another user can see my saved view")

	check("saved views are private to their owner", _views_are_per_user)

	_mine = [v for v in Q.list_views() if v["view_name"] == "IQTest View"][0]["name"]
	expect_throw(
		"deleting somebody else's view is refused",
		lambda: _as(sales_user, lambda: Q.delete_view(_mine)),
		"another user",
	)

	def _plant():
		return _as(sales_user, lambda: frappe.get_doc({
			"doctype": "Alpino Saved View", "view_name": "Planted", "page_route": Q.PAGE_ROUTE,
			"user": ecom_user, "columns_json": "[]", "filters_json": "{}", "is_default": 1,
		}).insert())

	expect_throw("a user cannot create a saved view through the API", _plant, exc=frappe.PermissionError)

	def _plant_bypassing_permissions():
		return _as(sales_user, lambda: frappe.get_doc({
			"doctype": "Alpino Saved View", "view_name": "Planted", "page_route": Q.PAGE_ROUTE,
			"user": ecom_user, "columns_json": "[]", "filters_json": "{}", "is_default": 1,
		}).insert(ignore_permissions=True))

	expect_throw("a saved view cannot be written for another user", _plant_bypassing_permissions,
		"only be saved for yourself")

	def _old_sidebar_filters_convert():
		from alpinos.patches.v1_0.invoice_queue_saved_filters_to_views import _filters

		got = _filters({"order_date": "2026-09-01", "customer": "C1", "po_date": "", "dispatch_date": "2026-09-02"})
		_assert(got == {"order_date_from": "2026-09-01", "order_date_to": "2026-09-01",
			"dispatch_date_from": "2026-09-02", "dispatch_date_to": "2026-09-02", "customer": "C1"}, got)

	check("old sidebar saved filters convert to the new date ranges", _old_sidebar_filters_convert)

	# --------------------------------------------------------- other filters
	def _remaining_filters():
		def got(**kw):
			return _names(Q.get_rows(filters=fx.f(**kw), page_length=500)["rows"])
		_assert(got(lr_number="LR-2") == {fx.ecom}, "LR No. filter")
		_assert(got(state="Maharashtra") == set(fx.all), "State filter")
		_assert(got(invoice_id=f"{fx.tag}-INV-03") == {fx.gt}, "Invoice Number filter")
		_assert(got(customer=fx.cust_g) == {fx.gt}, "Customer filter")
		_assert(got(order_date_from=add_days(fx.day, 1)) == set(), "Order Date From filter")

	check("LR No., State, Invoice Number, Customer and Order Date filters", _remaining_filters)

	# ------------------------------------------------- Changes(HP) #41 / #42
	def _page_is_renamed():
		import json, os

		path = os.path.join(frappe.get_app_path("alpinos"), "alpinos_development", "page",
			"invoice_download_queue", "invoice_download_queue.json")
		_assert(json.load(open(path))["title"] == "Order Fulfilment Report", "page title not renamed")
		_assert(frappe.db.get_value("Page", Q.PAGE_ROUTE, "title") == "Order Fulfilment Report",
			"site page title not renamed (migrate)")

	check("#41 the page is called Order Fulfilment Report", _page_is_renamed)

	def _created_by_filter():
		got = _names(Q.get_rows(filters=fx.f(created_by=fx.owner_a), page_length=500)["rows"])
		_assert(got == {fx.ecom}, f"Created By filter got {sorted(got)}")
		_assert("created_by" in Q.FILTER_KEYS, "a saved view would drop the Created By filter")
		offered = [r[0] for r in _as(sales_user, lambda: Q.creator_link_query("User", "", "name", 0, 500, {}))]
		_assert(fx.owner_z in offered, "the creator of an Offline order is not offered to a Sales user")
		_assert(fx.owner_a not in offered, "the creator of an E-com-only order is offered to a Sales user")

	check("#41 Created By filters by the order's creator, and offers only creators in the user's channels",
		_created_by_filter)

	def _undispatched_detail_for_the_popup():
		row = [r for r in Q.get_rows(filters=fx.f(), columns=["sales_order", "undispatched"], page_length=500)["rows"]
		       if r["sales_order"] == fx.combo_partial][0]
		items = [(i["item_code"], i["qty"]) for i in row["undispatched_items"]]
		_assert(items == [(fx.bundle, 10), (fx.plain, 6)], f"pop-up items {items}")
		out = Q.export_rows(filters={"sales_order": fx.combo_partial}, columns=["sales_order", "undispatched"])
		_assert(out["rows"][0][1] == f"{fx.bundle} (10), {fx.plain} (6)", f"export cell {out['rows'][0]}")

	check("#41 Undispatched carries every item for the pop-up; the export keeps the full text",
		_undispatched_detail_for_the_popup)

	def _invoice_amount_from_the_notes():
		rows = {r["sales_order"]: r for r in Q.get_rows(filters=fx.f(), page_length=500)["rows"]}
		_assert(flt(rows[fx.ecom]["invoice_amount"]) == 150,
			f"invoice amount {rows[fx.ecom]['invoice_amount']}, expected the two notes' 150")
		_assert(flt(rows[fx.ecom]["amount_diff"]) == 850, f"difference {rows[fx.ecom]['amount_diff']}")
		frappe.db.set_value("Sales Order", fx.offline, "custom_total_invoice_value", 0, update_modified=False)
		rows = {r["sales_order"]: r for r in Q.get_rows(filters=fx.f(), page_length=500)["rows"]}
		_assert(flt(rows[fx.offline]["invoice_amount"]) == 0, "an order with nothing dispatched invented an amount")
		_assert(flt(rows[fx.gt]["invoice_amount"]) == 900, "the stored value is not used before dispatch")

	check("#42 Invoice Amount comes from the submitted notes, else the order's stored value",
		_invoice_amount_from_the_notes)

	def _invoice_number_format():
		frappe.db.set_value("Sales Order", fx.gt, {"custom_invoice_no": "6055", "custom_dispatch_date": "2026-09-11"},
			update_modified=False)
		frappe.db.set_value("Sales Order", fx.offline, {"custom_invoice_no": "7001", "custom_dispatch_date": "2027-03-31"},
			update_modified=False)
		frappe.db.set_value("Sales Order", fx.shared_o, "custom_invoice_no", "AHF/25-26/99", update_modified=False)
		rows = {r["sales_order"]: r for r in Q.get_rows(filters=fx.f(), page_length=500)["rows"]}
		_assert(rows[fx.gt]["invoice_id"] == "AHF/26-27/6055", rows[fx.gt]["invoice_id"])
		_assert(rows[fx.offline]["invoice_id"] == "AHF/26-27/7001", f"31 March is still 26-27: {rows[fx.offline]['invoice_id']}")
		_assert(rows[fx.shared_o]["invoice_id"] == "AHF/25-26/99", "an already-prefixed number was changed")
		hit = _names(Q.get_rows(filters=fx.f(invoice_id="AHF/26-27/6055"), page_length=500)["rows"])
		_assert(hit == {fx.gt}, f"searching the displayed number found {sorted(hit)}")
		_assert(_names(Q.get_rows(filters=fx.f(invoice_id="6055"), page_length=500)["rows"]) == {fx.gt},
			"searching the bare number no longer works")

	check("#42 Invoice Number shows as AHF/<FY>/<number> and can be searched either way", _invoice_number_format)
