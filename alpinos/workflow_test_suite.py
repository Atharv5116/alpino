"""Operations workflow — repeatable test suite (roles, lifecycle, validations,
cancellation guards).

Run it against a site:

    bench --site <site> console
    >>> import alpinos.workflow_test_suite as t; t.run()

It is idempotent and self-cleaning: it provisions test users / an offline-buyer
master / geo fixtures, drives a full Sales Order -> Pick List -> Delivery Note
lifecycle through the real frontend server methods AS the role that owns each
step, asserts the workflow status at every stage, then verifies the permission
matrix, the validation rules and the cancellation guards. Created documents are
deleted at the end.

Requires master data that already exists on the Alpinos sites: a customer
(default "Test Combo Buyer"), company "Alpinos Health Foods", and a simple
stocked item (default "CA"). Override via the constants below if needed.
"""
import json

import frappe

CUSTOMER = "Test Combo Buyer"
COMPANY = "Alpinos Health Foods"
ITEM = "CA"
ORDER_TYPE = "GENERAL TRADE"
DISPATCH_DATE = "2026-06-22"

USERS = {
	"sm": ("wf_sales_manager@test.com", ["Sales Manager"]),
	"sadmin": ("wf_sales_admin@test.com", ["Sales Admin"]),
	"suser": ("wf_sales_user@test.com", ["Sales User"]),
	"wadmin": ("wf_wh_admin@test.com", ["Warehouse Admin"]),
	"pluser": ("wf_pl_user@test.com", ["PL User"]),
	"dnuser": ("wf_dn_user@test.com", ["DN User"]),
	"whuser": ("wf_wh_user@test.com", ["Warehouse User"]),
}


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

class _Results:
	def __init__(self):
		self.rows = []

	def check(self, name, cond, detail=""):
		self.rows.append((name, bool(cond), detail))
		print(("PASS" if cond else "FAIL"), "|", name, ("" if cond else "-> " + str(detail)))

	def summary(self):
		p = sum(1 for _, ok, _ in self.rows if ok)
		f = len(self.rows) - p
		print("\n===== SUMMARY: %d PASS / %d FAIL of %d =====" % (p, f, len(self.rows)))
		for n, ok, d in self.rows:
			if not ok:
				print("  FAIL:", n, "->", d)
		return {"pass": p, "fail": f, "total": len(self.rows)}


def _admin():
	frappe.set_user("Administrator")


def _u(key):
	return USERS[key][0]


def _wf(dt, name):
	return frappe.db.get_value(dt, name, "custom_workflow_status")


# ---------------------------------------------------------------------------
# Fixtures (idempotent)
# ---------------------------------------------------------------------------

def _ensure_fixtures():
	_admin()
	for _, (email, roles) in USERS.items():
		if not frappe.db.exists("User", email):
			frappe.get_doc({
				"doctype": "User", "email": email, "first_name": email.split("@")[0],
				"send_welcome_email": 0, "user_type": "System User",
			}).insert(ignore_permissions=True)
		u = frappe.get_doc("User", email)
		have = {r.role for r in u.roles}
		for r in roles:
			if r not in have:
				u.append("roles", {"role": r})
		u.save(ignore_permissions=True)

	# Address Template (offline-buyer master auto-creates an Address).
	if not frappe.db.exists("Address Template", {"is_default": 1}):
		frappe.get_doc({
			"doctype": "Address Template", "country": "India", "is_default": 1,
			"template": "{{ address_line1 }}",
		}).insert(ignore_permissions=True)

	# Geo fixtures for the offline-buyer address (State/City may be empty).
	for gd in [
		{"doctype": "State", "state_name": "Gujarat", "country": "India"},
		{"doctype": "City", "city_name": "Ahmedabad", "state": "Gujarat", "country": "India"},
	]:
		nm = gd.get("state_name") or gd.get("city_name")
		if not frappe.db.exists(gd["doctype"], nm):
			frappe.get_doc(gd).insert(ignore_permissions=True)

	# Offline Buyer Master so the customer passes the offline-buyer SO check.
	if not frappe.db.exists("Offline Buyer Master", {"customer": CUSTOMER}):
		frappe.get_doc({
			"doctype": "Offline Buyer Master", "customer": CUSTOMER,
			"customer_business_name": "WF Test Business", "customer_type": ORDER_TYPE,
			"gst_type": "Unregistered Business", "level": "N/A", "payment_term": "NA",
			"email": "wfbuyer@test.com", "contact_no": "9999999999", "contact_person": "WF Tester",
			"addresses": [{
				"is_primary": 1, "is_shipping": 1, "address_line": "1 Test St",
				"city": "Ahmedabad", "state": "Gujarat", "pincode": "380001",
				"country": "India", "address_label": "Main",
			}],
			"margins": [{"margin_percent": 0}],
		}).insert(ignore_permissions=True)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Helpers to build documents through the real frontend methods
# ---------------------------------------------------------------------------

def _create_so(as_user=None, submit=False, items=None):
	from alpinos.sales_order_api import create_sales_order

	if as_user:
		frappe.set_user(as_user)
	if items is None:
		items = [{"item_code": ITEM, "qty": 10, "custom_customer_mrp": 100, "custom_gst_percent": 0}]
	so = create_sales_order(
		CUSTOMER, ORDER_TYPE, COMPANY, json.dumps(items),
		dispatch_date=DISPATCH_DATE, submit_now=0,
	)
	so = so if isinstance(so, str) else getattr(so, "name", None) or so.get("name")
	if submit:
		frappe.get_doc("Sales Order", so).submit()
	return so


def _create_pl(so):
	from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import create_pick_list_as_draft
	from alpinos.sales_order_api import get_pick_list_mapping_data

	mp = get_pick_list_mapping_data(so)
	items = [dict(r) for r in (mp.locations or [])]
	return create_pick_list_as_draft(so, json.dumps({}), json.dumps(items))


def _delete(dt, name):
	if name and frappe.db.exists(dt, name):
		d = frappe.get_doc(dt, name)
		if d.docstatus == 1:
			try:
				d.cancel()
			except Exception:
				pass
		try:
			frappe.delete_doc(dt, name, force=1)
		except Exception:
			pass


# ---------------------------------------------------------------------------
# 1. Full lifecycle, each stage as its owning role
# ---------------------------------------------------------------------------

def _test_lifecycle(R):
	from alpinos.workflow_engine import mark_future_dispatch, start_picking, mark_delivered
	from alpinos.pick_list_api import generate_pick_list_stickers, create_delivery_note_from_pick_list

	so = pl = dn = None
	try:
		# Sales Manager creates + submits SO
		so = _create_so(as_user=_u("sm"))
		R.check("SO created by Sales Manager (no access error)", bool(so))
		R.check("SO status Draft", _wf("Sales Order", so) == "Draft", _wf("Sales Order", so))
		frappe.get_doc("Sales Order", so).submit()
		R.check("SO submit -> Warehouse Approval Pending",
				_wf("Sales Order", so) == "Warehouse Approval Pending", _wf("Sales Order", so))

		# Warehouse Admin marks Future Dispatch
		frappe.set_user(_u("wadmin"))
		mark_future_dispatch(so, "2026-07-01")
		R.check("Future Dispatch by Warehouse Admin", _wf("Sales Order", so) == "Future Dispatch", _wf("Sales Order", so))

		# Warehouse Admin creates Pick List
		frappe.set_user(_u("wadmin"))
		pl = _create_pl(so)
		R.check("PL created by Warehouse Admin (no access error)", bool(pl))
		R.check("SO -> Warehouse Approved", _wf("Sales Order", so) == "Warehouse Approved", _wf("Sales Order", so))
		R.check("PL status Draft", _wf("Pick List", pl) == "Draft", _wf("Pick List", pl))

		# Assign picker + transporter -> Picking Pending
		d = frappe.get_doc("Pick List", pl)
		d.custom_assigned_to = _u("pluser")
		d.custom_transporter = "Test Transporter"
		d.save()
		R.check("PL -> Picking Pending after assignment", _wf("Pick List", pl) == "Picking Pending", _wf("Pick List", pl))

		# PL User starts picking
		frappe.set_user(_u("pluser"))
		start_picking(pl)
		R.check("Start Picking by PL User (no access error)",
				_wf("Pick List", pl) in ("Picking In Progress", "Sticker Pending"), _wf("Pick List", pl))
		R.check("SO -> Picking In Progress", _wf("Sales Order", so) == "Picking In Progress", _wf("Sales Order", so))

		# Sticker -> Submission Pending (PDF render needs wkhtmltopdf on server)
		frappe.set_user(_u("wadmin"))
		try:
			generate_pick_list_stickers(pl)
		except OSError as oe:
			R.check("Sticker generation (env note)", "wkhtmltopdf" in str(oe), str(oe)[:60])
		R.check("PL -> Submission Pending after sticker",
				_wf("Pick List", pl) == "Submission Pending", _wf("Pick List", pl))

		# Submit PL -> Ready To Dispatch / SO Ready For Dispatch
		frappe.set_user(_u("wadmin"))
		frappe.get_doc("Pick List", pl).submit()
		R.check("PL submit by Warehouse Admin (no access error)", True)
		R.check("PL -> Ready To Dispatch", _wf("Pick List", pl) == "Ready To Dispatch", _wf("Pick List", pl))
		R.check("SO -> Ready For Dispatch", _wf("Sales Order", so) == "Ready For Dispatch", _wf("Sales Order", so))

		# Warehouse Admin creates DN
		frappe.set_user(_u("wadmin"))
		dn = create_delivery_note_from_pick_list(pl)
		R.check("DN created by Warehouse Admin (no access error)", bool(dn))
		R.check("SO -> Delivery Note Created", _wf("Sales Order", so) == "Delivery Note Created", _wf("Sales Order", so))

		# DN User enters logistics + submits -> Dispatched
		frappe.set_user(_u("dnuser"))
		d = frappe.get_doc("Delivery Note", dn)
		if frappe.get_meta("Delivery Note").get_field("custom_lr_gr_no"):
			d.custom_lr_gr_no = "LR-TEST-123"
		if not d.get("vehicle_no"):
			d.vehicle_no = "PO-TEST-1"
		if not d.get("custom_dispatch_from"):
			d.custom_dispatch_from = "Main Warehouse"
		if not (d.get("custom_dispatch_to") or []):
			d.append("custom_dispatch_to", {"dispatch_to_address": "Test Dispatch Address"})
		d.save()
		d.submit()
		R.check("DN submit by DN User (no access error)", frappe.db.get_value("Delivery Note", dn, "docstatus") == 1)
		R.check("PL -> Dispatched", _wf("Pick List", pl) == "Dispatched", _wf("Pick List", pl))
		R.check("SO -> Dispatched", _wf("Sales Order", so) == "Dispatched", _wf("Sales Order", so))

		# Sales Manager marks Delivered -> Completed
		frappe.set_user(_u("sm"))
		mark_delivered(so)
		R.check("Mark Delivered by Sales Manager -> Completed", _wf("Sales Order", so) == "Completed", _wf("Sales Order", so))
	except Exception as e:
		R.check("Lifecycle ran without unexpected error", False, type(e).__name__ + ": " + str(e)[:200])
	finally:
		_admin()
		_delete("Delivery Note", dn)
		_delete("Pick List", pl)
		_delete("Sales Order", so)
		frappe.db.commit()


# ---------------------------------------------------------------------------
# 2. Permission matrix (frontend access) per role
# ---------------------------------------------------------------------------

PERMISSION_EXPECT = {
	"sm": {"Sales Order": {"create": 1, "write": 1, "submit": 1, "cancel": 1, "delete": 0},
		   "Pick List": {"read": 1, "create": 0, "write": 0},
		   "Delivery Note": {"read": 1, "create": 0, "write": 0}},
	"suser": {"Sales Order": {"read": 1, "create": 0, "write": 0, "submit": 0}},
	"sadmin": {"Sales Order": {"create": 1, "write": 1, "submit": 1, "cancel": 1, "delete": 1},
			   "Pick List": {"read": 1, "write": 0}, "Delivery Note": {"read": 1, "write": 0}},
	"wadmin": {"Sales Order": {"read": 1, "create": 0, "write": 0},
			   "Pick List": {"create": 1, "write": 1, "submit": 1, "cancel": 1, "delete": 1},
			   "Delivery Note": {"create": 1, "write": 1, "submit": 1}},
	"pluser": {"Pick List": {"read": 1, "write": 1, "create": 0, "submit": 0},
			   "Sales Order": {"read": 0}, "Delivery Note": {"read": 0}},
	"dnuser": {"Delivery Note": {"read": 1, "write": 1, "submit": 1, "create": 0},
			   "Pick List": {"read": 0}, "Sales Order": {"read": 0}},
	"whuser": {"Pick List": {"read": 1, "write": 1, "submit": 0},
			   "Delivery Note": {"read": 1, "write": 1, "submit": 1}},
}


def _test_permissions(R):
	try:
		for key, dts in PERMISSION_EXPECT.items():
			user = _u(key)
			frappe.set_user(user)
			for dt, ptypes in dts.items():
				for pt, exp in ptypes.items():
					got = 1 if frappe.has_permission(dt, ptype=pt) else 0
					R.check("perm %s: %s.%s == %d" % (key, dt, pt, exp), got == exp, "got %d" % got)
	finally:
		_admin()


# ---------------------------------------------------------------------------
# 3. Validation rules
# ---------------------------------------------------------------------------

def _test_validations(R):
	so = pl = None
	try:
		# SO with no items is rejected
		frappe.set_user(_u("sm"))
		try:
			_create_so(items=[])
			R.check("SO create with no items is rejected", False, "no error raised")
		except Exception as e:
			R.check("SO create with no items is rejected", "item" in str(e).lower(), str(e)[:80])

		# PL picked qty > ordered is rejected. Build as Sales Manager / Admin,
		# but edit the PL as Warehouse Admin (who has Pick List write) so the
		# qty rule — not a permission error — is what we exercise.
		_admin()
		so = _create_so(as_user=_u("sm"), submit=True)
		_admin()
		pl = _create_pl(so)
		frappe.set_user(_u("wadmin"))
		d = frappe.get_doc("Pick List", pl)
		if d.locations:
			# Set an explicit ordered qty and pick beyond it so the rule fires
			# (the rule is skipped when there is no ordered qty to compare against).
			d.locations[0].custom_ordered_qty = 5
			d.locations[0].qty = 100
			try:
				d.save()
				R.check("PL picked qty > ordered is rejected", False, "no error raised")
			except Exception as e:
				msg = str(e).lower()
				R.check("PL picked qty > ordered is rejected", "exceed" in msg or "greater" in msg, str(e)[:80])
	except Exception as e:
		R.check("Validation tests ran without unexpected error", False, type(e).__name__ + ": " + str(e)[:160])
	finally:
		_admin()
		_delete("Pick List", pl)
		_delete("Sales Order", so)
		frappe.db.commit()


# ---------------------------------------------------------------------------
# 4. Cancellation guards (each on its own fresh documents)
# ---------------------------------------------------------------------------

def _test_cancellations(R):
	from alpinos.workflow_engine import mark_sticker_printed
	from alpinos.pick_list_api import create_delivery_note_from_pick_list

	# C1: SO cancel blocked while an active Pick List exists
	so = pl = dn = None
	try:
		so = _create_so(as_user=_u("sm"), submit=True)
		_admin()
		pl = _create_pl(so)
		frappe.set_user(_u("sm"))
		try:
			frappe.get_doc("Sales Order", so).cancel()
			R.check("SO cancel blocked by active Pick List", False, "cancel succeeded")
		except Exception as e:
			R.check("SO cancel blocked by active Pick List", "Pick List" in str(e), str(e)[:80])
	except Exception as e:
		R.check("C1 setup ok", False, str(e)[:160])
	finally:
		_admin()
		_delete("Pick List", pl)
		_delete("Sales Order", so)
		frappe.db.commit()

	# C2: Pick List cancel blocked while an active Delivery Note exists
	so = pl = dn = None
	try:
		so = _create_so(as_user=_u("sm"), submit=True)
		_admin()
		pl = _create_pl(so)
		d = frappe.get_doc("Pick List", pl)
		d.custom_assigned_to = _u("pluser")
		d.custom_transporter = "T"
		d.save()
		frappe.db.set_value("Pick List", pl, "custom_picking_started", 1)
		mark_sticker_printed(pl)
		frappe.get_doc("Pick List", pl).submit()
		dn = create_delivery_note_from_pick_list(pl)
		try:
			frappe.get_doc("Pick List", pl).cancel()
			R.check("PL cancel blocked by active Delivery Note", False, "cancel succeeded")
		except Exception as e:
			R.check("PL cancel blocked by active Delivery Note", "Delivery Note" in str(e), str(e)[:80])
	except Exception as e:
		R.check("C2 setup ok", False, str(e)[:160])
	finally:
		_admin()
		_delete("Delivery Note", dn)
		_delete("Pick List", pl)
		_delete("Sales Order", so)
		frappe.db.commit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
	_ensure_fixtures()
	R = _Results()
	print("\n========== 1. LIFECYCLE (each stage as its role) ==========")
	_test_lifecycle(R)
	print("\n========== 2. PERMISSION MATRIX ==========")
	_test_permissions(R)
	print("\n========== 3. VALIDATION RULES ==========")
	_test_validations(R)
	print("\n========== 4. CANCELLATION GUARDS ==========")
	_test_cancellations(R)
	_admin()
	return R.summary()
