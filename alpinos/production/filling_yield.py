"""Total Process Loss evaluation -- FRD 6.5.

When every Sub PO of a Parent PO is Completed, the Parent's yield is recorded in a
Production Yield Record (rather than adding fields to the Production Order doctype):

    Overall Process Loss (KG) = Original Issued RM (KG) - Total Final Filled FG (KG)
    % Process Loss            = Overall Process Loss / Original Issued RM x 100

default pending BA confirmation (the FRD itself says "Need to confirm with Production team"):
Issued RM = net submitted Material Issues minus Material Returns of the Parent's Sub POs,
counting RM and Additive rows (PM excluded) in their stock UOM, assumed KG.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from alpinos.production import constants as C
from alpinos.production import filling_common as F

KIND_ISSUE = "Material Issue"
KIND_RETURN = "Material Return"
RM_TYPES = (C.MATERIAL_RM, C.MATERIAL_ADDITIVE)


def _net_issued(sub_names):
	if not sub_names or not F.has_field(F.SE, "custom_entry_kind") or not F.has_field(F.SE, F.B_SUB):
		return 0.0
	totals = {}
	for kind, sign in ((KIND_ISSUE, 1), (KIND_RETURN, -1)):
		entries = frappe.get_all(F.SE, filters={"custom_entry_kind": kind, F.B_SUB: ("in", sub_names),
		                                        "docstatus": 1}, pluck="name")
		if not entries:
			continue
		fields = ["item_code", "transfer_qty", "qty"]
		if F.has_field("Stock Entry Detail", "custom_material_type"):
			fields.append("custom_material_type")
		for r in frappe.get_all("Stock Entry Detail", filters={"parent": ("in", entries)}, fields=fields):
			totals.setdefault(r.item_code, [0.0, r.get("custom_material_type")])
			totals[r.item_code][0] += sign * flt(r.transfer_qty or r.qty)
	if not totals:
		return 0.0
	item_types = {}
	if F.has_field("Item", "custom_material_type"):
		item_types = dict(frappe.get_all("Item", filters={"name": ("in", list(totals))},
		                                 fields=["name", "custom_material_type"], as_list=True))
	out = 0.0
	for item, (qty, row_type) in totals.items():
		mtype = row_type or item_types.get(item)
		if mtype and mtype not in RM_TYPES:
			continue
		out += qty
	return max(out, 0.0)


def compute_yield(parent_po):
	if not parent_po or not frappe.db.exists("DocType", F.YIELD):
		return None
	subs = frappe.get_all(F.WORK_ORDER, filters={F.PARENT_FIELD: parent_po, "docstatus": ("<", 2)},
	                      pluck="name")
	issued = flt(_net_issued(subs), 3)
	rows = frappe.get_all(F.INWARD, filters={"parent_po": parent_po, "docstatus": 1},
	                      fields=["target_sku", "sum(filled_kg) as kg", "sum(input_pcs) as pcs"],
	                      group_by="target_sku")
	filled = flt(sum(flt(r.kg) for r in rows), 3)
	pcs = sum(cint(r.pcs) for r in rows)
	loss = flt(issued - filled, 3)
	name = frappe.db.get_value(F.YIELD, {"parent_po": parent_po}, "name")
	doc = frappe.get_doc(F.YIELD, name) if name else frappe.new_doc(F.YIELD)
	doc.parent_po = parent_po
	doc.fg_item = frappe.db.get_value("Production Order", parent_po, "fg_item")
	doc.issued_rm_kg = issued
	doc.filled_kg = filled
	doc.filled_pcs = pcs
	doc.loss_kg = loss
	doc.loss_pct = flt(loss / issued * 100, 2) if issued else 0
	doc.sku_breakdown = "\n".join(f"{r.target_sku}: {cint(r.pcs)} pcs / {flt(r.kg, 3)} KG" for r in rows)
	doc.computed_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	return doc.name


def check_parent_completion(parent_po):
	"""Run 6.5 once every Sub PO of the Parent is Completed. Never fails the caller."""
	try:
		if not parent_po:
			return None
		statuses = frappe.get_all(F.WORK_ORDER, filters={F.PARENT_FIELD: parent_po, "docstatus": ("<", 2)},
		                          pluck=F.EXEC_FIELD)
		if statuses and all(s == "Completed" for s in statuses):
			return compute_yield(parent_po)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Filling: yield record")
	return None


@frappe.whitelist()
def recompute_yield(parent_po):
	F.require(F.PLANNER_ROLES + (F.ROLE_PLANT_HEAD,), _("recompute the yield"))
	name = compute_yield(parent_po)
	frappe.db.commit()
	return {"name": name}
