"""Club Download (SO + Invoice, SO + PL + Invoice) of many orders, built in the background.

The Order Fulfilment Report's club download makes one Sales Order PDF (and Pick List PDF) per
order. Inside a web request that stops at 120 s: 92 orders of SO + Invoice timed out on live on
19 Nov 2026. So above SYNC_LIMIT orders the page calls start(), a long-queue job builds the
same ZIP with the same code (sales_order_api.build_bundle), saves it as a private File of the
user, and tells the user it is ready: a realtime event the page turns into a Download button,
and a bell notification for when they have moved on. The files are removed after KEEP_DAYS.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

# orders a request still builds itself; keep in step with BUNDLE_SYNC_LIMIT in the page
SYNC_LIMIT = 10
EVENT = "order_bundle_ready"
FILE_PREFIX = "order-bundle-"
KEEP_DAYS = 2


def _renders(wanted):
	"""Only the Sales Order and Pick List parts are made as PDFs; the invoice is a stored file."""
	return any(p in ("so", "pl") for p in wanted)


@frappe.whitelist()
def start(names, parts="so,invoice", no_letterhead=0):
	"""{"mode": "direct"} when the request can build it (the page then downloads as before),
	else the job is queued: {"mode": "queued", "count": n}."""
	from alpinos.invoice_queue_api import assert_orders_in_channel
	from alpinos.sales_order_api import bundle_wanted

	if isinstance(names, str):
		names = json.loads(names) if names else []
	names = [n for n in (names or []) if n]
	if not names:
		frappe.throw(_("Please select at least one Sales Order."))
	assert_orders_in_channel(names)
	wanted = bundle_wanted(parts)
	if not _renders(wanted) or len(names) <= SYNC_LIMIT:
		return {"mode": "direct"}
	frappe.enqueue(
		"alpinos.order_bundle_job.build",
		queue="long",
		timeout=3600,
		names=names,
		parts=",".join(wanted),
		no_letterhead=cint(no_letterhead),
	)
	return {"mode": "queued", "count": len(names)}


def build(names, parts, no_letterhead=0):
	"""The job (runs as the user who asked, so the same read permission applies per order)."""
	from alpinos.sales_order_api import build_bundle, bundle_wanted, bundle_zip

	user = frappe.session.user
	wanted = bundle_wanted(parts)
	label = " + ".join({"so": "SO", "pl": "PL", "invoice": "Invoice"}[p] for p in wanted)
	try:
		built, _skipped, incomplete = build_bundle(names, wanted, no_letterhead)
		# the invoice part stamps custom_invoice_downloaded, as the direct download does
		frappe.db.commit()
		if not built:
			_tell(user, None, _("{0} download: nothing could be generated for the {1} orders.").format(label, len(names)), incomplete)
			return
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "{0}{1}-{2}-{3}.zip".format(FILE_PREFIX, "-".join(wanted), len(names), frappe.generate_hash(length=6)),
			"is_private": 1,
			"content": bundle_zip(built),
		})
		file_doc.save(ignore_permissions=True)
		frappe.db.commit()
		_tell(user, file_doc, _("{0} download of {1} orders is ready.").format(label, len(names)), incomplete)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Club download failed ({0} orders)".format(len(names)))
		_tell(user, None, _("{0} download of {1} orders failed. Please try again with fewer orders.").format(label, len(names)), [])


def _tell(user, file_doc, subject, incomplete):
	"""The page's Download button (realtime) and a bell notification that opens the file."""
	frappe.publish_realtime(
		EVENT,
		{
			"ok": bool(file_doc),
			"message": subject,
			"file_url": file_doc.file_url if file_doc else None,
			"file_name": file_doc.file_name if file_doc else None,
			"incomplete": (incomplete or [])[:20],
			"incomplete_count": len(incomplete or []),
		},
		user=user,
	)
	note = {
		"doctype": "Notification Log",
		"for_user": user,
		"from_user": user,
		"type": "Alert",
		"subject": subject,
	}
	if file_doc:
		note.update(document_type="File", document_name=file_doc.name)
	try:
		frappe.get_doc(note).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="Club download: notification failed")


def cleanup():
	"""Daily: the ZIPs are a one-off hand-over, not records; remove them after KEEP_DAYS."""
	old = frappe.get_all(
		"File",
		filters={"file_name": ("like", FILE_PREFIX + "%.zip"), "creation": ("<", add_days(now_datetime(), -KEEP_DAYS))},
		pluck="name",
	)
	for name in old:
		try:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)
		except Exception:
			frappe.log_error(title="Club download cleanup: {0}".format(name))
	if old:
		frappe.db.commit()
