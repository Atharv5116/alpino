"""Changes(HP) #21 reject reason, #22 channel by role, #39 Item Display Configuration,
#43 Dispatch Date editable on a draft Delivery Note.

Run:  bench --site alpinos.test execute alpinos.hp_21_22_39_43_test.run

Fixtures are written straight to the tables (tag HPB-<run>); #43 also drives the real
save of a draft Delivery Note on the site. One transaction, rolled back at the end, and
commits made by the code under test are ignored while it runs.
"""

import frappe
from frappe.utils import add_days, get_datetime, getdate, today

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {str(e)[:300]}"))


def skip(label, why):
	R.append(("SKIP", label, why))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def throws(fn, fragment, exc=None):
	try:
		fn()
	except Exception as e:
		msg = str(e) or str(frappe.flags.get("error_message") or "")
		if exc and not isinstance(e, exc):
			raise AssertionError(f"raised {type(e).__name__}, expected {exc.__name__}: {msg[:150]}")
		if fragment and fragment.lower() not in msg.lower():
			raise AssertionError(f"threw without {fragment!r}: {msg[:150]}")
		return
	raise AssertionError("expected a refusal, none raised")


def _insert(doctype, **values):
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.db_insert()
	return doc


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
			"send_welcome_email": 0, "user_type": "System User"}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	u.set("roles", [{"role": r} for r in roles])
	u.save(ignore_permissions=True)
	frappe.clear_cache(user=email)
	return email


def _as(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


def run():
	R.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		tag = "HPB-" + frappe.generate_hash(length=6).upper()
		_reject_reason(tag)
		_channel_by_role(tag)
		_item_display_configuration(tag)
		_dispatch_date_on_draft_note()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")
		from alpinos.item_display_config import clear_cache

		clear_cache()

	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{sum(1 for r in R if r[0] != 'SKIP')} passed"
	      + (f", {sum(1 for r in R if r[0] == 'SKIP')} skipped" if any(r[0] == "SKIP" for r in R) else ""))
	return R


# ---------------------------------------------------------------- #21 reject


def _reject_reason(tag):
	from alpinos.workflow_engine import reject_sales_order

	so = _insert("Sales Order", name=f"{tag}-REJ", docstatus=1, custom_workflow_status="Warehouse Approval Pending",
		custom_channel="Offline", customer="X", customer_name="X").name
	wh = _user(f"{tag.lower()}.wh@example.com", ["Warehouse Manager"])

	check("#21 rejecting without a reason is refused", lambda: throws(
		lambda: _as(wh, lambda: reject_sales_order(so, reason="   ")), "reason for rejection"))
	check("#21 a refused rejection leaves the order untouched", lambda: _assert(
		frappe.db.get_value("Sales Order", so, "custom_workflow_status") == "Warehouse Approval Pending"))

	def _rejected_with_reason():
		_as(wh, lambda: reject_sales_order(so, reason="Buyer cancelled the PO"))
		row = frappe.db.get_value("Sales Order", so, ["custom_workflow_status", "custom_rejection_reason",
			"custom_rejected_by", "custom_rejected_on"], as_dict=True)
		_assert(row.custom_workflow_status == "Rejected", row)
		_assert(row.custom_rejection_reason == "Buyer cancelled the PO", row)
		_assert(row.custom_rejected_by == wh and row.custom_rejected_on, row)
		_assert(frappe.db.exists("Comment", {"reference_doctype": "Sales Order", "reference_name": so,
			"content": ["like", "%Buyer cancelled the PO%"]}), "no comment on the order")

	check("#21 a rejection stores the reason, who and when, on the order", _rejected_with_reason)

	sales = _user(f"{tag.lower()}.sales@example.com", ["Sales Manager"])
	so2 = _insert("Sales Order", name=f"{tag}-REJ2", docstatus=1, custom_workflow_status="Warehouse Approval Pending",
		custom_channel="Offline", customer="X", customer_name="X").name
	check("#21 only the warehouse may reject", lambda: throws(
		lambda: _as(sales, lambda: reject_sales_order(so2, reason="x")), "not permitted"))


# ------------------------------------------------------------ #22 channel


def _channel_by_role(tag):
	from alpinos import channel_access as C

	sos = {}
	for key, channel in (("E", "E-com"), ("O", "Offline"), ("G", "General Trade"), ("B", "")):
		name = f"{tag}-SO-{key}"
		_insert("Sales Order", name=name, docstatus=1, custom_channel=channel, customer="X", customer_name="X")
		sos[key] = name
		_insert("Pick List", name=f"{tag}-PL-{key}", docstatus=1, custom_sales_order_id=name)
		_insert("Delivery Note", name=f"{tag}-DN-{key}", docstatus=0, is_return=0, custom_sales_order_id=name)

	users = {
		"ecom": _user(f"{tag.lower()}.ecm@example.com", ["E-Commerce Manager"]),
		"sales": _user(f"{tag.lower()}.slm@example.com", ["Sales Manager"]),
		"wh": _user(f"{tag.lower()}.whm@example.com", ["Warehouse Manager"]),
		"mixed": _user(f"{tag.lower()}.mix@example.com", ["E-Commerce Admin", "Sales Admin"]),
	}
	prefix_of = {"Sales Order": "SO", "Pick List": "PL", "Delivery Note": "DN"}
	like = f"{tag}-SO-%"

	def visible(user, doctype):
		pattern = f"{tag}-{prefix_of[doctype]}-%"
		return set(_as(user, lambda: frappe.get_list(doctype, filters={"name": ["like", pattern]}, pluck="name")))

	def names(doctype, keys):
		prefix = {"Sales Order": "SO", "Pick List": "PL", "Delivery Note": "DN"}[doctype]
		return {f"{tag}-{prefix}-{k}" for k in keys}

	for doctype in ("Sales Order", "Pick List", "Delivery Note"):
		check(f"#22 E-Commerce Manager sees only E-com {doctype}s", lambda d=doctype: _assert(
			visible(users["ecom"], d) == names(d, "E"), sorted(visible(users["ecom"], d))))
		check(f"#22 Sales Manager sees only Offline / General Trade {doctype}s", lambda d=doctype: _assert(
			visible(users["sales"], d) == names(d, "OGB"), sorted(visible(users["sales"], d))))
		check(f"#22 Warehouse Manager sees every channel's {doctype}s", lambda d=doctype: _assert(
			visible(users["wh"], d) == names(d, "EOGB"), sorted(visible(users["wh"], d))))
	check("#22 E-Commerce + Sales roles together see both", lambda: _assert(
		visible(users["mixed"], "Sales Order") == names("Sales Order", "EOGB")))

	def _record_by_url():
		_assert(not _as(users["ecom"], lambda: frappe.has_permission("Sales Order", "read", doc=sos["O"])),
			"an E-Commerce user can open an Offline order")
		_assert(_as(users["ecom"], lambda: frappe.has_permission("Sales Order", "read", doc=sos["E"])),
			"an E-Commerce user cannot open an E-com order")
		_assert(not _as(users["sales"], lambda: frappe.has_permission("Pick List", "read", doc=f"{tag}-PL-E")),
			"a Sales user can open an E-com Pick List")
		_assert(not _as(users["sales"], lambda: frappe.has_permission("Delivery Note", "read", doc=f"{tag}-DN-E")),
			"a Sales user can open an E-com Delivery Note")

	check("#22 opening an order, Pick List or Delivery Note of another channel is refused", _record_by_url)

	def _export_follows_the_list():
		from frappe.desk.reportview import get_form_params  # noqa: F401 (export builds on get_list)

		rows = _as(users["ecom"], lambda: frappe.get_list("Sales Order", filters={"name": ["like", like]},
			fields=["name", "custom_channel"], as_list=True))
		_assert({r[1] for r in rows} == {"E-com"}, rows)

	check("#22 the Report view / export query (get_list) returns only the user's channel", _export_follows_the_list)

	def _assigned_rule_still_applies():
		pl_user = _user(f"{tag.lower()}.plu@example.com", ["PL User"])
		frappe.db.set_value("Pick List", f"{tag}-PL-O", "custom_assigned_to", pl_user, update_modified=False)
		seen = visible(pl_user, "Pick List")
		_assert(seen == {f"{tag}-PL-O"}, f"assigned-only PL User saw {sorted(seen)}")
		_assert(not _as(pl_user, lambda: frappe.has_permission("Pick List", "read", doc=f"{tag}-PL-E")),
			"the channel hook overrode the assigned-only rule")

	check("#22 the existing assigned-only rule for PL Users still holds", _assigned_rule_still_applies)

	def _custom_list_pages():
		from alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry import get_delivery_note_list
		from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import get_pick_list_entry_list

		pls = {r.name for r in _as(users["ecom"], lambda: get_pick_list_entry_list(page_length=5000)["data"])
		       if r.name.startswith(tag)}
		_assert(pls == {f"{tag}-PL-E"}, f"Pick List page gave an E-Commerce user {sorted(pls)}")
		dns = {r.get("name") for r in (_as(users["sales"], lambda: get_delivery_note_list(page_length=5000)) or {}).get("data", [])
		       if str(r.get("name", "")).startswith(tag)}
		_assert(dns == names("Delivery Note", "OGB"), f"Delivery Note page gave a Sales user {sorted(dns)}")
		none = _as(users["ecom"], lambda: get_pick_list_entry_list(page_length=50, sales_order=sos["O"])["data"])
		_assert(not none, "filtering the Pick List page by an Offline order showed its Pick Lists to E-com")

	check("#22 the Pick List and Delivery Note list pages apply the channel too", _custom_list_pages)

	def _accounts_format_report():
		from alpinos.alpinos_development.report.accounts_format_report.accounts_format_report import _channel_scoped

		got = set(_as(users["sales"], lambda: _channel_scoped(list(sos.values()))))
		_assert(got == {sos["O"], sos["G"], sos["B"]}, f"Accounts Format Report kept {sorted(got)} for Sales")

	check("#22 Accounts Format Report (and its export) keeps only the user's channel", _accounts_format_report)


# ----------------------------------------------------- #39 item display


def _item_display_configuration(tag):
	from alpinos import item_display_config as D

	report = frappe.db.get_value("Report", {"report_type": "Script Report", "name": ["not in", [
		"Stock Ledger", "Stock Balance", "Stock Projected Qty", "Item-wise Sales Register", "Stock Ageing"]]}, "name")
	page = frappe.db.get_value("Page", {"name": "dispatch-report"}, "name") or frappe.db.get_value("Page", {}, "name")

	def new_config(**kw):
		d = frappe.get_doc(dict({"doctype": "Item Display Configuration", "config_name": f"{tag} cfg",
			"enabled": 1, "sku_field": "item_code", "apply_item_color": 1}, **kw))
		return d

	check("#39 a configuration with no report or page is refused", lambda: throws(
		lambda: new_config().insert(), "at least one report or page"))
	check("#39 a configuration that applies nothing is refused", lambda: throws(
		lambda: new_config(apply_item_color=0, reports=[{"report": report}]).insert(), "Apply Item Master"))

	def _rules_reach_the_boot():
		d = new_config(reports=[{"report": report}], pages=[{"page": page}], color_display="Both",
			apply_item_sequence=1, sort_direction="Descending")
		d.insert()
		rules = D.get_rules()
		_assert(rules["reports"].get(report, {}).get("sort_dir") == "Descending", rules["reports"].get(report))
		_assert(rules["pages"].get(page, {}).get("color_display") == "Both", rules["pages"].get(page))
		boot = frappe._dict()
		D.extend_bootinfo(boot)
		_assert(boot.get("alpinos_item_display") and "items" in boot.alpinos_item_display, "nothing in the boot")
		return d

	check("#39 an enabled configuration reaches the browser boot for its reports and pages", _rules_reach_the_boot)

	def _one_config_per_target():
		throws(lambda: new_config(config_name=f"{tag} other", reports=[{"report": report}]).insert(), "already follow")

	check("#39 a report cannot follow two configurations", _one_config_per_target)

	def _disabled_is_ignored():
		d = frappe.get_doc("Item Display Configuration", f"{tag} cfg")
		d.enabled = 0
		d.save()
		_assert(report not in D.get_rules()["reports"], "a disabled configuration still applies")

	check("#39 a disabled configuration applies nowhere", _disabled_is_ignored)

	check("#39 the stock reports kept their colour as a default configuration", lambda: _assert(
		frappe.db.exists("Item Display Configuration", "Stock Reports - Item Colour")))

	def _item_meta():
		code = frappe.db.get_value("Item", {"disabled": 0}, "name")
		frappe.db.set_value("Item", code, {"custom_color": "#123456", "custom_sequence": 7}, update_modified=False)
		meta = D.get_item_meta()
		_assert(meta.get(code) == ["#123456", 7], meta.get(code))

	check("#39 each Item's colour and sequence are sent with the rules", _item_meta)


# --------------------------------------------------- #43 draft DN date


def _dispatch_date_on_draft_note():
	from alpinos.alpinos_development.page.delivery_note_entry.delivery_note_entry import (
		get_delivery_note_data,
		save_delivery_note_data,
	)

	dn = frappe.db.sql(
		"""
		SELECT dn.name, dn.custom_sales_order_id AS so, MAX(dni.against_pick_list) AS pl
		FROM `tabDelivery Note` dn JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 0 AND IFNULL(dn.is_return, 0) = 0 AND IFNULL(dni.against_pick_list, '') <> ''
		  AND IFNULL(dn.custom_sales_order_id, '') <> '' AND IFNULL(dn.custom_transporter_name, '') <> ''
		GROUP BY dn.name ORDER BY dn.modified DESC LIMIT 1
		""",
		as_dict=True,
	)
	if not dn:
		skip("#43 draft Delivery Note date", "no draft Delivery Note with a Pick List and Transporter")
		return
	n = dn[0]
	new = add_days(today(), 6)

	def _editable_and_carried():
		frappe.db.set_value("Delivery Note", n.name, "custom_dispatch_date", f"{today()} 15:45:00", update_modified=False)
		data = get_delivery_note_data(n.name)
		_assert(data.get("custom_dispatch_date_value") == str(today()), f"page value {data.get('custom_dispatch_date_value')}")
		save_delivery_note_data(n.name, frappe.as_json({"custom_dispatch_date": str(new)}))
		value = frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date")
		_assert(getdate(value) == getdate(new), f"note still {value}")
		_assert(get_datetime(value).strftime("%H:%M:%S") == "15:45:00", f"time of day lost: {value}")
		_assert(getdate(frappe.db.get_value("Sales Order", n.so, "custom_dispatch_date")) == getdate(new), "Sales Order not updated")
		_assert(getdate(frappe.db.get_value("Pick List", n.pl, "custom_dispatch_date")) == getdate(new), "Pick List not updated")

	check("#43 a draft note's page saves a new Dispatch Date and carries it to the order and Pick List",
		_editable_and_carried)

	def _blank_does_not_clear():
		before = frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date")
		save_delivery_note_data(n.name, frappe.as_json({"custom_dispatch_date": None}))
		_assert(frappe.db.get_value("Delivery Note", n.name, "custom_dispatch_date") == before, "a blank date cleared it")

	check("#43 an empty date on the page does not blank the mandatory Dispatch Date", _blank_does_not_clear)
