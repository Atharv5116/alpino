"""
Dispatch date utilities for Alpinos.

- Before 2 PM  → default dispatch date = today
- At/after 2 PM → default = next working day (skips weekends + company holiday list)
- Validation: today's date cannot be selected at/after 2 PM
"""

import frappe
from frappe.utils import today, now_datetime, add_days, getdate

CUTOFF_HOUR = 14  # 2:00 PM — change here to adjust cutoff


@frappe.whitelist()
def get_default_dispatch_date():
	"""Return the appropriate default dispatch date based on current time."""
	now = now_datetime()
	if now.hour < CUTOFF_HOUR:
		return {"date": today(), "is_today": True}
	return {"date": _get_next_working_day(add_days(today(), 1)), "is_today": False}


@frappe.whitelist()
def validate_dispatch_date(date):
	"""Return {valid, message} for the chosen dispatch date.

	Two rejections:
	  1. Any date before today is invalid.
	  2. Today is invalid once the clock is past the cutoff (default 2:00 PM).
	"""
	chosen = getdate(date)
	today_date = getdate(today())
	if chosen < today_date:
		return {
			"valid": False,
			"message": "Dispatch Date cannot be in the past.",
		}
	now = now_datetime()
	if now.hour >= CUTOFF_HOUR and chosen == today_date:
		return {
			"valid": False,
			"message": "After 2:00 PM, today's date cannot be selected as the dispatch date.",
		}
	return {"valid": True}


def validate_dispatch_date_on_save(doc, method=None):
	"""Doc-event hook — called on Sales Order validate."""
	if not doc.custom_dispatch_date:
		return
	result = validate_dispatch_date(doc.custom_dispatch_date)
	if not result.get("valid"):
		frappe.throw(result["message"])


def _get_next_working_day(from_date):
	"""Walk forward from from_date until a non-weekend, non-holiday weekday is found."""
	company = frappe.defaults.get_defaults().get("company")
	holiday_list = None
	if company:
		holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")

	date = getdate(from_date)
	for _ in range(30):
		if date.weekday() >= 5:  # Saturday=5, Sunday=6
			date = getdate(add_days(str(date), 1))
			continue
		if holiday_list and frappe.db.exists(
			"Holiday", {"parent": holiday_list, "holiday_date": date}
		):
			date = getdate(add_days(str(date), 1))
			continue
		break
	return str(date)
