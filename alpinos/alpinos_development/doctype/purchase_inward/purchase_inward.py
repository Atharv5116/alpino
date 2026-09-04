# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""Purchase Inward — the material-arrival document shared by Purchase and Store.

BRD "Purchase Inward Part -1", sections 1.x and 2.x.

Many Purchase Inwards may be raised against one Purchase Order until the pending
quantity reaches zero, so "Previously Received Quantity" is summed over SUBMITTED
Purchase Inwards rather than read off Purchase Order Item.received_qty — that core
column only counts submitted Purchase Receipts, and the BRD deliberately parks the
GRN in Draft until an Admin finally submits it (BR-QC-17 / BR-QC-20). Reading it
would let two inwards raised in the same window both see the full pending quantity
and jointly over-receive with no error.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, get_link_to_form, getdate, now_datetime

from alpinos.purchase import constants as C
from alpinos.purchase.settings import get_settings


class PurchaseInward(Document):
	# ------------------------------------------------------------------ hooks

	def validate(self):
		self._assert_section_access()
		self._validate_purchase_order()
		self._sync_item_provenance()
		self._validate_unique_po_detail()
		self._compute_previously_received()
		self._validate_invoice_number()
		self._validate_challan_no()
		self._apply_default_target_warehouse()
		self._set_expiry_dates()
		self._validate_received_quantities()
		self._validate_receiving_details()
		self._stamp_dispute_attachments()
		self._roll_up_totals()
		self._sync_status()

	def before_submit(self):
		if not self.get("items"):
			frappe.throw(_("Please add at least one item to the Purchase Inward."))
		self.inward_status = C.PI_PENDING_RECEIPT

	def on_submit(self):
		self.db_set("inward_status", C.PI_PENDING_RECEIPT, update_modified=False)
		self._refresh_po_progress()

	def before_update_after_submit(self):
		"""Store receiving edits land here (every receiving field is allow_on_submit).

		This has to be the BEFORE hook. Frappe runs before_update_after_submit from
		run_before_save_methods (document.py:1151) but on_update_after_submit only from
		run_post_save_methods (document.py:1188) -- by which point db_update() and
		update_children() have already flushed the row. Deriving expiry dates, previous
		quantities and the total_* roll-ups in the post-save hook assigned them to an
		in-memory doc that is never written again, so every derived value was discarded
		and the validations fired too late to block a bad receipt.
		"""
		self._assert_section_access()
		self._guard_engine_owned_fields()
		self._validate_unique_po_detail()
		self._compute_previously_received()
		self._apply_default_target_warehouse()
		self._set_expiry_dates()
		self._validate_received_quantities()
		self._validate_receiving_details()
		self._stamp_dispute_attachments()
		self._roll_up_totals()

	def on_update_after_submit(self):
		"""Side effects that must observe the persisted row."""
		self._refresh_po_progress()
		self._resync_draft_grn()

	def _resync_draft_grn(self):
		"""BR-GRN-04 / task 299 - keep a Draft GRN in step with the receipt it came from.

		Without this the GRN was drafted once and never looked at the inward again, so any
		later correction to the receiving section (a target warehouse, a batch, a quantity)
		left a stale draft that the Admin would then submit. Runs after the row is written
		so the re-pull reads the persisted values, and is a no-op unless a Draft GRN exists.
		"""
		from alpinos.purchase.grn import resync_draft_grn

		resync_draft_grn(self)

	def on_cancel(self):
		self._block_cancel_with_downstream()
		self.db_set("inward_status", C.PI_CANCELLED, update_modified=False)
		self._refresh_po_progress()

	#: Fields the workflow engine alone may write. Every one is read_only=1 +
	#: allow_on_submit=1, and read_only is a CLIENT-side hint only -- so without this
	#: guard a plain REST call (frappe.client.set_value, which does update()+save())
	#: could drive a submitted inward straight to "Completed" with nothing received, or
	#: point purchase_receipt at an unrelated submitted GRN and satisfy the downstream
	#: guards. The engine itself writes these with db_set(), which never enters the save
	#: path, so nothing legitimate is blocked here.
	ENGINE_OWNED_FIELDS = (
		"inward_status",
		"qc_status",
		"grn_status",
		"purchase_qc",
		"purchase_receipt",
		"purchase_invoice",
		"merged_into",
		"original_invoice_number",
	)

	def _guard_engine_owned_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return

		changed = [
			fieldname
			for fieldname in self.ENGINE_OWNED_FIELDS
			if (self.get(fieldname) or None) != (before.get(fieldname) or None)
		]
		if not changed:
			return

		labels = ", ".join(self.meta.get_label(fieldname) for fieldname in changed)
		frappe.throw(
			_(
				"{0} is maintained by the Purchase Inward workflow and cannot be edited "
				"directly. Use the action buttons on the Purchase Inward instead."
			).format(frappe.bold(labels)),
			frappe.PermissionError,
			title=_("Not Permitted"),
		)

	def _assert_section_access(self):
		"""Server twin of the role-gated section visibility (task 288).

		The client script hides the sections, but depends_on and a hidden field are
		client-only -- a REST or bulk write would otherwise let Store edit the
		Purchase-owned header, or Purchase rewrite the receipt.
		"""
		from alpinos.purchase.roles import assert_section_edits_allowed

		assert_section_edits_allowed(self)

	def _refresh_po_progress(self):
		"""Roll this inward's quantities up onto the Purchase Order.

		Imported lazily: a migrate that syncs this doctype before the Purchase
		Order custom fields exist must still be able to import the controller.
		"""
		from alpinos.purchase.purchase_order_fields import refresh_inward_progress

		refresh_inward_progress(self.purchase_order)

	# --------------------------------------------------- purchase order gate

	def _validate_purchase_order(self):
		"""VAL-PI-01/02 and the PO-side gates VAL-PO-10 / 12 / 13 / 15."""
		if not self.purchase_order:
			frappe.throw(_("Please select a valid Purchase Order."), title=_("VAL-PI-01"))

		po = frappe.db.get_value(
			"Purchase Order",
			self.purchase_order,
			[
				"docstatus",
				"status",
				"supplier",
				"company",
				"custom_direct_purchase_invoice",
				"custom_inward_type",
			],
			as_dict=True,
		)
		if not po:
			frappe.throw(_("Purchase Order {0} does not exist.").format(self.purchase_order))

		if po.docstatus == 2:
			frappe.throw(
				_("Cancelled Purchase Order cannot be used for material receiving."),
				title=_("VAL-PO-12"),
			)
		if po.docstatus != 1:
			frappe.throw(
				_("Only an Approved Purchase Order can be used for Purchase Inward."),
				title=_("VAL-PO-15"),
			)
		if cint(po.custom_direct_purchase_invoice):
			frappe.throw(
				_("This Purchase Order is configured for Direct Purchase Invoice."),
				title=_("VAL-PO-13"),
			)
		if po.status in ("Closed", "On Hold"):
			frappe.throw(
				_("Purchase Inward cannot be created against a Purchase Order that is {0}.").format(
					po.status
				),
				title=_("VAL-PI-02"),
			)

		self.supplier = po.supplier
		self.company = po.company
		# BRD 2.1.1 defines Inward Type as Auto Fetch from the Purchase Order. Copying it
		# only when blank left the Select editable in Draft, so a user could raise an
		# inward against an FG order and retype the type as RM -- which skips the FG
		# mandatory-batch rule in _validate_receiving_details and makes QC mint the RM/PM
		# internal batch format instead of the FG one (BR-QC-11 vs BR-QC-12).
		if po.custom_inward_type:
			self.inward_type = po.custom_inward_type

	# ------------------------------------------------------- item provenance

	def _sync_item_provenance(self):
		"""Stamp every line with its source PO row and the ordered quantity."""
		po_items = {
			row.name: row
			for row in frappe.get_all(
				"Purchase Order Item",
				filters={"parent": self.purchase_order, "docstatus": 1},
				fields=[
					"name",
					"item_code",
					"item_name",
					"uom",
					"stock_uom",
					"conversion_factor",
					"qty",
					"rate",
					"amount",
					"warehouse",
					"description",
				],
			)
		}
		by_item = {}
		for row in po_items.values():
			by_item.setdefault(row.item_code, row)

		for line in self.get("items"):
			src = po_items.get(line.po_detail) or by_item.get(line.item_code)
			if not src:
				frappe.throw(
					_("Row {0}: item {1} is not on Purchase Order {2}.").format(
						line.idx, line.item_code or "?", self.purchase_order
					)
				)
			line.po_detail = src.name
			line.purchase_order = self.purchase_order
			line.item_code = src.item_code
			line.item_name = src.item_name
			line.uom = src.uom
			line.stock_uom = src.stock_uom
			line.conversion_factor = flt(src.conversion_factor) or 1.0
			line.order_qty = flt(src.qty)
			line.rate = flt(src.rate)
			line.amount = flt(src.amount)
			if not line.description:
				line.description = src.description
			line.stock_qty = flt(line.received_qty) * flt(line.conversion_factor)

	# ------------------------- previously received / pending (task 298) -----

	def _stamp_dispute_attachments(self):
		"""Record who attached each piece of dispute evidence, and when (BRD 2.2.1).

		PurchaseInwardAttachment.before_insert cannot do this: frappe never runs controller
		lifecycle methods on child-table rows -- children are written with
		BaseDocument.db_insert()/db_update(), and run_method("before_insert") fires only on
		the parent. Both fields are read_only, so nobody could fill them by hand either, and
		every photo/video of a damaged consignment was stored with a NULL uploader and a
		NULL timestamp -- exactly the provenance a vendor debit-note claim needs.
		"""
		for row in self.get("dispute_attachments") or []:
			if not row.get("uploaded_by"):
				row.uploaded_by = frappe.session.user
			if not row.get("uploaded_on"):
				row.uploaded_on = now_datetime()

	def _validate_unique_po_detail(self):
		"""One Purchase Order line may appear at most once on an inward.

		Both the pending quantity and the VAL-PI-07 over-receipt check are derived per row
		from the PO line's remaining quantity, so two rows pointing at the same po_detail
		each see the FULL pending quantity and neither notices the other. Without this the
		document happily accepts 100 + 100 against an order of 100, reports excess_qty 0,
		and pushes 200 into stock through the QC/GRN chain. The Get Items dialog already
		dedupes; this closes the manual Add Row path (and any row set predating the fix).
		"""
		seen = {}
		for line in self.get("items"):
			if not line.po_detail:
				continue
			first = seen.get(line.po_detail)
			if first:
				frappe.throw(
					_(
						"Rows {0} and {1} both receive against the same Purchase Order line "
						"for {2}. Combine them into a single row."
					).format(first, line.idx, frappe.bold(line.item_code)),
					title=_("Duplicate Purchase Order Line"),
				)
			seen[line.po_detail] = line.idx

	def _compute_previously_received(self):
		"""BR-PI-11 / BR-PI-12 — cumulative receipt over other SUBMITTED inwards."""
		details = [line.po_detail for line in self.get("items") if line.po_detail]
		received = self.received_by_po_detail(
			self.purchase_order, details, exclude_inward=self.name
		)
		for line in self.get("items"):
			prev = flt(received.get(line.po_detail))
			line.previously_received_qty = prev
			line.pending_qty = max(flt(line.order_qty) - prev, 0.0)
			over = flt(line.received_qty) - flt(line.pending_qty)
			line.excess_qty = over if over > 0 else 0.0

	@staticmethod
	def received_by_po_detail(purchase_order, po_details, exclude_inward=None):
		"""{po_detail: qty} received by submitted Purchase Inwards on this PO."""
		if not purchase_order or not po_details:
			return {}
		rows = frappe.get_all(
			"Purchase Inward Item",
			filters={
				"parent": ("!=", exclude_inward or ""),
				"po_detail": ("in", list(po_details)),
				"docstatus": 1,
			},
			fields=["po_detail", "sum(received_qty) as qty"],
			group_by="po_detail",
		)
		return {r.po_detail: flt(r.qty) for r in rows}

	# ------------------------------- invoice / challan uniqueness -----------

	def _validate_invoice_number(self):
		"""BR-PI-15 / VAL-PI-13 / VAL-PI-15 — unique invoice number per vendor."""
		if not (self.invoice_number and self.supplier):
			return
		clash = frappe.get_all(
			"Purchase Inward",
			filters={
				"name": ("!=", self.name),
				"supplier": self.supplier,
				"invoice_number": self.invoice_number,
				"docstatus": ("<", 2),
			},
			pluck="name",
			limit=5,
		)
		if not clash:
			return
		if self.merged_into:
			return
		links = ", ".join(get_link_to_form("Purchase Inward", n) for n in clash)
		frappe.throw(
			_(
				"This Invoice Number already exists for this Vendor. Please merge with the "
				"existing Purchase Inward or use a different Invoice Number.<br><br>"
				"Existing: {0}"
			).format(links),
			title=_("VAL-PI-15"),
		)

	def _validate_challan_no(self):
		"""VAL-PI-22 — challan number is unique per vendor."""
		if not (self.challan_no and self.supplier):
			return
		clash = frappe.get_all(
			"Purchase Inward",
			filters={
				"name": ("!=", self.name),
				"supplier": self.supplier,
				"challan_no": self.challan_no,
				"docstatus": ("<", 2),
			},
			pluck="name",
			limit=5,
		)
		if clash:
			links = ", ".join(get_link_to_form("Purchase Inward", n) for n in clash)
			frappe.throw(
				_("This Challan Number has already been recorded for this Vendor.<br><br>{0}").format(
					links
				),
				title=_("VAL-PI-22"),
			)

	# ------------------------------------- receiving detail (tasks 297/300) -

	def _apply_default_target_warehouse(self):
		if not self.target_warehouse:
			return
		for line in self.get("items"):
			if not line.target_warehouse:
				line.target_warehouse = self.target_warehouse

	def _set_expiry_dates(self):
		"""Expiry = Manufacturing Date + the item's shelf life (task 297)."""
		shelf = {}
		for line in self.get("items"):
			if not line.manufacturing_date:
				line.expiry_date = None
				continue
			if line.item_code not in shelf:
				shelf[line.item_code] = cint(
					frappe.db.get_value("Item", line.item_code, "shelf_life_in_days")
				)
			days = shelf[line.item_code]
			line.expiry_date = (
				add_days(getdate(line.manufacturing_date), days) if days else None
			)

	def _validate_received_quantities(self):
		"""VAL-PI-07 / VAL-PI-08 and the over-receipt tolerance (task 300)."""
		settings = get_settings(self.company)
		tolerance = flt(settings.get("over_receipt_tolerance_percent"))
		block = cint(settings.get("block_over_receipt"))

		for line in self.get("items"):
			received = flt(line.received_qty)
			if received < 0:
				frappe.throw(_("Row {0}: Received Qty cannot be negative.").format(line.idx))

			line.stock_qty = received * (flt(line.conversion_factor) or 1.0)
			pending = flt(line.pending_qty)
			over = received - pending
			line.excess_qty = over if over > 0 else 0.0

			if over <= 0:
				continue

			# Excess is allowed outright when the Store ticked the box (BR-PI-14).
			if cint(self.allow_excess_qty):
				continue

			# Otherwise a configured tolerance may still absorb it.
			allowed = pending * tolerance / 100.0 if tolerance else 0.0
			if over <= allowed:
				continue

			if block:
				frappe.throw(
					_(
						"Row {0} ({1}): Received Quantity cannot be greater than Pending "
						"Quantity. Pending is {2}, received is {3}. Tick <b>Allow Excess "
						"Quantity</b> to receive the excess."
					).format(line.idx, line.item_code, pending, received),
					title=_("VAL-PI-07"),
				)
			frappe.msgprint(
				_("Row {0} ({1}): receiving {2} against a pending quantity of {3}.").format(
					line.idx, line.item_code, received, pending
				),
				title=_("Excess Quantity"),
				indicator="orange",
			)

	def _validate_receiving_details(self):
		"""Guards for the Store Receiving section. depends_on is client-only, so the
		mandatory rules are re-checked here (VAL-PI-05 / 09 / 10 / 12)."""
		if self.docstatus != 1:
			return
		if not self._receiving_started():
			return

		if cint(self.vehicle_details_verified) and not (
			(self.actual_vehicle_no or "").strip()
			or (self.actual_driver_contact_no or "").strip()
		):
			frappe.throw(
				_("Please enter the correct vehicle and driver details."),
				title=_("VAL-PI-05"),
			)

		if not self.actual_arrival_datetime:
			frappe.throw(
				_("Please enter the Actual Arrival Date & Time."), title=_("VAL-PI-12")
			)

		for line in self.get("items"):
			if flt(line.received_qty) <= 0:
				continue
			if not line.target_warehouse:
				frappe.throw(
					_("Row {0}: please select a Target Location.").format(line.idx),
					title=_("VAL-PI-09"),
				)
			if self.inward_type == C.INWARD_FG and not (line.batch_no or "").strip():
				frappe.throw(
					_("Row {0}: Batch No. is mandatory for an FG inward.").format(line.idx)
				)

			# BRD 2.2.1 marks Manufacturing Date mandatory. It is enforced where the value
			# actually carries downstream meaning: a shelf-life item cannot derive its
			# Expiry Date without it (the row silently stored expiry NULL), and BR-QC-12's
			# FG internal batch format is "{batch_no}-{mfg_date}". Loose material with no
			# shelf life is left alone rather than inventing friction the BRD does not need.
			if not line.manufacturing_date:
				shelf_life = cint(
					frappe.db.get_value("Item", line.item_code, "shelf_life_in_days")
				)
				if shelf_life or self.inward_type == C.INWARD_FG:
					frappe.throw(
						_(
							"Row {0} ({1}): Manufacturing Date is required - the Expiry Date "
							"is derived from it."
						).format(line.idx, line.item_code),
						title=_("BRD 2.2.1"),
					)

	def _receiving_started(self):
		return any(flt(line.received_qty) for line in self.get("items")) or bool(
			self.actual_arrival_datetime
		)

	# ------------------------------------------------------------- roll-ups -

	def _roll_up_totals(self):
		self.total_order_qty = sum(flt(l.order_qty) for l in self.get("items"))
		self.total_previously_received_qty = sum(
			flt(l.previously_received_qty) for l in self.get("items")
		)
		self.total_pending_qty = sum(flt(l.pending_qty) for l in self.get("items"))
		self.total_received_qty = sum(flt(l.received_qty) for l in self.get("items"))
		self.total_excess_qty = sum(flt(l.excess_qty) for l in self.get("items"))
		self.total_items = len(self.get("items"))

	def _sync_status(self):
		if self.docstatus == 0:
			self.inward_status = C.PI_DRAFT
		elif self.docstatus == 2:
			self.inward_status = C.PI_CANCELLED

	# ------------------------------------------------------- cancellation ---

	def _block_cancel_with_downstream(self):
		"""BRD 5.3 — cancellation runs in reverse-chronological order."""
		if self.purchase_receipt and frappe.db.get_value(
			"Purchase Receipt", self.purchase_receipt, "docstatus"
		) == 1:
			frappe.throw(
				_("Cancel GRN {0} before cancelling this Purchase Inward.").format(
					self.purchase_receipt
				)
			)
		if self.purchase_qc and frappe.db.get_value(
			"Purchase QC", self.purchase_qc, "docstatus"
		) != 2:
			frappe.throw(
				_("Cancel Purchase QC {0} before cancelling this Purchase Inward.").format(
					self.purchase_qc
				)
			)
