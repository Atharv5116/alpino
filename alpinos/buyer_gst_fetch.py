"""Changes(HP) #57: fill a Buyer Master from its GST No.

    "Integrate Indian Compliance in Buyer Master to fetch customer details using the entered
     GST No... All fetched details must remain editable... If the user changes or corrects
     the GST No., the system must fetch the details again... Show a clear message if the GST
     No. is invalid, not found, or if the GST service/API cannot return details."

The lookup itself belongs to india_compliance, which owns the GSP subscription and the
response caching. This module is the translation layer: it asks that app, maps what comes
back onto the fields Buyer Master actually has, and -- the part the ticket is firm about --
turns every way the lookup can fail into a sentence somebody can act on.

Nothing is written here. The call returns values and the form fills them in, so every field
stays editable exactly as the ticket requires; a correction the user makes afterwards is not
competing with anything.

india_compliance is present in the bench but is NOT installed on alpinos.test, and the
lookup needs a GSP subscription besides. So `available()` is checked first and the caller is
told plainly when the feature cannot run, rather than the form failing in a way that looks
like the GST number was wrong.
"""

import re

import frappe
from frappe import _

#: 15 characters: 2 state digits, 10 PAN, 1 entity, 1 Z, 1 checksum.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

#: india_compliance's GST category -> the Buyer Master GST Type options.
_GST_TYPE_BY_CATEGORY = {
	"Registered Regular": "Registered Business",
	"Registered Composition": "Registered Business",
	"Tax Deductor": "Registered Business",
	"Tax Collector": "Registered Business",
	"UIN Holders": "Registered Business",
	"Input Service Distributor": "Registered Business",
	"SEZ": "Registered Business",
	"Deemed Export": "Registered Business",
	"Unregistered": "Unregistered Business",
	"Overseas": "Overseas",
}


def available():
	"""Whether the GST lookup can run on this site at all."""
	try:
		import india_compliance  # noqa: F401
	except ImportError:
		return False
	return "india_compliance" in frappe.get_installed_apps()


def validate_gstin_format(gstin):
	"""(ok, message). Checked here so an obvious typo never costs an API call."""
	gstin = (gstin or "").strip().upper()
	if not gstin:
		return False, _("Enter a GST No. first.")
	if len(gstin) != 15:
		return False, _("A GST No. is 15 characters; this one is {0}.").format(len(gstin))
	if not GSTIN_RE.match(gstin):
		return False, _("{0} is not a valid GST No.").format(gstin)
	return True, ""


def _key(text):
	"""A spelling-proof key for a place name: "Jammu And Kashmir" finds "Jammu & Kashmir"."""
	return re.sub(r"[^a-z]", "", (text or "").lower().replace("&", "and"))


def _state_record(state, gstin=""):
	"""The State record for the GST record's state name, else for the GST No.'s state code."""
	names = [state]
	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS

		names += [name for name, code in STATE_NUMBERS.items() if code == (gstin or "")[:2]]
	except ImportError:
		pass
	records = {_key(name): name for name in frappe.get_all("State", pluck="name")}
	return next((records[_key(n)] for n in names if _key(n) in records), "")


def _city_record(candidates, state):
	"""The City record, of that state, for the first candidate that is one. The address row
	only offers the cities of its state, so a namesake in another state would not do."""
	if not state:
		return ""
	records = {_key(c.city_name): c.name for c in frappe.get_all("City", filters={"state": state}, fields=["name", "city_name"])}
	return next((records[_key(n)] for n in candidates if _key(n) in records), "")


def map_to_buyer_fields(info):
	"""india_compliance's response, in the shape Buyer Master keeps its data. State and City
	are links, so they come back as the State / City records they match, or blank."""
	if not info:
		return {}
	address = (info.get("permanent_address") or {}) if hasattr(info, "get") else {}
	line1 = (address.get("address_line1") or "").strip()
	line2 = (address.get("address_line2") or "").strip()
	# The GST record's city is the district ("Bengaluru Urban", "Mumbai Suburban"); the
	# locality and city proper sit at the end of its second line.
	district = (address.get("city") or "").strip()
	candidates = [district, re.sub(r"\s+(urban|rural|suburban|city|district)$", "", district, flags=re.I)]
	candidates += [p.strip() for p in reversed(line2.split(",")) if p.strip()]
	registered_state = (address.get("state") or "").strip()
	state = _state_record(registered_state, info.get("gstin")) if (registered_state or district) else ""
	return {
		"customer_business_name": (info.get("business_name") or "").strip(),
		"gst_type": _GST_TYPE_BY_CATEGORY.get(info.get("gst_category") or "", ""),
		"gst_status": (info.get("status") or "").strip(),
		"address_line": ", ".join([p for p in (line1, line2) if p]),
		"city": _city_record(candidates, state),
		"state": state,
		"pincode": (address.get("pincode") or "").strip(),
		"country": (address.get("country") or "India").strip(),
		# As the GST record has them, for the message when no City / State record matches.
		"registered_city": district,
		"registered_state": registered_state,
	}


@frappe.whitelist()
def fetch_gstin_details(gstin):
	"""Look up a GST No. and return the Buyer Master values it implies.

	Always returns a dict with `ok` and `message`; it never raises at the caller, because a
	form field losing its data to a traceback is worse than being told the lookup failed.
	"""
	gstin = (gstin or "").strip().upper()
	ok, message = validate_gstin_format(gstin)
	if not ok:
		return {"ok": 0, "reason": "invalid", "message": message, "data": {}}

	if not available():
		return {
			"ok": 0,
			"reason": "unavailable",
			"message": _(
				"GST lookup is not set up on this site. The India Compliance app has to be "
				"installed and its GST API subscription configured before details can be "
				"fetched. Enter the details by hand for now."
			),
			"data": {},
		}

	try:
		from india_compliance.gst_india.utils.gstin_info import get_gstin_info

		info = get_gstin_info(gstin, throw_error=True)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"GSTIN lookup failed for {gstin}")
		return {
			"ok": 0,
			"reason": "service",
			"message": _("The GST service could not return details for {0}: {1}").format(
				gstin, frappe.utils.strip_html(str(e))[:200]
			),
			"data": {},
		}

	if not info or not info.get("gstin"):
		return {
			"ok": 0,
			"reason": "not_found",
			"message": _("No details were found for {0}.").format(gstin),
			"data": {},
		}

	data = map_to_buyer_fields(info)
	missing = []
	if data["registered_state"] and not data["state"]:
		missing.append(_("State {0} is not in the State list").format(data["registered_state"]))
	elif data["registered_city"] and not data["city"]:
		missing.append(_("City {0} is not in the City list").format(data["registered_city"]))
	message = _("Details fetched for {0}. Everything below stays editable.").format(gstin)
	if missing:
		message += " " + _("{0}: pick it on the address row.").format("; ".join(missing))
	return {
		"ok": 1,
		"reason": "",
		"message": message,
		"missing": missing,
		"data": data,
		"status": data.get("gst_status") or "",
	}
