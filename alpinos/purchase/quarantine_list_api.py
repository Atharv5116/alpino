"""Server side of the Quarantine Stock list screen.

One paginated endpoint feeds the desk page at `purchase_quarantine_list`: every Purchase
Quarantine document, with what it still holds, its reminder, and the buttons the user may
press. Same shape as the Purchase Inward / QC / GRN list endpoints.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from alpinos.purchase import constants as C
from alpinos.purchase.quarantine import RELEASE_ROLES

DOCTYPE = "Purchase Quarantine"
ITEM_DOCTYPE = "Purchase Quarantine Item"
LIST_PAGE = "purchase_quarantine_list"
VIEW_PAGE = "purchase_quarantine_view"

PAGE_LENGTHS = (20, 50, 100)
DEFAULT_PAGE_LENGTH = 20
PAGE_ROLES = tuple(C.ALL_PURCHASE_ROLES) + ("System Manager",)

LIST_FIELDS = (
	"name",
	"purchase_inward",
	"purchase_order",
	"supplier",
	"supplier_name",
	"status",
	"quarantine_date",
	"quarantined_by",
	"entire_inward",
	"reason",
	"reminder_days",
	"next_reminder_on",
	"total_qty",
	"held_qty",
	"released_qty",
	"modified",
)

_SORTABLE = frozenset(
	{"name", "purchase_inward", "supplier_name", "status", "quarantine_date", "next_reminder_on", "held_qty", "modified"}
)


def _like(value):
	safe = str(value or "").strip().replace("%", "").replace("_", "")
	return f"%{safe}%" if safe else ""


def _date(value):
	try:
		return getdate(value) if value else None
	except Exception:
		return None


@frappe.whitelist()
def get_quarantine_list(
	start=0,
	page_length=DEFAULT_PAGE_LENGTH,
	quarantine_id=None,
	purchase_inward=None,
	supplier=None,
	item_code=None,
	status=None,
	from_date=None,
	to_date=None,
	reminder_due=None,
	sort_field=None,
	sort_dir=None,
):
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), max(PAGE_LENGTHS))

	filters = []
	for field, raw in (("name", quarantine_id), ("purchase_inward", purchase_inward)):
		pattern = _like(raw)
		if pattern:
			filters.append([field, "like", pattern])
	if supplier:
		filters.append(["supplier", "=", str(supplier).strip()])
	status = str(status or "").strip()
	if status in C.QRN_STATUSES:
		filters.append(["status", "=", status])
	fd, td = _date(from_date), _date(to_date)
	if fd:
		filters.append(["quarantine_date", ">=", f"{fd} 00:00:00"])
	if td:
		filters.append(["quarantine_date", "<=", f"{td} 23:59:59"])
	if cint(reminder_due):
		filters.append(["next_reminder_on", "<=", getdate()])
		filters.append(["status", "!=", C.QRN_RELEASED])
	if item_code:
		# Resolved to parents first: a child filter on get_list returns a document once per
		# matching line and breaks the count.
		parents = frappe.get_all(
			ITEM_DOCTYPE,
			filters={"parenttype": DOCTYPE, "item_code": str(item_code).strip()},
			pluck="parent",
			distinct=True,
		)
		filters.append(["name", "in", parents or ["__none__"]])

	sf = str(sort_field or "").strip()
	sd = "asc" if str(sort_dir or "").strip().lower() == "asc" else "desc"
	order_by = f"`{sf}` {sd}" if sf in _SORTABLE else "modified desc"

	count_rows = frappe.get_list(DOCTYPE, fields=["count(name) as total"], filters=filters, limit_page_length=0)
	total = cint(count_rows[0].get("total")) if count_rows else 0
	rows = frappe.get_list(
		DOCTYPE,
		fields=list(LIST_FIELDS),
		filters=filters,
		limit_start=start,
		limit_page_length=page_length + 1,
		order_by=order_by,
	)
	has_more = len(rows) > page_length
	rows = rows[:page_length]

	if rows:
		lines = frappe.get_all(
			ITEM_DOCTYPE,
			filters={"parenttype": DOCTYPE, "parent": ["in", [r.name for r in rows]]},
			fields=["parent", "item_code", "item_name", "qty", "uom", "status"],
			order_by="parent asc, idx asc",
		)
		by_parent = {}
		for line in lines:
			by_parent.setdefault(line.parent, []).append(line)
		may_release = bool(set(frappe.get_roles()).intersection(RELEASE_ROLES))
		today = getdate()
		for row in rows:
			items = by_parent.get(row.name, [])
			row["items"] = [
				{"item_code": i.item_code, "item_name": i.item_name, "qty": flt(i.qty), "uom": i.uom, "status": i.status}
				for i in items
			]
			row["item_count"] = len(items)
			row["held_items"] = len([i for i in items if i.status == C.QUARANTINE_HELD])
			row["reminder_due"] = bool(
				row.next_reminder_on and getdate(row.next_reminder_on) <= today and row.status != C.QRN_RELEASED
			)
			actions = [{"action": "view", "label": _("View"), "kind": "view"}]
			if may_release and row["held_items"]:
				actions.append({"action": "release", "label": _("Release"), "kind": "transition"})
			row["actions"] = actions

	return {"data": rows, "has_more": int(has_more), "start": start, "page_length": page_length, "total": total}


@frappe.whitelist()
def get_filter_options():
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return {"statuses": "\n" + "\n".join(C.QRN_STATUSES), "page_lengths": list(PAGE_LENGTHS)}


def setup_quarantine_page_access():
	"""Let the module roles open both quarantine pages. Idempotent; safe on every migrate."""
	for page in (LIST_PAGE, VIEW_PAGE):
		if not frappe.db.exists("Page", page):
			continue
		for role in PAGE_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			if frappe.db.exists("Has Role", {"parenttype": "Page", "parent": page, "role": role}):
				continue
			frappe.get_doc(
				{"doctype": "Has Role", "parenttype": "Page", "parentfield": "roles", "parent": page, "role": role}
			).insert(ignore_permissions=True)
	frappe.clear_cache()
