"""Regression tests for after-submit paperwork edits (run on a TEST site).

Run:  cd ~/frappe-bench/sites && ~/frappe-bench/env/bin/python -c \
        "import frappe; frappe.init(site='alpinos.test'); frappe.connect(); \
         from alpinos import after_submit_test as t; t.run()"

The case these pin down: ERPNext's PickList.on_update_after_submit refuses ANY save once
a pick list has Stock Reservation Entries, and the Alpinos flow reserves stock FROM every
pick list on creation -- so correcting a dispatch date after dispatch was arranged threw
"The Pick List having Stock Reservation Entries cannot be updated". CustomPickList now
skips that guard for allow_on_submit paperwork with no picked row moved, and keeps it for
everything else.
"""

import json

import frappe
from frappe.utils import add_days, today

R = []


def _check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:90]}"))


def _reserved_pick_list():
	"""A submitted Pick List that actually holds Stock Reservation Entries."""
	rows = frappe.db.sql(
		"""
		select p.name
		from `tabPick List` p
		join `tabStock Reservation Entry` s
		  on s.from_voucher_type = 'Pick List' and s.from_voucher_no = p.name and s.docstatus = 1
		where p.docstatus = 1
		limit 1
		""",
		as_dict=True,
	)
	return rows[0].name if rows else None


def run():
	R.clear()
	frappe.set_user("Administrator")

	pick_list = _reserved_pick_list()
	if not pick_list:
		print("SKIPPED: no submitted Pick List with Stock Reservation Entries on this site")
		return R

	from alpinos.after_submit_sync import update_after_submit_fields

	def reserved_precondition():
		doc = frappe.get_doc("Pick List", pick_list)
		assert doc.has_reserved_stock(), f"{pick_list} holds no reservation, nothing is being tested"

	def dispatch_date_is_editable():
		target = str(add_days(today(), 4))
		update_after_submit_fields(
			"Pick List", pick_list, json.dumps({"custom_dispatch_date": target})
		)
		frappe.db.commit()
		got = str(frappe.db.get_value("Pick List", pick_list, "custom_dispatch_date"))
		assert got == target, f"dispatch date is {got}, expected {target}"

	def transporter_is_editable():
		# A fresh value every run: an unchanged value makes update_after_submit_fields a
		# no-op, which would pass even with the fix reverted and hide a regression.
		target = "REGRESSION-TPT-" + frappe.generate_hash(length=6)
		update_after_submit_fields(
			"Pick List", pick_list, json.dumps({"custom_transporter": target})
		)
		frappe.db.commit()
		got = frappe.db.get_value("Pick List", pick_list, "custom_transporter")
		assert got == target, f"transporter is {got!r}, expected {target!r}"

	def the_edit_is_still_audited():
		before = frappe.db.count("Field Change Log", {"reference_name": pick_list})
		update_after_submit_fields(
			"Pick List", pick_list, json.dumps({"custom_dispatch_date": str(add_days(today(), 7))})
		)
		frappe.db.commit()
		after = frappe.db.count("Field Change Log", {"reference_name": pick_list})
		assert after > before, "the change was not written to the audit log"
		assert frappe.db.get_value("Pick List", pick_list, "custom_changed_after_submit"), (
			"custom_changed_after_submit was not set"
		)

	def reservation_guard_still_fires():
		"""group_same_items is allow_on_submit but re-groups picked rows, so it is
		deliberately NOT in AFTER_SUBMIT_SAFE_FIELDS and must still be refused."""
		doc = frappe.get_doc("Pick List", pick_list)
		doc.group_same_items = 0 if doc.group_same_items else 1
		doc.flags.ignore_permissions = True
		try:
			doc.save()
		except Exception as e:
			assert "Stock Reservation Entries cannot be updated" in str(e), (
				f"blocked, but not by the reservation guard: {str(e)[:90]}"
			)
			frappe.db.rollback()
			return
		frappe.db.rollback()
		raise AssertionError("a non-paperwork change was allowed; the guard was lost")

	def override_is_actually_installed():
		from frappe.model.base_document import get_controller

		assert get_controller("Pick List").__name__ == "CustomPickList", (
			"Pick List is not using CustomPickList, so the fix is not in effect"
		)

	_check("a reserved pick list is the precondition", reserved_precondition)
	_check("Pick List is using CustomPickList", override_is_actually_installed)
	_check("dispatch date is editable on a reserved pick list", dispatch_date_is_editable)
	_check("transporter is editable on a reserved pick list", transporter_is_editable)
	_check("the after-submit edit is still audited", the_edit_is_still_audited)
	_check("the reservation guard still refuses a stock change", reservation_guard_still_fires)

	width = max(len(r[1]) for r in R)
	print("=" * (width + 12))
	print("After-submit paperwork edits")
	print("=" * (width + 12))
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 12))
	print(f"{passed}/{len(R)} passed")
	return R
