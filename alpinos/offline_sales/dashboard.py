"""Offline Sales dashboard (doc Section 8, W8): 11 KPI cards, role-based, real time.

Counts go through frappe.get_list, so each user counts only the records they may see (Sales
Officer: their buyers; the rest per Section 1); a Sales Admin's counts open on their Secondary
POC buyers, with Show All for every permitted Offline record (list scope only). Every card
opens its filtered list. Quotation Status, Payment Status, SO Eligibility and Force Complete
stay separate: "Force Complete Applied" is its own card, never a Quotation status.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_first_day, getdate, now_datetime, today

SO, SM, SA = "Sales Officer", "Sales Manager", "Sales Admin"
ALL3 = (SO, SM, SA)
MGR = (SM, SA)
REPORT = "Offline Payment Follow-up"


def _roles():
	roles = set(frappe.get_roles())
	if "System Manager" in roles or frappe.session.user == "Administrator":
		roles |= set(ALL3)
	return roles


def _scope(show_all):
	"""Extra Secondary POC filter for a Sales Admin whose lists open on their own buyers."""
	from alpinos.offline_sales import access

	scope = access.list_scope() or {}
	if scope.get("secondary_poc_default") and not cint(show_all):
		return scope.get("employee")
	return None


def _count(doctype, filters, sec_field=None, employee=None):
	if not frappe.db.table_exists(doctype):
		return 0
	filters = list(filters)
	if employee and sec_field and frappe.db.has_column(doctype, sec_field):
		filters.append([doctype, sec_field, "=", employee])
	return len(frappe.get_list(doctype, filters=filters, pluck="name", limit_page_length=0))


def _has(doctype, field):
	return frappe.db.has_column(doctype, field)


def _obligations(kind, employee=None):
	"""Due Today / Overdue Credit obligations the user may see: (count, total pending)."""
	from alpinos.offline_sales.payment_reminders import obligations

	day = getdate(today())
	rows = [o for o in obligations() if (o[2] == day if kind == "due" else day > o[2])]
	if not rows:
		return 0, 0.0
	names = list({o[0].name for o in rows})
	filters = [["Quotation", "name", "in", names]]
	if employee and _has("Quotation", "custom_secondary_poc"):
		filters.append(["Quotation", "custom_secondary_poc", "=", employee])
	visible = set(frappe.get_list("Quotation", filters=filters, pluck="name", limit_page_length=0))
	mine = [o for o in rows if o[0].name in visible]
	return len(mine), flt(sum(o[3] for o in mine), 2)


def _route(doctype, filters):
	return {"doctype": doctype, "filters": filters}


@frappe.whitelist()
def get_dashboard(show_all=0):
	# company-scope: n/a (every count goes through frappe.get_list, which applies the company scope)
	roles = _roles()
	if not roles & set(ALL3):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	emp = _scope(show_all)
	esc_hours = cint(frappe.db.get_single_value("Offline Sales Settings", "escalation_hours")) or 48
	cutoff = add_to_date(now_datetime(), hours=-esc_hours)
	offline = ["Buyer Master", "channel", "!=", "E-com"]
	cards = []

	def card(key, title, visible_to, count, link, amount=None):
		if roles & set(visible_to):
			cards.append({"key": key, "title": title, "count": count, "amount": amount, "link": link})

	if roles & set(MGR):
		pending = [offline, ["Buyer Master", "buyer_status", "=", "Pending Approval"]]
		card("K1", _("Pending Buyer Approvals"), MGR, _count("Buyer Master", pending, "secondary_poc", emp),
			_route("Buyer Master", {"buyer_status": "Pending Approval"}))
		late = pending + [["Buyer Master", "creation", "<", cutoff]]
		card("K2", _("Buyer Approvals > 48h"), MGR, _count("Buyer Master", late, "secondary_poc", emp),
			_route("Buyer Master", {"buyer_status": "Pending Approval", "creation": ["<", str(cutoff)]}))
	# K3 Draft Opportunities / K4 Opportunities on Hold: none since the Opportunity is skipped
	# (20 Nov 2026); a buyer's request is a Draft Quotation, counted in K5.
	if _has("Quotation", "custom_quotation_status"):
		for key, title, status in (("K5", _("Draft Quotations"), "Draft"), ("K6", _("Negotiation Quotations"), "Negotiation")):
			card(key, title, ALL3, _count("Quotation", [["Quotation", "custom_quotation_status", "=", status]], "custom_secondary_poc", emp),
				_route("Quotation", {"custom_quotation_status": status}))
		k7 = [
			["Quotation", "custom_quotation_status", "=", "Finalized"],
			["Quotation", "custom_payment_status", "!=", "Fully Received"],
			["Quotation", "custom_force_complete_applied", "=", 0],
		]
		card("K7", _("Finalized with Payment Pending"), ALL3, _count("Quotation", k7, "custom_secondary_poc", emp),
			_route("Quotation", {"custom_quotation_status": "Finalized", "custom_payment_status": ["!=", "Fully Received"],
				"custom_force_complete_applied": 0}))
		due, due_amt = _obligations("due", emp)
		card("K8", _("Payments Due Today"), ALL3, due, {"report": REPORT, "filters": {"queue": "Due Today"}}, due_amt)
		over, over_amt = _obligations("overdue", emp)
		card("K9", _("Overdue Payments"), ALL3, over, {"report": REPORT, "filters": {"queue": "Overdue"}}, over_amt)
		card("K10", _("Force Complete Applied"), MGR,
			_count("Quotation", [["Quotation", "custom_force_complete_applied", "=", 1]], "custom_secondary_poc", emp),
			_route("Quotation", {"custom_force_complete_applied": 1}))
	first = get_first_day(today())
	so_filters = [
		["Sales Order", "custom_channel", "!=", "E-com"],
		["Sales Order", "transaction_date", ">=", first],
		["Sales Order", "docstatus", "<", 2],
		["Sales Order", "custom_workflow_status", "not in", ["Cancelled", "Rejected"]],
	]
	card("K11", _("Sales Orders Created MTD"), ALL3, _count("Sales Order", so_filters),
		{"page": "sales-order-entry-list", "route_options": {"from_date": str(first)}})
	return {"cards": cards, "show_all_available": bool(_scope(0) or cint(show_all))}
