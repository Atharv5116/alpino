"""Bulk Sales Order PDF download (30 Oct 2026). Run on a TEST site that has submitted orders:

	bench --site <test site> execute alpinos.so_pdf_zip_test.run

A PDF takes 1 to 2.5 seconds and nginx / gunicorn stop a request at 120 seconds, so 100
orders timed out (504). More than SO_ZIP_INLINE_LIMIT orders now go to a background job that
saves the ZIP as the user's private File and leaves a notification with its link.

The PDFs themselves are stand-ins unless real_pdfs=1 is passed: what is under test is the
queue, the file, the notification and who may open it, not wkhtmltopdf.
"""

import zipfile
from io import BytesIO

import frappe
from frappe.utils import add_days, now_datetime

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({
			"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}).insert(ignore_permissions=True)
	return email


def run(real_pdfs=0):
	from alpinos import sales_order_api as S

	real_get_print = frappe.get_print
	if not int(real_pdfs):
		frappe.get_print = lambda doctype, name, *args, **kwargs: b"%PDF-1.4 stand-in for " + str(name).encode()
	try:
		return _run(S)
	finally:
		frappe.get_print = real_get_print


def _run(S):
	R.clear()
	frappe.set_user("Administrator")
	names = frappe.get_all("Sales Order", {"docstatus": 1}, pluck="name", order_by="creation desc", limit=S.SO_ZIP_INLINE_LIMIT + 5)
	if len(names) <= S.SO_ZIP_INLINE_LIMIT:
		R.append(("ERROR", "fixtures", "this site needs more than {0} submitted Sales Orders".format(S.SO_ZIP_INLINE_LIMIT)))
		return _report()

	def _direct_refuses_a_large_selection():
		try:
			S.download_sales_orders_zip(frappe.as_json(names))
		except frappe.ValidationError as e:
			_assert("Reload the list" in str(e), str(e))
			return
		raise AssertionError("a selection over the limit was rendered in the request")

	check("the direct download refuses more orders than one request can render", _direct_refuses_a_large_selection)

	queued = []
	real_enqueue = frappe.enqueue
	frappe.enqueue = lambda method, **kw: queued.append((method, kw))
	try:
		out = S.queue_sales_orders_zip(frappe.as_json(names))
	finally:
		frappe.enqueue = real_enqueue
	check("a large selection is queued on the long queue", lambda: _assert(
		out == {"queued": len(names)} and queued and queued[0][0] == "alpinos.sales_order_api.build_sales_orders_zip"
		and queued[0][1]["queue"] == "long" and queued[0][1]["names"] == names, (out, queued)))

	user = _user("pdfzip.salesuser@example.com", ["Sales User", "Sales Manager"])
	other = _user("pdfzip.other@example.com", ["Sales User"])
	frappe.set_user(user)
	started = now_datetime()
	S.build_sales_orders_zip(names)
	frappe.set_user("Administrator")

	note = frappe.get_all("Notification Log", {"for_user": user, "creation": (">=", started)},
		["subject", "link", "type"], order_by="creation desc", limit=1)
	f = frappe.get_all("File", {"file_url": note[0].link}, ["name", "owner", "is_private", "file_url"]) if note and note[0].link else []
	check("the job leaves a notification with the download link", lambda: _assert(
		note and note[0].type == "Alert" and note[0].link.startswith("/private/files/" + S.SO_ZIP_PREFIX), note))
	check("the ZIP is a private file of the user who asked", lambda: _assert(
		f and f[0].is_private and f[0].owner == user, f))

	def _zip_has_every_order():
		content = frappe.get_doc("File", f[0].name).get_content()
		with zipfile.ZipFile(BytesIO(content)) as zf:
			got = sorted(n[:-4] for n in zf.namelist())
		_assert(got == sorted(n.replace("/", "-") for n in names), got)

	check("the ZIP holds one PDF per order", _zip_has_every_order)
	check("another user cannot open it", lambda: _assert(
		frappe.has_permission("File", "read", doc=f[0].name, user=user)
		and not frappe.has_permission("File", "read", doc=f[0].name, user=other)))

	frappe.db.set_value("File", f[0].name, "creation", add_days(now_datetime(), -2), update_modified=False)
	S._delete_old_sales_order_zips()
	check("ZIPs older than a day are deleted", lambda: _assert(not frappe.db.exists("File", f[0].name)))

	return _report()


def _report():
	width = max((len(r[1]) for r in R), default=10)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R
