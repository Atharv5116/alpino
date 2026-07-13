# Copyright (c) 2026, Alpinos and contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now


class PostDelivery(Document):
	def validate(self):
		self._stamp_asn_upload()
		self._validate_grn()
		self._roll_up_status()
		self._compute_fill_rate()

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

	def _compute_fill_rate(self):
		"""SO-level fill rate = total dispatched qty (all DNs) / total PO qty × 100."""
		if not self.sales_order:
			return
		total_po = flt(frappe.db.get_value("Sales Order", self.sales_order, "total_qty")) or _so_ordered_qty(self.sales_order)
		dispatched = _so_dispatched_qty(self.sales_order)
		self.fill_rate = flt((dispatched / total_po * 100.0), 2) if total_po else 0.0

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
			}, update_modified=False)


def _so_ordered_qty(sales_order):
	return flt(frappe.db.sql(
		"SELECT SUM(qty) FROM `tabSales Order Item` WHERE parent=%s", (sales_order,)
	)[0][0] or 0)


def _so_dispatched_qty(sales_order):
	"""Sum of Delivery Note item qty across all submitted DNs linked to the SO."""
	return flt(frappe.db.sql(
		"""
		SELECT SUM(dni.qty)
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.custom_sales_order_id = %s AND dn.docstatus = 1
		""",
		(sales_order,),
	)[0][0] or 0)
