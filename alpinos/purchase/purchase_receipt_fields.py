"""Purchase Receipt = the GRN: custom fields, form layout and the GRN naming series.

BRD "Purchase Inward Part -1" section 5 (5.2.1 header, 5.2.2 item details, 5.4 VAL-GRN-*,
5.5 BR-GRN-*) and the GRN half of the naming-series requirement.

Quantity mapping — the BRD's three quantities are already native on Purchase Receipt Item,
so this module adds NO qty fields of its own:

	BRD "Total Received Qty"  ->  received_qty  (read_only; BuyingController.
	                              validate_accepted_rejected_qty forces it to
	                              accepted + rejected and raises QtyMismatchError otherwise)
	BRD "Approved Qty"        ->  qty           (core label is already "Accepted Quantity")
	BRD "Rejected Qty"        ->  rejected_qty  (posts a real SLE into rejected_warehouse)

A custom approved_qty / rejected_qty pair would fight QtyMismatchError, would be invisible
to the Purchase Order roll-up (which reads received_qty) and would leave the rejected stock
with nowhere to land. BR-GRN-08 is therefore satisfied by the core fields.

Registered in alpinos/hooks.py (owned by the orchestrator):

	after_migrate                                                -> setup_purchase_receipt_fields
	doc_events["Purchase Receipt"]["validate"]                   -> validate_grn_fields
	doc_events["Purchase Receipt"]["before_update_after_submit"] -> validate_grn_status
"""

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint, flt

from alpinos.purchase import constants as C

DOCTYPE = "Purchase Receipt"
ITEM_DOCTYPE = "Purchase Receipt Item"

# Purchase Receipt autonames by `naming_series:`, and set_name_by_naming_series appends its
# own ".#####" to whatever the option holds — parse_naming_series ignores the second counter
# (series_set), so the explicit suffix here is redundant but harmless, and it keeps this
# module's series string identical to the Purchase Inward / Purchase QC ones.
GRN_NAMING_SERIES = "GRN-.YYYY.-.#####"

# Link/Table targets that must exist before the parent fields can be created.
_LINK_TARGETS = ("Purchase Inward", "Purchase QC", "Purchase GRN Change Log")

# Blank first option so a plain (non-inward) Purchase Receipt can legitimately carry no GRN
# status, and so the standard filter offers "not a GRN" — same shape as core `status`.
_GRN_STATUS_OPTIONS = "\n" + C.select_options(C.GRN_STATUSES)

# VAL-QC-05: a rejected line must carry a reason. Scoped to rows on a real GRN so ordinary
# ERPNext Purchase Receipts are not made stricter. Client-only — see validate_grn_fields().
_REJECTED = "eval:doc.rejected_qty > 0"
_REJECTED_ON_GRN = "eval:doc.rejected_qty > 0 && parent.custom_purchase_inward"


def setup_purchase_receipt_fields():
	"""Idempotent entry point; safe to re-run on every migrate.

	All-or-nothing on purpose. The naming series is touched only once every link target
	exists, so a run that cannot create the GRN fields cannot renumber Purchase Receipt
	either — a site with GRN- numbering and no GRN fields is worse than an untouched one.
	"""
	missing = [dt for dt in _LINK_TARGETS if not frappe.db.exists("DocType", dt)]
	if missing:
		# Error Log, not frappe.logger: after_migrate runs once every app doctype is synced,
		# so reaching this means the migrate applied only part of the module and somebody has
		# to see it. The next run with the doctypes present completes the setup.
		frappe.log_error(
			title="Purchase Receipt GRN fields skipped",
			message=(
				"alpinos.purchase.purchase_receipt_fields made NO changes: missing doctype(s) "
				"{0}. Purchase Receipt keeps its core naming series and carries no GRN fields "
				"until those doctypes are migrated and this runs again."
			).format(", ".join(missing)),
		)
		return

	_setup_naming_series()
	create_custom_fields(_custom_fields(), update=True)
	_apply_form_layout()
	_drop_retired_fields()
	frappe.clear_cache(doctype=DOCTYPE)
	frappe.clear_cache(doctype=ITEM_DOCTYPE)


def execute():
	setup_purchase_receipt_fields()


# --- custom fields ----------------------------------------------------------


def _custom_fields():
	return {
		DOCTYPE: [
			# BRD 5.2.1 header. Sits directly under the supplier block so the inward chain
			# is the first thing a reviewer sees on the GRN.
			dict(
				fieldname="custom_grn_section",
				label="GRN Details",
				fieldtype="Section Break",
				insert_after="return_against",
			),
			dict(
				fieldname="custom_purchase_inward",
				label="Purchase Inward",
				fieldtype="Link",
				options="Purchase Inward",
				insert_after="custom_grn_section",
				read_only=1,
				search_index=1,
				description="Parent Purchase Inward this GRN was generated from (BR-GRN-01).",
			),
			dict(
				fieldname="custom_purchase_qc",
				label="Purchase QC",
				fieldtype="Link",
				options="Purchase QC",
				insert_after="custom_purchase_inward",
				read_only=1,
				description="Purchase QC whose approved quantity produced this GRN.",
			),
			dict(
				fieldname="custom_grn_status",
				label="GRN Status",
				fieldtype="Select",
				options=_GRN_STATUS_OPTIONS,
				insert_after="custom_purchase_qc",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				in_list_view=1,
				in_standard_filter=1,
				description="Draft until the Admin final-submits (BR-GRN-03 / BR-GRN-06).",
			),
			dict(
				fieldname="custom_grn_col_1",
				fieldtype="Column Break",
				insert_after="custom_grn_status",
			),
			# No vehicle field of our own: core `lr_no` is already labelled "Vehicle Number",
			# the BRD's GRN header (5.2.1) lists none, and a second field would leave lr_no —
			# what the standard print format and every report read — blank on every GRN. The
			# GRN generator writes the inward's vehicle number into lr_no.
			dict(
				fieldname="custom_final_submitted_by",
				label="Final Submitted By",
				fieldtype="Link",
				options="User",
				insert_after="custom_grn_col_1",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="Admin who performed the final GRN submission (BR-GRN-06).",
			),
			dict(
				fieldname="custom_final_submission_datetime",
				label="Final Submission Date & Time",
				fieldtype="Datetime",
				insert_after="custom_final_submitted_by",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
			),
			dict(
				fieldname="custom_grn_col_2",
				fieldtype="Column Break",
				insert_after="custom_final_submission_datetime",
			),
			dict(
				fieldname="custom_debit_note",
				label="Debit Note",
				fieldtype="Link",
				options="Purchase Invoice",
				insert_after="custom_grn_col_2",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
				description="Raised only when the rejected quantity is greater than zero (BR-GRN-09 / BR-GRN-10).",
			),
			dict(
				fieldname="custom_purchase_quarantine",
				label="Quarantine Document",
				fieldtype="Link",
				options="Purchase Quarantine",
				insert_after="custom_debit_note",
				read_only=1,
				allow_on_submit=1,
				depends_on="eval:doc.custom_purchase_quarantine",
				description="QC quarantined items on this GRN: they are received into the Quarantine warehouse and move to their warehouse when released.",
			),
			dict(
				fieldname="custom_grn_attachment",
				label="GRN Attachment",
				fieldtype="Attach",
				insert_after="custom_purchase_quarantine",
			),
			dict(
				fieldname="custom_receiving_remarks",
				label="Receiving Remarks",
				fieldtype="Small Text",
				insert_after="custom_grn_attachment",
			),
			# BR-GRN-05: every Draft GRN edit is recorded with old value, new value, user,
			# timestamp and reason. Kept out of the header so the form stays readable.
			dict(
				fieldname="custom_grn_change_log_section",
				label="GRN Change Log",
				fieldtype="Section Break",
				insert_after="per_returned",
				collapsible=1,
				depends_on="eval:doc.custom_purchase_inward",
			),
			dict(
				fieldname="custom_grn_change_log",
				label="GRN Change Log",
				fieldtype="Table",
				options="Purchase GRN Change Log",
				insert_after="custom_grn_change_log_section",
				read_only=1,
				allow_on_submit=1,
				no_copy=1,
			),
		],
		ITEM_DOCTYPE: [
			dict(
				fieldname="custom_rejection_reason",
				label="Rejection Reason",
				fieldtype="Small Text",
				insert_after="rejected_qty",
				in_list_view=1,
				columns=3,
				depends_on=_REJECTED,
				mandatory_depends_on=_REJECTED_ON_GRN,
				description="VAL-QC-05: required whenever the Rejected Quantity is greater than zero.",
			),
			dict(
				fieldname="custom_usp",
				label="USP",
				fieldtype="Data",
				insert_after="sample_quantity",
			),
			dict(
				fieldname="custom_mrp",
				label="MRP",
				fieldtype="Currency",
				insert_after="custom_usp",
			),
			# Row name of the Purchase Inward Item this line came from — mirrors how core
			# stores purchase_order_item. Purchase Inward Item autonames by hash, so item
			# code alone cannot identify the source line.
			dict(
				fieldname="custom_purchase_inward_item",
				label="Purchase Inward Item",
				fieldtype="Data",
				insert_after="purchase_order_item",
				read_only=1,
				no_copy=1,
				search_index=1,
			),
			# QC quarantine (quarantine.create_from_qc): the line's approved quantity is
			# received into the Quarantine warehouse and moved to the release warehouse when
			# the Quarantine document releases it. Not no_copy: an amended GRN keeps the hold.
			dict(
				fieldname="custom_quarantine_status",
				label="Quarantine",
				fieldtype="Select",
				options="\nQuarantined\nReleased",
				insert_after="warehouse",
				read_only=1,
				allow_on_submit=1,
				depends_on="eval:doc.custom_quarantine_status",
			),
			dict(
				fieldname="custom_release_warehouse",
				label="Release To Warehouse",
				fieldtype="Link",
				options="Warehouse",
				insert_after="custom_quarantine_status",
				read_only=1,
				allow_on_submit=1,
				depends_on="eval:doc.custom_quarantine_status",
			),
		],
	}


# --- naming series (BRD row 291, GRN half) ----------------------------------


def _setup_naming_series():
	"""Offer the GRN series on Purchase Receipt without taking over its numbering.

	Appended, never prepended, and no `default` property setter: get_default_naming_series
	returns the FIRST option as the server-side fallback, so leading with GRN- would number
	every plain receipt and every make_purchase_return document GRN-YYYY-NNNNN and the GRN
	number would stop identifying a goods receipt. The GRN generator selects the series
	explicitly — `pr.naming_series = purchase_receipt_fields.GRN_NAMING_SERIES`.
	"""
	options = _series_options(DOCTYPE, GRN_NAMING_SERIES)
	if options is not None:
		_ps(DOCTYPE, "naming_series", "options", options, "Text")
	_clear_series_default()


def _series_options(doctype, series):
	"""Return the options string with `series` last, or None when it is already correct.

	Reads the raw stored value (Property Setter first, then the shipped DocField) rather
	than meta, so a stale doctype cache cannot make this drop MAT-PR-RET-.YYYY.-. The list
	is rebuilt from scratch rather than appended to, so a site left with the series in the
	leading position by an earlier version of this module is corrected on the next migrate.
	"""
	current = frappe.db.get_value(
		"Property Setter",
		{"doc_type": doctype, "field_name": "naming_series", "property": "options"},
		"value",
	)
	if not current:
		current = frappe.db.get_value(
			"DocField", {"parent": doctype, "fieldname": "naming_series"}, "options"
		)

	existing = [line.strip() for line in (current or "").splitlines() if line.strip()]
	wanted = [line for line in existing if line != series] + [series]
	if wanted == existing:
		return None
	return "\n".join(wanted)


def _clear_series_default():
	"""Remove the site-wide naming_series default an earlier version of this module set.

	Only a row holding our own series is deleted, so a default set by anyone else survives.
	"""
	for name in frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": DOCTYPE,
			"field_name": "naming_series",
			"property": "default",
			"value": GRN_NAMING_SERIES,
		},
		pluck="name",
	):
		frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)


# --- retired fields ---------------------------------------------------------

# Created by an earlier version of this module. custom_vehicle_no duplicated core `lr_no`
# with no sync between them; the data lives in lr_no now.
_RETIRED_FIELDS = ((DOCTYPE, "custom_vehicle_no"),)


def _drop_retired_fields():
	for doctype, fieldname in _RETIRED_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
		if not name:
			continue
		if frappe.db.has_column(doctype, fieldname) and frappe.db.count(
			doctype, {fieldname: ("is", "set")}
		):
			# Deleting the Custom Field leaves the column orphaned but strips the field from
			# meta, so the values stop being readable through the form, the API and reports.
			# Never strand live data silently.
			frappe.log_error(
				title="Purchase Receipt: retired field still holds data",
				message=(
					"{0}.{1} is retired in favour of core lr_no but still holds values, so it "
					"was left in place. Copy the values into lr_no, then delete the Custom Field."
				).format(doctype, fieldname),
			)
			continue
		frappe.delete_doc("Custom Field", name, ignore_permissions=True)


# --- form layout ------------------------------------------------------------


def _apply_form_layout():
	# The item grid is already at Frappe's 11-column budget (grid.js setup_visible_columns
	# bails out of the loop the moment the running total exceeds it), so a new grid column
	# has to be paid for. `amount` is the cheapest to give up: the BRD's GRN grid (5.2.2)
	# carries quantities only, and `amount` is still one click away in the row form.
	_ps(ITEM_DOCTYPE, "amount", "in_list_view", 0, "Check")
	_ps(ITEM_DOCTYPE, "item_code", "columns", 2, "Int")

	# Make the BRD -> ERPNext quantity mapping visible to the people using the form.
	_ps(
		ITEM_DOCTYPE,
		"received_qty",
		"description",
		"BRD Total Received Qty. Always Accepted + Rejected; set the other two and leave this alone.",
		"Text",
	)
	_ps(ITEM_DOCTYPE, "qty", "description", "BRD Approved Qty — the quantity QC approved.", "Text")
	_ps(
		ITEM_DOCTYPE,
		"rejected_qty",
		"description",
		"BRD Rejected Qty — receives into the Rejected Warehouse and still consumes the PO quantity.",
		"Text",
	)


def _ps(doctype, fieldname, prop, value, property_type):
	"""make_property_setter deletes any prior row for the same key, so this is idempotent."""
	make_property_setter(
		doctype,
		fieldname,
		prop,
		value,
		property_type,
		validate_fields_for_doctype=False,
	)


# --- server guards ----------------------------------------------------------


def validate_grn_fields(doc, method=None):
	"""Server twin of the client-only mandatory_depends_on above (VAL-GRN-03 / VAL-QC-05).

	mandatory_depends_on never runs on the server, so a REST, script or bulk-edit write could
	otherwise submit a GRN line with a rejected quantity and no reason.

	Runs on EVERY Purchase Receipt on the site, including plain non-inward receipts and
	returns, so it stays silent unless the receipt is one of ours: doc.get() reads the
	instance dict and returns None for a field that has not been created yet, which makes the
	first line both the "not a GRN" guard and the "fields not migrated" guard.
	"""
	if not doc.get("custom_purchase_inward"):
		return

	validate_grn_status(doc)

	if not frappe.get_meta(ITEM_DOCTYPE).has_field("custom_rejection_reason"):
		# Half-migrated site: demanding a reason there is nowhere to type would block every
		# GRN save. setup_purchase_receipt_fields() creates the field on the next migrate.
		return

	# rejected_qty is not allow_on_submit, so this half belongs on `validate` only. Returns
	# carry a negative rejected_qty and are left alone.
	for row in doc.get("items") or []:
		if flt(row.get("rejected_qty")) > 0 and not (row.get("custom_rejection_reason") or "").strip():
			frappe.throw(
				_("Row #{0}: Please enter the Rejection Reason.").format(row.idx),
				title=_("Rejection Reason Required"),
			)

	_validate_quarantined_lines(doc)
	log_draft_grn_edits(doc)


def _validate_quarantined_lines(doc):
	"""A line QC quarantined is received into the Quarantine warehouse and nowhere else.

	Moving it to its real warehouse on the draft would put held stock into use without a
	release; the Quarantine document's Release is the only way out (it re-points the draft
	line itself, with grn_system_sync set).
	"""
	if doc.flags.get("grn_system_sync") or cint(doc.get("is_return")):
		return
	held = [r for r in doc.get("items") or [] if r.get("custom_quarantine_status") == "Quarantined"]
	if not held:
		return
	from alpinos.purchase.quarantine import warehouse_name

	store = warehouse_name(doc.get("company"))
	for row in held:
		if store and row.warehouse != store:
			frappe.throw(
				_(
					"Row #{0}: {1} is quarantined, so it is received into {2}. Release it from "
					"Quarantine Document {3} to move it to {4}."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					frappe.bold(store),
					frappe.bold(doc.get("custom_purchase_quarantine") or ""),
					frappe.bold(row.get("custom_release_warehouse") or _("its warehouse")),
				),
				title=_("Quarantined Item"),
			)


#: What a person may change on a Draft GRN, and therefore what the change log records.
#: posting_date is logged only when "Edit Posting Date and Time" is on; otherwise ERPNext
#: resets it to now on every save and each save would log a change nobody made.
LOGGED_HEADER_FIELDS = (
	"posting_date",
	"posting_time",
	"supplier_delivery_note",
	"lr_no",
	"lr_date",
	"set_warehouse",
	"rejected_warehouse",
	"custom_receiving_remarks",
)
LOGGED_ITEM_FIELDS = (
	"qty",
	"rejected_qty",
	"warehouse",
	"rejected_warehouse",
	"batch_no",
	"rate",
	"custom_rejection_reason",
	"custom_usp",
	"custom_mrp",
)
_NUMERIC_LOGGED = {"qty", "rejected_qty", "rate", "custom_mrp"}


def _log_text(fieldname, value):
	if fieldname in _NUMERIC_LOGGED:
		return "{0:g}".format(flt(value))
	if value in (None, ""):
		return ""
	return str(value)


def log_draft_grn_edits(doc):
	"""VAL-GRN-06 / BR-GRN-05 — record every edit a person makes to a Draft GRN.

	The Purchase GRN Change Log table existed and the GRN screen displayed it, but nothing
	ever wrote to it. That had a second cost: sync_from_inward protects exactly the fields
	this log names, so with an empty log a hand edit was silently overwritten the next time
	the Store Team corrected the inward.

	Runs on validate, so edits from the GRN screen and from the desk form are logged alike.
	A brand-new receipt (the system minting it) and the system's own re-sync
	(flags.grn_system_sync) are not edits by a person and are not logged.
	"""
	if cint(doc.docstatus) != 0 or doc.is_new() or doc.flags.get("grn_system_sync"):
		return
	before = doc.get_doc_before_save()
	if not before:
		return

	meta = frappe.get_meta(DOCTYPE)
	item_meta = frappe.get_meta(ITEM_DOCTYPE)
	entries = []

	for fieldname in LOGGED_HEADER_FIELDS:
		if fieldname in ("posting_date", "posting_time") and not cint(doc.get("set_posting_time")):
			continue
		if not meta.has_field(fieldname):
			continue
		old, new = _log_text(fieldname, before.get(fieldname)), _log_text(fieldname, doc.get(fieldname))
		if old != new:
			entries.append((meta.get_label(fieldname), old, new))

	previous_rows = {row.name: row for row in (before.get("items") or [])}
	kept = set()
	for row in doc.get("items") or []:
		prev = previous_rows.get(row.name)
		if not prev:
			entries.append((_("Row {0}: Item").format(row.idx), "", row.item_code or ""))
			continue
		kept.add(row.name)
		for fieldname in LOGGED_ITEM_FIELDS:
			if not item_meta.has_field(fieldname):
				continue
			old, new = _log_text(fieldname, prev.get(fieldname)), _log_text(fieldname, row.get(fieldname))
			if old != new:
				entries.append(
					(_("Row {0}: {1}").format(row.idx, item_meta.get_label(fieldname)), old, new)
				)
	for name, prev in previous_rows.items():
		if name not in kept:
			entries.append((_("Row {0}: Item").format(prev.idx), prev.item_code or "", _("(removed)")))

	now = frappe.utils.now_datetime()
	for label, old, new in entries:
		doc.append(
			"custom_grn_change_log",
			{
				"field_label": label,
				"old_value": old[:140],
				"new_value": new[:140],
				"reason": doc.flags.get("grn_edit_reason"),
				"changed_by": frappe.session.user,
				"changed_on": now,
			},
		)


def validate_grn_completeness(doc, method=None):
	"""VAL-GRN-03 / VAL-QC-20 - block a final submit that is missing information, and SAY WHAT.

	Both rules end in "identify the missing information", which a field-by-field throw does
	not do: the Admin fixes one blank, submits again, and is told about the next one. This
	collects everything first and names it in a single message, so one pass is enough.

	Silent for anything that is not one of this module's GRNs.
	"""
	if not doc.get("custom_purchase_inward"):
		return

	missing = []

	# BRD 5.2.1 header. Only fields that can REALLY be blank and that a person can fix are
	# demanded. The display mirrors (Invoice Number, Supplier Order No., Inward Type) are
	# fetch_from the linked inward and are not resolved at submit time, so requiring one
	# would block every GRN over a value that is merely not mirrored yet.
	for fieldname, label in (
		("custom_purchase_inward", _("Purchase Inward ID")),
		("supplier", _("Vendor Name")),
		("posting_date", _("GRN Date")),
	):
		if not doc.get(fieldname):
			missing.append(_("Header: {0}").format(label))

	# The QC link is what carries the approved/rejected split, so its absence IS a blocker -
	# but it is read off the inward, which is the source of truth for it.
	if doc.get("custom_purchase_inward") and not doc.get("custom_purchase_qc"):
		if not frappe.db.get_value("Purchase Inward", doc.custom_purchase_inward, "purchase_qc"):
			missing.append(_("Header: QC ID (no Purchase QC exists for this inward)"))

	if not (doc.get("items") or []):
		missing.append(_("No item rows"))

	# BRD 5.2.2 item rows. Batch / manufacturing / expiry are conditional on the item
	# actually being batch-tracked or shelf-life bearing, so they are only demanded there.
	for row in doc.get("items") or []:
		if not row.get("warehouse"):
			missing.append(_("Row #{0}: Target Location").format(row.idx))
		if flt(row.get("rejected_qty")) > 0 and not (row.get("custom_rejection_reason") or "").strip():
			missing.append(_("Row #{0}: Rejection Reason").format(row.idx))
		if not row.get("item_code"):
			missing.append(_("Row #{0}: Item Code").format(row.idx))
			continue
		# Batch is demanded only where the item is actually batch-tracked. `batch_no` is the
		# only batch column Purchase Receipt Item has -- there is no custom expiry/internal
		# batch field on the receipt, so nothing else can be asserted here without inventing
		# a requirement the document cannot satisfy.
		if cint(frappe.get_cached_value("Item", row.item_code, "has_batch_no")) and not row.get("batch_no"):
			missing.append(_("Row #{0} ({1}): Batch Number").format(row.idx, row.item_code))

	if not missing:
		return

	frappe.throw(
		_("This GRN cannot be submitted yet. The following is missing:")
		+ "<br><br>&bull; "
		+ "<br>&bull; ".join(missing),
		title=_("VAL-GRN-03 / VAL-QC-20"),
	)


def validate_grn_status(doc, method=None):
	"""Whitelist custom_grn_status. Registered on `validate` (via validate_grn_fields) AND on
	`before_update_after_submit`.

	custom_grn_status is allow_on_submit and is written Draft -> Completed after the receipt
	is submitted (BR-GRN-03 / BR-GRN-06). Document.run_before_save_methods runs `validate`
	only for the save and submit actions, so a guard living on `validate` alone would never
	see the write it was built for.
	"""
	if not doc.get("custom_purchase_inward"):
		return

	status = doc.get("custom_grn_status")
	if status and status not in C.GRN_STATUSES:
		frappe.throw(
			_("{0} is not a valid GRN Status.").format(frappe.bold(status)),
			title=_("Invalid GRN Status"),
		)
