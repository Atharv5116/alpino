"""Offline Sales build 1 ("Opportunity to Sales Order v1.0.0", Sections 1 and 4). TEST sites only.

Run:  bench --site <test site> execute alpinos.offline_sales.offline_sales_test.run

Everything is rolled back: commits are disabled for the run, users / employees are written
with db_insert like the other buyer tests, and the settings are restored by the rollback.
"""

import json

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

R = []
TAG = "OST" + frappe.generate_hash(length=4).upper()
F = frappe._dict()


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERR ", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def refused(fn):
	"""The error text fn() raises ("" when it went through), undoing only what fn() did."""
	sp = "ost_" + frappe.generate_hash(length=6)
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:
		frappe.db.rollback(save_point=sp)
		frappe.clear_messages()
		return frappe.utils.strip_html(str(e)) or type(e).__name__
	finally:
		frappe.set_user("Administrator")
	return ""


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_validate = True
	doc.db_insert()
	return doc.name


def as_(user, fn):
	frappe.set_user(user)
	frappe.local.role_permissions = {}
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")
		frappe.local.role_permissions = {}


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	# these checks create Sales Orders on the entry page directly; the "Sales Order only from a
	# Quotation" switch (so_handoff_test covers it) is off for the run, which is rolled back
	frappe.db.set_single_value("Offline Sales Settings", "quotation_required_for_sales_order", 0)
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.clear_cache()
		frappe.set_user("Administrator")
	width = max(len(r[1]) for r in R) if R else 10
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	return R


# ----------------------------------------------------------------------------- fixtures

_SEQ = [0]


def _letters(n):
	import random
	import string

	return "".join(random.choice(string.ascii_uppercase) for _ in range(n))


def gstin(state="24"):
	return f"{state}{_letters(5)}{1000 + len(R) + _SEQ[0]:04d}{_letters(1)}1Z5"


def pan():
	return f"{_letters(5)}{2000 + len(R) + _SEQ[0]:04d}{_letters(1)}"


def _person(suffix, *roles):
	user = f"{TAG.lower()}.{suffix}@example.com"
	_insert("User", name=user, email=user, first_name=f"{TAG} {suffix}", user_type="System User", enabled=1)
	for i, role in enumerate(roles):
		_insert("Has Role", name=f"{TAG}-HR-{suffix}-{i}", parent=user, parenttype="User", parentfield="roles", role=role)
	emp = _insert(
		"Employee", name=f"{TAG}-{suffix.upper()}", employee_name=f"{TAG} {suffix.title()}", first_name=suffix,
		status="Active", company=F.company, date_of_joining="2026-01-01", user_id=user,
	)
	return frappe._dict(user=user, emp=emp)


def _fixtures():
	F.company = frappe.defaults.get_global_default("company")
	F.customer_type = frappe.db.sql(
		"SELECT customer_type FROM `tabBuyer Master` WHERE IFNULL(channel,'') != 'E-com' AND IFNULL(customer_type,'') != '' "
		"GROUP BY customer_type ORDER BY COUNT(*) DESC LIMIT 1"
	)[0][0]
	F.city_gj = frappe.db.get_value("City", {"state": "Gujarat"}, "name")
	F.city_mh = frappe.db.get_value("City", {"state": "Maharashtra"}, "name")
	F.so1 = _person("so1", "Sales Officer")
	F.so2 = _person("so2", "Sales Officer")
	F.sm1 = _person("sm1", "Sales Manager")
	F.sm2 = _person("sm2", "Sales Manager")
	F.sa1 = _person("sa1", "Sales Admin")
	F.wh = _person("wh", "Sales Officer", "Warehouse Manager")
	frappe.clear_cache()

	settings = frappe.get_single("Offline Sales Settings")
	settings.set("default_primary_pocs", [{"employee": F.sm1.emp}])
	settings.assignment_scope_for_managers = 0
	settings.escalation_hours = 48
	settings.save(ignore_permissions=True)


def buyer_data(**kw):
	_SEQ[0] += 1
	n = _SEQ[0]
	data = {
		"doctype": "Buyer Master",
		"channel": "Offline",
		"customer_business_name": f"{TAG} Buyer {n}",
		"customer_type": F.customer_type,
		"gst_type": "Registered Business",
		"gst_no": gstin(),
		"level": "N/A",
		"payment_term": "Advance",
		"contact_person": "Ravi",
		"email": f"buyer{n}@example.com",
		"contact_no": "9876543210",
		"secondary_poc": F.sa1.emp,
		"sales_officers": [{"employee": F.so1.emp}],
		"addresses": [
			{
				"site_name": f"Site {n}", "address_line": "1 Test Road", "state": "Gujarat", "city": F.city_gj,
				"pincode": "380001", "country": "India", "is_primary": 1, "is_shipping": 1,
			}
		],
	}
	data.update(kw)
	return data


def new_buyer(user="Administrator", **kw):
	def _make():
		doc = frappe.get_doc(buyer_data(**kw))
		doc.insert()
		return doc

	return as_(user, _make)


def set_status(name, status, catalog=None):
	frappe.db.set_value("Buyer Master", name, "buyer_status", status, update_modified=False)
	if catalog:
		frappe.db.set_value("Buyer Master", name, "buyer_catalog_status", catalog, update_modified=False)


def trail(name, action=None):
	filters = {"reference_doctype": "Buyer Master", "reference_name": name}
	if action:
		filters["action"] = action
	return frappe.get_all(
		"Field Change Log", filters=filters,
		fields=["action", "field_label", "previous_value", "new_value", "reason", "user_role", "item_code", "changed_by"],
		order_by="creation asc",
	)


# ----------------------------------------------------------------------------- tests


def _run():
	_fixtures()
	_matrix()
	_creation()
	_status_actions()
	_corrections()
	_duplicates()
	_validations()
	_escalation()
	_gate()
	_catalog()
	_access()
	_audit_trail()
	_modal()
	_real_flows()


def _matrix():
	def perm(user, doctype, ptype):
		return as_(user, lambda: bool(frappe.has_permission(doctype, ptype)))

	def _so():
		_assert(perm(F.so1.user, "Buyer Master", "create"), "SO cannot create Buyer Master")
		_assert(perm(F.so1.user, "Buyer Master", "write"), "SO cannot write Buyer Master")
		_assert(perm(F.so1.user, "Quotation", "create"), "SO cannot create Quotation")
		_assert(not perm(F.so1.user, "Quotation", "submit"), "SO may submit (finalize) a Quotation")
		_assert(not perm(F.so1.user, "Quotation", "cancel"), "SO may cancel a Quotation")
		_assert(perm(F.so1.user, "Pick List", "read") and not perm(F.so1.user, "Pick List", "write"), "Pick List not read only")
		_assert(perm(F.so1.user, "Delivery Note", "read") and not perm(F.so1.user, "Delivery Note", "write"), "DN not read only")
		_assert(perm(F.so1.user, "Buyer Items", "read") and not perm(F.so1.user, "Buyer Items", "write"), "SO may write the catalogue")

	check("1.1 Sales Officer rows: Buyer Master create/write, Quotation no submit, PL/DN/catalogue read only", _so)

	def _sm():
		_assert(perm(F.sm1.user, "Buyer Items", "write") and perm(F.sm1.user, "Buyer Items", "create"), "SM cannot maintain the catalogue")
		_assert(perm(F.sa1.user, "Buyer Items", "write"), "SA cannot maintain the catalogue")

	check("1.1 Sales Manager and Sales Admin maintain the Buyer Catalog", _sm)


def _creation():
	def _by_so():
		doc = new_buyer(F.so1.user, channel="E-com")
		_assert(doc.buyer_status == "Pending Approval", f"status {doc.buyer_status}")
		_assert(doc.buyer_catalog_status == "Pending", f"catalog {doc.buyer_catalog_status}")
		_assert(doc.channel == "Offline", f"SO buyer channel {doc.channel}")
		_assert(F.sm1.emp in [r.employee for r in doc.primary_pocs], "default Primary POC not added")
		_assert(F.so1.emp in [r.employee for r in doc.sales_officers], "creating SO not assigned")
		_assert(not doc.approved_by, "an SO buyer carries an approver")
		_assert(trail(doc.name, "Buyer Master Created"), "creation not in the trail")
		F.pending = doc.name

	check("4.2 a Sales Officer's buyer is Pending Approval, Offline, default POC and creator assigned", _by_so)

	def _by_sm():
		doc = new_buyer(F.sm1.user)
		_assert(doc.buyer_status == "Approved", f"status {doc.buyer_status}")
		_assert(doc.approved_by == F.sm1.user and doc.approver_role == "Sales Manager", f"{doc.approved_by} {doc.approver_role}")
		_assert(doc.buyer_catalog_status == "Pending", "an SM buyer skips the catalogue setup")
		F.approved_new = doc.name

	check("4.2 a Sales Manager's buyer is auto-approved, catalogue still Pending", _by_sm)

	def _ecom():
		doc = new_buyer(channel="E-com", sales_officers=[])
		_assert(doc.buyer_status == "Approved" and doc.buyer_catalog_status == "Completed", f"{doc.buyer_status} {doc.buyer_catalog_status}")
		_assert(not doc.primary_pocs, "an E-com buyer got the default Primary POC")

	check("3.1 an E-com buyer is Approved and never waits for a catalogue", _ecom)

	def _so_margins():
		err = refused(lambda: new_buyer(F.so1.user, margins=[{"sku": frappe.db.get_value("Item", {"disabled": 0}), "margin_percent": 10}]))
		_assert("cannot set Buyer Catalog pricing" in err, err)

	check("3.1 a Sales Officer cannot price a buyer while creating it", _so_margins)


def _act(user, buyer, action, reason=None):
	from alpinos.offline_sales.buyer_status import buyer_action

	return as_(user, lambda: buyer_action(buyer, action, reason))


def _status_actions():
	b = new_buyer(F.so1.user).name

	def _so_cannot():
		err = refused(lambda: _act(F.so1.user, b, "approve"))
		_assert("Only a Sales Manager or Sales Admin" in err, err)

	check("7 a Sales Officer cannot approve", _so_cannot)

	def _reason_needed():
		err = refused(lambda: _act(F.sm1.user, b, "hold", ""))
		_assert("Enter the reason" in err, err)

	check("7.1 Put On Hold needs a reason", _reason_needed)

	def _lifecycle():
		_act(F.sm1.user, b, "hold", "GST certificate unreadable")
		_assert(frappe.db.get_value("Buyer Master", b, "buyer_status") == "On Hold", "not On Hold")
		_act(F.sa1.user, b, "approve")
		row = frappe.db.get_value("Buyer Master", b, ["buyer_status", "approved_by", "approver_role", "approved_on"], as_dict=True)
		_assert(row.buyer_status == "Approved" and row.approved_by == F.sa1.user and row.approver_role == "Sales Admin" and row.approved_on, str(row))
		_act(F.sm1.user, b, "inactive", "No orders this season")
		_assert(frappe.db.get_value("Buyer Master", b, "buyer_status") == "Inactive", "not Inactive")
		_act(F.sm1.user, b, "reactivate")
		_assert(frappe.db.get_value("Buyer Master", b, "buyer_status") == "Approved", "not reactivated")
		_act(F.sm1.user, b, "cancel", "Closed the business")
		_assert(frappe.db.get_value("Buyer Master", b, "buyer_status") == "Cancelled", "not Cancelled")
		hold = trail(b, "Buyer Master Put On Hold")
		_assert(hold and hold[0].previous_value == "Pending Approval" and hold[0].new_value == "On Hold"
			and hold[0].reason == "GST certificate unreadable" and hold[0].user_role == "Sales Manager", str(hold))
		for action in ("Buyer Master Approved", "Buyer Master Made Inactive", "Buyer Master Reactivated", "Buyer Master Cancelled"):
			_assert(trail(b, action), f"{action} not in the trail")

	check("4.1 Pending > On Hold > Approved > Inactive > Approved > Cancelled, each audited with role and reason", _lifecycle)

	def _cancelled_final():
		for action in ("reactivate", "approve", "hold", "inactive", "cancel"):
			err = refused(lambda: _act(F.sm1.user, b, action, "x"))
			_assert("Cancelled Buyer Master cannot be reactivated" in err, f"{action}: {err}")

	check("8.5 a Cancelled buyer cannot move to any status", _cancelled_final)

	def _wrong_from():
		a = new_buyer(F.sm1.user).name
		_assert("cannot be" in refused(lambda: _act(F.sm1.user, a, "hold", "x")), "Approved put On Hold")
		_assert("cannot be" in refused(lambda: _act(F.sm1.user, a, "approve")), "Approved approved again")
		_assert("cannot be" in refused(lambda: _act(F.sm1.user, a, "reactivate")), "Approved reactivated")

	check("7 actions only from their statuses (no hold or reactivate of an Approved buyer)", _wrong_from)

	def _plain_save():
		a = new_buyer(F.sm1.user).name

		def _edit():
			doc = frappe.get_doc("Buyer Master", a)
			doc.buyer_status = "Inactive"
			doc.save()

		err = refused(_edit)
		_assert("changes only through" in err, err)

		def _edit_cancelled():
			doc = frappe.get_doc("Buyer Master", b)
			doc.buyer_status = "Approved"
			doc.save()

		err = refused(_edit_cancelled)
		_assert("Cancelled Buyer Master cannot be reactivated" in err, err)

	check("8.5 the status cannot be changed by a plain save (Cancelled gives the 8.5 message)", _plain_save)


def _corrections():
	b = new_buyer(F.so1.user).name

	def _edit(user, buyer, **values):
		def _go():
			doc = frappe.get_doc("Buyer Master", buyer)
			for k, v in values.items():
				doc.set(k, v)
			doc.save()

		return refused(lambda: as_(user, _go))

	def _pending_ok():
		err = _edit(F.so1.user, b, contact_person="Ravi Patel")
		_assert(not err, err)
		rows = trail(b, "Buyer Master Corrected")
		_assert(any(r.field_label == "Contact Person" and r.new_value == "Ravi Patel" for r in rows), str(rows))

	check("4.5 a Sales Officer corrects a Pending buyer, and the correction is audited", _pending_ok)

	def _non_modal():
		err = _edit(F.so1.user, b, tally_buyer_name="Something")
		_assert("cannot change" in err, err)

	check("4.1 a Sales Officer cannot change a field outside the creation form", _non_modal)

	def _default_poc():
		def _go():
			doc = frappe.get_doc("Buyer Master", b)
			doc.set("primary_pocs", [r for r in doc.primary_pocs if r.employee != F.sm1.emp] or [])
			doc.append("primary_pocs", {"employee": F.sm2.emp})
			doc.save()

		err = refused(lambda: as_(F.so1.user, _go))
		_assert("cannot remove the default Primary POC" in err, err)

	check("3.3 a Sales Officer can add Primary POCs but not remove the default", _default_poc)

	def _on_hold_ok():
		_act(F.sm1.user, b, "hold", "Check address")
		err = _edit(F.so1.user, b, contact_person="Ravi P")
		_assert(not err, err)

	check("4.1 a Sales Officer corrects an On Hold buyer", _on_hold_ok)

	def _approved_blocked():
		_act(F.sm1.user, b, "approve")
		err = _edit(F.so1.user, b, contact_person="Changed")
		_assert("Pending Approval or On Hold" in err, err)
		_assert(not _edit(F.sm1.user, b, contact_person="Changed by SM"), "a Sales Manager could not edit")

	check("4.1 an Approved buyer is closed to the Sales Officer, open to the Sales Manager", _approved_blocked)


def _duplicates():
	def _matrix_for(field, make_kwargs, msg_word):
		existing = {}
		for status in ("Pending Approval", "Approved", "On Hold", "Inactive", "Cancelled"):
			kwargs = make_kwargs()
			doc = new_buyer(**kwargs)
			set_status(doc.name, status)
			existing[status] = (doc, kwargs)
		for status, (doc, kwargs) in existing.items():
			again = dict(kwargs)
			again["customer_business_name"] = kwargs.get("customer_business_name") if field == "customer_business_name" else f"{TAG} Other {status}"
			err = refused(lambda: new_buyer(**again))
			if status == "Cancelled":
				_assert(not err, f"{msg_word}: Cancelled match blocked: {err}")
			elif status == "Inactive":
				_assert("currently Inactive" in err and doc.name in err, f"{msg_word} Inactive: {err}")
			else:
				_assert("already exists" in err and doc.name in err, f"{msg_word} {status}: {err}")

	def _gstin():
		_matrix_for("gst_no", lambda: {"gst_no": gstin()}, "GSTIN")

	check("8.6 duplicate GSTIN: blocked for Pending/Approved/On Hold, reactivate for Inactive, allowed for Cancelled", _gstin)

	def _pan():
		_matrix_for("pan_no", lambda: {"gst_type": "Unregistered Business", "gst_no": None, "pan_no": pan()}, "PAN")

	check("8.7 duplicate PAN, same five rules", _pan)

	def _overseas():
		def kw():
			_SEQ[0] += 1
			return {"gst_type": "Overseas", "gst_no": None, "customer_business_name": f"{TAG} Overseas {_SEQ[0]}  Ltd",
				"addresses": buyer_data()["addresses"]}

		_matrix_for("customer_business_name", kw, "Overseas name")

	check("8.8 duplicate overseas Customer Name (case and spacing ignored), same five rules", _overseas)

	def _family():
		g = gstin()
		parent = new_buyer(gst_no=g, is_parent=1)
		child = new_buyer(gst_no=g, parent_buyer=parent.name)
		_assert(child.name, "a site of the same family was refused")

	check("3.1.1 a parent and its site may share the GSTIN", _family)

	def _legacy():
		rows = frappe.db.sql(
			"""SELECT a.name FROM `tabBuyer Master` a JOIN `tabBuyer Master` b ON a.gst_no = b.gst_no AND a.name != b.name
			WHERE IFNULL(a.gst_no,'') != '' AND IFNULL(a.parent_buyer,'') = '' AND IFNULL(b.parent_buyer,'') = ''
			AND a.is_parent = 0 AND b.is_parent = 0 AND IFNULL(a.channel,'') != 'E-com' LIMIT 1"""
		)
		_assert(rows, "no legacy shared GSTIN on this site")
		doc = frappe.get_doc("Buyer Master", rows[0][0])
		doc.flags.ignore_mandatory = True
		doc.remarks = "x" if doc.meta.has_field("remarks") else None
		doc.save()

	check("3.1.1 an old buyer whose GSTIN is already shared still saves", _legacy)

	def _api():
		from alpinos.offline_sales.buyer_create import check_duplicate

		doc = new_buyer()
		r = check_duplicate("Registered Business", gst_no=doc.gst_no.lower())
		_assert(r and doc.name in r["message"], str(r))
		_assert(check_duplicate("Registered Business", gst_no=gstin()) is None, "a new GSTIN reported as duplicate")

	check("3.1.1 the modal's live duplicate check", _api)


def _validations():
	def _state():
		err = refused(lambda: new_buyer(gst_no=gstin("24"), addresses=[
			{"site_name": "Pune", "address_line": "2 Road", "state": "Maharashtra", "city": F.city_mh, "pincode": "411001",
			 "country": "India", "is_primary": 1, "is_shipping": 1}]))
		_assert("GSTIN state code 24 corresponds to Gujarat, while the selected state is Maharashtra" in err, err)
		ok = refused(lambda: new_buyer(gst_no=gstin("27"), addresses=[
			{"site_name": "Pune", "address_line": "2 Road", "state": "Maharashtra", "city": F.city_mh, "pincode": "411001",
			 "country": "India", "is_primary": 1, "is_shipping": 1}]))
		_assert(not ok, ok)

	check("8.3 GSTIN state code against the address state", _state)

	def _pin():
		for bad in ("50007", "50007A"):
			addr = dict(buyer_data()["addresses"][0], pincode=bad)
			err = refused(lambda: new_buyer(addresses=[addr]))
			_assert("Pincode must be exactly 6 numeric digits" in err, f"{bad}: {err}")

	check("8.1 Pincode must be exactly 6 numeric digits", _pin)

	def _contact():
		_assert("not a valid email" in refused(lambda: new_buyer(email="not-an-email")), "bad email accepted")
		_assert("10-digit mobile" in refused(lambda: new_buyer(contact_no="12345")), "short phone accepted")
		_assert(not refused(lambda: new_buyer(contact_no="+91 98765 43210")), "+91 number refused")
		_assert(not refused(lambda: new_buyer(gst_type="Overseas", gst_no=None, contact_no="+44 20 7946 0958")), "overseas phone refused")

	check("3.3 email format and 10-digit Contact No (not for Overseas)", _contact)

	def _legacy_mismatch():
		from alpinos.offline_sales.buyer_rules import GST_STATE_CODES
		from alpinos import offline_buyer_api as api

		rows = frappe.db.sql(
			"""SELECT bm.name, bm.gst_no, a.state FROM `tabBuyer Master` bm JOIN `tabBuyer Address` a ON a.parent = bm.name
			WHERE bm.gst_type = 'Registered Business' AND IFNULL(bm.gst_no, '') != '' AND IFNULL(bm.channel, '') != 'E-com'
			AND (a.is_primary = 1 OR a.is_shipping = 1)""",
			as_dict=True,
		)
		bad = next((r.name for r in rows if GST_STATE_CODES.get((r.state or "").strip().lower())
			and r.gst_no[:2] not in GST_STATE_CODES[(r.state or "").strip().lower()]), None)
		_assert(bad, "no old GSTIN / state mismatch on this site")
		doc = frappe.get_doc("Buyer Master", bad)
		addresses = [{k: r.get(k) for k in ("site_name", "address_label", "address_line", "pincode", "country", "state",
			"city", "area", "sub_area", "is_primary", "is_shipping")} for r in doc.addresses]
		err = refused(lambda: api.update_offline_buyer_master(bad, json.dumps({"contact_person": "Updated"}), json.dumps(addresses)))
		_assert("GSTIN state code" not in err, f"{bad}: an old mismatch blocked an unrelated edit: {err}")

	check("8.3 an old buyer's existing mismatch does not block an unrelated edit (address rows rewritten)", _legacy_mismatch)


def _escalation():
	from alpinos.offline_sales import escalation

	def _flow():
		b = new_buyer(F.so1.user).name
		created = frappe.db.get_value("Buyer Master", b, "creation")
		now = add_to_date(created, hours=47)
		_assert(b not in escalation.run(now), "escalated at 47 hours")
		now = add_to_date(created, hours=48, seconds=1)
		done = escalation.run(now)
		_assert(b in done, f"not escalated at 48 hours: {done}")
		logs = frappe.get_all("Notification Log", filters={"document_name": b, "document_type": "Buyer Master"}, fields=["for_user", "subject"])
		users = {l.for_user for l in logs}
		_assert({F.sm1.user, F.sa1.user} <= users, f"recipients {users}")
		_assert(F.so1.user not in users, "the Sales Officer got the escalation")
		_assert(all("URGENT ESCALATION" in l.subject and "PENDING" in l.subject for l in logs), logs[0].subject if logs else "")
		_assert(frappe.db.get_value("Buyer Master", b, "escalated_on"), "escalated_on not set")
		_assert(trail(b, "Approval Escalated"), "escalation not audited")
		_assert(b not in escalation.run(add_to_date(created, hours=60)), "escalated twice")
		if frappe.db.exists("Email Account", {"enable_outgoing": 1}):
			mails = frappe.get_all("Email Queue", filters={"reference_doctype": "Buyer Master", "reference_name": b}, pluck="name")
			_assert(len(mails) == 1, f"escalation email queued {len(mails)} times")
			to = set(frappe.get_all("Email Queue Recipient", filters={"parent": mails[0]}, pluck="recipient"))
			_assert({F.sm1.user, F.sa1.user} <= to, f"email recipients {to}")

	check("5 48-hour escalation to every Primary POC and the Secondary POC, once", _flow)

	def _approved_not():
		b = new_buyer(F.so1.user).name
		_act(F.sm1.user, b, "approve")
		created = frappe.db.get_value("Buyer Master", b, "creation")
		_assert(b not in escalation.run(add_to_date(created, hours=72)), "an approved buyer was escalated")

	check("5.1 a buyer no longer Pending is not escalated", _approved_not)


def _gate():
	from alpinos.offline_sales.catalog_gate import readiness

	def _grid():
		b = new_buyer(F.so1.user).name
		_assert("Buyer Approval & Buyer Catalog creation is pending" in (readiness(b, "Sales Order") or ""), "Pending allowed")
		set_status(b, "Approved", "Pending")
		_assert("mandatory Buyer Catalog setup is pending" in (readiness(b, "Quotation") or ""), "catalogue Pending allowed")
		set_status(b, "Approved", "Completed")
		_assert(readiness(b, "Sales Order") is None, "ready buyer refused")
		set_status(b, "On Hold")
		_assert("currently On Hold" in (readiness(b, "Sales Order") or ""), "On Hold allowed")
		set_status(b, "Inactive")
		_assert("Inactive" in (readiness(b, "Sales Order") or ""), "Inactive allowed")
		set_status(b, "Cancelled")
		_assert("Cancelled" in (readiness(b, "Sales Order") or ""), "Cancelled allowed")
		set_status(b, "", "")
		_assert(readiness(b, "Sales Order") is None, "a legacy (blank) buyer refused")

	check("6.1 readiness grid: only Approved + Catalog Completed (or an old buyer) may sell", _grid)

	def _sales_order():
		wh = frappe.db.get_value("Warehouse", {"is_group": 0, "company": F.company}, "name")
		item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
		b = new_buyer(F.so1.user)

		def _order():
			doc = frappe.get_doc({
				"doctype": "Sales Order", "company": F.company, "customer": b.customer, "transaction_date": today(),
				"delivery_date": add_days(today(), 3), "custom_offline_buyer_master": b.name,
				"custom_site_name": b.addresses[0].site_name, "custom_workflow_status": "Draft", "set_warehouse": wh,
				"custom_dispatch_date": add_days(today(), 2), "custom_channel": "Offline",
				"items": [{"item_code": item, "qty": 5, "rate": 100, "warehouse": wh, "delivery_date": add_days(today(), 3),
					"conversion_factor": 1}],
			})
			doc.insert(ignore_permissions=True)
			return doc

		err = refused(_order)
		_assert("Buyer Approval & Buyer Catalog creation is pending" in err, err)
		set_status(b.name, "Approved", "Completed")
		err = refused(_order)
		_assert("Buyer Approval" not in err and "Buyer Catalog" not in err, f"ready buyer's order refused by the gate: {err}")

		from alpinos.offline_sales.catalog_gate import sales_order_gate

		set_status(b.name, "On Hold")
		so = frappe._dict(custom_offline_buyer_master=b.name, custom_channel="Offline", _action="submit", flags=frappe._dict())
		so.is_new = lambda: False
		_assert("On Hold" in refused(lambda: sales_order_gate(so)), "submission for an On Hold buyer allowed")
		so._action = "save"
		_assert(not refused(lambda: sales_order_gate(so)), "editing an existing draft refused")
		so.custom_channel = "E-com"
		so._action = "submit"
		_assert(not refused(lambda: sales_order_gate(so)), "an E-com order was gated")

	check("6.1 a Sales Order is refused for a buyer not ready, on create and on submit", _sales_order)

	def _quotation():
		from alpinos.offline_sales.catalog_gate import quotation_validate

		from alpinos.offline_sales.catalog_gate import readiness

		# the Opportunity is skipped (20 Nov 2026): a Draft Quotation may wait for the approval and
		# the catalogue; Start Negotiation / Finalize may not; On Hold / Inactive / Cancelled refuse
		b = new_buyer(F.so1.user).name
		q = frappe.new_doc("Quotation")
		q.quotation_to = "Buyer Master"
		q.party_name = b
		_assert(not refused(lambda: quotation_validate(q)), "Draft Quotation for a Pending buyer refused")
		_assert(q.custom_buyer_master == b, "custom_buyer_master not filled")
		_assert("Buyer Approval & Buyer Catalog creation is pending" in (readiness(b, "Quotation", action="finalized") or ""), "Finalize not held")
		set_status(b, "Approved", "Pending")
		_assert(not refused(lambda: quotation_validate(q)), "Draft Quotation for a catalogue-pending buyer refused")
		_assert("mandatory Buyer Catalog setup is pending" in (readiness(b, "Quotation", action="finalized") or ""), "Finalize not held for the catalogue")
		set_status(b, "On Hold")
		_assert("On Hold" in refused(lambda: quotation_validate(q)), "Quotation for an On Hold buyer allowed")
		set_status(b, "Approved", "Completed")
		_assert(not refused(lambda: quotation_validate(q)), "ready buyer's Quotation refused")
		_assert(not readiness(b, "Quotation", action="finalized"), "ready buyer held")
		_assert(q.custom_secondary_poc == F.sa1.emp, "Secondary POC not carried to the Quotation")

	check("4.4 / 6.1 a Draft Quotation may wait for approval and catalogue; Finalize may not; On Hold refused", _quotation)


def _catalog():
	from alpinos import offline_buyer_api as api

	item = frappe.db.sql(
		"""SELECT i.name FROM tabItem i WHERE i.disabled = 0 AND NOT EXISTS
		(SELECT 1 FROM `tabItem MRP` m WHERE m.parent = i.name) LIMIT 1"""
	)[0][0]

	def _complete():
		b = new_buyer(F.sm1.user)
		record = as_(F.sm1.user, lambda: api.create_record(f"{TAG} Catalogue", offline_buyer_master=b.name))
		as_(F.sm1.user, lambda: api.save_buyer_items(record, json.dumps([
			{"selected": 1, "item_code": item, "item_name": item, "mrp": 500, "margin_percent": 20}])))
		row = frappe.db.get_value("Buyer Master", b.name, ["buyer_catalog_status", "catalog_completed_by"], as_dict=True)
		_assert(row.buyer_catalog_status == "Completed" and row.catalog_completed_by == F.sm1.user, str(row))
		_assert(trail(b.name, "Buyer Catalog Completed"), "completion not audited")
		lines = trail(b.name, "Buyer Catalog Changed")
		_assert(any(l.item_code == item and l.field_label.startswith("Flat Discount %") and l.new_value in ("20", "20.0") for l in lines), str(lines))
		_assert(any(l.item_code == item and l.field_label.startswith("Selling Price") and float(l.new_value) == 400 for l in lines), str(lines))
		as_(F.sm1.user, lambda: api.save_buyer_items(record, json.dumps([
			{"selected": 1, "item_code": item, "item_name": item, "mrp": 500, "margin_percent": 25}])))
		lines = trail(b.name, "Buyer Catalog Changed")
		_assert(any(l.previous_value in ("20", "20.0") and l.new_value in ("25", "25.0") and l.user_role == "Sales Manager" for l in lines), str(lines))
		F.catalog_record, F.catalog_buyer, F.catalog_item = record, b, item

	check("4.4 saving a priced catalogue completes setup; each change audited with SKU, old/new, role", _complete)

	def _so_refused():
		err = refused(lambda: as_(F.so1.user, lambda: api.save_buyer_items(F.catalog_record, json.dumps([
			{"selected": 1, "item_code": F.catalog_item, "mrp": 500, "margin_percent": 50}]))))
		_assert("Sales Officer cannot create or change Buyer Catalog pricing" in err, err)

	check("3.1 a Sales Officer cannot change Buyer Catalog pricing", _so_refused)

	def _margins():
		b = new_buyer(F.sm1.user).name

		def _go():
			doc = frappe.get_doc("Buyer Master", b)
			doc.append("margins", {"sku": item, "margin_percent": 15})
			doc.save()

		as_(F.sm1.user, _go)
		_assert(frappe.db.get_value("Buyer Master", b, "buyer_catalog_status") == "Completed", "margins did not complete it")
		_assert(any(l.item_code == item for l in trail(b, "Buyer Catalog Changed")), "margin not audited")

	check("4.4 SKU margins on the buyer count as the catalogue too", _margins)

	def _sync():
		from alpinos.sales_order_offline_buyer import update_offline_buyer_margin_if_changed, upsert_buyer_catalog_selling_rate

		b = F.catalog_buyer
		frappe.flags.alpinos_catalog_sync = "SO-TEST"
		try:
			upsert_buyer_catalog_selling_rate(b.customer, F.catalog_item, 380, mrp=500)
			update_offline_buyer_margin_if_changed(b.customer, F.catalog_item, 30, mrp=500)
		finally:
			frappe.flags.alpinos_catalog_sync = None
		lines = trail(b.name, "Buyer Catalog Synced from Sales Order")
		_assert(any(l.field_label.startswith("Selling Price") and float(l.new_value) == 380 for l in lines), str(lines))
		_assert(any(l.field_label.startswith("Flat Discount %") and float(l.new_value) == 30 for l in lines), str(lines))

	check("4.4 / 5.2 catalogue changes a submitted Sales Order writes are audited as such", _sync)


def _access():
	from alpinos import buyer_assignment_visibility as V
	from alpinos.offline_sales import access

	mine = new_buyer(F.sm1.user, sales_officers=[{"employee": F.so1.emp}], primary_pocs=[{"employee": F.sm2.emp}]).name
	other = new_buyer(F.sm1.user, sales_officers=[{"employee": F.so2.emp}], secondary_poc=None).name
	F.mine, F.other = mine, other

	def names(user, doctype, **filters):
		return as_(user, lambda: set(frappe.get_list(doctype, filters=filters, pluck="name", limit_page_length=0)))

	def _quotation():
		q1 = _insert("Quotation", name=f"{TAG}-Q1", quotation_to="Buyer Master", party_name=mine, custom_buyer_master=mine,
			company=F.company, transaction_date=today(), docstatus=0)
		q2 = _insert("Quotation", name=f"{TAG}-Q2", quotation_to="Buyer Master", party_name=other, custom_buyer_master=other,
			company=F.company, transaction_date=today(), docstatus=0)
		seen = names(F.so1.user, "Quotation", name=("in", [q1, q2]))
		_assert(seen == {q1}, f"SO sees {seen}")
		_assert(as_(F.so1.user, lambda: V.quotation_has_permission(frappe.get_doc("Quotation", q2), F.so1.user, "read")) is False,
			"SO may open another buyer's Quotation")

	check("4.1 a Sales Officer sees only the Quotations of their buyers", _quotation)

	def _downstream():
		so_a = _insert("Sales Order", name=f"{TAG}-SOA", custom_offline_buyer_master=mine, company=F.company, docstatus=1)
		so_b = _insert("Sales Order", name=f"{TAG}-SOB", custom_offline_buyer_master=other, company=F.company, docstatus=1)
		pl_a = _insert("Pick List", name=f"{TAG}-PLA", custom_sales_order_id=so_a, company=F.company, purpose="Delivery", docstatus=0)
		pl_b = _insert("Pick List", name=f"{TAG}-PLB", custom_sales_order_id=so_b, company=F.company, purpose="Delivery", docstatus=0)
		dn_a = _insert("Delivery Note", name=f"{TAG}-DNA", custom_sales_order_id=so_a, company=F.company, docstatus=1)
		dn_b = _insert("Delivery Note", name=f"{TAG}-DNB", custom_sales_order_id=so_b, company=F.company, docstatus=1)
		_assert(names(F.so1.user, "Pick List", name=("in", [pl_a, pl_b])) == {pl_a}, "Pick List scope wrong")
		_assert(names(F.so1.user, "Delivery Note", name=("in", [dn_a, dn_b])) == {dn_a}, "Delivery Note scope wrong")
		pl = frappe.get_doc("Pick List", pl_a)
		_assert(V.pick_list_has_permission(pl, F.so1.user, "write") is False, "SO may write a Pick List")
		_assert(V.pick_list_has_permission(pl, F.so1.user, "read") is not False, "SO may not read their Pick List")
		_assert(names(F.wh.user, "Pick List", name=("in", [pl_a, pl_b])) == {pl_a, pl_b}, "warehouse role narrowed")

	check("4.2 Pick List / Delivery Note: a Sales Officer reads those of their buyers' orders only", _downstream)

	def _switch():
		_assert(other in names(F.sm2.user, "Buyer Master", name=("in", [mine, other])), "switch off: SM narrowed")
		frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 1)
		try:
			seen = names(F.sm2.user, "Buyer Master", name=("in", [mine, other]))
			_assert(seen == {mine}, f"switch on: SM sees {seen}")
			seen = names(F.sa1.user, "Buyer Master", name=("in", [mine, other]))
			_assert(seen == {mine, other}, f"switch on: SA sees {seen}")
			defaults = as_(F.sa1.user, lambda: access.sa_default_buyers())
			_assert(defaults is not None and mine in defaults and other not in defaults, "SA default list wrong")
			_assert(as_(F.sa1.user, lambda: access.list_scope())["secondary_poc_default"] == 1, "list_scope off for SA")
			_assert(as_(F.sm2.user, lambda: access.list_scope())["secondary_poc_default"] == 0, "list_scope on for SM")
		finally:
			frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 0)
		_assert(as_(F.sa1.user, lambda: access.sa_default_buyers()) is None, "switch off: SA default filter applied")

	check("4.1 / 3.3 switch on: SM sees assigned buyers, SA all, SA lists default to their Secondary POC buyers", _switch)

	def _coverage():
		r = access.coverage_report()
		_assert(r["buyers"] > 0 and r["without_primary_poc"] <= r["buyers"] and r["without_any"] <= r["without_secondary_poc"], str(r))

	check("coverage report counts buyers missing each assignment", _coverage)


def _audit_trail():
	from alpinos.offline_sales.audit import get_trail

	def _immutable():
		name = frappe.get_all("Field Change Log", filters={"reference_name": F.mine}, pluck="name", limit=1)[0]

		def _edit():
			doc = frappe.get_doc("Field Change Log", name)
			doc.new_value = "tampered"
			doc.save(ignore_permissions=True)

		_assert("cannot be changed" in refused(lambda: as_(F.sm1.user, _edit)), "a trail entry was edited")
		_assert("cannot be deleted" in refused(lambda: as_(F.sm1.user, lambda: frappe.delete_doc("Field Change Log", name, ignore_permissions=True))),
			"a trail entry was deleted")

	check("5.1 trail entries cannot be edited or deleted by business users", _immutable)

	def _reader():
		rows = as_(F.so1.user, lambda: get_trail("Buyer Master", F.mine))
		_assert(rows and rows[0].changed_by_name, "trail empty for an assigned SO")
		err = refused(lambda: as_(F.so1.user, lambda: get_trail("Buyer Master", F.other)))
		_assert(err, "an SO read the trail of a buyer they cannot see")

	check("5.1 the trail reader follows the record's read permission", _reader)


def _modal():
	from alpinos.offline_sales.buyer_create import create_buyer, get_create_context

	def payload(**kw):
		_SEQ[0] += 1
		data = {
			"customer_business_name": f"{TAG} Modal {_SEQ[0]}", "customer_type": F.customer_type,
			"gst_type": "Registered Business", "gst_no": gstin(), "gst_certificate": "/files/gst.pdf",
			"level": "N/A", "payment_term": "Advance", "contact_person": "Asha", "email": f"m{_SEQ[0]}@example.com",
			"contact_no": "9876500000", "secondary_poc": F.sa1.emp, "primary_pocs": [], "sales_officers": [],
			"addresses": [
				{"site_name": "HQ", "address_line": "1 Ring Road", "state": "Gujarat", "city": F.city_gj, "pincode": "380015", "is_primary": 1},
				{"site_name": "Godown", "address_line": "Plot 9", "state": "Gujarat", "city": F.city_gj, "pincode": "382010", "is_shipping": 1},
			],
		}
		data.update(kw)
		return json.dumps(data)

	def _ctx():
		ctx = as_(F.so1.user, get_create_context)
		_assert(ctx["is_sales_officer"] and ctx["me"]["employee"] == F.so1.emp, str(ctx))
		_assert([p["employee"] for p in ctx["default_primary_pocs"]] == [F.sm1.emp], str(ctx["default_primary_pocs"]))

	check("2 the modal knows the creator and the default Primary POCs", _ctx)

	def _save():
		r = as_(F.so1.user, lambda: create_buyer(payload()))
		doc = frappe.get_doc("Buyer Master", r["name"])
		_assert(r["buyer_status"] == "Pending Approval" and doc.channel == "Offline", str(r))
		_assert(F.so1.emp in [x.employee for x in doc.sales_officers] and F.sm1.emp in [x.employee for x in doc.primary_pocs], "assignments")
		_assert(len(doc.addresses) == 2 and doc.customer, "addresses / customer")

	check("7 Save Buyer as a Sales Officer: Pending Approval with both addresses and assignments", _save)

	def _rules():
		_assert("GST Certificate" in refused(lambda: as_(F.so1.user, lambda: create_buyer(payload(gst_certificate=None)))), "no certificate accepted")
		_assert("Shipping" in refused(lambda: as_(F.so1.user, lambda: create_buyer(payload(addresses=[
			{"site_name": "HQ", "address_line": "1", "state": "Gujarat", "city": F.city_gj, "pincode": "380015", "is_primary": 1}])))), "no shipping row accepted")
		_assert("PAN" in refused(lambda: as_(F.so1.user, lambda: create_buyer(payload(gst_type="Unregistered Business", gst_no=None, pan_no=pan()))))
			, "no PAN attachment accepted")
		_assert("Secondary POC" in refused(lambda: as_(F.so1.user, lambda: create_buyer(payload(secondary_poc=None)))), "no Secondary POC accepted")
		first = as_(F.sm1.user, lambda: create_buyer(payload(sales_officers=[F.so1.emp])))
		dup = frappe.db.get_value("Buyer Master", first["name"], "gst_no")
		_assert("already exists" in refused(lambda: as_(F.so1.user, lambda: create_buyer(payload(gst_no=dup)))), "duplicate accepted")
		_assert(first["buyer_status"] == "Approved", "SM modal buyer not auto-approved")

	check("3.1-3.3 modal rules: certificate, PAN attachment, shipping row, Secondary POC, duplicate", _rules)


def _real_flows():
	"""The real paths: the Sales Order entry page's own create / submit, a Quotation save, the
	Sales Order list page, the buyer picker."""
	from alpinos import sales_order_api
	from alpinos.offline_sales import access

	ref = frappe.db.sql(
		"""SELECT soi.item_code, soi.custom_customer_mrp AS mrp, soi.custom_gst_percent AS gst
		FROM `tabSales Order` so JOIN `tabSales Order Item` soi ON soi.parent = so.name
		WHERE so.docstatus = 1 AND IFNULL(so.custom_channel, '') IN ('', 'Offline')
			AND EXISTS (SELECT 1 FROM `tabItem MRP` m WHERE m.parent = soi.item_code AND ROUND(m.mrp, 2) = ROUND(soi.custom_customer_mrp, 2) AND m.active = 1)
			AND (SELECT COUNT(*) FROM `tabItem MRP` m2 WHERE m2.parent = soi.item_code AND m2.active = 1) = 1
		ORDER BY so.creation DESC LIMIT 1""",
		as_dict=True,
	)
	_assert(ref, "no one-MRP offline order line on this site to copy")
	ref = ref[0]
	day = add_days(today(), 1)
	items = json.dumps([{"item_code": ref.item_code, "qty": 2, "custom_customer_mrp": ref.mrp,
		"custom_selling_price": ref.mrp, "custom_gst_percent": ref.gst}])
	b = new_buyer(F.sm1.user)
	F.flow_buyer = b

	def entry(submit, buyer=b):
		return as_(F.sm1.user, lambda: sales_order_api.create_sales_order(
			customer=buyer.customer, order_type=F.customer_type, company="", items=items,
			delivery_date=add_days(day, 7), dispatch_date=day, site_name=buyer.addresses[0].site_name, submit_now=submit))

	def _page_create():
		err = refused(lambda: entry(0))
		_assert("mandatory Buyer Catalog setup is pending" in err, f"catalogue-pending buyer's order: {err}")
		set_status(b.name, "Approved", "Completed")
		out = entry(0)
		F.flow_draft = out["name"]
		_assert(frappe.db.get_value("Sales Order", F.flow_draft, "docstatus") == 0, "draft not saved")

	check("6.1 entry page: refused while the catalogue is pending, saved once it is set up", _page_create)

	def _page_submit():
		_assert(F.get("flow_draft"), "no draft from the step before")
		set_status(b.name, "On Hold")

		def _submit():
			frappe.set_user(F.sm1.user)
			frappe.get_doc("Sales Order", F.flow_draft).submit()

		err = refused(_submit)
		_assert("currently On Hold" in err, f"draft of an On Hold buyer submitted: {err}")
		set_status(b.name, "Approved")
		out = entry(1)
		_assert(frappe.db.get_value("Sales Order", out["name"], "docstatus") == 1, "a ready buyer's order was not submitted")
		synced = trail(b.name, "Buyer Catalog Synced from Sales Order")
		_assert(any(l.item_code == ref.item_code for l in synced), f"submit's catalogue sync not in the trail: {synced}")

	check("6.1 real submit: refused for an On Hold buyer, goes through (and syncs the catalogue) for a ready one", _page_submit)

	def _quotation_real():
		p = new_buyer(F.so1.user)
		q = {"doctype": "Quotation", "quotation_to": "Customer", "party_name": p.customer, "company": F.company,
			"order_type": F.customer_type, "transaction_date": today(), "valid_till": add_days(today(), 10),
			"custom_payment_mode": "Debit",  # Advance / Partial need a proof attachment
			"custom_expected_payment_date": add_days(today(), 5),
			"items": [{"item_code": ref.item_code, "qty": 1, "rate": ref.mrp}]}
		set_status(p.name, "On Hold")
		err = refused(lambda: frappe.get_doc(dict(q)).insert(ignore_permissions=True))
		_assert("On Hold" in err, f"Quotation for an On Hold buyer: {err}")
		set_status(p.name, "Approved", "Completed")
		doc = frappe.get_doc(dict(q))
		err = refused(lambda: doc.insert(ignore_permissions=True))
		_assert(not err, f"ready buyer's Quotation not saved: {err}")
		if not err:
			saved = frappe.db.get_value("Quotation", doc.name, ["custom_buyer_master", "custom_secondary_poc"], as_dict=True)
			_assert(saved.custom_buyer_master == p.name and saved.custom_secondary_poc == F.sa1.emp, str(saved))
			F.flow_quotation, F.flow_quotation_buyer = doc.name, p.name

	check("6.1 real Quotation save: refused for an On Hold buyer, carries Buyer + Secondary POC when ready", _quotation_real)

	def _quotation_follows_spoc():
		_assert(F.get("flow_quotation"), "no Quotation from the step before")

		def _go():
			doc = frappe.get_doc("Buyer Master", F.flow_quotation_buyer)
			doc.secondary_poc = None
			doc.save()

		as_(F.sm1.user, _go)
		_assert(not frappe.db.get_value("Quotation", F.flow_quotation, "custom_secondary_poc"), "Quotation kept the old Secondary POC")

	check("3.3 a buyer's new Secondary POC follows onto its Quotations", _quotation_follows_spoc)

	def _so_list_sa():
		other = new_buyer(F.sm1.user, secondary_poc=None)
		other_so = _insert("Sales Order", name=f"{TAG}-SO-OTHER", customer=other.customer, customer_name=other.customer_business_name,
			custom_offline_buyer_master=other.name, company=F.company, custom_channel="Offline", docstatus=0,
			transaction_date=today(), custom_workflow_status="Draft")

		def names(show_all):
			res = as_(F.sa1.user, lambda: sales_order_api.get_sales_order_entry_list(page_length=100, channel="Offline",
				show_all=show_all, search=TAG))
			return {r.get("name") for r in res["data"]}

		frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 1)
		try:
			mine = names(0)
			_assert(F.flow_draft in mine and other_so not in mine, f"SA default list: {mine}")
			every = names(1)
			_assert({F.flow_draft, other_so} <= every, f"SA Show All: {every}")
		finally:
			frappe.db.set_single_value("Offline Sales Settings", "assignment_scope_for_managers", 0)
		_assert(other_so in names(0), "switch off: SA list narrowed")

	check("3.3 Sales Order Entry list: SA default to Secondary POC buyers, Show All lifts it, switch off = as before", _so_list_sa)

	def _picker():
		from alpinos.sales_order_offline_buyer import sales_order_customer_query

		pending = new_buyer(F.so1.user)
		rows = sales_order_customer_query("Customer", pending.customer_business_name, "name", 0, 20, {})
		row = next((r for r in rows if r[0] == pending.customer), None)
		_assert(row and len(row) == 3 and "not ready" in row[2], f"pending buyer row: {row}")
		ready = sales_order_customer_query("Customer", F.flow_buyer.customer_business_name, "name", 0, 20, {})
		row = next((r for r in ready if r[0] == F.flow_buyer.customer), None)
		_assert(row and len(row) == 2, f"ready buyer labelled: {row}")

	check("6 the Sales Order buyer picker labels a buyer not ready for orders", _picker)
