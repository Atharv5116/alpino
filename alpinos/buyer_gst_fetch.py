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


def map_to_buyer_fields(info):
	"""india_compliance's response, in the shape Buyer Master keeps its data."""
	if not info:
		return {}
	address = (info.get("permanent_address") or {}) if hasattr(info, "get") else {}
	line1 = (address.get("address_line1") or "").strip()
	line2 = (address.get("address_line2") or "").strip()
	return {
		"customer_business_name": (info.get("business_name") or "").strip(),
		"gst_type": _GST_TYPE_BY_CATEGORY.get(info.get("gst_category") or "", ""),
		"gst_status": (info.get("status") or "").strip(),
		"address_line": ", ".join([p for p in (line1, line2) if p]),
		"city": (address.get("city") or "").strip(),
		"state": (address.get("state") or "").strip(),
		"pincode": (address.get("pincode") or "").strip(),
		"country": (address.get("country") or "India").strip(),
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
	return {
		"ok": 1,
		"reason": "",
		"message": _("Details fetched for {0}. Everything below stays editable.").format(gstin),
		"data": data,
		"status": data.get("gst_status") or "",
	}
