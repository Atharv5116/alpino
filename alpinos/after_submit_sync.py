"""Allow Transporter / LR No / Dispatch Date to be changed AFTER submission on the
Pick List and Delivery Note, keep the two docs in sync, and audit every change.

- Pick List: Transporter + Dispatch Date edits propagate to the linked Delivery
  Note(s) (even if the DN is already submitted).
- Delivery Note: Transporter + Dispatch Date edits propagate back to the Pick List;
  LR No. edits are logged only.
- Every change is written to the Field Change Log (previous/new/user/time) and the
  edited doc's "Changed After Submission" flag is set.

Propagation uses db.set_value (no doc events), so PL<->DN updates never loop.
"""

import frappe

from alpinos.alpinos_development.doctype.field_change_log.field_change_log import log_field_change

# Pick List field -> (label, Delivery Note field to propagate to | None)
_PL_WATCH = {
	"custom_transporter": ("Transporter", "custom_transporter_name"),
	"custom_dispatch_date": ("Dispatch Date", "custom_dispatch_date"),
}
# Delivery Note field -> (label, Pick List field to propagate to | None)
_DN_WATCH = {
	"custom_transporter_name": ("Transporter", "custom_transporter"),
	"custom_dispatch_date": ("Dispatch Date", "custom_dispatch_date"),
	"custom_lr_gr_no": ("LR No.", None),
}


def _changed(doc, watch):
	"""{fieldname: (old, new)} for watched fields that actually changed vs the pre-save doc."""
	before = doc.get_doc_before_save()
	if not before:
		return {}
	out = {}
	for f in watch:
		if not doc.meta.has_field(f):
			continue
		old, new = before.get(f), doc.get(f)
		if str(old or "") != str(new or ""):
			out[f] = (old, new)
	return out


def _dns_for_pick_list(pl_name):
	return list({
		r.parent for r in frappe.get_all(
			"Delivery Note Item", filters={"against_pick_list": pl_name}, fields=["parent"]
		)
	})


def _pick_lists_for_dn(doc):
	return list({it.against_pick_list for it in (doc.get("items") or []) if it.get("against_pick_list")})


def pick_list_on_update_after_submit(doc, method=None):
	changes = _changed(doc, _PL_WATCH)
	if not changes:
		return
	dns = _dns_for_pick_list(doc.name)
	for f, (old, new) in changes.items():
		label, dn_field = _PL_WATCH[f]
		log_field_change("Pick List", doc.name, label, old, new, after_submit=1)
		if dn_field:
			for dn in dns:
				cur = frappe.db.get_value("Delivery Note", dn, dn_field)
				if str(cur or "") != str(new or ""):
					frappe.db.set_value("Delivery Note", dn, dn_field, new, update_modified=False)
					frappe.db.set_value("Delivery Note", dn, "custom_changed_after_submit", 1, update_modified=False)
					log_field_change("Delivery Note", dn, label + " (from Pick List)", cur, new, after_submit=1)
	frappe.db.set_value("Pick List", doc.name, "custom_changed_after_submit", 1, update_modified=False)


def delivery_note_on_update_after_submit(doc, method=None):
	changes = _changed(doc, _DN_WATCH)
	if not changes:
		return
	pls = _pick_lists_for_dn(doc)
	for f, (old, new) in changes.items():
		label, pl_field = _DN_WATCH[f]
		log_field_change("Delivery Note", doc.name, label, old, new, after_submit=1)
		if pl_field:
			for pl in pls:
				cur = frappe.db.get_value("Pick List", pl, pl_field)
				if str(cur or "") != str(new or ""):
					frappe.db.set_value("Pick List", pl, pl_field, new, update_modified=False)
					frappe.db.set_value("Pick List", pl, "custom_changed_after_submit", 1, update_modified=False)
					log_field_change("Pick List", pl, label + " (from Delivery Note)", cur, new, after_submit=1)
	frappe.db.set_value("Delivery Note", doc.name, "custom_changed_after_submit", 1, update_modified=False)


# Draft Delivery Note: which field edits propagate to the Pick List while still in Draft.
_DN_DRAFT_WATCH = {
	"custom_transporter_name": ("Transporter", "custom_transporter"),
}


def delivery_note_on_update_draft(doc, method=None):
	"""While a Delivery Note is still in DRAFT, a Transporter edit propagates to the
	linked Pick List(s) and is logged on both docs. (A submitted DN goes through
	delivery_note_on_update_after_submit instead.) Fires on every draft save but only
	acts on a genuine change vs the pre-save value, so creating a DN — which just
	inherits the Pick List's transporter — never loops back onto the Pick List."""
	if doc.docstatus != 0:
		return
	changes = _changed(doc, _DN_DRAFT_WATCH)
	if not changes:
		return
	pls = _pick_lists_for_dn(doc)
	for f, (old, new) in changes.items():
		label, pl_field = _DN_DRAFT_WATCH[f]
		log_field_change("Delivery Note", doc.name, label, old, new, after_submit=0)
		for pl in pls:
			cur = frappe.db.get_value("Pick List", pl, pl_field)
			if str(cur or "") != str(new or ""):
				frappe.db.set_value("Pick List", pl, pl_field, new, update_modified=False)
				log_field_change("Pick List", pl, label + " (from Delivery Note)", cur, new, after_submit=0)


_AFTER_SUBMIT_EDITABLE = {
	"Pick List": {"custom_transporter", "custom_dispatch_date"},
	"Delivery Note": {"custom_transporter_name", "custom_lr_gr_no", "custom_dispatch_date"},
}


@frappe.whitelist()
def update_after_submit_fields(doctype, name, values):
	"""Save Transporter / LR No / Dispatch Date edits on a SUBMITTED Pick List / Delivery
	Note (from the custom entry pages). doc.save() runs update_after_submit, which fires
	on_update_after_submit -> PL<->DN propagation + Field Change Log audit."""
	import json

	if isinstance(values, str):
		values = json.loads(values)
	allowed = _AFTER_SUBMIT_EDITABLE.get(doctype)
	if not allowed:
		frappe.throw(frappe._("After-submit editing is not allowed for {0}.").format(doctype))
	frappe.has_permission(doctype, "write", doc=name, throw=True)

	doc = frappe.get_doc(doctype, name)
	if doc.docstatus != 1:
		frappe.throw(frappe._("Only a submitted {0} can be updated here.").format(doctype))

	changed = False
	for f, v in (values or {}).items():
		if f in allowed and doc.meta.has_field(f):
			v = v or None
			if str(doc.get(f) or "") != str(v or ""):
				doc.set(f, v)
				changed = True
	if changed:
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()
	return {"ok": True, "changed": changed}


def ensure_after_submit_fields():
	"""Idempotently make the watched fields editable after submit and add the
	'Changed After Submission' indicator to Pick List + Delivery Note. Run on migrate."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	# Indicator field on both docs.
	create_custom_fields(
		{
			"Pick List": [{
				"fieldname": "custom_changed_after_submit", "label": "Changed After Submission",
				"fieldtype": "Check", "read_only": 1, "allow_on_submit": 1, "insert_after": "custom_dispatch_date",
			}],
			"Delivery Note": [{
				"fieldname": "custom_changed_after_submit", "label": "Changed After Submission",
				"fieldtype": "Check", "read_only": 1, "allow_on_submit": 1, "insert_after": "custom_lr_gr_no",
			}],
		},
		ignore_validate=True,
	)

	# Allow the watched fields to be edited after submit.
	for dt, fields in (
		("Pick List", ["custom_transporter", "custom_dispatch_date"]),
		("Delivery Note", ["custom_transporter_name", "custom_lr_gr_no", "custom_dispatch_date"]),
	):
		for f in fields:
			if frappe.get_meta(dt).has_field(f):
				make_property_setter(dt, f, "allow_on_submit", 1, "Check", validate_fields_for_doctype=False)

	# Delivery Note Transporter must be EDITABLE in Draft (BRD). It was originally
	# read-only ("fetched from Pick List"); a draft edit now propagates back to the
	# Pick List. A read-only field's changes are dropped by doc.save(), so clear it.
	if frappe.get_meta("Delivery Note").has_field("custom_transporter_name"):
		make_property_setter(
			"Delivery Note", "custom_transporter_name", "read_only", 0, "Check",
			validate_fields_for_doctype=False,
		)
	frappe.clear_cache(doctype="Pick List")
	frappe.clear_cache(doctype="Delivery Note")
