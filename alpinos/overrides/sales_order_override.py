from erpnext.selling.doctype.sales_order.sales_order import SalesOrder


class CustomSalesOrder(SalesOrder):
	def validate_party_address(self, party, party_type, billing_address, shipping_address=None):
		"""Skip ERPNext's "Billing/Shipping Address does not belong to the {party}" check.

		Alpino manages buyer billing/shipping addresses through the Buyer Master and
		the Modern-Trade / e-com entry flow. An order's ``customer_address`` /
		``shipping_address_name`` is therefore often a Buyer Master / shared /
		imported Address that is NOT Dynamic-Link-ed to the Customer, which makes the
		base ``validate_party_address`` throw. The address is already validated
		against the Buyer Master in the entry flow, so this ownership check is
		intentionally a no-op here.

		Only the address check is dropped — contact ownership is still enforced by
		``validate_party_contact`` (called from ``validate_party_address_and_contact``).
		"""
		return
