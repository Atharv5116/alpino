"""Offline Payment Follow-up (doc Section 8): the Payment Follow-up Queue (Due Today) and the
Overdue Payment Queue. One row per outstanding Credit obligation (a Credit Quotation, or a
Credit row of a Partial schedule) of a Finalized / Sales Order Created Quotation that is not
Force Completed; amounts are what is pending now. Only Quotations the user may see."""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _rows(filters.get("queue") or "Due Today")


def _columns():
	return [
		{"label": _("Quotation"), "fieldname": "quotation", "fieldtype": "Link", "options": "Quotation", "width": 150},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Data", "width": 200},
		{"label": _("Payment Term"), "fieldname": "payment_term", "fieldtype": "Data", "width": 100},
		{"label": _("Schedule Row"), "fieldname": "row", "fieldtype": "Data", "width": 100},
		{"label": _("Expected Payment Date"), "fieldname": "expected", "fieldtype": "Date", "width": 130},
		{"label": _("Expected Amount"), "fieldname": "expected_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Received"), "fieldname": "received", "fieldtype": "Currency", "width": 110},
		{"label": _("Pending"), "fieldname": "pending", "fieldtype": "Currency", "width": 110},
		{"label": _("Days Overdue"), "fieldname": "days", "fieldtype": "Int", "width": 100},
		{"label": _("Responsible Sales Officer"), "fieldname": "responsible", "fieldtype": "Data", "width": 160},
		{"label": _("Finalized By"), "fieldname": "finalized_by", "fieldtype": "Data", "width": 140},
	]


def _rows(queue):
	from alpinos.offline_sales.payment_reminders import obligations

	day = getdate(today())
	picked = [o for o in obligations() if (o[2] == day if queue == "Due Today" else day > o[2])]
	if not picked:
		return []
	visible = set(frappe.get_list("Quotation", filters={"name": ("in", list({o[0].name for o in picked}))}, pluck="name",
		limit_page_length=0))
	out = []
	for q, row, expected, pending in picked:
		if q.name not in visible:
			continue
		extra = frappe.db.get_value("Quotation", q.name, ["grand_total", "custom_total_received", "custom_responsible_sales_officer",
			"custom_finalized_by"], as_dict=True) or {}
		if row:
			sched = frappe.db.get_value("Quotation Payment Schedule", {"parent": q.name, "idx": row.idx},
				["expected_amount", "received_amount"], as_dict=True) or {}
			expected_amount, received = flt(sched.get("expected_amount")), flt(sched.get("received_amount"))
		else:
			expected_amount, received = flt(extra.get("grand_total")), flt(extra.get("custom_total_received"))
		out.append({
			"quotation": q.name, "customer": q.customer_name or q.party_name, "payment_term": q.custom_payment_term,
			"row": f"Row {row.idx}" if row else "", "expected": expected, "expected_amount": expected_amount,
			"received": received, "pending": pending, "days": max(date_diff(day, expected), 0),
			"responsible": extra.get("custom_responsible_sales_officer") or "", "finalized_by": extra.get("custom_finalized_by") or "",
		})
	return sorted(out, key=lambda r: (r["expected"], r["quotation"]))
