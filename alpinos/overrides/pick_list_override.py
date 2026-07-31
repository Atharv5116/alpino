import frappe
from frappe import _
from erpnext.stock.doctype.pick_list.pick_list import PickList


class CustomPickList(PickList):
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
