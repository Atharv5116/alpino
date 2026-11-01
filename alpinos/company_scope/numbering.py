"""Document numbers per company.

A company with a Series Code (Company.custom_series_code) gets it in its document numbers,
right after the series' first part:

    SOR-2627-.#####    ->  SOR-APC-2627-.#####     (SOR-APC-2627-00001)
    POR-.FYS.-.#####   ->  POR-APC-.FYS.-.#####
    MAT-DN-.YYYY.-     ->  MAT-APC-DN-.YYYY.-

Each company counts on its own (the counter is per prefix). A company without a code - Alpino
Health Foods - keeps its numbers exactly as they are. Applies to every document named by a
naming series; runs on before_naming, after alpinos' own before_insert has chosen the series.
"""

import frappe


def series_code(company):
	if not company:
		return None
	return (frappe.get_cached_value("Company", company, "custom_series_code") or "").strip() or None


def with_code(series, code):
	if not series or not code or "-" not in series:
		return series
	head, rest = series.split("-", 1)
	if rest.startswith(code + "-"):
		return series
	return f"{head}-{code}-{rest}"


def before_naming(doc, method=None):
	if not doc.get("naming_series") or doc.get("amended_from"):
		return
	company = doc.get("company")
	if not company:
		return
	code = series_code(company)
	if code:
		doc.naming_series = with_code(doc.naming_series, code)
