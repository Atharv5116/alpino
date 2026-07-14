# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now


class PostDelivery(Document):
	def validate(self):
		self._validate_appointment_lock()
		self._stamp_asn_upload()
		self._validate_grn()
		self._roll_up_status()
		self._compute_aggregates()

	def _validate_appointment_lock(self):
		"""Appointment ID is editable only until the Sales Order reaches a
		terminal status (BRD: editable at Dispatched / Forced Dispatched)."""
		before = self.get_doc_before_save()
		old = (before.get("appointment_id") if before else "") or ""
		if (self.appointment_id or "") == old:
			return
		status = frappe.db.get_value("Sales Order", self.sales_order, "custom_workflow_status")
		if status in ("Completed", "Forced Completed", "Cancelled"):
			frappe.throw(
				_("Appointment ID can no longer be changed — Sales Order {0} is {1}.").format(
					self.sales_order, status
				)
			)

	def on_update(self):
		self.reflect_to_dn_and_so()
		self._notify_rejections()

	def _notify_rejections(self):
		"""N19 (ASN rejected) / N20 (GRN rejected) — fire once on transition."""
		from alpinos import so_notifications as son

		before = self.get_doc_before_save()
		if (self.asn_status == "Rejected") and (not before or before.get("asn_status") != "Rejected"):
			son.safe(lambda: son.n19_asn_rejected(self))

		rejected_qty = sum(flt(r.grn_rejected_qty) for r in (self.grn_items or []))
		now_rejected = (self.grn_status == "Rejected") or rejected_qty > 0
		was_rejected = False
		if before:
			was_rejected = (before.get("grn_status") == "Rejected") or any(
				flt(r.grn_rejected_qty) > 0 for r in (before.get("grn_items") or [])
			)
		if now_rejected and not was_rejected:
			son.safe(lambda: son.n20_grn_rejected(self, rejected_qty))

	# ------------------------------------------------------------------
	def _stamp_asn_upload(self):
		"""Auto-record who/when the ASN was uploaded (once it leaves Pending)."""
		if (self.asn_status or "Pending") != "Pending" and not self.asn_uploaded_by:
			self.asn_uploaded_by = frappe.session.user
			self.asn_uploaded_on = now()

	def _validate_grn(self):
		"""GRN date/qty rules — only when the buyer shares GRN."""
		if not cint(self.grn_available):
			return
		if self.grn_date and self.dispatch_date and getdate(self.grn_date) < getdate(self.dispatch_date):
			frappe.throw(_("GRN Date cannot be before Dispatch Date."))
		for row in self.grn_items or []:
			disp = flt(row.dispatched_qty)
			if flt(row.grn_qty) > disp:
				frappe.throw(_("GRN Qty cannot be greater than Dispatched Qty (SKU {0}).").format(row.item_code))
			if flt(row.grn_rejected_qty) > disp:
				frappe.throw(_("Rejected Qty cannot be greater than Dispatched Qty (SKU {0}).").format(row.item_code))
			if flt(row.grn_rejected_qty) > 0 and not row.rejection_reason:
				frappe.throw(_("Rejection Reason is required when Rejected Qty > 0 (SKU {0}).").format(row.item_code))

	def _roll_up_status(self):
		"""Overall post-delivery status from the ASN/GRN/appointment progress."""
		asn = self.asn_status or "Pending"
		grn = self.grn_status or "Pending"
		appt = self.appointment_status or "Pending"

		asn_final = asn in ("Accepted", "Rejected")
		grn_final = (not cint(self.grn_available)) or grn in ("Completed", "Rejected")
		appt_final = (not cint(self.appointment_required)) or appt in ("Completed", "Cancelled")

		touched = any([
			asn != "Pending", grn != "Pending",
			self.asn_id, self.grn_number, self.appointment_id,
		])

		if asn_final and grn_final and appt_final and touched:
			self.post_delivery_status = "Completed"
		elif touched:
			self.post_delivery_status = "In Progress"
		else:
			self.post_delivery_status = "Not Started"

	def _compute_aggregates(self):
		"""SO-level aggregate summary across all terms (BRD Module 3):
		fill rate, total terms (submitted DNs), total dispatched qty, and the
		GRN totals / Overall GRN Fill Rate across every Post Delivery of the SO."""
		if not self.sales_order:
			return
		total_po = flt(frappe.db.get_value("Sales Order", self.sales_order, "total_qty")) or _so_ordered_qty(self.sales_order)
		dispatched = _so_dispatched_qty(self.sales_order)
		self.fill_rate = flt((dispatched / total_po * 100.0), 2) if total_po else 0.0
		self.total_dispatched_qty = dispatched
		self.total_terms = frappe.db.count(
			"Delivery Note",
			{"custom_sales_order_id": self.sales_order, "docstatus": 1, "is_return": 0},
		)

		# GRN totals: stored rows of the SO's OTHER Post Deliveries + this doc's
		# (possibly unsaved) rows, so the numbers are correct on the current save.
		other = frappe.db.sql(
			"""
			SELECT IFNULL(SUM(gi.grn_qty), 0), IFNULL(SUM(gi.grn_rejected_qty), 0)
			FROM `tabPost Delivery GRN Item` gi
			INNER JOIN `tabPost Delivery` pd ON pd.name = gi.parent
			WHERE pd.sales_order = %(so)s AND pd.name != %(self)s
			""",
			{"so": self.sales_order, "self": self.name or ""},
		)[0]
		grn_qty = flt(other[0]) + sum(flt(r.grn_qty) for r in (self.grn_items or []))
		grn_rejected = flt(other[1]) + sum(flt(r.grn_rejected_qty) for r in (self.grn_items or []))
		self.total_grn_qty = flt(grn_qty, 2)
		self.total_grn_rejected_qty = flt(grn_rejected, 2)
		self.overall_grn_fill_rate = flt((grn_qty / dispatched * 100.0), 2) if dispatched else 0.0

	# ------------------------------------------------------------------
	def reflect_to_dn_and_so(self):
		"""Mirror the post-delivery status onto the Delivery Note and Sales Order
		(read-only display fields; both are submitted, so write via db.set_value)."""
		if self.delivery_note:
			frappe.db.set_value("Delivery Note", self.delivery_note, {
				"custom_post_delivery": self.name,
				"custom_post_delivery_status": self.post_delivery_status,
				"custom_asn_status": self.asn_status,
				"custom_grn_status": self.grn_status,
				"custom_appointment_status": self.appointment_status,
			}, update_modified=False)
		if self.sales_order:
			frappe.db.set_value("Sales Order", self.sales_order, {
				"custom_post_delivery_status": self.post_delivery_status,
				"custom_asn_status": self.asn_status,
				"custom_grn_status": self.grn_status,
				"custom_fill_rate": self.fill_rate,
				"custom_total_terms": self.total_terms,
				"custom_total_dispatched_qty": self.total_dispatched_qty,
				"custom_total_grn_qty": self.total_grn_qty,
				"custom_total_grn_rejected_qty": self.total_grn_rejected_qty,
				"custom_overall_grn_fill_rate": self.overall_grn_fill_rate,
			}, update_modified=False)


def _so_ordered_qty(sales_order):
	return flt(frappe.db.sql(
		"SELECT SUM(qty) FROM `tabSales Order Item` WHERE parent=%s", (sales_order,)
	)[0][0] or 0)


def _so_dispatched_qty(sales_order):
	"""Sum of Delivery Note item qty across all submitted, non-return DNs linked to
	the SO. Excludes sales returns so they don't inflate dispatched qty / fill rate
	(matches partial_dispatch.dispatched_qty_by_sku)."""
	return flt(frappe.db.sql(
		"""
		SELECT SUM(dni.qty)
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id = %s AND dn.docstatus = 1 AND IFNULL(dn.is_return, 0) = 0
		""",
		(sales_order,),
	)[0][0] or 0)
