# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""Purchase QC — the quality inspection of one Purchase Inward.

BRD "Purchase Inward Part -1" sections 4.1 to 4.10 (tasks 304-311).

Shape of the document
---------------------
One Purchase QC belongs to exactly one Purchase Inward. The header (4.1.1) is a
read-only mirror of that inward and is re-fetched on every save, so a QC can never
drift from the receipt it is inspecting. Four inspection sections (4.1.2 vehicle,
4.1.3 material, 4.1.4 packaging, 4.1.5 sample testing) plus the control sample
(4.1.6) may be filled in any order — BR-QC-05 forbids enforcing a sequence — and
each carries its own "…_done" flag. The `items` table (4.6.1) carries the actual
decision: approved and rejected quantity per line.

Quantity model — the one thing to get right
-------------------------------------------
Sample quantity is carved OUT OF the approved quantity, it is not a third bucket.
The reconciliation the BRD demands (4.6.2.1, VAL-QC-08) is

        approved + rejected == received          (per line and in total)

with `sample + control_sample <= approved` layered on top. Treating samples as a
separate bucket would make every sampled line fail reconciliation.

Stock movement (4.1.5 / 4.1.6)
------------------------------
Drawing a sample is a real stock movement: a submitted Material Transfer Stock
Entry out of the line's target location into the QC Sample warehouse (samples) or
the control-sample storage location. Its name is stored on the row so a cancel can
reverse exactly what it posted, and a row that already carries a submitted entry is
never re-posted.

The GRN posts the receipt stock, and the BRD parks that GRN in Draft until an Admin
final-submits it (BR-QC-17 / BR-QC-20) — so at QC-submit time the source warehouse
usually holds nothing yet. Rather than block the whole inspection on that, a
transfer that cannot post is DEFERRED: the row is left without a stock entry and
the reason is reported. `post_pending_stock_entries()` mints the missing entries
later, and is the function the GRN submit hook should call.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname, set_new_name
from frappe.utils import add_to_date, cint, flt, get_link_to_form, getdate, now_datetime

from alpinos.purchase import constants as C
from alpinos.purchase import workflow
from alpinos.purchase.settings import get_settings, sla_hours

# Quantities are compared with a tolerance rather than ==; a Float round-trip through
# the client leaves 0.1 + 0.2 != 0.3 and would fail reconciliation on honest data.
_TOL = 1e-6

# BRD 4.7 / VAL-QC-02. The "…_done" flag is the QC user's assertion that a section is
# finished; sample testing is only applicable where a sample id has to be minted.
MANDATORY_INSPECTIONS = (
	("vehicle_inspection_done", "Vehicle Inspection", None),
	("material_inspection_done", "Material Inspection", None),
	("packaging_inspection_done", "Packaging / Box Inspection", None),
	("sample_testing_done", "Sample Testing", C.BATCH_FROM_INVOICE_TYPES),
)

# QC statuses from which the decision may still be recorded.
_OPEN_QC_STATUSES = (
	C.QC_PENDING,
	C.QC_IN_PROGRESS,
	C.QC_SLA_BREACHED,
	C.QC_READY_FOR_DECISION,
)


def _eq(a, b):
	return abs(flt(a) - flt(b)) <= _TOL


def _gt(a, b):
	return flt(a) - flt(b) > _TOL


# --------------------------------------------------------------------------- 310


def qc_result_for(received, approved, rejected, ordered=0.0):
	"""BRD 4.6.2 — the system-generated QC result.

	The BRD's table overlaps: every "=> 0" row matches almost anything, and the
	excess row ("Received Qty => Ordered Qty") is a condition layered on top of the
	other three rather than an alternative to them. So the rules are evaluated
	MOST-SPECIFIC-FIRST:

	  1. received > ordered AND approved > 0   -> Excess Qty Approved
	     Excess outranks the plain results because it is the narrower statement, but
	     only while something was actually approved. A shipment that arrived over
	     quantity and was then rejected outright is Rejected, not "Excess Qty
	     Approved" — the latter is in C.QC_RESULTS_ALLOWING_GRN and would mint a GRN
	     with no approved quantity, which VAL-GRN-02 forbids.
	  2. approved == 0 AND rejected >= received -> Rejected
	  3. approved > 0 AND rejected > 0          -> Partially Approved
	  4. rejected == 0 AND approved == received -> Approved
	  5. anything else (nothing decided yet)    -> Pending

	2/3/4 are mutually exclusive once VAL-QC-08 reconciliation holds; they are still
	ordered narrowest-first so a half-filled draft never reads as "Approved".
	"""
	received = flt(received)
	approved = flt(approved)
	rejected = flt(rejected)
	ordered = flt(ordered)

	if received <= _TOL or (approved <= _TOL and rejected <= _TOL):
		return C.QC_RESULT_PENDING

	if ordered > _TOL and _gt(received, ordered) and approved > _TOL:
		return C.QC_RESULT_EXCESS_APPROVED
	if approved <= _TOL and (flt(rejected) >= flt(received) - _TOL):
		return C.QC_RESULT_REJECTED
	if approved > _TOL and rejected > _TOL:
		return C.QC_RESULT_PARTIAL
	if rejected <= _TOL and _eq(approved, received):
		return C.QC_RESULT_APPROVED
	return C.QC_RESULT_PENDING


# --------------------------------------------------------- batch / id formats


_TOKEN_MAP = (
	(r"\{y{4}\}", ".YYYY."),
	(r"\{y{2}\}", ".YY."),
	(r"\{m{2}\}", ".MM."),
	(r"\{d{2}\}", ".DD."),
)


def _naming_series(fmt, fallback):
	"""Normalise an id format into something make_autoname understands.

	Purchase Inward Settings ships "RMID-{yy}{mm}-{####}" while the module defaults
	say "RMID-.YYYY.-.#####"; both spellings are live, so both are accepted here
	rather than one of them silently minting the literal text as an id.
	"""
	fmt = (fmt or "").strip() or fallback
	for pattern, replacement in _TOKEN_MAP:
		fmt = re.sub(pattern, replacement, fmt, flags=re.IGNORECASE)
	fmt = re.sub(r"\{(#+)\}", lambda m: "." + m.group(1) + ".", fmt)
	fmt = re.sub(r"\.{2,}", ".", fmt)
	if "#" not in fmt:
		fmt = fmt + ".#####"
	return fmt


def _clean(value):
	"""Batch codes go on stickers and into the stock ledger — keep them tame."""
	value = re.sub(r"[^A-Za-z0-9_\-/]+", "-", (value or "").strip())
	return re.sub(r"-{2,}", "-", value).strip("-")


def _date_code(value):
	return getdate(value).strftime("%Y%m%d") if value else ""


class PurchaseQC(Document):
	# ------------------------------------------------------------------ hooks

	def _assert_section_access(self):
		"""Server twin of the QC section gating (task 288).

		roles.SECTIONS declares edit_roles / open_statuses / docstatus for the QC
		inspection and decision sections, and the generated Client Script honours them --
		but a Client Script is not a guard: a REST call, a bulk edit or a script would
		otherwise write an inspection or a decision that the UI would have refused. The
		Purchase Inward half has had this twin since it was built; this is the QC half.
		"""
		from alpinos.purchase.roles import assert_section_edits_allowed

		assert_section_edits_allowed(self)

	def validate(self):
		self._assert_section_access()
		self._validate_inward_link()
		self._sync_header()
		self._sync_items_from_inward()
		self._ensure_child_names()
		self._bind_child_rows()
		self._validate_vehicle_inspection()
		self._validate_material_inspection()
		self._validate_packaging_inspection()
		self._stamp_inspection_evidence()
		self._roll_up_sample_qty()
		self._apply_control_sample_retention()
		self._validate_decision_quantities()
		self._roll_up_totals()
		self._derive_qc_result()
		self._apply_sla()
		self._sync_qc_status()

	def after_insert(self):
		"""Link the inward back so workflow._guard_qc_exists can see this QC."""
		if self.purchase_inward and not frappe.db.get_value(
			"Purchase Inward", self.purchase_inward, "purchase_qc"
		):
			frappe.db.set_value(
				"Purchase Inward",
				self.purchase_inward,
				"purchase_qc",
				self.name,
				update_modified=False,
			)

	def before_submit(self):
		self._validate_mandatory_inspections()
		self._generate_internal_batches()
		self._generate_sample_ids()
		self._finalise_control_samples()
		self.qc_status = C.QC_COMPLETED
		# M09 — now that the handoff no longer pre-fills it, a QC submitted without a
		# Start QC click would print a blank "Inspected By" on the QC Inspection Report.
		if not self.inspector:
			self.inspector = frappe.session.user
		if not self.inspection_date:
			self.inspection_date = now_datetime()

	def on_submit(self):
		self._post_stock_entries()
		self._push_to_inward()
		self._generate_grn()

	def on_cancel(self):
		self._block_cancel_with_downstream()
		self._reverse_stock_entries()
		self.db_set("qc_status", C.QC_CANCELLED, update_modified=False)
		self._walk_inward_back()

	# ------------------------------------------------------------- 304 header

	def _validate_inward_link(self):
		"""VAL-QC-01 — a QC without its Purchase Inward has nothing to inspect."""
		if not self.purchase_inward:
			frappe.throw(_("Purchase Inward record not found."), title=_("VAL-QC-01"))
		if not frappe.db.exists("Purchase Inward", self.purchase_inward):
			frappe.throw(_("Purchase Inward record not found."), title=_("VAL-QC-01"))

		# The header link is the document's identity. read_only_depends_on is
		# client-only, so re-pointing it at another inward is blocked here.
		if not self.is_new():
			before = self.get_doc_before_save()
			if before and before.purchase_inward and before.purchase_inward != self.purchase_inward:
				frappe.throw(
					_("Purchase Inward cannot be changed once the QC has been created.")
				)

		if frappe.db.get_value("Purchase Inward", self.purchase_inward, "docstatus") != 1:
			frappe.throw(
				_("Purchase Inward {0} has not been submitted.").format(self.purchase_inward),
				title=_("VAL-QC-01"),
			)

	def _inward(self):
		if not getattr(self, "_inward_doc", None):
			self._inward_doc = frappe.get_doc("Purchase Inward", self.purchase_inward)
		return self._inward_doc

	def _sync_header(self):
		"""BRD 4.1.1 — the header is a mirror, never operator input."""
		inward = self._inward()
		self.supplier = inward.supplier
		self.supplier_name = inward.supplier_name
		self.supplier_order_no = inward.supplier_order_no
		self.invoice_number = inward.invoice_number
		self.inward_type = inward.inward_type
		self.company = inward.company
		self.received_qty = flt(inward.total_received_qty)
		# M09/M10 — BRD 4.1.1 + 3.1: Inspector is the QC user who runs the inspection and
		# Inspection Date is when it was run; both stay blank while the row is Pending QC.
		# validate() also runs on the Store handoff insert (notifications._ensure_purchase_qc),
		# so stamping here — or letting the __user / Now DocType defaults stand — named the
		# STORE user on every brand-new Pending QC and froze inspection_date at the handoff
		# second, leaving start_qc and before_submit nothing to fill in and making the BRD 3.3
		# Inspector / Inspection Date filters and the QC Inspection Report show the handoff.
		if self.is_new() and self.qc_status in (None, "", C.QC_PENDING):
			self.inspector = None
			self.inspection_date = None

	def _inward_items(self):
		"""{Purchase Inward Item row name: row} for the linked inward."""
		if getattr(self, "_inward_item_map", None) is None:
			self._inward_item_map = {row.name: row for row in self._inward().get("items") or []}
		return self._inward_item_map

	def _sync_items_from_inward(self):
		"""Seed and refresh the decision table from the inward's received lines.

		Only while the QC is a draft: after submit the rows are the QC record and
		the inward can no longer move underneath them.
		"""
		if self.docstatus != 0:
			return

		inward_items = self._inward_items()
		if not self.get("items"):
			for row in self._inward().get("items") or []:
				if flt(row.received_qty) <= 0:
					continue
				self.append(
					"items",
					{
						"item_code": row.item_code,
						"item_name": row.item_name,
						"uom": row.uom,
						"received_qty": flt(row.received_qty),
						"target_warehouse": row.target_warehouse,
						"manufacturing_date": row.manufacturing_date,
						"expiry_date": row.expiry_date,
						"quarantine": cint(row.quarantine),
						"po_detail": row.po_detail,
						"purchase_inward_item": row.name,
					},
				)
			return

		by_item = {}
		for row in self._inward().get("items") or []:
			by_item.setdefault(row.item_code, row)

		for line in self.get("items"):
			src = inward_items.get(line.purchase_inward_item) or by_item.get(line.item_code)
			if not src:
				continue
			line.purchase_inward_item = src.name
			line.po_detail = src.po_detail
			line.item_name = src.item_name
			line.uom = src.uom
			line.received_qty = flt(src.received_qty)
			line.target_warehouse = line.target_warehouse or src.target_warehouse
			line.manufacturing_date = line.manufacturing_date or src.manufacturing_date
			line.expiry_date = line.expiry_date or src.expiry_date

	def _ensure_child_names(self):
		"""Name rows this controller appended during validate.

		Frappe names new children in _save BEFORE validate runs, so anything appended
		inside validate is still nameless until db_insert. Every cross-table reference
		below keys on the QC item row name, so the names are minted here instead.
		"""
		for row in self.get_all_children():
			if not row.name:
				set_new_name(row)

	def _bind_child_rows(self):
		"""Point every inspection / sample row at a QC item row.

		VAL-QC-09 and the damage checks are all "against that line", so a row whose
		`qc_item` is blank is bound here rather than validated against the whole
		document. One item code legitimately occupies SEVERAL decision lines (two PO
		lines, two target warehouses, two manufacturing dates), so "the first line
		carrying this item" is a guess, and a wrong guess drew the sample out of the
		wrong warehouse and capped VAL-QC-09 against another line's approved quantity.
		The QC user therefore names the line with `qc_item_idx` (the row number in the
		Item Decision table); it is stamped back so an existing row shows which line it
		is bound to and can be corrected.
		"""
		by_idx, first_by_item = {}, {}
		for line in self.get("items"):
			by_idx[cint(line.idx)] = line
			first_by_item.setdefault(line.item_code, line)
		by_name = self._items_by_name()

		for field in ("material_inspection", "packaging_inspection", "sample_testing", "control_sample"):
			for row in self.get(field) or []:
				line = None
				if cint(row.get("qc_item_idx")):
					line = by_idx.get(cint(row.qc_item_idx))
					if not line or line.item_code != row.item_code:
						frappe.throw(
							_(
								"Row {0}: Item Decision row {1} does not carry {2}."
							).format(row.idx, cint(row.qc_item_idx), row.item_code),
							title=_("VAL-QC-09"),
						)
				# A row saved before qc_item_idx existed carries only qc_item; keep the
				# line it was bound to so a migrated document never silently re-points a
				# sample that has already moved stock.
				if line is None and row.get("qc_item"):
					line = by_name.get(row.qc_item)
				if line is None:
					line = first_by_item.get(row.item_code)

				row.qc_item = line.name if line else None
				if line is not None and row.meta.has_field("qc_item_idx"):
					row.qc_item_idx = cint(line.idx)

				# A sample or control sample draws real quantity out of a decision line.
				# If no line matches, VAL-QC-09 would have nothing to cap it against and
				# the quantity would leave the document unaccounted for, so refuse the row
				# rather than silently ignoring it.
				if not row.qc_item and field in ("sample_testing", "control_sample"):
					frappe.throw(
						_(
							"Row {0}: {1} was not received on Purchase Inward {2}, so no "
							"sample can be drawn against it."
						).format(row.idx, row.item_code, self.purchase_inward),
						title=_("VAL-QC-09"),
					)

	def _items_by_name(self):
		return {line.name: line for line in self.get("items")}

	# --------------------------------------------------- 305 vehicle section

	def _validate_vehicle_inspection(self):
		"""VAL-QC-03 — a damaged vehicle must say why. mandatory_depends_on is
		client-only, so the rule is re-checked here."""
		for row in self.get("vehicle_inspection") or []:
			damaged = cint(row.vehicle_damage) or row.vehicle_condition == C.CONDITION_DAMAGED
			if damaged:
				row.vehicle_damage = 1
				row.vehicle_condition = C.CONDITION_DAMAGED
				if not (row.damage_reason or "").strip():
					frappe.throw(
						_("Row {0}: please enter the Vehicle Damage Reason.").format(row.idx),
						title=_("VAL-QC-03"),
					)

	# -------------------------------------------------- 306 material section

	def _validate_material_inspection(self):
		"""Damaged material needs both a quantity and a reason (BRD 4.1.3)."""
		# The damage cap is per ITEM, not per decision line: the same item received on
		# two inward lines (100 + 100) can honestly be 150 damaged, and capping it
		# against the single line the row happened to bind to rejected that with
		# "Damaged Quantity 150 cannot exceed the Received Quantity 100".
		received_by_item = {}
		for line in self.get("items"):
			received_by_item[line.item_code] = flt(received_by_item.get(line.item_code)) + flt(
				line.received_qty
			)

		for row in self.get("material_inspection") or []:
			damaged = cint(row.material_damage) or row.material_condition == C.CONDITION_DAMAGED
			if damaged:
				row.material_damage = 1
				row.material_condition = C.CONDITION_DAMAGED
				if flt(row.damaged_qty) <= 0:
					frappe.throw(
						_("Row {0} ({1}): please enter the Damaged Quantity.").format(
							row.idx, row.item_code
						)
					)
			if flt(row.damaged_qty) > 0 and not (row.damage_reason or "").strip():
				frappe.throw(
					_("Row {0} ({1}): please enter the Damage Reason.").format(
						row.idx, row.item_code
					)
				)

			received = received_by_item.get(row.item_code)
			if received is not None and _gt(row.damaged_qty, received):
				frappe.throw(
					_(
						"Row {0} ({1}): Damaged Quantity {2} cannot exceed the Received "
						"Quantity {3}."
					).format(row.idx, row.item_code, flt(row.damaged_qty), flt(received))
				)

	# ------------------------------------------------- 307 packaging section

	def _validate_packaging_inspection(self):
		"""Damaged packaging needs both a package count and a reason (BRD 4.1.4)."""
		for row in self.get("packaging_inspection") or []:
			damaged = cint(row.packaging_damage) or row.packaging_condition == C.CONDITION_DAMAGED
			if damaged:
				row.packaging_damage = 1
				row.packaging_condition = C.CONDITION_DAMAGED
				if flt(row.damaged_qty) <= 0:
					frappe.throw(
						_("Row {0} ({1}): please enter the damaged package quantity.").format(
							row.idx, row.item_code
						)
					)
			if flt(row.damaged_qty) > 0 and not (row.damage_reason or "").strip():
				frappe.throw(
					_("Row {0} ({1}): please enter the Damage Reason.").format(
						row.idx, row.item_code
					)
				)

	# ------------------------------------- 308 / 309 sample + control sample

	def _stamp_inspection_evidence(self):
		"""Record who attached each piece of evidence, and when (BRD 4.1.2-4.1.4).

		Frappe never runs controller lifecycle methods on child rows -- children are written
		with BaseDocument.db_insert()/db_update() -- so a before_insert on the child would
		never fire and both fields would stay NULL, exactly as they did on the Purchase
		Inward dispute attachments.
		"""
		for row in self.get("inspection_evidence") or []:
			if not row.get("uploaded_by"):
				row.uploaded_by = frappe.session.user
			if not row.get("uploaded_on"):
				row.uploaded_on = now_datetime()

	def _roll_up_sample_qty(self):
		"""Sample and control-sample quantities are owned by their own tables; the
		QC item columns are a roll-up, so they are recomputed, never trusted."""
		lines = self._items_by_name()
		for line in self.get("items"):
			line.sample_qty = 0.0
			line.control_sample_qty = 0.0

		for row in self.get("sample_testing") or []:
			if flt(row.sample_qty) < 0:
				frappe.throw(
					_("Row {0}: Sample Quantity cannot be negative.").format(row.idx)
				)
			line = lines.get(row.qc_item)
			if line:
				line.sample_qty = flt(line.sample_qty) + flt(row.sample_qty)
				row.uom = row.uom or line.uom

		for row in self.get("control_sample") or []:
			if not cint(row.control_sample_taken):
				continue
			if flt(row.control_sample_qty) <= 0:
				frappe.throw(
					_("Row {0} ({1}): please enter the Control Sample Quantity.").format(
						row.idx, row.item_code
					)
				)
			line = lines.get(row.qc_item)
			if line:
				line.control_sample_qty = flt(line.control_sample_qty) + flt(
					row.control_sample_qty
				)

	def _apply_control_sample_retention(self):
		"""309 — every retained control sample gets a storage location and an end date.

		The BRD names Storage Location and leaves retention open, so the retention date
		is derived rather than demanded: the line's own expiry date first, then the
		item's shelf life from the manufacturing date. A control sample whose item has
		neither simply keeps a blank retention date; QC can type one.
		"""
		control_wh = get_settings(self.company).get("control_sample_warehouse") or get_settings(
			self.company
		).get("qc_sample_warehouse")
		lines = self._items_by_name()

		for row in self.get("control_sample") or []:
			if not cint(row.control_sample_taken):
				continue
			line = lines.get(row.qc_item)
			if not row.storage_location:
				row.storage_location = control_wh
			if row.retention_until:
				continue

			expiry = line.expiry_date if line else None
			if not expiry:
				shelf_life = cint(
					frappe.get_cached_value("Item", row.item_code, "shelf_life_in_days")
				)
				start = (line.manufacturing_date if line else None) or getdate()
				expiry = add_to_date(start, days=shelf_life) if shelf_life else None
			row.retention_until = getdate(expiry) if expiry else None

	def _finalise_control_samples(self):
		"""BRD 4.1.6 — Batch is mandatory on a retained control sample.

		mandatory_depends_on covers the form only. The internal batch is minted in the
		same before_submit pass, so a blank batch is filled from the decision line before
		the rule is enforced and QC is not asked to retype a system-generated code.
		"""
		lines = self._items_by_name()
		for row in self.get("control_sample") or []:
			if not cint(row.control_sample_taken):
				continue
			line = lines.get(row.qc_item)
			if not (row.batch_no or "").strip() and line:
				row.batch_no = line.internal_batch_no
			if not (row.batch_no or "").strip():
				frappe.throw(
					_("Row {0} ({1}): please enter the Batch for the control sample.").format(
						row.idx, row.item_code
					)
				)

	# ------------------------------------------------------ 310 / 311 decision

	def _ordered_qty(self):
		"""{qc item row name: ceiling qty} — what BRD 4.6.2's excess result tests against.

		The ceiling is the quantity that was still PENDING for this inward, not the whole
		PO line. order_qty is the full ordered quantity, so on a second or later delivery
		against the same PO line every excess escaped detection: a PO line of 100 already
		receiving 60, then an inward of 50, has the inward correctly stamping excess_qty 10
		(pending was 40) while QC compared 50 against 100 and reported plain "Approved".
		pending_qty is what the inward itself measured over-receipt against
		(purchase_inward._compute_previously_received), so the two now agree.
		"""
		inward_items = self._inward_items()
		per_line = {}
		for line in self.get("items"):
			src = inward_items.get(line.purchase_inward_item)
			per_line[line.name] = self._ceiling_for(src)
		return per_line

	@staticmethod
	def _ceiling_for(src):
		"""Pending quantity for an inward row, falling back to the ordered quantity."""
		if not src:
			return 0.0
		pending = flt(src.get("pending_qty"))
		return pending if pending else flt(src.get("order_qty"))

	def _validate_decision_quantities(self):
		"""BRD 4.6.2.1 / 4.9 — VAL-QC-04 to VAL-QC-09."""
		ordered = self._ordered_qty()

		for line in self.get("items"):
			received = flt(line.received_qty)
			approved = flt(line.approved_qty)
			rejected = flt(line.rejected_qty)

			if approved < 0 or rejected < 0:
				frappe.throw(
					_("Row {0} ({1}): quantities cannot be negative.").format(
						line.idx, line.item_code
					)
				)

			# VAL-QC-06 / VAL-QC-07 are checked before reconciliation so the operator
			# gets the precise message rather than a generic mismatch.
			if _gt(approved, received):
				frappe.throw(
					_("Row {0} ({1}): Approved Quantity cannot exceed Received Quantity.").format(
						line.idx, line.item_code
					),
					title=_("VAL-QC-06"),
				)
			if _gt(rejected, received):
				frappe.throw(
					_("Row {0} ({1}): Rejected Quantity cannot exceed Received Quantity.").format(
						line.idx, line.item_code
					),
					title=_("VAL-QC-07"),
				)

			# VAL-QC-04 / VAL-QC-05 / BR-QC-08. A line-level reason is preferred; the
			# document-level Rejection Reason is accepted so a single-reason rejection
			# does not have to be typed on every line.
			if rejected > _TOL and not (
				(line.rejection_reason or "").strip() or (self.rejection_reason or "").strip()
			):
				frappe.throw(
					_("Row {0} ({1}): please enter the Rejection Reason.").format(
						line.idx, line.item_code
					),
					title=_("VAL-QC-04"),
				)

			# VAL-QC-08. Only once a decision has been started: a draft QC with the
			# decision columns still blank must remain savable (BR-QC-05, parallel work).
			decided = approved > _TOL or rejected > _TOL
			if decided and not _eq(approved + rejected, received):
				frappe.throw(
					_(
						"Row {0} ({1}): Approved Quantity + Rejected Quantity ({2}) must equal "
						"the Received Quantity ({3})."
					).format(line.idx, line.item_code, approved + rejected, received),
					title=_("VAL-QC-08"),
				)

			# VAL-QC-09. The sample is carved out of what was approved, so it is
			# capped by the approved quantity once a decision exists and by the
			# received quantity while the decision is still open.
			drawn = flt(line.sample_qty) + flt(line.control_sample_qty)
			ceiling = approved if decided else received
			if _gt(drawn, ceiling):
				frappe.throw(
					_(
						"Row {0} ({1}): Sample Quantity cannot exceed the available quantity. "
						"Drawn {2}, available {3}."
					).format(line.idx, line.item_code, drawn, ceiling),
					title=_("VAL-QC-09"),
				)

			line.qc_result = qc_result_for(received, approved, rejected, ordered.get(line.name))

		# The same reconciliation in total (BRD 4.6.2.1 note), but only at submit.
		# On a draft this summed form is a completeness gate, not a reconciliation:
		# each decided line is already reconciled by the per-line check above, so the
		# only way the totals can differ is a line the QC user has not reached yet.
		# Enforcing it on every save made a multi-line QC unsavable in progress (fill
		# line 1, leave line 2 blank -> "total 600 must equal 1100"), which contradicts
		# BRD 4.x "can save the inspection progress and continue with other inspection
		# activities". BR-QC-06 puts completeness at FINAL submission — docstatus is
		# already 1 when validate() runs under submit()/complete_qc(), so the gate
		# still fires there, and a wholly undecided QC can no longer be submitted.
		received = sum(flt(l.received_qty) for l in self.get("items"))
		approved = sum(flt(l.approved_qty) for l in self.get("items"))
		rejected = sum(flt(l.rejected_qty) for l in self.get("items"))
		if self.docstatus > 0 and not _eq(approved + rejected, received):
			frappe.throw(
				_(
					"Total Approved Quantity + Rejected Quantity ({0}) must equal the total "
					"Received Quantity ({1})."
				).format(approved + rejected, received),
				title=_("VAL-QC-08"),
			)

		# VAL-QC-10 / BR-QC-13: Supplier Batch No. is deliberately NOT validated here.
		# A blank supplier batch must never block QC completion.

	def _roll_up_totals(self):
		"""Posted totals are never trusted — they are recomputed from the rows."""
		self.total_received_qty = sum(flt(l.received_qty) for l in self.get("items"))
		self.total_approved_qty = sum(flt(l.approved_qty) for l in self.get("items"))
		self.total_rejected_qty = sum(flt(l.rejected_qty) for l in self.get("items"))
		self.total_sample_qty = sum(flt(l.sample_qty) for l in self.get("items"))
		self.total_control_sample_qty = sum(
			flt(l.control_sample_qty) for l in self.get("items")
		)

	def _total_ordered_qty(self):
		"""De-duplicated ceiling behind the whole QC (pending, not the full PO line)."""
		inward_items = self._inward_items()
		seen = {}
		for line in self.get("items"):
			src = inward_items.get(line.purchase_inward_item)
			if src:
				seen[src.name] = self._ceiling_for(src)
		return sum(seen.values())

	def _derive_qc_result(self):
		"""310 — system result, with a recorded manual override.

		The override is stored rather than merely applied: `system_qc_result` keeps
		what the rules produced and `qc_result_overridden` marks that a human
		disagreed, so a QC Report can show both.
		"""
		system = qc_result_for(
			self.total_received_qty,
			self.total_approved_qty,
			self.total_rejected_qty,
			self._total_ordered_qty(),
		)
		if self.meta.has_field("system_qc_result"):
			self.system_qc_result = system

		manual = (self.get("manual_qc_result") or "").strip()
		if manual and manual in C.QC_RESULTS and manual != system:
			self.qc_result = manual
			if self.meta.has_field("qc_result_overridden"):
				self.qc_result_overridden = 1
		else:
			self.qc_result = system
			if self.meta.has_field("qc_result_overridden"):
				self.qc_result_overridden = 0

	def _sync_qc_status(self):
		"""Derive the inspection status, and refuse a move BRD 4.7 does not allow.

		The derivation below is the only thing that SHOULD write qc_status, but the field
		is allow_on_submit, so a REST or script write could previously put an inspection
		straight from Pending QC to QC Completed with nothing inspected. Every derived
		result is now checked against workflow.QC_TRANSITIONS, which also catches a
		hand-set value arriving on the document.
		"""
		from alpinos.purchase.workflow import assert_qc_transition

		previous = self.get_doc_before_save().qc_status if self.get_doc_before_save() else None

		if self.docstatus == 2:
			target = C.QC_CANCELLED
		elif self.docstatus == 1:
			target = C.QC_COMPLETED
		else:
			target = self.qc_status
			if target in (None, "", C.QC_PENDING):
				target = C.QC_PENDING if not self._any_inspection_started() else C.QC_IN_PROGRESS
			if target in (C.QC_IN_PROGRESS, C.QC_READY_FOR_DECISION) and not self._missing_inspections():
				target = C.QC_READY_FOR_DECISION

		# On a brand-new document there is nothing to move FROM.
		if previous:
			assert_qc_transition(previous, target)
		self.qc_status = target

	def _any_inspection_started(self):
		return any(
			cint(self.get(field)) for field, _label, _types in MANDATORY_INSPECTIONS
		) or bool(
			self.get("vehicle_inspection")
			or self.get("material_inspection")
			or self.get("packaging_inspection")
			or self.get("sample_testing")
		)

	# --------------------------------------------------------------- 311 gate

	def _applicable_inspections(self):
		for field, label, types in MANDATORY_INSPECTIONS:
			if types and self.inward_type not in types:
				continue
			yield field, label

	def _missing_inspections(self):
		return [label for field, label in self._applicable_inspections() if not cint(self.get(field))]

	def _validate_mandatory_inspections(self):
		"""VAL-QC-02 / BR-QC-06 — name the incomplete sections, do not just refuse."""
		missing = self._missing_inspections()
		if missing:
			frappe.throw(
				_("Please complete all mandatory QC inspections. Pending: {0}").format(
					", ".join(missing)
				),
				title=_("VAL-QC-02"),
			)

		if self.inward_type in C.BATCH_FROM_INVOICE_TYPES and not self.get("sample_testing"):
			frappe.throw(
				_("Please record at least one Sample Testing row for an {0} inward.").format(
					self.inward_type
				),
				title=_("VAL-QC-02"),
			)

		if not self.get("items"):
			frappe.throw(_("Please record the item-wise QC decision before submitting."))

		if self.qc_result == C.QC_RESULT_PENDING:
			frappe.throw(
				_("Please enter the Approved and Rejected Quantity before completing QC.")
			)

	# ------------------------------------------------------- 308 batch / ids

	def _batch_context(self, line):
		"""Every alias both settings spellings use, so either format string renders."""
		inward = self._inward()
		src = self._inward_items().get(line.purchase_inward_item)
		batch_no = (getattr(src, "batch_no", None) or "") if src else ""
		mfg = line.manufacturing_date or (getattr(src, "manufacturing_date", None) if src else None)
		return {
			"invoice_number": _clean(inward.invoice_number),
			"invoice_no": _clean(inward.invoice_number),
			"inward_date": _date_code(inward.inward_datetime or inward.invoice_date),
			"invoice_date": _date_code(inward.invoice_date),
			"batch_no": _clean(batch_no),
			"batch_number": _clean(batch_no),
			"manufacturing_date": _date_code(mfg),
			"mfg_date": _date_code(mfg),
			"item_code": _clean(line.item_code),
			"supplier": _clean(inward.supplier),
		}

	def _generate_internal_batches(self):
		"""BR-QC-11 / BR-QC-12 / VAL-QC-11.

		RM and PM take Invoice Number + Inward Date; FG takes Batch Number +
		Manufacturing Date. MM has no rule, so it gets no internal batch and is not
		blocked for the lack of one.
		"""
		if self.inward_type in C.BATCH_FROM_INVOICE_TYPES:
			fmt = get_settings(self.company).get("rm_pm_batch_format")
			required = ("invoice_number", "inward_date")
		elif self.inward_type in C.BATCH_FROM_MFG_TYPES:
			fmt = get_settings(self.company).get("fg_batch_format")
			required = ("batch_no", "manufacturing_date")
		else:
			return

		for line in self.get("items"):
			if (line.internal_batch_no or "").strip():
				continue
			context = self._batch_context(line)
			missing = [key for key in required if not context.get(key)]
			if missing:
				frappe.throw(
					_(
						"Row {0} ({1}): Internal Batch Number could not be generated. Please "
						"verify the required batch information ({2})."
					).format(line.idx, line.item_code, ", ".join(missing)),
					title=_("VAL-QC-11"),
				)
			batch = _clean(_render(fmt, context))
			if not batch:
				frappe.throw(
					_(
						"Row {0} ({1}): Internal Batch Number could not be generated. Please "
						"verify the required batch information."
					).format(line.idx, line.item_code),
					title=_("VAL-QC-11"),
				)
			line.internal_batch_no = batch

		# M15: the code above is plain Data until a Batch document actually carries it.
		# grn._batch_no drops a batch id that has no Batch, so the receipt auto-minted an id
		# of its own and stock, GRN and QC report each named a different batch. Minting here,
		# BEFORE the sample rows are stamped, keeps every copy on the id really created.
		self._mint_internal_batches()

		batches = {line.name: line.internal_batch_no for line in self.get("items")}
		for row in self.get("sample_testing") or []:
			if not (row.internal_batch_no or "").strip():
				row.internal_batch_no = batches.get(row.qc_item)

	def _mint_internal_batches(self):
		"""Create the Batch each internal batch code names (BR-QC-11 / BR-QC-12).

		Without a Batch document the code traced to nothing: grn._batch_no dropped it,
		ERPNext auto-minted an id of its own at GRN submit, and the batch in the stock
		ledger appeared nowhere on this QC document.
		"""
		for line in self.get("items"):
			code = (line.internal_batch_no or "").strip()
			if not code:
				continue
			if not cint(frappe.get_cached_value("Item", line.item_code, "has_batch_no")):
				# Batch.item_has_batch_enabled() refuses a Batch on an untracked item and the
				# GRN carries none either; the code stays a plain reference on the document.
				continue
			minted = self._mint_batch(line, code)
			if minted:
				line.internal_batch_no = minted

	def _mint_batch(self, line, code):
		"""The Batch id to record for `code`, creating the Batch when it is missing.

		A Batch belongs to exactly one Item, while the BR-QC-11 code (invoice number + inward
		date) is shared by every line of the inward, so a code already held by another item is
		minted per item and the row is corrected to the id really created — the document has to
		name the batch the ledger holds. create_new_batch is not consulted: Batch.autoname only
		reads it when batch_id is blank, and this names the batch explicitly, exactly as a user
		typing it on the receipt would.
		"""
		has_expiry, shelf_life = frappe.get_cached_value(
			"Item", line.item_code, ["has_expiry_date", "shelf_life_in_days"]
		)
		mfg = line.manufacturing_date
		if cint(has_expiry) and not line.expiry_date and not (cint(shelf_life) and mfg):
			# Batch.set_expiry_date() would throw and take the whole QC submission with it;
			# leave the code as plain Data and let the GRN report that item misconfiguration.
			return None

		for batch_id in (code, _clean(code + "-" + line.item_code)):
			owner = frappe.db.get_value("Batch", batch_id, "item")
			if owner == line.item_code:
				return batch_id
			if owner:
				continue
			batch = frappe.new_doc("Batch")
			batch.batch_id = batch_id
			batch.item = line.item_code
			batch.supplier = self.supplier
			batch.manufacturing_date = mfg
			batch.expiry_date = line.expiry_date
			batch.reference_doctype = self.doctype
			batch.reference_name = self.name
			batch.flags.ignore_permissions = True
			batch.insert()
			return batch.name
		return None

	def _generate_sample_ids(self):
		"""BR-QC-14 / VAL-QC-12 — RMID for RM, PMID for PM, one per sample row."""
		prefix = C.SAMPLE_ID_PREFIX.get(self.inward_type)
		if not prefix:
			return

		settings = get_settings(self.company)
		fmt = settings.get("rmid_format" if self.inward_type == C.INWARD_RM else "pmid_format")
		series = _naming_series(fmt, prefix + "-.YYYY.-.#####")

		for row in self.get("sample_testing") or []:
			if (row.sample_id or "").strip():
				continue
			if flt(row.sample_qty) <= 0:
				continue
			row.sample_id = make_autoname(series)

	# ---------------------------------------------- 308 / 309 stock movement

	def _post_stock_entries(self):
		"""Move sample and control-sample quantity out of the receiving location.

		Returns the rows that could not be posted yet, as (doctype, row name, reason).
		"""
		settings = get_settings(self.company)
		sample_wh = settings.get("qc_sample_warehouse")
		control_wh = settings.get("control_sample_warehouse") or sample_wh
		hold_wh = settings.get("qc_hold_warehouse")
		deferred = []

		for row in self.get("sample_testing") or []:
			deferred += self._transfer_row(
				row,
				flt(row.sample_qty),
				sample_wh,
				hold_wh,
				_("Purchase QC {0}: sample {1}").format(self.name, row.sample_id or row.item_code),
			)

		for row in self.get("control_sample") or []:
			if not cint(row.control_sample_taken):
				continue
			deferred += self._transfer_row(
				row,
				flt(row.control_sample_qty),
				row.storage_location or control_wh,
				hold_wh,
				_("Purchase QC {0}: control sample {1}").format(self.name, row.item_code),
			)

		if deferred:
			frappe.msgprint(
				_(
					"The sample stock movement has been deferred and will be posted once the "
					"stock is available in the receiving location.<br><br>{0}"
				).format(
					"<br>".join(
						_("Row {0}: {1}").format(name, reason) for _dt, name, reason in deferred
					)
				),
				title=_("Sample stock pending"),
				indicator="orange",
			)
		return deferred

	def _transfer_row(self, row, qty, target, hold_warehouse, remarks):
		"""Post one Material Transfer for `row`, or report why it cannot post yet."""
		if qty <= 0:
			return []
		if row.stock_entry and frappe.db.get_value("Stock Entry", row.stock_entry, "docstatus") == 1:
			# Already moved. One row never posts twice.
			return []

		line = self._items_by_name().get(row.qc_item)
		source = (line.target_warehouse if line else None) or hold_warehouse

		src_item = self._inward_items().get(line.purchase_inward_item) if line else None
		factor = flt(getattr(src_item, "conversion_factor", 0)) or 1.0
		# Posted in the stock UOM so no UOM conversion has to exist on the item for a
		# sample to be drawn.
		stock_uom = frappe.get_cached_value("Item", row.item_code, "stock_uom")
		stock_qty = flt(qty) * factor
		batch_no = self._receipt_batch(line, row.item_code, source)

		reason = self._blocked_reason(row.item_code, stock_qty, source, target, batch_no)
		if reason:
			return [(row.doctype, row.name, reason)]

		entry = frappe.new_doc("Stock Entry")
		entry.stock_entry_type = "Material Transfer"
		entry.purpose = "Material Transfer"
		entry.company = self.company
		entry.remarks = remarks
		entry.append(
			"items",
			{
				"item_code": row.item_code,
				"uom": stock_uom,
				"stock_uom": stock_uom,
				"conversion_factor": 1.0,
				"qty": stock_qty,
				"s_warehouse": source,
				"t_warehouse": target,
				"allow_zero_valuation_rate": 1,
				# A batch-tracked item has no stock outside a batch, so the sample must name
				# the batch the GRN received into `source`. use_serial_batch_fields is what
				# makes ERPNext read batch_no instead of demanding a Serial and Batch Bundle;
				# both are inert for an untracked item, where batch_no stays None.
				"use_serial_batch_fields": 1 if batch_no else 0,
				"batch_no": batch_no,
			},
		)
		entry.flags.ignore_permissions = True
		entry.insert()
		entry.submit()

		# stock_entry is read_only and not allow_on_submit, so db_set is the only way to
		# stamp it from on_submit.
		frappe.db.set_value(row.doctype, row.name, "stock_entry", entry.name, update_modified=False)
		row.stock_entry = entry.name
		return []

	def _receipt_batch(self, line, item_code, warehouse):
		"""The Batch the submitted GRN put into `warehouse`, or None while there is none.

		Purchase QC mints only the batch *code* (internal_batch_no) — no Batch document
		ever carries it, so grn._batch_no drops it and ERPNext auto-mints its own Batch
		when the receipt is submitted. Reading that batch back off the receipt is the only
		way the sample transfer can name what it draws from; without it every batch-tracked
		sample was deferred forever and the receiving warehouse kept holding stock that is
		physically in the QC lab (BRD 4.1.5 / 4.1.6, BR-QC-14).
		"""
		if not cint(frappe.get_cached_value("Item", item_code, "has_batch_no")):
			return None
		internal = ((line.internal_batch_no or "").strip() if line else "")
		if internal and frappe.db.exists("Batch", internal):
			return internal
		receipt = self.purchase_receipt or frappe.db.get_value(
			"Purchase Inward", self.purchase_inward, "purchase_receipt"
		)
		if not receipt or frappe.db.get_value("Purchase Receipt", receipt, "docstatus") != 1:
			return None
		filters = {"parent": receipt, "item_code": item_code, "warehouse": warehouse}
		if line and line.purchase_inward_item:
			filters["custom_purchase_inward_item"] = line.purchase_inward_item
		for pr_row in frappe.get_all(
			"Purchase Receipt Item",
			filters=filters,
			fields=["batch_no", "serial_and_batch_bundle"],
			order_by="idx asc",
		):
			# batch_no is only filled when the GRN linked a Batch that already existed; an
			# auto-minted one is reachable only through the receipt's bundle.
			if pr_row.batch_no:
				return pr_row.batch_no
			if pr_row.serial_and_batch_bundle:
				batch = frappe.db.get_value(
					"Serial and Batch Entry",
					{"parent": pr_row.serial_and_batch_bundle},
					"batch_no",
					order_by="idx asc",
				)
				if batch:
					return batch
		return None

	def _blocked_reason(self, item_code, stock_qty, source, target, batch_no=None):
		"""Why this transfer cannot post yet, or None when it can."""
		if not source:
			return _("no receiving location on the QC line and no QC Hold warehouse configured")
		if not target:
			return _("the destination warehouse has not been configured in Purchase Inward Settings")
		if source == target:
			return _("the source and destination warehouse are the same")
		if cint(frappe.get_cached_value("Item", item_code, "has_batch_no")) and not batch_no:
			# A deferral, never a permanent block: the Batch exists from the moment the GRN
			# submits, and post_pending_stock_entries posts this row then. Blocking on
			# has_batch_no alone left the sample stock in the receiving warehouse forever.
			return _("{0} is batch tracked and the GRN has not created its batch yet").format(
				item_code
			)
		if batch_no:
			# Bin is not batch aware. The internal Batch exists from QC submit but is only
			# filled when the GRN posts, so the warehouse can hold plenty of the item and
			# nothing at all of THIS batch — posting that transfer fails outright instead of
			# deferring until the GRN has run.
			from erpnext.stock.doctype.batch.batch import get_batch_qty

			available = flt(get_batch_qty(batch_no=batch_no, warehouse=source))
			if _gt(stock_qty, available):
				return _("only {0} of batch {1} is available in {2}").format(
					available, batch_no, source
				)
			return None
		available = flt(
			frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": source}, "actual_qty")
		)
		if _gt(stock_qty, available):
			return _("only {0} is available in {1}").format(available, source)
		return None

	def _reverse_stock_entries(self):
		"""BRD 5.3 — a cancel must undo exactly what the submit posted."""
		for field in ("sample_testing", "control_sample"):
			for row in self.get(field) or []:
				if not row.stock_entry:
					continue
				entry_name = row.stock_entry
				# Drop the row's link BEFORE the cancel. A GRN cancel unwinds these while the
				# Purchase QC is still SUBMITTED, and check_no_back_links_exist then refuses
				# the Stock Entry cancel ("Cannot delete or cancel because Stock Entry ... is
				# linked with Purchase QC ..."). Clearing first removes that back-link and
				# leaves the same end state the QC's own cancel always produced.
				frappe.db.set_value(row.doctype, row.name, "stock_entry", None, update_modified=False)
				row.stock_entry = None
				if frappe.db.get_value("Stock Entry", entry_name, "docstatus") == 1:
					entry = frappe.get_doc("Stock Entry", entry_name)
					entry.flags.ignore_permissions = True
					entry.cancel()

	# --------------------------------------------------- submit / cancel side

	def _push_to_inward(self):
		"""BRD 4.11 "Update Purchase Inward Status"."""
		inward = frappe.get_doc("Purchase Inward", self.purchase_inward)
		inward.db_set("purchase_qc", self.name, update_modified=False)
		inward.db_set("qc_status", C.QC_COMPLETED, update_modified=False)
		# Purchase Inward does not carry qc_result today; mirror it the moment it does,
		# so the list screen never has to open the QC to colour a row.
		if inward.meta.has_field("qc_result"):
			inward.db_set("qc_result", self.qc_result, update_modified=False)
		workflow.set_status(inward, C.PI_QC_COMPLETED)

	def _generate_grn(self):
		"""BR-QC-17 / VAL-QC-16 — mint the Draft GRN when the result allows one.

		grn is imported lazily: this controller is loaded during migrate, and an
		import-order problem in a sibling module must not make the doctype unloadable.
		"""
		if self.qc_result not in C.QC_RESULTS_ALLOWING_GRN:
			return
		if flt(self.total_approved_qty) <= 0:
			# VAL-GRN-02: nothing approved, nothing to receive.
			return

		inward = frappe.get_doc("Purchase Inward", self.purchase_inward)
		if inward.purchase_receipt:
			return

		try:
			from alpinos.purchase.grn import make_purchase_receipt
		except ImportError:
			frappe.log_error(
				title="Purchase QC: GRN module unavailable",
				message="alpinos.purchase.grn.make_purchase_receipt could not be imported.",
			)
			frappe.msgprint(
				_("QC is complete, but the GRN could not be generated automatically."),
				indicator="orange",
			)
			return

		receipt = make_purchase_receipt(inward)
		name = receipt if isinstance(receipt, str) else receipt.name
		self.db_set("purchase_receipt", name, update_modified=False)
		inward.db_set("purchase_receipt", name, update_modified=False)
		inward.db_set("grn_status", C.GRN_DRAFT, update_modified=False)
		workflow.set_status(inward, C.PI_GRN_GENERATED)

	def _block_cancel_with_downstream(self):
		"""BRD 5.3 — cancellation is strictly reverse-chronological."""
		receipt = self.purchase_receipt or frappe.db.get_value(
			"Purchase Inward", self.purchase_inward, "purchase_receipt"
		)
		if receipt and frappe.db.get_value("Purchase Receipt", receipt, "docstatus") != 2:
			frappe.throw(
				_("Cancel GRN {0} before cancelling this Purchase QC.").format(
					get_link_to_form("Purchase Receipt", receipt)
				)
			)

	def _walk_inward_back(self):
		"""Return the inward to Pending QC so a fresh inspection can be raised."""
		if not self.purchase_inward:
			return
		inward = frappe.get_doc("Purchase Inward", self.purchase_inward)
		if inward.docstatus != 1 or inward.inward_status in C.PI_TERMINAL:
			return
		if inward.purchase_qc == self.name:
			inward.db_set("purchase_qc", None, update_modified=False)
		inward.db_set("qc_status", "", update_modified=False)
		inward.db_set("grn_status", "", update_modified=False)
		if inward.meta.has_field("qc_result"):
			inward.db_set("qc_result", "", update_modified=False)
		if inward.inward_status in (
			C.PI_QC_IN_PROGRESS,
			C.PI_QC_COMPLETED,
			C.PI_GRN_GENERATED,
		):
			workflow.set_status(inward, C.PI_PENDING_QC)

	# --------------------------------------------------------------- 304 SLA

	def _apply_sla(self):
		"""BR-QC-03 — the 2h clock starts at Purchase Inward submission."""
		inward = self._inward()
		start = self.sla_start or inward.get("receiving_datetime") or inward.get(
			"actual_arrival_datetime"
		) or inward.get("modified")
		if not start:
			return
		self.sla_start = start
		self.sla_due = add_to_date(start, hours=sla_hours(self.company), as_datetime=True)
		if self.docstatus == 0 and self.qc_status in _OPEN_QC_STATUSES:
			self.sla_breached = 1 if now_datetime() > self.sla_due else 0
			if self.sla_breached and self.qc_status in (C.QC_PENDING, C.QC_IN_PROGRESS):
				self.qc_status = C.QC_SLA_BREACHED
		elif self.docstatus == 1:
			self.sla_breached = cint(self.sla_breached)


def _render(fmt, context):
	"""format() a settings template without letting an unknown token explode."""

	class _Safe(dict):
		def __missing__(self, key):
			return ""

	try:
		return (fmt or "").format_map(_Safe(context))
	except (ValueError, IndexError):
		return ""


# ------------------------------------------------------------- whitelisted API


@frappe.whitelist()
def make_purchase_qc(purchase_inward):
	"""Raise the Purchase QC for a submitted inward, or return the existing one."""
	inward = frappe.get_doc("Purchase Inward", purchase_inward)
	inward.check_permission("read")
	if inward.purchase_qc and frappe.db.get_value("Purchase QC", inward.purchase_qc, "docstatus") != 2:
		return inward.purchase_qc

	qc = frappe.new_doc("Purchase QC")
	qc.purchase_inward = inward.name
	qc.insert()
	return qc.name


@frappe.whitelist()
def start_qc(purchase_qc):
	"""BRD 4.7 — Pending QC -> QC In Progress, gated by the inward workflow."""
	qc = frappe.get_doc("Purchase QC", purchase_qc)
	qc.check_permission("write")

	inward = frappe.get_doc("Purchase Inward", qc.purchase_inward)
	if not inward.purchase_qc:
		inward.db_set("purchase_qc", qc.name, update_modified=False)
		inward.reload()

	workflow.assert_transition(inward, "start_qc")
	workflow.set_status(inward, C.PI_QC_IN_PROGRESS)
	inward.db_set("qc_status", C.QC_IN_PROGRESS, update_modified=False)

	qc.db_set("qc_status", C.QC_IN_PROGRESS, update_modified=False)
	# M09 — BRD 4.1.1: the QC user who picks the job up is the Inspector. _sync_header no
	# longer stamps at the Store handoff, so this is the point where the field is filled;
	# db_set matches how the engine writes every other derived field.
	if not qc.inspector:
		qc.db_set("inspector", frappe.session.user, update_modified=False)
	if not qc.inspection_date:
		qc.db_set("inspection_date", now_datetime(), update_modified=False)
	return qc.qc_status


@frappe.whitelist()
def complete_qc(purchase_qc):
	"""BRD 4.7 — record the decision and submit; the rest happens in on_submit."""
	qc = frappe.get_doc("Purchase QC", purchase_qc)
	qc.check_permission("submit")

	inward = frappe.get_doc("Purchase Inward", qc.purchase_inward)
	workflow.assert_transition(inward, "complete_qc")

	if qc.docstatus == 0:
		qc.submit()
	return {"qc_status": qc.qc_status, "qc_result": qc.qc_result}


@frappe.whitelist()
def override_qc_result(purchase_qc, result, reason=None):
	"""310 — replace the system result with a human decision, on the record.

	The override is written to the document AND to its comment timeline, so the
	change survives even on a site where the override custom fields are absent.
	"""
	if result not in C.QC_RESULTS:
		frappe.throw(_("Unknown QC Result: {0}").format(result))
	if not (reason or "").strip():
		frappe.throw(_("Please give a reason for overriding the QC Result."))

	qc = frappe.get_doc("Purchase QC", purchase_qc)
	qc.check_permission("write")
	if not set(frappe.get_roles()) & set(C.QC_ROLES + C.ADMIN_ROLES):
		frappe.throw(
			_("You do not have permission to override the QC Result."), frappe.PermissionError
		)

	# L09 / VAL-QC-16 — a GRN was already minted from the old result. grn._assert_qc_complete
	# only runs when the receipt is generated, and Purchase Receipt submit never re-reads
	# qc_result, so overriding to a result that forbids a GRN leaves that Draft GRN
	# submittable and rejected material posts into stock as accepted. BRD 5.3 makes the
	# unwind strictly reverse-chronological, so refuse until the GRN is cancelled.
	if qc.docstatus == 1 and result not in C.QC_RESULTS_ALLOWING_GRN:
		receipt = qc.purchase_receipt or frappe.db.get_value(
			"Purchase Inward", qc.purchase_inward, "purchase_receipt"
		)
		if receipt and frappe.db.get_value("Purchase Receipt", receipt, "docstatus") != 2:
			frappe.throw(
				_("Cancel GRN {0} before overriding the QC Result to {1}.").format(
					get_link_to_form("Purchase Receipt", receipt), result
				),
				title=_("VAL-QC-16"),
			)

	previous = qc.qc_result
	if qc.meta.has_field("manual_qc_result"):
		qc.db_set("manual_qc_result", result, update_modified=False)
	if qc.meta.has_field("system_qc_result") and not qc.get("system_qc_result"):
		qc.db_set("system_qc_result", previous, update_modified=False)
	if qc.meta.has_field("qc_result_overridden"):
		qc.db_set("qc_result_overridden", 1, update_modified=False)
	if qc.meta.has_field("override_reason"):
		qc.db_set("override_reason", reason, update_modified=False)
	qc.db_set("qc_result", result, update_modified=False)

	qc.add_comment(
		"Info",
		_("QC Result overridden from {0} to {1} by {2}. Reason: {3}").format(
			previous, result, frappe.session.user, reason
		),
	)
	if qc.docstatus == 1 and qc.purchase_inward:
		frappe.db.set_value(
			"Purchase Inward", qc.purchase_inward, "qc_status", qc.qc_status, update_modified=False
		)
	return result


@frappe.whitelist()
def post_pending_stock_entries(purchase_qc):
	"""Mint the sample / control-sample transfers that were deferred at QC submit.

	Call this once the GRN has posted the receipt stock; rows that already carry a
	submitted Stock Entry are skipped, so it is safe to re-run.
	"""
	qc = frappe.get_doc("Purchase QC", purchase_qc)
	qc.check_permission("write")
	deferred = qc._post_stock_entries()
	return {
		"posted": [
			row.name
			for field in ("sample_testing", "control_sample")
			for row in qc.get(field) or []
			if row.stock_entry
		],
		"deferred": [{"row": name, "reason": reason} for _dt, name, reason in deferred],
	}


def reverse_pending_stock_entries(purchase_qc):
	"""Cancel the sample / control-sample transfers a submitted GRN made possible.

	The mirror image of post_pending_stock_entries, called from the GRN's own cancel
	(BRD 5.3, reverse-chronological): without it the receipt cancel dies with
	NegativeStockError against the sample Stock Entry and the module has no way out.
	The rows are left with a blank stock_entry, so post_pending_stock_entries re-posts
	them unchanged when the GRN is amended and submitted again. Deliberately not
	whitelisted — samples are only ever unwound by a GRN cancel or by the QC's own.
	"""
	frappe.get_doc("Purchase QC", purchase_qc)._reverse_stock_entries()


@frappe.whitelist()
def get_pending_inspections(purchase_qc):
	"""VAL-QC-02 support — what the QC user still has to finish."""
	qc = frappe.get_doc("Purchase QC", purchase_qc)
	qc.check_permission("read")
	return qc._missing_inspections()
