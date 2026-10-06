"""Which shift is on now.

Shifts are READ from the existing HR "Shift Type" master (user decision 2026-10-05: use all
Shift Types; Shift Type itself is never modified). Where shifts overlap, the one that
started most recently wins. The old Production Shift master is only a fallback for a site
without Shift Type. When nothing matches the result is None and callers leave it blank.
"""

import datetime

import frappe
from frappe.utils import get_datetime, now_datetime, to_timedelta

SHIFT_DOCTYPE = "Shift Type"
FALLBACK_SHIFT_DOCTYPE = "Production Shift"


def _seconds(value):
	"""Seconds since midnight for a Time value (timedelta, time or 'HH:MM:SS')."""
	if value in (None, ""):
		return None
	if isinstance(value, datetime.time):
		return value.hour * 3600 + value.minute * 60 + value.second
	if not isinstance(value, datetime.timedelta):
		value = to_timedelta(str(value))
	return int(value.total_seconds()) % 86400


def _in_shift(now_s, start_s, end_s):
	if start_s < end_s:
		return start_s <= now_s < end_s
	# Overnight: e.g. 22:00 -> 06:00.
	return now_s >= start_s or now_s < end_s


def all_shifts():
	"""[(name, start_time, end_time)] from Shift Type (or the fallback master)."""
	if frappe.db.exists("DocType", SHIFT_DOCTYPE):
		rows = frappe.get_all(SHIFT_DOCTYPE, fields=["name", "start_time", "end_time"],
		                      order_by="start_time asc, name asc")
	elif frappe.db.exists("DocType", FALLBACK_SHIFT_DOCTYPE):
		rows = frappe.get_all(FALLBACK_SHIFT_DOCTYPE, filters={"is_active": 1},
		                      fields=["name", "start_time", "end_time"], order_by="start_time asc")
	else:
		rows = []
	return [(r.name, r.start_time, r.end_time) for r in rows]


def shift_names():
	return [name for name, _s, _e in all_shifts()]


def current_shift(at=None):
	"""dict(name, start, end) of the shift covering `at` (default now), or None."""
	try:
		moment = get_datetime(at) if at else now_datetime()
		now_s = moment.hour * 3600 + moment.minute * 60 + moment.second
		best, best_age = None, None
		for name, start, end in all_shifts():
			start_s, end_s = _seconds(start), _seconds(end)
			if start_s is None or end_s is None or start_s == end_s:
				continue
			if _in_shift(now_s, start_s, end_s):
				age = (now_s - start_s) % 86400  # how long ago it started
				if best_age is None or age < best_age:
					best, best_age = frappe._dict(name=name, start=start, end=end), age
		return best
	except Exception:
		frappe.log_error(frappe.get_traceback(), "current_shift")
	return None


@frappe.whitelist()
def get_current_shift():
	"""For pages: the current shift as a dict, or None."""
	return current_shift()
