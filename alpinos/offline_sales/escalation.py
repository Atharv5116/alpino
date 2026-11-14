"""The 48-hour approval escalation (document Section 4, 5).

Hourly: a buyer still Pending Approval `escalation_hours` (48) calendar hours after it was
created is escalated once to every assigned Primary POC and the Secondary POC, in-app and by
email, with the document's wording. escalated_on records it; a status action clears it, so a
buyer that comes back to Pending Approval cannot (Pending is only ever a starting status, but
the rule is kept simple and explicit).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from alpinos.offline_sales import ECOM_CHANNEL, PENDING
from alpinos.offline_sales import audit
from alpinos.offline_sales.settings import escalation_hours


def due_buyers(now=None):
	cutoff = add_to_date(now or now_datetime(), hours=-escalation_hours())
	return frappe.get_all(
		"Buyer Master",
		filters={
			"buyer_status": PENDING,
			"escalated_on": ("is", "not set"),
			"creation": ("<=", cutoff),
			"channel": ("!=", ECOM_CHANNEL),
		},
		fields=["name", "customer_business_name", "owner", "secondary_poc"],
		order_by="creation asc",
	)


def recipients(buyer, secondary_poc=None):
	"""Users of every assigned Primary POC and of the Secondary POC (4.3, 5.2)."""
	employees = set(
		frappe.get_all(
			"Buyer Primary POC", filters={"parent": buyer, "parenttype": "Buyer Master"}, pluck="employee"
		)
	)
	if secondary_poc:
		employees.add(secondary_poc)
	employees.discard(None)
	if not employees:
		return []
	return sorted(
		set(
			frappe.get_all(
				"Employee", filters={"name": ("in", list(employees)), "user_id": ("is", "set")}, pluck="user_id"
			)
		)
	)


def message(row):
	creator = frappe.db.get_value("User", row.owner, "full_name") or row.owner
	return (
		f"URGENT ESCALATION: Buyer Master [{row.customer_business_name}] submitted by {creator} has been "
		f"PENDING APPROVAL for over {escalation_hours()} hours. Please review and take the required approval action."
	)


def run(now=None):
	from alpinos.production.notify import notify

	done = []
	for row in due_buyers(now):
		users = recipients(row.name, row.secondary_poc)
		subject = message(row)
		sent = notify([], subject, doctype="Buyer Master", name=row.name, email=True, users=users) if users else []
		frappe.db.set_value("Buyer Master", row.name, "escalated_on", now or now_datetime(), update_modified=False)
		# doc Section 8: system time, hours elapsed and recipients
		elapsed = int((((now or now_datetime()) - row.creation).total_seconds()) // 3600) if row.get("creation") else escalation_hours()
		audit.log(
			"Buyer Master", row.name, "Approval Escalated", "Escalated To", "", ", ".join(sent) or "(no POC user)",
			reason=_("Pending Approval for {0} hours").format(elapsed), role="System",
		)
		done.append(row.name)
	if done:
		frappe.db.commit()
	return done
