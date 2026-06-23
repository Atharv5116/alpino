import frappe
from frappe import _
from erpnext.stock.doctype.pick_list.pick_list import PickList


class CustomPickList(PickList):
	def validate_sales_order(self):
		"""ERPNext blocks submitting a Pick List when its Sales Order has reserved
		stock. In the Alpinos flow we deliberately reserve the SO qty *from this
		Pick List* on creation, so that reservation must not block the PL. We keep
		ERPNext's block for any reservation that came from another source."""
		if self.purpose != "Delivery":
			return

		so_list = {loc.sales_order for loc in self.locations if loc.sales_order}
		for so in so_list:
			total = frappe.db.count(
				"Stock Reservation Entry",
				{"voucher_type": "Sales Order", "voucher_no": so, "docstatus": 1},
			)
			from_this_pl = frappe.db.count(
				"Stock Reservation Entry",
				{
					"voucher_type": "Sales Order",
					"voucher_no": so,
					"docstatus": 1,
					"from_voucher_type": "Pick List",
					"from_voucher_no": self.name,
				},
			)
			# Any reservation not sourced from this Pick List -> keep the block.
			if total > from_this_pl:
				frappe.throw(
					_(
						"Cannot create a pick list for Sales Order {0} because it has reserved stock. Please unreserve the stock in order to create a pick list."
					).format(frappe.bold(so))
				)
