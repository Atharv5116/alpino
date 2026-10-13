"""Bulk invoice resync: queued, and one Drive client for the batch.

Run:  bench --site alpinos.test execute alpinos.invoice_resync_bulk_test.run

Reported 13-10: resyncing invoices in bulk times out. It ran the whole selection inside the
HTTP request, and each order rebuilt the Drive client and re-resolved <root>/<FY>/<Month>
from a fresh cache. Serially that passes the gateway timeout, so the user sees a 504 while
the job is still running -- the worst shape of failure, because the work is half done and
nothing says so.

Two fixes, two sets of checks. A selection beyond a quick handful is queued, as the Excel
path already did for the same reason. And the batch builds one Drive client and shares one
folder cache, instead of one of each per order.

Drive is not configured on the test site, so the Drive calls are stood in for -- that is
also what lets the client be COUNTED, which is the point of the second half.
"""

import frappe

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _refused(fn):
	try:
		fn()
		return False
	except (frappe.ValidationError, frappe.PermissionError):
		return True


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import invoice_sync as S

	tag = "RSY" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")

	def _so(i):
		name = f"SO-{tag}-{i}"
		doc = frappe.get_doc({
			"doctype": "Sales Order", "name": name, "docstatus": 1, "company": company,
			"customer": "Cust", "custom_invoice_no": f"1000{i}",
		})
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_validate = True
		doc.db_insert()
		return name

	orders = [_so(i) for i in range(6)]

	# ---- stand-ins for Drive, and a record of how often each is used ----
	calls = {"service": 0, "fetch": 0, "caches": []}
	real = {
		"drive_enabled": S._drive_enabled,
		"drive_service": S._drive_service,
		"fetch": S._fetch_invoice_pdf,
		"enqueue": frappe.enqueue,
	}

	def fake_service(s):
		calls["service"] += 1
		return object()

	def fake_fetch(drive, s, so_id, invoice_no, folder_cache, ext=None):
		calls["fetch"] += 1
		calls["caches"].append(id(folder_cache))
		return f"/files/{invoice_no}.pdf", None

	queued = []

	def fake_enqueue(method, **kwargs):
		queued.append({"method": method, **kwargs})

	S._drive_enabled = lambda s: True
	S._drive_service = fake_service
	S._fetch_invoice_pdf = fake_fetch
	frappe.enqueue = fake_enqueue

	try:
		def _a_large_selection_is_queued():
			"""The reported fault: it ran inline and the gateway gave up."""
			queued.clear()
			out = S.resync_invoices_bulk(orders)          # 6 > RESYNC_INLINE_LIMIT
			_assert(out.get("queued") is True, f"not queued: {out}")
			_assert(len(queued) == 1, f"expected one job, got {len(queued)}")
			job = queued[0]
			_assert(job["method"] == "alpinos.invoice_sync._run_resync_bulk", job["method"])
			_assert(job.get("queue") == "long", f"queue is {job.get('queue')!r}")
			_assert(int(job.get("timeout") or 0) >= 600,
				f"timeout {job.get('timeout')} is too short for a Drive fetch per order")

		check("a large selection is queued, not run in the request",
			_a_large_selection_is_queued)

		def _the_reply_says_where_to_look():
			queued.clear()
			out = S.resync_invoices_bulk(orders)
			msg = out.get("message") or ""
			_assert("background" in msg.lower(), msg)
			_assert("Invoice Sync Log" in msg,
				f"the reply does not say where the results land: {msg!r}")

		check("the queued reply names the Invoice Sync Log", _the_reply_says_where_to_look)

		def _a_handful_still_runs_inline():
			"""Two orders is quicker done than queued, and the user gets the counts."""
			queued.clear()
			out = S.resync_invoices_bulk(orders[:2])
			_assert(out.get("queued") is False, f"a small selection was queued: {out}")
			_assert(not queued, "a job was enqueued for a small selection")
			_assert(out.get("success") == 2, out)

		check("a handful still runs inline and returns its counts",
			_a_handful_still_runs_inline)

		def _one_drive_client_for_the_whole_batch():
			"""The other half of the timeout.

			Every order used to build its own client, which is a credential exchange and a
			client construction each time. Six orders, one client.
			"""
			calls["service"] = 0
			S._run_resync_bulk(orders)
			_assert(calls["service"] == 1,
				f"built the Drive client {calls['service']} times for {len(orders)} orders")

		check("the batch builds one Drive client, not one per order",
			_one_drive_client_for_the_whole_batch)

		def _one_folder_cache_for_the_whole_batch():
			"""Each order used to pass an empty cache, so the same month folder was
			re-resolved over the network for every order."""
			calls["caches"] = []
			S._run_resync_bulk(orders)
			_assert(len(set(calls["caches"])) == 1,
				f"{len(set(calls['caches']))} different folder caches across one batch")

		check("the batch shares one folder cache across its orders",
			_one_folder_cache_for_the_whole_batch)

		def _one_bad_order_does_not_stop_the_rest():
			def sometimes_fails(drive, s, so_id, invoice_no, folder_cache, ext=None):
				if so_id == orders[2]:
					raise Exception("Drive said no")
				return f"/files/{invoice_no}.pdf", None

			S._fetch_invoice_pdf = sometimes_fails
			try:
				out = S._run_resync_bulk(orders)
			finally:
				S._fetch_invoice_pdf = fake_fetch
			_assert(out["failed"] >= 1, out)
			_assert(out["success"] == len(orders) - 1,
				f"one failure took others with it: {out['success']} of {len(orders) - 1}")

		check("one order failing does not stop the batch", _one_bad_order_does_not_stop_the_rest)

		def _an_empty_selection_is_refused():
			_assert(_refused(lambda: S.resync_invoices_bulk([])), "an empty selection was accepted")

		check("an empty selection is refused", _an_empty_selection_is_refused)

		def _the_permission_check_still_bites():
			"""Queueing must not become a way around the role check."""
			user = frappe.db.get_value("User",
				{"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]}, "name")
			if not user:
				raise AssertionError("no ordinary User on this site to check with")
			frappe.set_user(user)
			try:
				roles = set(frappe.get_roles())
				if S._INVOICE_RESYNC_ROLES & roles:
					RES.append(("SKIP", "the permission check still bites",
						f"{user} holds a resync role"))
					return
				_assert(_refused(lambda: S.resync_invoices_bulk(orders)),
					"a user without the role was allowed to queue a resync")
			finally:
				frappe.set_user("Administrator")

		check("the permission check still bites before anything is queued",
			_the_permission_check_still_bites)

	finally:
		S._drive_enabled = real["drive_enabled"]
		S._drive_service = real["drive_service"]
		S._fetch_invoice_pdf = real["fetch"]
		frappe.enqueue = real["enqueue"]
