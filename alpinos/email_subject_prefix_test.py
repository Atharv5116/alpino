"""UAT email subject prefix ("UAT – "). TEST sites only; nothing is sent, everything is rolled back.

Run:  ../env/bin/python ~/alpinos-wt/mrp_work/run.py <site> alpinos.email_subject_prefix_test.run
"""

import email
from email.parser import Parser
from email.policy import SMTP, default

import frappe
from frappe.utils import safe_encode

from alpinos.email_subject_prefix import CONFIG_KEY

PREFIX = "UAT – "
TO = "prefix-test@example.com"
R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))
	finally:
		frappe.set_user("Administrator")
		frappe.clear_messages()


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	R.clear()
	frappe.set_user("Administrator")
	had, old = CONFIG_KEY in frappe.local.conf, frappe.local.conf.get(CONFIG_KEY)
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		if had:
			frappe.local.conf[CONFIG_KEY] = old
		else:
			frappe.local.conf.pop(CONFIG_KEY, None)
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


def _prefix(on):
	if on:
		frappe.local.conf[CONFIG_KEY] = PREFIX
	else:
		frappe.local.conf.pop(CONFIG_KEY, None)


def _queue(subject, **kw):
	q = frappe.sendmail(recipients=[TO], subject=subject, message="<p>Body text <b>here</b></p>", delayed=True, **kw)
	_assert(q and q.doctype == "Email Queue", f"not queued: {q}")
	return q


def _subject(q):
	"""The subject as Frappe reads it at send time."""
	return str(Parser(policy=SMTP.clone(refold_source="none")).parsestr(q.message)["Subject"])


def _sent_bytes(q):
	"""The bytes Frappe would hand to the mail server (SendMailContext.build_message), without connecting."""
	from frappe.email.doctype.email_queue.email_queue import SendMailContext

	ctx = object.__new__(SendMailContext)
	ctx.queue_doc = q
	ctx.email_account_doc = q.get_email_account(raise_error=True)
	return safe_encode(ctx.build_message(TO))


def _leaves(raw):
	m = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode(), policy=default)
	return [(p.get_content_type(), p.get_payload(decode=True)) for p in m.walk() if not p.is_multipart()]


def _run():
	def _uat_subject():
		_prefix(True)
		q = _queue("Leave Request Approved")
		_assert(_subject(q) == "UAT – Leave Request Approved", _subject(q))

	check("UAT: 'Leave Request Approved' goes out as 'UAT – Leave Request Approved'", _uat_subject)

	def _what_the_inbox_sees():
		_prefix(True)
		q = _queue("Attendance Request Pending Approval")
		raw = _sent_bytes(q)
		m = email.message_from_bytes(raw, policy=default)
		_assert(m["Subject"] == "UAT – Attendance Request Pending Approval", m["Subject"])
		head = raw.split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in raw else raw.split(b"\n\n", 1)[0]
		_assert(all(b < 128 for b in head), "the en dash must be encoded in the header")

	check("UAT: the message handed to the mail server reads 'UAT – ...' (header encoded)", _what_the_inbox_sees)

	def _live_unchanged():
		_prefix(False)
		q = _queue("Sales Order Submitted")
		_assert(_subject(q) == "Sales Order Submitted", _subject(q))

	check("Live (no email_subject_prefix in site config): subject unchanged", _live_unchanged)

	def _body_untouched():
		_prefix(False)
		plain = _queue("Sales Order Submitted", attachments=[{"fname": "note.txt", "fcontent": "hello"}])
		_prefix(True)
		uat = _queue("Sales Order Submitted", attachments=[{"fname": "note.txt", "fcontent": "hello"}])
		a, b = _leaves(_sent_bytes(plain)), _leaves(_sent_bytes(uat))
		_assert(a == b and len(a) >= 2, f"{[x[0] for x in a]} vs {[x[0] for x in b]}")
		_assert(any(ct == "text/plain" and pl == b"hello" for ct, pl in b), "attachment lost")

	check("UAT: body and attachments are exactly as without the prefix", _body_untouched)

	def _long_and_unicode():
		_prefix(True)
		s = "Sales Order SOR-2627-00012 for M/S Kishore Distributors – 204 units of Alpino Peanut Butter Super Oats Chocolate 1KG submitted"
		q = _queue(s)
		_assert(_subject(q) == PREFIX + s, _subject(q))

	check("UAT: a long subject with its own dash keeps every character", _long_and_unicode)

	def _no_double():
		_prefix(True)
		q = _queue("UAT – Sales Order Submitted")
		_assert(_subject(q) == "UAT – Sales Order Submitted", _subject(q))

	check("UAT: a subject that already starts with 'UAT –' is not prefixed twice", _no_double)

	def _communication():
		from frappe.core.doctype.communication.email import make

		_prefix(True)
		r = make(recipients=TO, subject="Re: Purchase Order POR-0001", content="Reply body", send_email=True)
		comm = frappe.get_doc("Communication", r["name"])
		q = frappe.get_last_doc("Email Queue", filters={"communication": comm.name})
		_assert(_subject(q) == "UAT – Re: Purchase Order POR-0001", _subject(q))
		_assert(comm.subject == "Re: Purchase Order POR-0001", f"timeline subject changed: {comm.subject}")

	check("UAT: an email sent from a document's timeline is prefixed; the timeline entry keeps its subject", _communication)
