"""The "+ Create New Buyer" modal's server side (document Section 4, 2-3 and 7 "Save Buyer").

The modal asks for what the document's 3.1-3.3 tables list, plus Payment Term (and Days),
which Buyer Master requires. Its own mandatory rules are checked here (attachments by GST type,
a Billing and a Shipping address, the contact, the three assignments); everything else is the
Buyer Master's own validation, so a buyer made here and one made on the form obey one rule set.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, cstr

from alpinos.offline_sales import SALES_OFFICER, is_manager, is_sales_officer_only
from alpinos.offline_sales import buyer_rules, settings


def _options(fieldname):
	df = frappe.get_meta("Buyer Master").get_field(fieldname)
	return [o for o in (df.options or "").split("\n") if o]


@frappe.whitelist()
def get_create_context():
	"""Defaults and choices for the modal."""
	# company-scope: n/a (Buyer Master has no company; reads the user's own Employee and settings)
	frappe.has_permission("Buyer Master", "create", throw=True)
	from alpinos.buyer_assignment import employee_for_user

	def person(employee):
		return {"employee": employee, "employee_name": frappe.db.get_value("Employee", employee, "employee_name") or employee}

	me = employee_for_user()
	return {
		"is_manager": 1 if is_manager() else 0,
		"is_sales_officer": 1 if is_sales_officer_only() else 0,
		"default_primary_pocs": [person(e) for e in settings.default_primary_pocs(eligible_only=True)],
		"me": person(me) if me and SALES_OFFICER in frappe.get_roles() else None,
		"gst_types": _options("gst_type"),
		"levels": _options("level"),
		"payment_terms": _options("payment_term"),
	}


@frappe.whitelist()
def check_duplicate(gst_type, gst_no=None, pan_no=None, customer_business_name=None):
	"""The modal's live duplicate check (3.1.1): the message, or None."""
	# company-scope: n/a (Buyer Master has no company)
	frappe.has_permission("Buyer Master", "create", throw=True)
	row = buyer_rules.find_duplicate(gst_type, gst_no, pan_no, customer_business_name)
	return {"message": buyer_rules.duplicate_message(row), "buyer": row.name, "status": row.buyer_status} if row else None


def _require(condition, message):
	if not condition:
		frappe.throw(message, title=_("Create New Buyer"))


@frappe.whitelist()
def create_buyer(data):
	"""Save Buyer: a Pending Approval buyer for a Sales Officer, an Approved one for SM / SA."""
	# company-scope: n/a (Buyer Master has no company)
	frappe.has_permission("Buyer Master", "create", throw=True)
	data = frappe._dict(json.loads(data) if isinstance(data, str) else data)

	gst_type = cstr(data.gst_type)
	_require(cstr(data.customer_business_name).strip(), _("Enter the Customer Name."))
	_require(data.customer_type, _("Select the Customer Type."))
	_require(gst_type, _("Select the GST Type."))
	if gst_type == "Registered Business":
		_require(cstr(data.gst_no).strip(), _("GST No is mandatory for a Registered Business."))
		_require(data.gst_certificate, _("Attach the GST Certificate."))
	elif gst_type == "Unregistered Business":
		_require(cstr(data.pan_no).strip(), _("PAN No is mandatory for an Unregistered Business."))
		_require(data.pan_attachment, _("Attach the PAN."))
	pan = cstr(data.pan_no).strip().upper()
	if pan:
		_require(len(pan) == 10 and pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha(),
			_("PAN No must be 10 characters: 5 letters, 4 digits and a letter."))

	addresses = data.addresses or []
	_require(addresses, _("Add at least one address."))
	for i, row in enumerate(addresses, start=1):
		row = frappe._dict(row)
		for field, label in (("site_name", _("Site Name")), ("address_line", _("Address Line")), ("state", _("State")),
				("city", _("City")), ("pincode", _("Pincode"))):
			_require(cstr(row.get(field)).strip(), _("Address row {0}: {1} is mandatory.").format(i, label))
		_require(cstr(row.pincode).strip().isdigit() and len(cstr(row.pincode).strip()) == 6,
			_("Address row {0}: Pincode must be exactly 6 numeric digits.").format(i))
	_require(sum(cint(frappe._dict(r).is_primary) for r in addresses) >= 1,
		_("Tick Primary (Billing) on at least one address."))
	_require(sum(cint(frappe._dict(r).is_primary) for r in addresses) == 1,
		_("Only one address can be the Primary (Billing) address."))
	_require(any(cint(frappe._dict(r).is_shipping) for r in addresses),
		_("Tick Shipping on at least one address."))

	for field, label in (("contact_person", _("Contact Person")), ("email", _("Email Address")), ("contact_no", _("Contact No"))):
		_require(cstr(data.get(field)).strip(), _("{0} is mandatory.").format(label))
	_require(data.secondary_poc, _("Select the Secondary POC."))

	primary = [e for e in (data.primary_pocs or []) if e]
	for e in settings.default_primary_pocs(eligible_only=True):
		if e not in primary:
			primary.append(e)
	_require(primary, _("Select at least one Primary POC."))

	officers = [e for e in (data.sales_officers or []) if e]
	if is_sales_officer_only():
		from alpinos.buyer_assignment import employee_for_user

		me = employee_for_user()
		if me and me not in officers:
			officers.append(me)
	_require(officers, _("Select at least one Sales Officer."))

	doc = frappe.new_doc("Buyer Master")
	doc.update(
		{
			"channel": "Offline",
			"customer_business_name": cstr(data.customer_business_name).strip(),
			"customer_type": data.customer_type,
			"gst_type": gst_type,
			"gst_no": cstr(data.gst_no).strip().upper() if gst_type == "Registered Business" else None,
			"gst_certificate": data.gst_certificate if gst_type == "Registered Business" else None,
			"pan_no": pan or None,
			"pan_attachment": data.pan_attachment if gst_type == "Unregistered Business" else None,
			"level": data.level,
			"payment_term": data.payment_term or "Advance",
			"payment_term_days": cstr(data.payment_term_days).strip() or None,
			"contact_person": cstr(data.contact_person).strip(),
			"email": cstr(data.email).strip(),
			"contact_no": cstr(data.contact_no).strip(),
			"alternate_no": cstr(data.alternate_no).strip() or None,
			"secondary_poc": data.secondary_poc,
			"site_name": cstr(frappe._dict(addresses[0]).site_name).strip(),
		}
	)
	for row in addresses:
		row = frappe._dict(row)
		doc.append(
			"addresses",
			{
				"site_name": cstr(row.site_name).strip(),
				"address_line": cstr(row.address_line).strip(),
				"state": row.state,
				"city": row.city,
				"pincode": cstr(row.pincode).strip(),
				"country": row.country or "India",
				"is_primary": cint(row.is_primary),
				"is_shipping": cint(row.is_shipping),
			},
		)
	for e in primary:
		doc.append("primary_pocs", {"employee": e})
	for e in officers:
		doc.append("sales_officers", {"employee": e})

	doc.insert()
	_attach(doc, ("gst_certificate", "pan_attachment"))
	return {
		"name": doc.name,
		"customer": doc.customer,
		"customer_business_name": doc.customer_business_name,
		"buyer_status": doc.buyer_status,
		"buyer_catalog_status": doc.buyer_catalog_status,
	}


def _attach(doc, fields):
	"""Files uploaded in the modal belong to no record yet: give them to the new buyer."""
	for field in fields:
		url = doc.get(field)
		if not url:
			continue
		for name in frappe.get_all(
			"File",
			filters={"file_url": url, "attached_to_name": ("is", "not set"), "owner": frappe.session.user},
			pluck="name",
		):
			frappe.db.set_value(
				"File", name,
				{"attached_to_doctype": "Buyer Master", "attached_to_name": doc.name, "attached_to_field": field},
				update_modified=False,
			)
