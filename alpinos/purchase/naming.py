"""Financial-year-wise document IDs for the purchase chain.

    Purchase Order       POR-2627-00001
    Purchase Inward      INW-2627-00001
    Purchase QC          PQC-2627-00001
    Quarantine           QRN-2627-00001
    GRN                  GRN-2627-00001
    Purchase Invoice     PIV-2627-00001

`.FYS.` is the short financial year (2026-27 -> "2627"), taken from the document's own
date. It is part of the series prefix, so every financial year counts from 00001 on its
own. Registered in hooks.py as a naming_series_variable; applied in before_insert, so a
document carrying an older series (a duplicated PO, an API caller) still gets the new ID.

Forward-only: documents already named keep their names. Debit Notes keep their own series.
"""

import frappe
from frappe.utils import getdate

FY_TOKEN = "FYS"

SERIES = {
	"Purchase Order": "POR-.FYS.-.#####",
	"Purchase Inward": "INW-.FYS.-.#####",
	"Purchase QC": "PQC-.FYS.-.#####",
	"Purchase Quarantine": "QRN-.FYS.-.#####",
	"Purchase Receipt": "GRN-.FYS.-.#####",
	"Purchase Invoice": "PIV-.FYS.-.#####",
}

# The date a document belongs to, most specific first.
_DATE_FIELDS = ("transaction_date", "posting_date", "inward_datetime", "inspection_date", "creation")


def fy_short(date=None, company=None):
	"""'2627' for any date in the financial year 2026-27."""
	date = getdate(date) if date else getdate()
	try:
		from erpnext.accounts.utils import get_fiscal_year

		_name, start, end = get_fiscal_year(date=date, company=company)[:3]
		return "%02d%02d" % (getdate(start).year % 100, getdate(end).year % 100)
	except Exception:
		# No Fiscal Year set up: the Indian April - March year.
		start_year = date.year if date.month >= 4 else date.year - 1
		return "%02d%02d" % (start_year % 100, (start_year + 1) % 100)


def parse_fys(doc, variable):
	"""naming_series_variables hook: `.FYS.` in a series."""
	date, company = None, None
	if doc:
		for field in _DATE_FIELDS:
			if doc.get(field):
				date = doc.get(field)
				break
		company = doc.get("company")
	return fy_short(date, company)


def series_for(doc):
	"""The series this document is named by, or None to leave its own."""
	if doc.doctype == "Purchase Invoice" and doc.get("is_return"):
		return None  # Debit Notes keep their own series
	if doc.doctype == "Purchase Receipt" and (doc.get("is_return") or not doc.get("custom_purchase_inward")):
		return None  # only a module GRN is a GRN
	return SERIES.get(doc.doctype)


def before_insert(doc, method=None):
	series = series_for(doc)
	if series and doc.meta.get_field("naming_series"):
		doc.naming_series = series


def setup():
	"""after_migrate: offer each series on its doctype (first, and as the default)."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for doctype, series in SERIES.items():
		meta = frappe.get_meta(doctype)
		field = meta.get_field("naming_series")
		if not field:
			continue
		current = [s.strip() for s in (field.options or "").splitlines() if s.strip()]
		# A plain Purchase Receipt keeps its own first option; only the GRN generator
		# (and before_insert) picks the GRN series.
		if doctype == "Purchase Receipt":
			wanted = [s for s in current if s != series] + [series]
		else:
			wanted = [series] + [s for s in current if s != series]
		if wanted != current:
			make_property_setter(doctype, "naming_series", "options", "\n".join(wanted), "Text",
				validate_fields_for_doctype=False)
		if doctype != "Purchase Receipt" and field.default != series:
			make_property_setter(doctype, "naming_series", "default", series, "Text",
				validate_fields_for_doctype=False)
		frappe.clear_cache(doctype=doctype)
