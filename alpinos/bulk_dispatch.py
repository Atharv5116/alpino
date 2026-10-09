"""Changes(HP) #59: create and submit Pick Lists, and create Delivery Notes, in bulk.

    "Warehouse Admin and Warehouse Manager should be able to:
     - Create Pick Lists in bulk with Draft status.
     - Submit Pick Lists in bulk.
     - Create Delivery Notes in bulk with Draft status."

Every action here is the existing single-record path run over a list, deliberately: a bulk
button that took a shortcut would diverge from what the Pick List entry page produces, and
the two would drift apart. So a bulk Pick List is built through the same mapping the entry
page uses, at the mapped quantity for every line, and a bulk Delivery Note goes through
create_delivery_note_from_pick_list with its batch resolution intact.

One bad record never stops the batch. Each row runs inside its own savepoint, so a Sales
Order that cannot be picked is reported and rolled back on its own while the rest go
through -- the opposite behaviour (abort everything) is useless when someone has just
ticked forty orders.
"""

import frappe
from frappe import _
from frappe.utils import cint

#: Who may run a bulk action. System Manager is included because it administers the queue.
BULK_ROLES = {"Warehouse Admin", "Warehouse Manager", "System Manager"}


def _check_permitted(action):
	if frappe.session.user == "Administrator":
		return
	if not (BULK_ROLES & set(frappe.get_roles(frappe.session.user))):
		frappe.throw(
			_("Only Warehouse Admin and Warehouse Manager may {0} in bulk.").format(action),
			frappe.PermissionError,
		)


def _as_list(value):
	"""Accept a JSON string, a list, or a single name -- the desk sends all three."""
	if value is None:
		return []
	if isinstance(value, str):
		value = value.strip()
		if value.startswith("["):
			import json

			return [str(v).strip() for v in json.loads(value) if str(v).strip()]
		return [value] if value else []
	return [str(v).strip() for v in value if str(v).strip()]


def _run_each(names, worker):
	"""Run `worker` per name in its own savepoint; collect one outcome per name."""
	done, skipped, failed = [], [], []
	for name in names:
		savepoint = f"bulk_{abs(hash(name)) % 10**8}"
		frappe.db.savepoint(savepoint)
		try:
			outcome = worker(name)
			if outcome.get("skipped"):
				frappe.db.rollback(save_point=savepoint)
				skipped.append({"name": name, "reason": outcome["skipped"]})
			else:
				done.append({"name": name, **{k: v for k, v in outcome.items() if k != "skipped"}})
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			failed.append({"name": name, "error": f"{type(e).__name__}: {e}"})
			frappe.log_error(frappe.get_traceback(), f"Bulk dispatch failed for {name}")
	# One commit for the batch. Each record already stands or falls on its own savepoint,
	# so this makes the successes durable without letting a failure take them with it.
	frappe.db.commit()
	return {
		"total": len(names),
		"done": done,
		"skipped": skipped,
		"failed": failed,
		"counts": {"done": len(done), "skipped": len(skipped), "failed": len(failed)},
	}


# ---------------------------------------------------------------------------
# Pick Lists
# ---------------------------------------------------------------------------

#: Header defaults the mapping supplies. The entry page shows these in the form and the
#: user submits them as they stand; a bulk create has no form, so it has to apply them
#: itself -- without the transporter the Pick List cannot be submitted at all.
_HEADER_DEFAULTS = ("custom_dispatch_date", "custom_gate", "custom_transporter")


def _default_header_and_items(so_name, remaining_only=0):
	"""The mapping's own header defaults, and every mapped line at its mapped quantity."""
	from alpinos.sales_order_api import get_pick_list_mapping_data

	data = get_pick_list_mapping_data(so_name, remaining_only=cint(remaining_only))
	header = {f: data.get(f) for f in _HEADER_DEFAULTS if data.get(f)}
	items = [
		{
			"name": row.get("name"),
			"qty": row.get("qty"),
			"custom_box": row.get("custom_box"),
		}
		for row in (data.locations or [])
	]
	return header, items


def _existing_open_pick_list(so_name):
	return frappe.db.get_value(
		"Pick List", {"custom_sales_order_id": so_name, "docstatus": ["<", 2]}, "name"
	)


@frappe.whitelist()
def bulk_create_pick_lists(sales_orders, remaining_only=0):
	"""Create one Draft Pick List per Sales Order.

	  bench --site SITE execute alpinos.bulk_dispatch.bulk_create_pick_lists --kwargs "{'sales_orders':['SOR-...']}"
	"""
	_check_permitted(_("create Pick Lists"))
	names = _as_list(sales_orders)
	remaining_only = cint(remaining_only)

	def worker(so_name):
		docstatus = frappe.db.get_value("Sales Order", so_name, "docstatus")
		if docstatus is None:
			return {"skipped": _("no such Sales Order")}
		if docstatus != 1:
			return {"skipped": _("the Sales Order is not submitted")}
		if cint(frappe.db.get_value("Sales Order", so_name, "custom_force_closed")):
			# Force close is permanent and refuses new Pick Lists. That is a business
			# outcome, not a failure, so it is reported as a skip with the rest.
			return {"skipped": _("the order is Force Closed")}
		if not remaining_only:
			existing = _existing_open_pick_list(so_name)
			if existing:
				return {"skipped": _("Pick List {0} already exists").format(existing)}

		header, items = _default_header_and_items(so_name, remaining_only)
		if not items:
			return {"skipped": _("nothing left to pick")}

		# The entry page's create_pick_list_as_draft() commits on its way out, which would
		# end the transaction and take every savepoint with it. The builder underneath it
		# does not, so call that and keep its permission gate here.
		if not frappe.has_permission("Pick List", "create"):
			frappe.throw(_("You are not permitted to create Pick Lists."), frappe.PermissionError)

		from alpinos.alpinos_development.page.pick_list_entry.pick_list_entry import (
			_build_pick_list_from_mapping,
		)

		pick_list = _build_pick_list_from_mapping(
			so_name, header=header, items=items, removed_rows=[], remaining_only=remaining_only
		)
		return {"pick_list": pick_list.name, "lines": len(items)}

	return _run_each(names, worker)


@frappe.whitelist()
def bulk_submit_pick_lists(pick_lists):
	"""Submit each Draft Pick List, through the document's own submit so hooks still run."""
	_check_permitted(_("submit Pick Lists"))
	names = _as_list(pick_lists)

	def worker(name):
		docstatus = frappe.db.get_value("Pick List", name, "docstatus")
		if docstatus is None:
			return {"skipped": _("no such Pick List")}
		if docstatus == 1:
			return {"skipped": _("already submitted")}
		if docstatus == 2:
			return {"skipped": _("cancelled")}
		if not frappe.has_permission("Pick List", "submit", doc=name):
			return {"skipped": _("you are not permitted to submit this Pick List")}
		doc = frappe.get_doc("Pick List", name)
		try:
			doc.submit()
		except frappe.ValidationError as e:
			# A Pick List that is simply not ready -- no PO No., no Transporter, a short
			# pick needing a decision -- is reported with the rule's own words and left
			# alone. Only something unexpected counts as a failure; in a batch of forty,
			# "not ready yet" and "broken" are different news.
			return {"skipped": frappe.utils.strip_html(str(e)) or _("validation failed")}
		return {"pick_list": name, "sales_order": doc.get("custom_sales_order_id")}

	return _run_each(names, worker)


# ---------------------------------------------------------------------------
# Delivery Notes
# ---------------------------------------------------------------------------

@frappe.whitelist()
def bulk_create_delivery_notes(pick_lists):
	"""Create one Draft Delivery Note per submitted Pick List."""
	_check_permitted(_("create Delivery Notes"))
	names = _as_list(pick_lists)

	def worker(name):
		docstatus = frappe.db.get_value("Pick List", name, "docstatus")
		if docstatus is None:
			return {"skipped": _("no such Pick List")}
		if docstatus != 1:
			return {"skipped": _("the Pick List is not submitted")}

		existing = frappe.db.get_value(
			"Delivery Note Item", {"against_pick_list": name, "docstatus": ["<", 2]}, "parent"
		)
		if existing:
			return {"skipped": _("Delivery Note {0} already exists").format(existing)}

		from alpinos.pick_list_api import create_delivery_note_from_pick_list

		dn = create_delivery_note_from_pick_list(name)
		# The helper returns a name whether it created or found one; it stays a draft here,
		# because #59 asks for Draft Delivery Notes and submission is its own decision.
		return {"pick_list": name, "delivery_note": dn}

	return _run_each(names, worker)


@frappe.whitelist()
def bulk_action_preview(sales_orders=None, pick_lists=None):
	"""What a bulk run would do, without doing it. Backs the confirmation dialog."""
	out = {}
	if sales_orders:
		rows = []
		for so in _as_list(sales_orders):
			existing = _existing_open_pick_list(so)
			rows.append(
				{
					"sales_order": so,
					"submitted": frappe.db.get_value("Sales Order", so, "docstatus") == 1,
					"existing_pick_list": existing,
					"eligible": bool(not existing)
					and frappe.db.get_value("Sales Order", so, "docstatus") == 1,
				}
			)
		out["pick_lists_to_create"] = rows
	if pick_lists:
		rows = []
		for pl in _as_list(pick_lists):
			docstatus = frappe.db.get_value("Pick List", pl, "docstatus")
			existing_dn = frappe.db.get_value(
				"Delivery Note Item", {"against_pick_list": pl, "docstatus": ["<", 2]}, "parent"
			)
			rows.append(
				{
					"pick_list": pl,
					"docstatus": docstatus,
					"can_submit": docstatus == 0,
					"can_make_dn": docstatus == 1 and not existing_dn,
					"existing_delivery_note": existing_dn,
				}
			)
		out["pick_lists"] = rows
	return out
