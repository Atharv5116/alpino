"""Remove what the committing purchase test suites leave on a site.

task_functional_test (and the older e2e / regression suites) commit on purpose, so every
run leaves real Purchase Orders, inwards, QCs, GRNs, invoices, stock and accounting
entries, TFT- items and tft- users behind, plus the bell / Raven / email alerts those
documents raised. On a shared site those show up in every list next to real work.

Everything is found by what only a test creates, never by date alone:

    documents   supplier = TEST_SUPPLIER (Stock Entries: every line is a TEST_ITEM_PREFIX item)
    items       name starts with TEST_ITEM_PREFIX
    users       name starts with TEST_USER_PREFIX

and a voucher that carries any non-test item aborts the whole purge rather than delete a
real stock or accounting row. Alerts are matched by the document names they mention.

    from alpinos.purchase.test_cleanup import purge
    purge()                  # dry run: counts only
    purge(dry_run=False)     # delete, and commit
"""

import re

import frappe
from frappe.utils import add_to_date, cint, get_datetime

TEST_SUPPLIER = "PITEST Supplier 001"
TEST_ITEM_PREFIX = "TFT-"
TEST_USER_PREFIX = "tft-"

# Deleted in this order: every document goes before the documents it was made from.
VOUCHERS = (
	("Payment Entry", "party"),
	("Purchase Invoice", "supplier"),
	("Purchase Receipt", "supplier"),
	("Stock Entry", None),
	("Purchase QC", "supplier"),
	("Purchase Quarantine", "supplier"),
	("Purchase Inward", "supplier"),
	("Purchase Order", "supplier"),
)
ITEM_TABLES = {
	"Purchase Invoice": "Purchase Invoice Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Stock Entry": "Stock Entry Detail",
	"Purchase Order": "Purchase Order Item",
}
LEDGERS = (
	("GL Entry", "voucher_no"),
	("Stock Ledger Entry", "voucher_no"),
	("Payment Ledger Entry", "voucher_no"),
	("Payment Ledger Entry", "against_voucher_no"),
	("Repost Item Valuation", "voucher_no"),
	("Serial and Batch Bundle", "voucher_no"),
)
# Raven push failures and mail-flush failures are raised by the alerts, not the documents.
ALERT_ERROR_METHODS = ("Raven Cloud Push Notification Error", "Raven approval DM")


def purge(dry_run=True, supplier=TEST_SUPPLIER):
	report = {"dry_run": bool(dry_run), "documents": {}, "other": {}, "errors": []}
	scope = _voucher_scope(supplier)
	_assert_only_test_items(scope)

	names = sorted({n for rows in scope.values() for n in rows})
	for dt, rows in scope.items():
		report["documents"][dt] = len(rows)

	window = _window(scope)
	items = frappe.get_all("Item", filters={"name": ("like", TEST_ITEM_PREFIX + "%")}, pluck="name")
	users = frappe.get_all("User", filters={"name": ("like", TEST_USER_PREFIX + "%")}, pluck="name")
	report["documents"]["Item"] = len(items)
	report["documents"]["User"] = len(users)

	alerts = _alert_scope(names, window)
	for key, rows in alerts.items():
		report["other"][key] = len(rows)

	if dry_run:
		return report

	for dt, _field in VOUCHERS:
		for name in scope.get(dt, []):
			_delete_voucher(dt, name, report)

	_delete_where("Comment", "reference_name", names)
	_delete_where("Version", "docname", names)
	_delete_where("Access Log", "reference_document", names)
	_delete_where("Error Log", "reference_name", names)
	_delete_where("Notification Log", "name", alerts["Notification Log"])
	_delete_where("Raven Message", "name", alerts["Raven Message"])
	_delete_where("Email Queue Recipient", "parent", alerts["Email Queue"])
	_delete_where("Error Log", "reference_name", alerts["Email Queue"])
	_delete_where("Email Queue", "name", alerts["Email Queue"])
	_delete_where("Error Log", "name", alerts["Error Log"])
	# Only files attached to a test voucher, matched on doctype AND name. This used to filter
	# on attached_to_name alone, with `names or [""]` when no voucher was found -- and Frappe
	# turns "in ('')" into ifnull(attached_to_name, '') in (''), which matched EVERY file not
	# attached to anything: a purge that only removed a tft- user deleted 29 real uploads.
	if names:
		for file_name in frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": ("in", [dt for dt, _field in VOUCHERS]),
				"attached_to_name": ("in", names),
			},
			pluck="name",
		):
			_try(report, "File", file_name, lambda n=file_name: frappe.delete_doc(
				"File", n, force=True, ignore_permissions=True, delete_permanently=True))

	for item in items:
		_delete_where("Bin", "item_code", [item])
		_delete_where("Item Price", "item_code", [item])
		_try(report, "Item", item, lambda n=item: frappe.delete_doc(
			"Item", n, force=True, ignore_permissions=True, delete_permanently=True))

	for user in users:
		_delete_user(user, report)
	frappe.db.sql(
		"DELETE FROM `tabDeleted Document` WHERE owner LIKE %s", (TEST_USER_PREFIX + "%",)
	)

	report["series"] = _rewind_series(scope)
	frappe.db.commit()
	return report


# ------------------------------------------------------------------ scope


def _voucher_scope(supplier):
	scope = {}
	for dt, field in VOUCHERS:
		if not frappe.db.table_exists(dt):
			continue
		if field:
			scope[dt] = frappe.get_all(dt, filters={field: supplier}, pluck="name")
		else:
			scope[dt] = frappe.db.sql_list(
				"""SELECT DISTINCT parent FROM `tabStock Entry Detail`
				WHERE item_code LIKE %s""",
				(TEST_ITEM_PREFIX + "%",),
			)
	return scope


def _assert_only_test_items(scope):
	"""A voucher with a real item on it would take real stock or ledger rows with it."""
	offenders = []
	for dt, child in ITEM_TABLES.items():
		if not scope.get(dt):
			continue
		rows = frappe.db.sql(
			f"""SELECT DISTINCT parent, item_code FROM `tab{child}`
			WHERE parent IN %(names)s AND item_code NOT LIKE %(prefix)s""",
			{"names": scope[dt], "prefix": TEST_ITEM_PREFIX + "%"},
		)
		offenders += [(dt, parent, item) for parent, item in rows]
	if offenders:
		frappe.throw(
			"Refusing to purge: these test vouchers carry non-test items: {0}".format(offenders[:10])
		)


def _window(scope):
	stamps = []
	for dt, rows in scope.items():
		if rows:
			stamps += frappe.db.sql_list(
				f"SELECT MIN(creation) FROM `tab{dt}` WHERE name IN %(n)s UNION ALL "
				f"SELECT MAX(modified) FROM `tab{dt}` WHERE name IN %(n)s",
				{"n": rows},
			)
	stamps = [get_datetime(s) for s in stamps if s]
	if not stamps:
		return None
	return add_to_date(min(stamps), minutes=-1), add_to_date(max(stamps), hours=1)


def _alert_scope(names, window):
	"""Alerts that name a test document, raised while the test documents existed."""
	out = {"Notification Log": [], "Raven Message": [], "Email Queue": [], "Error Log": []}
	if not names or not window:
		return out
	pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
	start, end = window

	out["Notification Log"] = frappe.get_all(
		"Notification Log", filters={"document_name": ("in", names)}, pluck="name"
	)
	for dt, field in (("Raven Message", "text"), ("Email Queue", "message")):
		if not frappe.db.table_exists(dt):
			continue
		rows = frappe.db.sql(
			f"SELECT name, `{field}` FROM `tab{dt}` WHERE creation BETWEEN %s AND %s", (start, end)
		)
		out[dt] = [name for name, body in rows if body and pattern.search(body)]
	out["Error Log"] = frappe.get_all(
		"Error Log",
		filters={"creation": ("between", [start, end]), "method": ("in", ALERT_ERROR_METHODS)},
		pluck="name",
	)
	out["Error Log"] += frappe.get_all(
		"Error Log", filters={"owner": ("like", TEST_USER_PREFIX + "%")}, pluck="name"
	)
	return out


# ----------------------------------------------------------------- delete


def _delete_voucher(dt, name, report):
	for ledger, field in LEDGERS:
		if frappe.db.table_exists(ledger):
			frappe.db.sql(f"DELETE FROM `tab{ledger}` WHERE `{field}` = %s", (name,))
	# delete_doc refuses a submitted record; a test voucher is removed, not reversed, so
	# its ledger rows are gone above and it is simply marked cancelled first.
	if cint(frappe.db.get_value(dt, name, "docstatus")) == 1:
		frappe.db.sql(f"UPDATE `tab{dt}` SET docstatus = 2 WHERE name = %s", (name,))
	_try(report, dt, name, lambda: frappe.delete_doc(
		dt, name, force=True, ignore_permissions=True, ignore_on_trash=True, delete_permanently=True))


def _delete_user(user, report):
	for dt, field in (("Contact", "user"), ("Notification Settings", "name"), ("DocShare", "user"),
	                  ("Raven Channel Member", "user_id"), ("Raven User", "user")):
		if frappe.db.table_exists(dt):
			frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE `{field}` = %s", (user,))
	if frappe.db.table_exists("Raven Channel"):
		for channel in frappe.db.sql_list(
			"SELECT name FROM `tabRaven Channel` WHERE is_direct_message = 1 AND channel_name LIKE %s",
			(user + "%",),
		):
			frappe.db.sql("DELETE FROM `tabRaven Message` WHERE channel_id = %s", (channel,))
			frappe.db.sql("DELETE FROM `tabRaven Channel Member` WHERE channel_id = %s", (channel,))
			frappe.db.sql("DELETE FROM `tabRaven Channel` WHERE name = %s", (channel,))
	_try(report, "User", user, lambda: frappe.delete_doc(
		"User", user, force=True, ignore_permissions=True, delete_permanently=True))


def _delete_where(dt, field, values):
	if values and frappe.db.table_exists(dt):
		frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE `{field}` IN %(v)s", {"v": list(values)})


def _try(report, dt, name, fn):
	savepoint = "purge_" + frappe.generate_hash(length=8)
	frappe.db.savepoint(savepoint)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=savepoint)
		report["errors"].append((dt, name, f"{type(e).__name__}: {e}"[:200]))


def _rewind_series(scope):
	"""Give the deleted numbers back when nothing real was numbered after them."""
	changed = {}
	for dt, rows in scope.items():
		for name in rows:
			match = re.match(r"^(.*?)(\d+)$", name)
			if not match or "-" in name[match.end(1):]:
				continue
			prefix, digits = match.group(1), match.group(2)
			if prefix in changed:
				continue
			current = frappe.db.get_value("Series", prefix, "current", order_by="name")
			if current is None:
				continue
			remaining = frappe.db.sql_list(
				f"SELECT name FROM `tab{dt}` WHERE name LIKE %s", (prefix + "%",)
			)
			numbers = [
				int(m.group(1)) for m in (re.match(re.escape(prefix) + r"(\d+)", n) for n in remaining) if m
			]
			top = max(numbers) if numbers else 0
			if cint(current) > top:
				frappe.db.sql("UPDATE `tabSeries` SET current = %s WHERE name = %s", (top, prefix))
				changed[prefix] = (cint(current), top)
	return changed
