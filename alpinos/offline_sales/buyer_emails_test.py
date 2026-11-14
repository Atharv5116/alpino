"""Buyer dispatch email (doc Section 2, 5.1). TEST sites only; rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.offline_sales.buyer_emails_test.run
"""

import frappe

from alpinos.offline_sales import buyer_emails as E

R = []


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


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	real_print = frappe.get_print
	frappe.get_print = lambda *a, **k: b"%PDF-1.4 test"  # wkhtmltopdf needs a web server; the template is not under test
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.get_print = real_print
		frappe.db.rollback()
		frappe.set_user("Administrator")
	for status, label, detail in R:
		print(f"[{status}] {label} {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")


def _run():
	dn = frappe.db.sql(
		"""SELECT dn.name, dn.custom_sales_order_id AS so FROM `tabDelivery Note` dn
		JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id
		WHERE dn.docstatus = 1 AND IFNULL(so.custom_channel, '') != 'E-com' AND IFNULL(dn.is_return, 0) = 0
		ORDER BY dn.creation DESC LIMIT 1""",
		as_dict=True,
	)
	_assert(dn, "no submitted offline Delivery Note on this site")
	dn = dn[0]
	so = frappe.get_doc("Sales Order", dn.so)
	buyer = so.get("custom_offline_buyer_master") or frappe.db.get_value("Buyer Master", {"customer": so.customer}, "name")
	frappe.db.set_value("Buyer Master", buyer, "email", "buyer.dispatch.test@example.com")
	frappe.db.set_value("Delivery Note", dn.name, {"custom_transporter_name": "Delhivery", "custom_lr_gr_no": "LR12345"})

	def _mail():
		E.send_dispatch_email(dn.name, so.name)
		q = frappe.get_all("Email Queue", filters={"reference_doctype": "Sales Order", "reference_name": so.name},
			fields=["name", "message"], order_by="creation desc", limit=1)
		_assert(q, "no email queued")
		text = E.dispatch_message(so.name, "Delhivery", "LR12345")
		_assert(text == f"Your Order {so.name} has been dispatched via Delhivery. Tracking ID: LR12345.", text)
		import email

		body = ""
		for part in email.message_from_string(q[0].message or "").walk():
			if part.get_content_type() in ("text/plain", "text/html"):
				body += (part.get_payload(decode=True) or b"").decode("utf-8", "ignore")
			if part.get_filename():
				body += f" [attachment {part.get_filename()}]"
		_assert(text in body, "the doc's text is not in the email")
		_assert(f"[attachment {so.name}.pdf]" in body, "the Sales Order PDF is not attached")

	check("S2 5.1: the buyer's dispatch email carries the doc's text with transporter and LR number", _mail)

	def _no_email():
		frappe.db.set_value("Buyer Master", buyer, "email", None)
		before = frappe.db.count("Email Queue")
		E.send_dispatch_email(dn.name, so.name)
		_assert(frappe.db.count("Email Queue") == before, "an email went out without a buyer email")

	check("S2 5.1: no buyer email, nothing is sent and the dispatch is untouched", _no_email)
