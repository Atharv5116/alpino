import frappe
from frappe import _
from erpnext.stock.doctype.pick_list.pick_list import PickList


class CustomPickList(PickList):
	#: Fields the Alpinos flow deliberately edits on a SUBMITTED pick list -- the
	#: transporter, dispatch date and assignment paperwork (after_submit_sync
	#: _AFTER_SUBMIT_EDITABLE), plus the two markers that ride along with them.
	#: `group_same_items` is deliberately NOT here: it re-groups the picked rows, so it
	#: keeps ERPNext's guard.
	AFTER_SUBMIT_SAFE_FIELDS = frozenset(
		{
			"custom_dispatch_date",
			"custom_transporter",
			"custom_assigned_to",
			"custom_changed_after_submit",
			"custom_workflow_status",
		}
	)

	#: Row values that describe what was actually picked. If any of these moved, the
	#: edit is a stock edit whatever else changed with it.
	_STOCK_ROW_FIELDS = (
		"item_code",
		"warehouse",
		"qty",
		"picked_qty",
		"stock_qty",
		"batch_no",
		"serial_no",
		"sales_order",
		"sales_order_item",
	)

	def on_update_after_submit(self):
		"""ERPNext refuses ANY after-submit save once a Pick List has reserved stock.

		The Alpinos flow reserves the SO quantity *from Pick Lists* on creation
		(stock_reservation.py rule 1, the same reason validate_sales_order is overridden
		below), so that guard fires on every pick list we raise -- including for an edit
		that cannot touch the reservation at all, like correcting the dispatch date or
		the transporter from the Pick List Entry screen. The result was that the
		paperwork could never be corrected after dispatch was arranged.

		So the guard is kept for anything that moves stock, and skipped when the change
		is confined to fields Frappe itself marks allow_on_submit and no picked row
		moved. Those two facts together mean there is nothing for the reservation guard
		to protect.
		"""
		if self._only_paperwork_changed():
			return
		super().on_update_after_submit()

	def _only_paperwork_changed(self):
		before = self.get_doc_before_save()
		if not before:
			# No baseline to compare (a programmatic save): let ERPNext decide.
			return False

		old_rows = before.get("locations") or []
		new_rows = self.get("locations") or []
		if len(old_rows) != len(new_rows):
			return False
		for old, new in zip(old_rows, new_rows):
			for fieldname in self._STOCK_ROW_FIELDS:
				if str(old.get(fieldname) or "") != str(new.get(fieldname) or ""):
					return False

		changed = {
			df.fieldname
			for df in self.meta.fields
			if df.fieldtype not in ("Table", "Table MultiSelect")
			and str(before.get(df.fieldname) or "") != str(self.get(df.fieldname) or "")
		}
		return changed <= self.AFTER_SUBMIT_SAFE_FIELDS

	def validate_sales_order(self):
		"""ERPNext blocks submitting a Pick List when its Sales Order has reserved
		stock. In the Alpinos flow we deliberately reserve the SO qty *from Pick
		Lists* on creation (stock_reservation.py rule 1), so any Pick-List-sourced
		reservation must not block a PL — including earlier rounds' reservations on
		a partial order. We keep ERPNext's block for reservations made directly on
		the Sales Order (user-made)."""
		if self.purpose != "Delivery":
			return

		so_list = {loc.sales_order for loc in self.locations if loc.sales_order}
		for so in so_list:
			total = frappe.db.count(
				"Stock Reservation Entry",
				{"voucher_type": "Sales Order", "voucher_no": so, "docstatus": 1},
			)
			from_pick_lists = frappe.db.count(
				"Stock Reservation Entry",
				{
					"voucher_type": "Sales Order",
					"voucher_no": so,
					"docstatus": 1,
					"from_voucher_type": "Pick List",
				},
			)
			# Any reservation not sourced from a Pick List -> keep the block.
			if total > from_pick_lists:
				frappe.throw(
					_(
						"Cannot create a pick list for Sales Order {0} because it has reserved stock. Please unreserve the stock in order to create a pick list."
					).format(frappe.bold(so))
				)
