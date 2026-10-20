"""Changes(HP) #85: the Gate defaults to G-7, and the report reads it off the Pick List.

Run:  bench --site alpinos.test execute alpinos.gate_no_test.run

    1. Pick List -- Default Gate Value: change the default value of the Gate field to G-7.
    2. Accounts Format Report -- Gate No.: the column should fetch and display the value
       from the corresponding Pick List.
    3. Accounts Format Report -- Terms of Delivery: the column should also fetch and
       display the value from the corresponding Pick List.

The three are one story. Parts 2 and 3 were already built that way, so the checks below
exist to prove it rather than to change it -- and to hold it, because the thing that made
the column look empty was an empty Gate field, which part 1 fixes. A default is not a
constant: a Pick List dispatched from another gate must still be able to say so, and that
has its own check.

Fixtures roll back.
"""

import io

import frappe

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	import os

	from alpinos.alpinos_development.report.accounts_format_report import accounts_format_report as R

	# The field is created by migrate, which is DDL, and DDL cannot be rolled back -- running
	# the setup from inside a suite that neutralises commit leaves the site half-altered.
	# So the app's definition is read from the source, and the site's copy from the database.

	def _the_app_defines_the_default():
		src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
			"pick_list_custom_fields.py"), encoding="utf-8").read()
		i = src.find('fieldname="custom_gate"')
		_assert(i != -1, "the custom_gate field is no longer defined")
		# up to the next field, so the default has to belong to THIS field
		j = src.find('fieldname="', i + 30)
		block = src[i:j if j != -1 else len(src)]
		_assert('default="G-7"' in block,
			"the app does not define G-7 as the Gate default")

	check("#85.1 the app defines the Gate default as G-7", _the_app_defines_the_default)

	def _this_site_carries_it():
		dflt = frappe.db.get_value("Custom Field",
			{"dt": "Pick List", "fieldname": "custom_gate"}, "default")
		_assert(dflt == "G-7",
			f"this site's Gate field default is {dflt!r}; run bench migrate")

	check("#85.1 the field on this site carries the default", _this_site_carries_it)

	def _a_new_pick_list_gets_it():
		"""The default is only worth anything if a new document actually picks it up."""
		doc = frappe.new_doc("Pick List")
		_assert(doc.get("custom_gate") == "G-7",
			f"a new Pick List came up with Gate {doc.get('custom_gate')!r}")

	check("#85.1 a new Pick List comes up with G-7 already filled", _a_new_pick_list_gets_it)

	# ---- fixtures for the report half ----
	tag = "GATE" + frappe.generate_hash(length=4).upper()
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")

	def _insert(doctype, **values):
		d = frappe.get_doc(dict(doctype=doctype, **values))
		d.flags.ignore_mandatory = True
		d.flags.ignore_validate = True
		d.db_insert()
		return d.name

	so = _insert("Sales Order", name=f"SO-{tag}", docstatus=1, company=company,
		customer="Cust", transaction_date=frappe.utils.today())
	pl = _insert("Pick List", name=f"PL-{tag}", docstatus=1, company=company,
		custom_sales_order_id=so, purpose="Delivery",
		custom_gate="G-7", custom_po_no="PO-9911", custom_transporter="Blue Dart",
		custom_total_box=12, custom_gross_weight=345.5)

	def _the_report_reads_the_gate_off_the_pick_list():
		h = R._pl_header(so)
		_assert(h, "the report found no Pick List header at all")
		_assert("G-7" in (h.get("gate_no") or ""),
			f"Gate No. reads {h.get('gate_no')!r}, which does not carry the Pick List's G-7")

	check("#85.2 Gate No. comes from the Pick List", _the_report_reads_the_gate_off_the_pick_list)

	def _it_follows_the_pick_list_rather_than_the_default():
		"""A gate other than G-7 must reach the report unchanged.

		Without this the first check would pass just as well if the column printed a
		hardcoded G-7 and never looked at the document.
		"""
		frappe.db.set_value("Pick List", pl, "custom_gate", "B-2", update_modified=False)
		h = R._pl_header(so)
		_assert("B-2" in (h.get("gate_no") or ""),
			f"Gate No. reads {h.get('gate_no')!r} after the Pick List was changed to B-2")
		frappe.db.set_value("Pick List", pl, "custom_gate", "G-7", update_modified=False)

	check("#85.2 Gate No. follows the Pick List, not a hardcoded value",
		_it_follows_the_pick_list_rather_than_the_default)

	def _terms_of_delivery_comes_from_the_pick_list():
		h = R._pl_header(so)
		tod = h.get("terms_of_delivery") or ""
		for wanted in ("PO-9911", "12", "345.50", "Blue Dart"):
			_assert(wanted in tod, f"Terms of Delivery is missing {wanted!r}: {tod!r}")

	check("#85.3 Terms of Delivery carries the Pick List's PO, box, weight and transporter",
		_terms_of_delivery_comes_from_the_pick_list)

	def _both_columns_are_offered_by_the_report():
		cols = R.get_columns() if hasattr(R, "get_columns") else None
		if cols is None:
			_, cols = R.execute({"from_date": frappe.utils.today(), "to_date": frappe.utils.today()})[:2]
		names = {c.get("fieldname") for c in cols if isinstance(c, dict)}
		_assert("gate_no" in names, "the report has no Gate No. column")
		_assert("terms_of_delivery" in names, "the report has no Terms of Delivery column")

	check("#85 the report offers both columns", _both_columns_are_offered_by_the_report)

	def _an_unpicked_order_is_blank_rather_than_wrong():
		"""No submitted Pick List means nothing to fetch, and the cell stays empty.

		Worth holding: inventing a gate here would be worse than showing none.
		"""
		bare = _insert("Sales Order", name=f"SO-{tag}-NOPL", docstatus=1, company=company,
			customer="Cust", transaction_date=frappe.utils.today())
		h = R._pl_header(bare)
		_assert(not h.get("gate_no"),
			f"an order with no Pick List showed a gate: {h.get('gate_no')!r}")

	check("#85 an order with no Pick List shows no gate, rather than a made-up one",
		_an_unpicked_order_is_blank_rather_than_wrong)
