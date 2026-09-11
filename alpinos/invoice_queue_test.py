"""Invoice Download Queue: channel access, filters, sorting, columns, export.

Run:  bench --site alpinos.test execute alpinos.invoice_queue_test.run

The access checks are the point. A role lock that only hides a filter on screen is
not a lock, so every one of these drives the SERVER entry points as a real user.
"""

import frappe
from frappe.utils import cint

from alpinos import invoice_queue_api as Q

R = []


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
			R.append(("FAIL", label, f"threw, but lacked {fragment!r}: {msg[:160]}"))
		else:
			R.append(("PASS", label, ""))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _user(email, role):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User",
		}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	have = {r.role for r in u.roles}
	for r in (role, "Sales User" if role != "Sales User" else "Sales Manager"):
		pass
	if role not in have:
		u.append("roles", {"role": role})
		u.save(ignore_permissions=True)
	return email


def _seed_invoiced_order(channel):
	"""An order in `channel` carrying an invoice number, so the queue has a row."""
	name = frappe.db.get_value(
		"Sales Order",
		{"custom_channel": channel, "docstatus": ("<", 2)},
		"name",
		order_by="creation desc",
	)
	if not name:
		return None
	if not frappe.db.get_value("Sales Order", name, "custom_invoice_no"):
		frappe.db.set_value(
			"Sales Order", name, "custom_invoice_no", f"IQTEST-{channel}-001",
			update_modified=False,
		)
	return name


def run():
	R.clear()
	frappe.set_user("Administrator")
	ecom_so = _seed_invoiced_order("E-com")
	offline_so = _seed_invoiced_order("Offline")
	frappe.db.commit()

	# ---------------------------------------------------------------- access
	def _unrestricted_sees_everything():
		frappe.set_user("Administrator")
		a = Q.resolve_access()
		_assert(a["channels"] is None, a)
		_assert(a["locked"] is False, a)

	check("an unrestricted user is not locked to a channel", _unrestricted_sees_everything)

	ecom_user = _user("iqtest.ecom@example.com", "E-Commerce Coordinator")
	sales_user = _user("iqtest.sales@example.com", "Sales User")
	wh_user = _user("iqtest.wh@example.com", "Warehouse Manager")
	frappe.db.commit()

	def _as(user, fn):
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	check(
		"an E-Commerce role is locked to E-com",
		lambda: _assert(
			_as(ecom_user, Q.resolve_access) == {
				"channels": ["E-com"], "locked": True, "default": "E-com", "group": "ecom"
			},
			_as(ecom_user, Q.resolve_access),
		),
	)
	check(
		"a Sales role is locked to the offline channels, General Trade included",
		lambda: _assert(
			_as(sales_user, Q.resolve_access)["channels"] == ["Offline", "General Trade"],
			_as(sales_user, Q.resolve_access),
		),
	)
	check(
		"a Warehouse role is unrestricted",
		lambda: _assert(_as(wh_user, Q.resolve_access)["locked"] is False,
			_as(wh_user, Q.resolve_access)),
	)

	# ------------------------------------------------- the lock is on the DATA
	def _ecom_cannot_read_offline_rows():
		rows = _as(ecom_user, lambda: Q.get_rows(page_length=500)["rows"])
		bad = [r for r in rows if r.get("channel") != "E-com"]
		_assert(not bad, f"an E-Commerce user was served {len(bad)} non-E-com rows")

	check("an E-Commerce user is served only E-com rows", _ecom_cannot_read_offline_rows)

	def _sales_cannot_read_ecom_rows():
		rows = _as(sales_user, lambda: Q.get_rows(page_length=500)["rows"])
		bad = [r for r in rows if r.get("channel") == "E-com"]
		_assert(not bad, f"a Sales user was served {len(bad)} E-com rows")

	check("a Sales user is served no E-com rows", _sales_cannot_read_ecom_rows)

	expect_throw(
		"asking for a channel outside the allowance is refused, not ignored",
		lambda: _as(ecom_user, lambda: Q.get_rows(filters={"channel": "Offline"})),
		"do not have access",
	)

	def _export_obeys_the_same_lock():
		out = _as(ecom_user, lambda: Q.export_rows(filters={}))
		_assert("Download" not in out["header"], "the Download action reached the export")
		idx = out["header"].index("Channel") if "Channel" in out["header"] else None
		_assert(idx is not None, out["header"])
		bad = [r for r in out["rows"] if r[idx] != "E-com"]
		_assert(not bad, "the export leaked rows the screen would have hidden")

	check("export obeys the channel lock and omits the Download column", _export_obeys_the_same_lock)

	def _customer_dropdown_obeys_the_lock():
		rows = _as(ecom_user, lambda: Q.get_customers())
		names = {r["value"] for r in rows}
		offline_customers = {
			c.customer for c in frappe.get_all(
				"Sales Order", filters={"custom_channel": "Offline"}, fields=["customer"]
			)
		}
		leaked = names.intersection(offline_customers - _ecom_customers())
		_assert(not leaked, f"offline-only customers offered to an E-com user: {list(leaked)[:3]}")

	check("the Customer dropdown obeys the channel lock", _customer_dropdown_obeys_the_lock)

	# ------------------------------------------------------------- columns
	def _unknown_column_is_dropped():
		out = Q.get_rows(columns=["sales_order", "customer_name", "so.custom_invoice_pdf", "../etc"])
		_assert(out["columns"] == ["sales_order", "customer_name"], out["columns"])

	check("a column outside the catalogue is dropped, not queried", _unknown_column_is_dropped)

	def _download_is_not_a_column():
		_assert("download" not in Q.COLUMNS, "Download is selectable, so it could be exported")
		cat = {c["key"] for c in Q.get_columns()["available"]}
		_assert("download" not in cat, "Download is offered as a data column")

	check("Download is an action, never a data column", _download_is_not_a_column)

	# ------------------------------------------------------------- sorting
	def _sort_both_ways():
		asc = Q.get_rows(sort_field="order_date", sort_dir="asc", page_length=200)["rows"]
		desc = Q.get_rows(sort_field="order_date", sort_dir="desc", page_length=200)["rows"]
		if len(asc) < 2:
			return
		a = [r["order_date"] for r in asc if r.get("order_date")]
		d = [r["order_date"] for r in desc if r.get("order_date")]
		_assert(a == sorted(a), "ascending sort is not ascending")
		_assert(d == sorted(d, reverse=True), "descending sort is not descending")

	check("sorting works in both directions", _sort_both_ways)

	def _unsortable_column_falls_back():
		out = Q.get_rows(sort_field="undispatched", page_length=5)
		_assert(out["rows"] is not None, "a computed column broke the sort")

	check("sorting on a computed column falls back instead of failing", _unsortable_column_falls_back)

	# ----------------------------------------------------------- undispatched
	def _undispatched_counts_in_component_units():
		rows = Q.get_rows(columns=["sales_order", "undispatched"], page_length=50)["rows"]
		_assert(any("undispatched" in r for r in rows), "the column was not attached")

	check("undispatched quantity is computed per row", _undispatched_counts_in_component_units)

	# ------------------------------------------------------------ saved views
	def _view_round_trips():
		Q.save_view(
			"IQTest View",
			columns=["sales_order", "customer_name", "invoice_id"],
			filters={"customer_type": "Amazon"},
			sort_field="order_date", sort_dir="asc", is_default=1,
		)
		views = [v for v in Q.list_views() if v["view_name"] == "IQTest View"]
		_assert(views, "the view did not come back")
		v = views[0]
		_assert(v["columns"] == ["sales_order", "customer_name", "invoice_id"], v["columns"])
		_assert(v["filters"] == {"customer_type": "Amazon"}, v["filters"])
		_assert(v["sort_dir"] == "asc", v["sort_dir"])
		_assert(cint(v["is_default"]) == 1, "default flag lost")

	check("a saved view round-trips columns, order, filters and sort", _view_round_trips)

	def _saving_the_same_name_replaces():
		before = len([v for v in Q.list_views() if v["view_name"] == "IQTest View"])
		Q.save_view("IQTest View", columns=["sales_order"], filters={})
		after = [v for v in Q.list_views() if v["view_name"] == "IQTest View"]
		_assert(before == 1 and len(after) == 1, f"{before} -> {len(after)} copies")
		_assert(after[0]["columns"] == ["sales_order"], after[0]["columns"])

	check("saving the same name replaces rather than piling up", _saving_the_same_name_replaces)

	def _a_view_cannot_smuggle_a_column():
		"""A saved view is user input like any other, so it goes through the catalogue."""
		Q.save_view("IQTest Sneaky", columns=["sales_order", "so.custom_invoice_pdf"])
		v = [x for x in Q.list_views() if x["view_name"] == "IQTest Sneaky"][0]
		_assert(v["columns"] == ["sales_order"], v["columns"])
		Q.delete_view(v["name"])

	check("a saved view cannot store a column outside the catalogue", _a_view_cannot_smuggle_a_column)

	def _views_are_per_user():
		mine = {v["view_name"] for v in Q.list_views()}
		theirs = _as(sales_user, lambda: {v["view_name"] for v in Q.list_views()})
		_assert("IQTest View" in mine, "my own view is missing")
		_assert("IQTest View" not in theirs, "another user can see my saved view")

	check("saved views are private to their owner", _views_are_per_user)

	# Resolve the target BEFORE switching user: a helper that flips back to
	# Administrator inside the lambda would delete as Administrator and prove nothing.
	_mine = [v for v in Q.list_views() if v["view_name"] == "IQTest View"][0]["name"]

	expect_throw(
		"deleting somebody else view is refused",
		lambda: _as(sales_user, lambda: Q.delete_view(_mine)),
		"another user",
	)

	# --------------------------------------------- download set spans all pages
	def _download_all_is_not_just_the_page():
		"""The queue is paged now; Download All must still mean every filtered row."""
		page = Q.get_rows(page_length=1)
		everything = Q.get_all_sales_orders()
		_assert(len(page["rows"]) <= 1, "page size ignored")
		_assert(
			len(everything) == page["total"],
			f"all-orders {len(everything)} != filtered total {page['total']}",
		)

	check("Download All spans every page, not the one on screen", _download_all_is_not_just_the_page)

	def _download_set_obeys_the_channel_lock():
		names = _as(ecom_user, lambda: Q.get_all_sales_orders())
		bad = [
			n for n in names
			if frappe.db.get_value("Sales Order", n, "custom_channel") != "E-com"
		]
		_assert(not bad, f"the download set leaked {len(bad)} other-channel orders")

	check("the Download All set obeys the channel lock too", _download_set_obeys_the_channel_lock)

	for v in Q.list_views():
		if v["view_name"].startswith("IQTest"):
			Q.delete_view(v["name"])

	frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _ecom_customers():
	return {
		c.customer for c in frappe.get_all(
			"Sales Order", filters={"custom_channel": "E-com"}, fields=["customer"]
		)
	}
