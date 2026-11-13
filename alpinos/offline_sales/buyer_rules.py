"""Buyer Master rules of "Opportunity to Sales Order v1.0.0", Section 4.

Called from BuyerMaster.validate in two steps:

  before_validate(doc)  first thing in validate, before the controller recomputes anything:
                        the status guard, the Sales Officer correction limits (4.1, 4.5), and
                        the default Primary POCs and starting status of a new buyer (4.2, 3.3);
  validate(doc)         after the controller's own checks: duplicate buyers (3.1.1, 8.6-8.8),
                        GSTIN state code against the address state (8.3), email and phone
                        formats (3.3), and Buyer Catalog completion from the Margins table.

and from doc_events: after_insert / on_update write the Activity Trail (5.1, 4.5).

Everything here only governs Offline buyers; an E-com buyer is created Approved with its
catalogue counted as done and is never stopped (3.1, "E-Commerce workflow excluded").
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import acting_role
from alpinos.offline_sales import (
	APPROVED,
	CANCELLED,
	CATALOG_COMPLETED,
	CATALOG_PENDING,
	CORRECTABLE,
	INACTIVE,
	ON_HOLD,
	PENDING,
	is_manager,
	is_offline,
	is_sales_officer_only,
)
from alpinos.offline_sales import audit, settings

#: Fields only the status actions and the system write. A plain save never changes them.
STATUS_FIELDS = (
	"buyer_status",
	"buyer_catalog_status",
	"status_reason",
	"approved_by",
	"approver_role",
	"approved_on",
	"catalog_completed_by",
	"catalog_completed_on",
	"escalated_on",
)

#: What a Sales Officer may correct: the fields of the Create New Buyer modal (3.1-3.3).
SO_EDITABLE = {
	"customer_business_name",
	"customer_type",
	"gst_type",
	"gst_no",
	"gst_certificate",
	"pan_no",
	"pan_attachment",
	"level",
	"payment_term",
	"payment_term_days",
	"site_name",
	"addresses",
	"shipping_same_as_profile",
	"shipping_address",
	"shipping_state",
	"shipping_city",
	"contact_person",
	"email",
	"contact_no",
	"alternate_no",
	"sales_officers",
	"primary_pocs",
	"secondary_poc",
}

#: Filled by the controller from other fields, so never "changed" by a person.
SYSTEM_SET = {
	"custom_search_alias",
	"customer",
	"customer_id",
	"primary_poc",
	"address",
	"pincode",
	"country",
	"state",
	"city",
	"area",
	"sub_area",
}

#: Not worth a trail line of their own.
_NOT_AUDITED = set(STATUS_FIELDS) | SYSTEM_SET | {"activity_html"}

_LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"}

# GST state codes. Andhra Pradesh GSTINs start 37 (28 before the 2014 split); the merged
# Dadra and Nagar Haveli and Daman and Diu uses 26, older Daman and Diu ones 25.
GST_STATE_CODES = {
	"jammu and kashmir": ("01",),
	"jammu & kashmir": ("01",),
	"himachal pradesh": ("02",),
	"punjab": ("03",),
	"chandigarh": ("04",),
	"uttarakhand": ("05",),
	"uttaranchal": ("05",),
	"haryana": ("06",),
	"delhi": ("07",),
	"new delhi": ("07",),
	"rajasthan": ("08",),
	"uttar pradesh": ("09",),
	"bihar": ("10",),
	"sikkim": ("11",),
	"arunachal pradesh": ("12",),
	"nagaland": ("13",),
	"manipur": ("14",),
	"mizoram": ("15",),
	"tripura": ("16",),
	"meghalaya": ("17",),
	"assam": ("18",),
	"west bengal": ("19",),
	"jharkhand": ("20",),
	"odisha": ("21",),
	"orissa": ("21",),
	"chhattisgarh": ("22",),
	"madhya pradesh": ("23",),
	"gujarat": ("24",),
	"daman and diu": ("25", "26"),
	"dadra and nagar haveli": ("26", "25"),
	"dadra and nagar haveli and daman and diu": ("26", "25"),
	"maharashtra": ("27",),
	"andhra pradesh": ("37", "28"),
	"karnataka": ("29",),
	"goa": ("30",),
	"lakshadweep": ("31",),
	"kerala": ("32",),
	"tamil nadu": ("33",),
	"puducherry": ("34",),
	"pondicherry": ("34",),
	"andaman and nicobar islands": ("35",),
	"telangana": ("36",),
	"ladakh": ("38",),
}

GST_CODE_STATE = {
	"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
	"05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
	"10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
	"15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
	"20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
	"24": "Gujarat", "25": "Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu",
	"27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa",
	"31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
	"35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
	"38": "Ladakh", "97": "Other Territory",
}

IDENTIFIER_LABEL = {"gst_no": "GSTIN", "pan_no": "PAN", "customer_business_name": "Customer Name"}


def status_of(doc_or_value):
	"""A blank status is a buyer from before the workflow: it counts as Approved."""
	value = doc_or_value.get("buyer_status") if hasattr(doc_or_value, "get") else doc_or_value
	return value or APPROVED


def catalog_of(doc_or_value):
	value = doc_or_value.get("buyer_catalog_status") if hasattr(doc_or_value, "get") else doc_or_value
	return value or CATALOG_COMPLETED


# ----------------------------------------------------------------------------- before validate


def before_validate(doc):
	before = None if doc.is_new() else doc.get_doc_before_save()
	if doc.is_new():
		_start(doc)
		return
	_guard_status_fields(doc, before)
	if is_sales_officer_only() and not doc.flags.alpinos_buyer_status_action:
		_limit_sales_officer(doc, before)


def _start(doc):
	"""Starting status (4.2): a Sales Officer's buyer waits for approval; anyone else's is
	approved at once. Either way an Offline buyer's catalogue is still to be set up (4.4)."""
	if doc.flags.alpinos_keep_status:
		return
	now = now_datetime()
	officer = is_sales_officer_only()
	if officer:
		# "Fixed to Offline for SO creation. E-Commerce workflow excluded." (3.1)
		doc.channel = "Offline"
	if not is_offline(doc.get("channel")):
		doc.buyer_status = APPROVED
		doc.buyer_catalog_status = CATALOG_COMPLETED
		for f in ("approved_by", "approver_role", "approved_on", "catalog_completed_by", "catalog_completed_on"):
			doc.set(f, None)
		return

	if officer:
		# pricing is not the Sales Officer's (3.1)
		if any(flt(r.get("margin_percent")) for r in doc.get("margins") or []):
			frappe.throw(
				_("A Sales Officer cannot set Buyer Catalog pricing. Leave the Margins table to the Sales Manager or Sales Admin."),
				frappe.PermissionError,
				title=_("Not Permitted"),
			)
		doc.buyer_status = PENDING
		doc.approved_by = doc.approver_role = doc.approved_on = None
	else:
		doc.buyer_status = APPROVED
		doc.approved_by = frappe.session.user
		doc.approver_role = acting_role() or None
		doc.approved_on = now
	doc.buyer_catalog_status = CATALOG_PENDING
	doc.catalog_completed_by = doc.catalog_completed_on = None
	doc.status_reason = None
	doc.escalated_on = None

	# "Default Primary POCs auto-populate" (3.3)
	have = {r.employee for r in doc.get("primary_pocs") or [] if r.employee}
	for employee in settings.default_primary_pocs(eligible_only=True):
		if employee not in have:
			doc.append("primary_pocs", {"employee": employee})
			have.add(employee)


def _guard_status_fields(doc, before):
	if doc.flags.alpinos_buyer_status_action or not before:
		return
	old, new = before.get("buyer_status"), doc.get("buyer_status")
	if (old or "") != (new or "") and new:
		if old == CANCELLED:
			frappe.throw(_cancelled_message(), title=_("Not Permitted"))
		frappe.throw(
			_("Buyer Status changes only through the Approve Buyer, Put Buyer On Hold, Make Buyer Inactive, Reactivate Buyer and Cancel Buyer actions."),
			title=_("Not Permitted"),
		)
	# the rest are written by the system alone: a stale form or an import keeps the stored value
	for field in STATUS_FIELDS:
		doc.set(field, before.get(field))


def _cancelled_message():
	return _("Cancelled Buyer Master cannot be reactivated. Please create a new Buyer Master if the Buyer needs to be onboarded again.")


def _limit_sales_officer(doc, before):
	status = status_of(before)
	if status not in CORRECTABLE:
		frappe.throw(
			_("This Buyer is {0}. A Sales Officer can change a Buyer Master only while it is Pending Approval or On Hold.").format(status),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	changed = [df.label or df.fieldname for df in _changed_fields(doc, before) if df.fieldname not in SO_EDITABLE]
	if changed:
		frappe.throw(
			_("A Sales Officer cannot change {0}. Only the fields of the buyer creation form can be corrected.").format(
				", ".join(frappe.bold(_(c)) for c in changed)
			),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)
	defaults = set(settings.default_primary_pocs())
	had = {r.employee for r in before.get("primary_pocs") or []} & defaults
	has = {r.employee for r in doc.get("primary_pocs") or []}
	removed = had - has
	if removed:
		frappe.throw(
			_("A Sales Officer cannot remove the default Primary POC {0}.").format(", ".join(sorted(removed))),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)


def _norm(df, value):
	if df.fieldtype in ("Check", "Int"):
		return cint(value)
	if df.fieldtype in ("Float", "Currency", "Percent"):
		return round(flt(value), 6)
	return cstr(value).strip()


def _table_rows(doc, df):
	meta = frappe.get_meta(df.options)
	keys = [f.fieldname for f in meta.fields if f.fieldtype not in _LAYOUT]
	return [tuple(_norm(meta.get_field(k), r.get(k)) for k in keys) for r in doc.get(df.fieldname) or []]


def _changed_fields(doc, before):
	"""Fields a person changed (not the ones the controller derives)."""
	out = []
	for df in doc.meta.fields:
		if df.fieldtype in _LAYOUT or df.fieldname in STATUS_FIELDS or df.fieldname in SYSTEM_SET:
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			if _table_rows(doc, df) != _table_rows(before, df):
				out.append(df)
		elif _norm(df, doc.get(df.fieldname)) != _norm(df, before.get(df.fieldname)):
			out.append(df)
	return out


# ----------------------------------------------------------------------------- validate


def validate(doc):
	before = None if doc.is_new() else doc.get_doc_before_save()
	validate_duplicate(doc, before)
	if is_offline(doc.get("channel")):
		_validate_gstin_state(doc, before)
		_validate_contact(doc, before)
		_complete_catalog_from_margins(doc)


def _identifier(gst_type, gst_no=None, pan_no=None, business_name=None):
	if gst_type == "Registered Business":
		return "gst_no", cstr(gst_no).strip().upper()
	if gst_type == "Unregistered Business":
		return "pan_no", cstr(pan_no).strip().upper()
	if gst_type == "Overseas":
		return "customer_business_name", re.sub(r"\s+", " ", cstr(business_name)).strip().lower()
	return None, ""


def find_duplicate(gst_type, gst_no=None, pan_no=None, business_name=None, exclude=None, parent_buyer=None, is_parent=0):
	"""The existing buyer a new one would duplicate (3.1.1), or None.

	A Cancelled buyer never counts; a buyer of the same family (parent and its sites) shares
	its GSTIN by design and does not count either.
	"""
	field, value = _identifier(gst_type, gst_no, pan_no, business_name)
	if not field or not value:
		return None
	if field == "customer_business_name":
		match = "LOWER(TRIM(REGEXP_REPLACE(IFNULL(bm.customer_business_name, ''), '[[:space:]]+', ' '))) = %(v)s"
	else:
		match = f"UPPER(TRIM(IFNULL(bm.{field}, ''))) = %(v)s"
	rows = frappe.db.sql(
		f"""
		SELECT bm.name, bm.customer_business_name, bm.buyer_status, bm.parent_buyer, bm.is_parent
		FROM `tabBuyer Master` bm
		WHERE {match}
			AND bm.name != %(ex)s
			AND IFNULL(bm.buyer_status, '') != %(cancelled)s
		ORDER BY (IFNULL(bm.buyer_status, '') = %(inactive)s) DESC, bm.creation ASC
		""",
		{"v": value, "ex": exclude or "", "cancelled": CANCELLED, "inactive": INACTIVE},
		as_dict=True,
	)
	mine = parent_buyer or (exclude if cint(is_parent) else None)
	for row in rows:
		theirs = row.parent_buyer or (row.name if cint(row.is_parent) else None)
		if mine and theirs and mine == theirs:
			continue
		row.field = field
		row.label = IDENTIFIER_LABEL[field]
		row.value = value
		row.buyer_status = status_of(row.buyer_status)
		return row
	return None


def duplicate_message(row):
	ref = f"{row.name} ({row.customer_business_name})"
	if row.buyer_status == INACTIVE:
		return _(
			"This Buyer already exists but is currently Inactive. Please reactivate the existing Buyer instead of creating a new Buyer. Existing Buyer: {0}"
		).format(ref)
	return _("A Buyer with this {0} already exists: {1}, status {2}. A new Buyer Master cannot be created for it.").format(
		_(row.label), ref, _(row.buyer_status)
	)


def validate_duplicate(doc, before=None):
	field, value = _identifier(doc.get("gst_type"), doc.get("gst_no"), doc.get("pan_no"), doc.get("customer_business_name"))
	if not field or not value:
		return
	if field != "gst_no" and not is_offline(doc.get("channel")):
		return  # E-com keeps the GSTIN rule it always had, nothing more
	if before is not None:
		old_field, old_value = _identifier(
			before.get("gst_type"), before.get("gst_no"), before.get("pan_no"), before.get("customer_business_name")
		)
		if (old_field, old_value) == (field, value):
			return  # unchanged: an old shared GSTIN is left as it is
	row = find_duplicate(
		doc.get("gst_type"), doc.get("gst_no"), doc.get("pan_no"), doc.get("customer_business_name"),
		exclude=None if doc.is_new() else doc.name, parent_buyer=doc.get("parent_buyer"), is_parent=doc.get("is_parent"),
	)
	if row:
		frappe.throw(duplicate_message(row), title=_("Duplicate Buyer"))


def _state_codes(state):
	return GST_STATE_CODES.get(cstr(state).strip().lower())


def _validate_gstin_state(doc, before):
	gstin = cstr(doc.get("gst_no")).strip().upper()
	if doc.get("gst_type") != "Registered Business" or len(gstin) < 2:
		return
	gstin_changed = before is None or cstr(before.get("gst_no")).strip().upper() != gstin

	# A row is judged when it is new or its state / billing / shipping changed. Rows are matched
	# by content, not by row ID: the Buyer Catalog page rewrites every address row on save, and
	# an old mismatch (11 buyers on UAT, 13 Nov 2026) must not block an unrelated edit there.
	def key(r):
		return (cstr(r.get("state")).strip().lower(), cint(r.get("is_primary")), cint(r.get("is_shipping")))

	old_keys = {key(r) for r in (before.get("addresses") if before else None) or []}
	code = gstin[:2]
	for row in doc.get("addresses") or []:
		if not (cint(row.get("is_primary")) or cint(row.get("is_shipping"))) or not row.get("state"):
			continue
		if not gstin_changed and key(row) in old_keys:
			continue
		codes = _state_codes(row.state)
		if not codes or code in codes:
			continue  # a state the table does not know (or a city typed as a state) is not judged
		frappe.throw(
			_("Address row #{0}: GSTIN state code does not match the selected address state. GSTIN state code {1} corresponds to {2}, while the selected state is {3}. Please correct the GSTIN or address state.").format(
				row.idx, code, GST_CODE_STATE.get(code, _("another state")), row.state
			),
			title=_("GSTIN State Mismatch"),
		)


def mobile_digits(value):
	"""A typed phone number as its digits, without a +91 / 0 prefix."""
	digits = re.sub(r"\D", "", cstr(value))
	if len(digits) == 12 and digits.startswith("91"):
		digits = digits[2:]
	elif len(digits) == 11 and digits.startswith("0"):
		digits = digits[1:]
	return digits


def _validate_contact(doc, before):
	def changed(field):
		return before is None or cstr(before.get(field)).strip() != cstr(doc.get(field)).strip()

	email = cstr(doc.get("email")).strip()
	if email and changed("email") and not frappe.utils.validate_email_address(email):
		frappe.throw(_("Email Address {0} is not a valid email address.").format(frappe.bold(email)), title=_("Contact"))
	if doc.get("gst_type") == "Overseas":
		return  # a foreign number is not a 10-digit Indian mobile
	for field, label in (("contact_no", _("Contact No")), ("alternate_no", _("Alternate No"))):
		value = cstr(doc.get(field)).strip()
		if value and changed(field) and not re.fullmatch(r"[6-9][0-9]{9}", mobile_digits(value)):
			frappe.throw(_("{0} must be a 10-digit mobile number.").format(label), title=_("Contact"))


def _complete_catalog_from_margins(doc):
	"""SKU margins on the buyer are Buyer Catalog pricing too (Flat Discount % per SKU)."""
	if catalog_of(doc) != CATALOG_PENDING or status_of(doc) != APPROVED or is_sales_officer_only():
		return
	if any(flt(r.get("margin_percent")) > 0 and r.get("sku") for r in doc.get("margins") or []):
		mark_catalog_completed(doc, save=False)


def mark_catalog_completed(doc, save=True):
	"""Buyer Catalog setup is done (4.4): Quotations and Sales Orders may follow."""
	doc.buyer_catalog_status = CATALOG_COMPLETED
	doc.catalog_completed_by = frappe.session.user
	doc.catalog_completed_on = now_datetime()
	doc.flags.alpinos_catalog_completed = True
	if save:
		for field in ("buyer_catalog_status", "catalog_completed_by", "catalog_completed_on"):
			frappe.db.set_value("Buyer Master", doc.name, field, doc.get(field), update_modified=False)
		audit.status_change("Buyer Master", doc.name, "Buyer Catalog Completed", CATALOG_PENDING, CATALOG_COMPLETED)


# ----------------------------------------------------------------------------- trail


def after_insert(doc, method=None):
	audit.log(
		"Buyer Master", doc.name, "Buyer Master Created", _("Buyer Status"), "", status_of(doc),
	)
	for row in doc.get("sales_officers") or []:
		audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", _("Sales Officer Added"), "", _person(row.employee))
	for row in doc.get("primary_pocs") or []:
		audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", _("Primary POC Added"), "", _person(row.employee))
	if doc.get("secondary_poc"):
		audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", _("Secondary POC"), "", _person(doc.secondary_poc))


def _person(employee):
	if not employee:
		return ""
	name = frappe.db.get_value("Employee", employee, "employee_name")
	return f"{employee} ({name})" if name else employee


def _row_text(row, fields):
	return ", ".join(cstr(row.get(f)) for f in fields if cstr(row.get(f)).strip())


_ADDRESS_FIELDS = ("site_name", "address_line", "city", "state", "pincode")


def on_update(doc, method=None):
	"""Every change a person made, as trail lines (4.5); assignments as added / removed."""
	if doc.flags.alpinos_catalog_completed:
		audit.status_change("Buyer Master", doc.name, "Buyer Catalog Completed", CATALOG_PENDING, CATALOG_COMPLETED)
	before = doc.get_doc_before_save()
	if not before:
		return
	action = "Buyer Master Corrected" if status_of(before) in CORRECTABLE else "Buyer Master Edited"
	for df in _changed_fields(doc, before):
		if df.fieldname in _NOT_AUDITED:
			continue
		label = _(df.label or df.fieldname)
		if df.fieldname in ("sales_officers", "primary_pocs"):
			old = {r.employee for r in before.get(df.fieldname) or []}
			new = {r.employee for r in doc.get(df.fieldname) or []}
			what = _("Sales Officer") if df.fieldname == "sales_officers" else _("Primary POC")
			for e in sorted(new - old):
				audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", _("{0} Added").format(what), "", _person(e))
			for e in sorted(old - new):
				audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", _("{0} Removed").format(what), _person(e), "")
		elif df.fieldname == "secondary_poc":
			audit.log("Buyer Master", doc.name, "Buyer Assignment Changed", label,
				_person(before.get("secondary_poc")), _person(doc.get("secondary_poc")))
			from alpinos.offline_sales.access import refresh_quotation_secondary_poc

			refresh_quotation_secondary_poc(doc.name, doc.get("secondary_poc"))
		elif df.fieldname == "addresses":
			old = {r.name: r for r in before.get("addresses") or []}
			for row in doc.get("addresses") or []:
				prev = old.pop(row.name, None) if row.name else None
				new_text, old_text = _row_text(row, _ADDRESS_FIELDS), _row_text(prev, _ADDRESS_FIELDS) if prev else ""
				if new_text != old_text:
					audit.log("Buyer Master", doc.name, action, _("Address row {0}").format(row.idx), old_text, new_text)
			for prev in old.values():
				audit.log("Buyer Master", doc.name, action, _("Address Removed"), _row_text(prev, _ADDRESS_FIELDS), "")
		elif df.fieldname == "margins":
			catalog_action = (
				"Buyer Catalog Synced from Sales Order" if frappe.flags.alpinos_catalog_sync else "Buyer Catalog Changed"
			)
			old = {r.sku: flt(r.margin_percent) for r in before.get("margins") or [] if r.sku}
			new = {r.sku: flt(r.margin_percent) for r in doc.get("margins") or [] if r.sku}
			for sku in sorted(set(old) | set(new)):
				if old.get(sku) != new.get(sku):
					audit.log("Buyer Master", doc.name, catalog_action, _("Flat Discount %"),
						"" if sku not in old else old[sku], "" if sku not in new else new[sku], item_code=sku)
		elif df.fieldtype in ("Table", "Table MultiSelect"):
			audit.log("Buyer Master", doc.name, action, label, _("{0} rows").format(len(before.get(df.fieldname) or [])),
				_("{0} rows").format(len(doc.get(df.fieldname) or [])))
		else:
			audit.log("Buyer Master", doc.name, action, label, before.get(df.fieldname), doc.get(df.fieldname))
