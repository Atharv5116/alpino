"""UAT only: every outgoing email's subject starts with "UAT – " (Drashti, 25 Nov 2026).

    UAT – Leave Request Approved
    UAT – Attendance Request Pending Approval

The prefix comes from the site's own config, so only the site that has it is affected:

    bench --site uat16.alpino.co.in set-config email_subject_prefix "UAT – "

Live has no such key, so its subjects stay as they are.

Every email Frappe sends (notifications, workflow and approval mails, alerts, replies, password
resets) is first written to the Email Queue, so the prefix is added there, once, for all of them.
The message is read and written back the same way Frappe itself does when it sends it
(EmailQueue's SendMailContext.get_message_object + as_string); only the Subject changes.
"""

from email.parser import Parser
from email.policy import SMTP

import frappe

CONFIG_KEY = "email_subject_prefix"


def subject_prefix():
	return frappe.conf.get(CONFIG_KEY) or ""


def add_subject_prefix(doc, method=None):
	"""Email Queue before_insert."""
	prefix = subject_prefix()
	if prefix and doc.message:
		doc.message = prefixed_message(doc.message, prefix)


def prefixed_message(message, prefix):
	msg = Parser(policy=SMTP.clone(refold_source="none")).parsestr(message)
	if "Subject" not in msg:
		return message
	subject = str(msg["Subject"])
	if subject.startswith(prefix.rstrip()):
		return message
	msg.replace_header("Subject", prefix + subject)
	return msg.as_string()
