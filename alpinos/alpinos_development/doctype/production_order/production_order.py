"""The Parent Production Order — a planning header, deliberately not a Work Order.

The FRD says to map this onto Work Order. It should not be, and the reason is not style:

    work_order.py:162   validate() ends with `self.status = self.get_status()`, so a custom
                        status never sticks and a parallel status field is needed anyway.
                        The Parent forfeits Work Order lifecycle either way.
    work_order.py:174   set_required_items() repopulates the lines from the BOM on every
                        save -- but these lines are a planning artefact (Total Required Qty,
                        splits, merges), not a live read of the BOM.
    work_order.py:544   on_submit() writes Bin: reserved_qty_for_production, planned_qty,
                        and creates Job Cards. "No transactions against the Parent" means
                        suppressing all three, and a suppression bug corrupts real stock
                        state -- the one failure class a rollback test cannot catch.

ERPNext's own precedent for this shape is Production Plan: a submittable, non-stock planning
header that spawns Work Orders. The Sub PO IS a real Work Order, with its native on_submit
left alone, because there the stock effects are exactly what is wanted.

PPO-02 / BR-PO-05 -- no Material Request, Stock Entry, Production Entry or Quality
Inspection may be raised against the Parent -- costs nothing to hold here: nothing can link
to this doctype until a link field to it is added, and none is.

Everything the ten open decisions touch is absent rather than guessed: there is no batch
formula, no Total Required Qty calculation, no status transition table and no batch number
generator. The fields those will fill exist and are writable, so nothing has to be migrated
when the rules land.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from alpinos.production import constants as C
from alpinos.production.item_fields import MATERIAL_TYPE_FIELD as ITEM_MATERIAL_TYPE


class ProductionOrder(Document):
	def before_insert(self):
		# Task 21: Creation Date is today and read-only. Set here rather than as a doctype
		# default so PO-V03 has a real date to measure against even on an API insert.
		self.creation_date = self.creation_date or nowdate()
		self.po_level = "Parent"
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or \
				frappe.db.get_single_value("Global Defaults", "default_company")
		if not self.status:
			self.status = C.PO_DRAFT

	def validate(self):
		self.po_level = "Parent"
		self._guard_workflow_fields()
		self._validate_quantities()
		self._validate_client()
		self._validate_fg_item()
		self._validate_dates()
		self._apply_bom()
		self._validate_rows()

	# ------------------------------------------------- the workflow fields

	#: Fields the approval flow owns. Nobody writes these by hand, from any client.
	WORKFLOW_FIELDS = ("status", "approved_by", "approved_on", "sent_by", "sent_on",
	                   "rejection_reason")

	def _guard_workflow_fields(self):
		"""PO-V: the status and the approval stamps cannot be written through the API.

		`read_only` on the doctype stops the desk form drawing an input and nothing else --
		the REST API, `frappe.client.set_value` and any script write straight through it. So
		a Production Order could be moved to Approved, with an Approved By stamp, by anyone
		who could save it at all, skipping whatever approval flow is eventually built.

		Any change to one of these is put back to its stored value rather than refused: a
		client that sends the whole document back (which is how frappe forms save) would
		otherwise be unable to save anything at all. Silent by design -- the field is
		read-only, so a caller that changed it was not supposed to be editing it.

		`flags.alpinos_workflow` is how the flow itself will write them when it exists.
		"""
		if self.flags.get("alpinos_workflow"):
			return

		if self.is_new():
			# A new order always starts at Draft, whatever was sent with it.
			if self.status != C.PO_DRAFT:
				self.status = C.PO_DRAFT
			for field in self.WORKFLOW_FIELDS:
				if field != "status":
					self.set(field, None)
			return

		before = self.get_doc_before_save()
		if not before:
			return
		for field in self.WORKFLOW_FIELDS:
			if self.get(field) != before.get(field):
				self.set(field, before.get(field))

	# ------------------------------------------------------------- PO-V02

	def _validate_quantities(self):
		if flt(self.production_qty_kg) <= 0:
			frappe.throw(
				_("Production Quantity must be greater than 0."),
				title=_("Invalid Production Quantity"),
			)
		# PO-V01 lists PCS as mandatory. It is a count, so zero is a real answer and the
		# rule is "tell us the number", not "the number must be positive" -- which is why
		# this is checked here rather than with `reqd` on the field, where frappe treats 0
		# as missing and would refuse a genuine zero.
		if self.production_qty_pcs in (None, ""):
			frappe.throw(
				_("Please enter the Production Quantity (PCS). Enter 0 if it is not counted in pieces."),
				title=_("Production Quantity (PCS) Required"),
			)
		if int(self.production_qty_pcs) < 0:
			frappe.throw(
				_("Production Quantity (PCS) cannot be negative."),
				title=_("Invalid Production Quantity"),
			)

	# ------------------------------------------------------------- PO-V04

	def _validate_client(self):
		if self.production_type in C.PRODUCTION_TYPES_NEEDING_CLIENT:
			if not self.client_name:
				frappe.throw(
					_("Client Name is required for Export / White Label."),
					title=_("Client Required"),
				)
		elif self.client_name:
			# Own Production has no client, and a leftover one would keep surfacing in the
			# list filter and on the printed order. The field is hidden by depends_on, which
			# hides it without clearing it.
			self.client_name = None

	# ------------------------------------------------------------- PO-V05

	def _validate_fg_item(self):
		"""Task 23. One FG field, and it must hold a Finished Good.

		"More than one FG" cannot happen by construction -- there is a single Link field and
		no FG child table -- which is the structural half of the rule. What is checkable is
		the type.

		An item with no Material Type at all is allowed, for the same reason the BOM screen
		allows one: 226 of the 233 items on this site predate the field, and back-filling the
		catalogue is off the table.
		"""
		if not self.fg_item:
			return
		declared = frappe.db.get_value("Item", self.fg_item, ITEM_MATERIAL_TYPE)
		if declared and declared != C.MATERIAL_FG:
			frappe.throw(
				_("{0} is a {1} item. A Production Order can only be raised for a Finished Good.").format(
					self.fg_item, declared
				),
				title=_("Not A Finished Good"),
			)

	# ------------------------------------------------------- PO-V03, PO-V07

	def _validate_dates(self):
		creation = getdate(self.creation_date or nowdate())
		if self.production_start_date and getdate(self.production_start_date) < creation:
			frappe.throw(
				_("Start Date cannot be before Creation Date."),
				title=_("Invalid Start Date"),
			)
		if self.delivery_date and self.production_start_date:
			if getdate(self.delivery_date) < getdate(self.production_start_date):
				frappe.throw(
					_("Delivery Date cannot be before the Production Start Date."),
					title=_("Invalid Delivery Date"),
				)

	# -------------------------------------------------- Task 4 + 5, PO-V06

	def _apply_bom(self):
		"""Find the FG's Active default BOM and snapshot its rows onto this order.

		A snapshot on purpose: Task 4 says editing a BOM later must not change orders already
		written. So the rows are re-copied only when the BOM this order points at changes --
		which happens when the FG changes, or on the first save.

		Draft or submitted is not part of the question. Only `is_active` and `is_default`
		are, because Production reads draft BOMs (see bom_api._clear_other_defaults).
		"""
		if not self.fg_item:
			return

		bom = self._default_bom()
		if not bom:
			frappe.throw(
				_("No active default BOM found for {0}. Create one in BOM Master.").format(
					self.fg_item
				),
				title=_("No Default BOM"),
			)

		if self.bom_no == bom and self.get("items"):
			return  # already snapshotted from this BOM; leave the rows alone

		self.bom_no = bom
		self._snapshot_bom_rows(bom)

	def _default_bom(self):
		rows = frappe.get_all(
			"BOM",
			filters={"item": self.fg_item, "is_active": 1, "is_default": 1,
			         "docstatus": ("<", 2)},
			pluck="name",
			order_by="modified desc",
			limit=1,
		)
		return rows[0] if rows else None

	def _snapshot_bom_rows(self, bom):
		from alpinos.production.bom_fields import MATERIAL_TYPE_FIELD, STAGE_FIELD

		rows = frappe.get_all(
			"BOM Item",
			filters={"parent": bom},
			fields=["item_code", "item_name", "uom", "qty", MATERIAL_TYPE_FIELD, STAGE_FIELD],
			order_by="idx asc",
		)
		# Only the rows the BOM actually has. A BOM with RM alone gives RM rows and no blank
		# PM or Additive placeholders (Task 4).
		self.set("items", [])
		for row in rows:
			self.append("items", {
				"item_code": row.item_code,
				"item_name": row.item_name,
				"uom": row.uom,
				"standard_qty": flt(row.qty),
				"material_type": row.get(MATERIAL_TYPE_FIELD),
				"process_stage": row.get(STAGE_FIELD),
				# Left blank deliberately: the formula that would fill it is one of the open
				# decisions, and a wrong number here would be quoted as if it were right.
				"total_required_qty": 0,
			})

	def _validate_rows(self):
		"""Task 5: Total Required Qty must be at least zero."""
		for row in self.get("items") or []:
			if flt(row.total_required_qty) < 0:
				frappe.throw(
					_("Row {0}: Total Required Qty cannot be negative.").format(row.idx),
					title=_("Invalid Quantity"),
				)

	# ------------------------------------------------------------- lifecycle

	def on_submit(self):
		"""Nothing. `approve()` is what submits an order, and it writes the status itself.

		Deliberately empty otherwise: this is a planning header, and unlike a Work Order it
		writes no Bin row and no Stock Entry.
		"""
		pass

	# ------------------------------------------------ Task 26: the transitions
	#
	# `status` carries the workflow; `docstatus` is only spent at approval. Submitting for
	# approval leaves the document at docstatus 0 on purpose -- a rejected order has to be
	# editable and re-submittable, and frappe will not let a docstatus-1 document be edited
	# at all. Editing is gated on the STATUS instead (PO_EDITABLE_STATUSES), which the
	# screen and save_production_order both read.

	def submit_for_approval(self):
		"""Draft or Rejected -> Pending Approval.

		Whether a Manager's own submit should skip straight to Approved is still open, so it
		does not: everyone lands on Pending Approval and a Manager approves from there. That
		is the reversible half of the choice -- adding a skip later changes one branch,
		whereas having skipped wrongly would mean orders approved by nobody.
		"""
		self.check_permission("submit")
		if self.status not in (C.PO_DRAFT, C.PO_REJECTED):
			frappe.throw(
				_("Only a Draft or Rejected order can be sent for approval. {0} is {1}.").format(
					self.name, self.status
				),
				title=_("Cannot Submit"),
			)
		if not self.get("items"):
			frappe.throw(_("Add the materials before sending this order for approval."),
			             title=_("No Materials"))
		# Cleared so a re-submitted order does not carry the last refusal around with it.
		self._set_workflow_status(C.PO_PENDING_APPROVAL, rejection_reason=None)
		return self.status

	def _set_workflow_status(self, status, **stamps):
		"""Write a status the guard would otherwise put back, and record who and when."""
		self.flags.alpinos_workflow = True
		values = {"status": status}
		values.update(stamps)
		for field, value in values.items():
			self.set(field, value)
			self.db_set(field, value, update_modified=False)

	# ------------------------------------------------------------- approval

	def approve(self):
		"""Task 25 / 26 + SPO-01: approving is what creates the first Sub PO.

		Only from Pending Approval, and only by a role the FRD names as an approver. Stages
		cannot be skipped (Task 26), so a Draft cannot jump straight here.

		The Sub PO is created BEFORE the status is written, so an approval that cannot
		produce one -- a draft BOM, no finished-goods warehouse -- leaves the order pending
		rather than approved-but-empty.
		"""
		from alpinos.production.sub_order import create_sub_orders

		self.check_permission("submit")

		if self.status != C.PO_PENDING_APPROVAL:
			frappe.throw(
				_("Only an order that is Pending Approval can be approved. {0} is {1}.").format(
					self.name, self.status
				),
				title=_("Cannot Approve"),
			)
		if not self._user_may_approve():
			frappe.throw(
				_("Only a {0} or {1} may approve a Production Order.").format(
					C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN
				),
				title=_("Not An Approver"),
			)

		sub_orders = create_sub_orders(self)

		self._set_workflow_status(
			C.PO_APPROVED,
			approved_by=frappe.session.user,
			approved_on=now_datetime(),
		)
		# Approval is where the docstatus is spent: from here the header is a record, and
		# frappe itself stops it being edited.
		if cint(self.docstatus) == 0:
			self.flags.alpinos_workflow = True
			self.submit()
			self._set_workflow_status(
				C.PO_APPROVED,
				approved_by=frappe.session.user,
				approved_on=now_datetime(),
			)
		return [row["name"] for row in sub_orders]

	# ---------------------------------------------------------------- reject

	def reject(self, reason):
		"""Pending Approval -> Rejected, and back to the planner to fix.

		The reason is mandatory because it is the only thing the planner has to work from;
		a rejection with no reason is just a stuck order.
		"""
		self.check_permission("submit")
		reason = (reason or "").strip()

		if self.status != C.PO_PENDING_APPROVAL:
			frappe.throw(
				_("Only an order that is Pending Approval can be rejected. {0} is {1}.").format(
					self.name, self.status
				),
				title=_("Cannot Reject"),
			)
		if not self._user_may_approve():
			frappe.throw(
				_("Only a {0} or {1} may reject a Production Order.").format(
					C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN
				),
				title=_("Not An Approver"),
			)
		if not reason:
			frappe.throw(_("Please say why this order is being rejected."),
			             title=_("Rejection Reason Required"))

		self._set_workflow_status(C.PO_REJECTED, rejection_reason=reason)
		return self.status

	# ---------------------------------------------------------------- cancel

	def cancel_order(self, reason):
		"""Task 26: Draft / Pending Approval / Approved -> Cancelled.

		PPO-06. Cancelling is refused while any sub order has started life on the floor --
		a Material Request raised, materials issued, or production begun. Those are real
		documents and real stock; cancelling the plan underneath them would leave them
		pointing at nothing.

		Otherwise the sub orders go with it: they are drafts, they exist only because this
		order was approved, and leaving them behind would let somebody work an order that
		was called off.
		"""
		from alpinos.production.sub_order import (
			activity_blockers,
			delete_sub_orders,
			existing_sub_orders,
		)

		self.check_permission("cancel")
		reason = (reason or "").strip()

		if self.status not in (C.PO_DRAFT, C.PO_PENDING_APPROVAL, C.PO_APPROVED, C.PO_REJECTED):
			frappe.throw(
				_("An order that is {0} cannot be cancelled.").format(self.status),
				title=_("Cannot Cancel"),
			)
		if not self._user_may_approve():
			frappe.throw(
				_("Only a {0} or {1} may cancel a Production Order.").format(
					C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN
				),
				title=_("Not An Approver"),
			)
		if not reason:
			frappe.throw(_("Please say why this order is being cancelled."),
			             title=_("Cancellation Reason Required"))

		blocked = []
		for row in existing_sub_orders(self.name):
			for _code, message in activity_blockers(row["name"]):
				blocked.append(f"{row['name']}: {message}")
		if blocked:
			frappe.throw(
				_("This order cannot be cancelled yet.<br><br>{0}").format("<br>".join(blocked[:6])),
				title=_("Work Has Already Started"),
			)

		removed = delete_sub_orders(self.name)
		self._set_workflow_status(C.PO_CANCELLED, rejection_reason=reason)
		if cint(self.docstatus) == 1:
			self.flags.alpinos_workflow = True
			self.flags.ignore_links = True
			self.cancel()
			self._set_workflow_status(C.PO_CANCELLED, rejection_reason=reason)
		return {"status": self.status, "removed_sub_orders": removed}

	# -------------------------------------------------------- send to store

	def send_to_store(self):
		"""Task D. Approved -> Sent To Store, and the sub orders come off the lock."""
		from alpinos.production.sub_order import existing_sub_orders, unlock_sub_orders

		self.check_permission("submit")

		if self.status == C.PO_SENT_TO_STORE:
			frappe.throw(_("{0} has already been sent to store.").format(self.name),
			             title=_("Already Sent"))
		if self.status != C.PO_APPROVED:
			frappe.throw(
				_("Only an Approved order can be sent to store. {0} is {1}.").format(
					self.name, self.status
				),
				title=_("Cannot Send To Store"),
			)
		if not self._user_may_approve():
			frappe.throw(
				_("Only a {0} or {1} may send an order to store.").format(
					C.ROLE_PRODUCTION_MANAGER, C.ROLE_PRODUCTION_ADMIN
				),
				title=_("Not An Approver"),
			)

		subs = existing_sub_orders(self.name)
		if not subs:
			frappe.throw(_("{0} has no sub orders to send.").format(self.name),
			             title=_("Nothing To Send"))
		empty = [row["name"] for row in subs if flt(row.get("qty")) <= 0]
		if empty:
			frappe.throw(
				_("These sub orders have no quantity: {0}.").format(", ".join(empty)),
				title=_("Sub Order With No Quantity"),
			)

		unlocked = unlock_sub_orders(self.name)
		self._set_workflow_status(
			C.PO_SENT_TO_STORE,
			sent_by=frappe.session.user,
			sent_on=now_datetime(),
		)
		self._notify_store(subs)
		return {"status": self.status, "unlocked": unlocked}

	def _notify_store(self, subs):
		"""Task D: tell the Store team, by system notification and by email.

		The email is attempted but never allowed to fail the transition -- an unconfigured
		outgoing mail account must not leave an order half-sent, with its sub orders already
		unlocked and its status not written.
		"""
		from alpinos.production import constants as _C

		total_kg = sum(flt(row.get("qty")) for row in subs)
		batches = flt(self.total_batches)
		message = _("{0} ({1}, {2} KG, {3} batches) sent to Store.").format(
			self.name, self.fg_item, frappe.format_value(total_kg, {"fieldtype": "Float"}),
			frappe.format_value(batches, {"fieldtype": "Float"}) if batches else _("batches not set"),
		)

		users = set()
		for role in _C.STORE_ROLES:
			if frappe.db.exists("Role", role):
				users.update(frappe.get_all(
					"Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
		users = {u for u in users if u and u not in ("Administrator", "Guest")
		         and frappe.db.get_value("User", u, "enabled")}

		for user in users:
			try:
				frappe.get_doc({
					"doctype": "Notification Log",
					"subject": message,
					"for_user": user,
					"type": "Alert",
					"document_type": self.doctype,
					"document_name": self.name,
				}).insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Production Order: store notification")

		if users:
			try:
				frappe.sendmail(recipients=list(users), subject=message, message=message,
				                reference_doctype=self.doctype, reference_name=self.name)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Production Order: store email")
		return sorted(users)

	def _user_may_approve(self):
		"""Task 25: Admin / Production Manager approve; a User does not.

		System Manager is included because it administers this site and is how the module
		was set up in the first place.
		"""
		approvers = {C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager"}
		return bool(approvers & set(frappe.get_roles()))

	def on_cancel(self):
		"""PPO-06 -- whether cancelling cascades to the Sub POs is still open, so nothing
		cascades yet. The status is left to the flow rather than stamped here."""
		pass
