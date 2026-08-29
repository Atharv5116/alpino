"""Customer naming: ID carries "business - GST/PAN", display name is the plain business name."""

import frappe


def execute():
	buyers = frappe.get_all(
		"Buyer Master",
		filters={"customer": ["is", "set"]},
		fields=["name", "customer", "customer_business_name", "gst_no", "pan_no"],
	)
	renamed = fixed = 0
	for b in buyers:
		biz = (b.customer_business_name or "").strip()
		tax = (b.gst_no or b.pan_no or "").strip()
		if not biz or not frappe.db.exists("Customer", b.customer):
			continue
		try:
			# Rename first: after_rename resets customer_name to the docname
			cust_id = b.customer
			target = f"{biz} - {tax}" if tax else biz
			if cust_id != target and not frappe.db.exists("Customer", target):
				frappe.rename_doc("Customer", cust_id, target, force=True)
				cust_id = target
				renamed += 1
			if frappe.db.get_value("Customer", cust_id, "customer_name") != biz:
				frappe.db.set_value("Customer", cust_id, "customer_name", biz, update_modified=False)
				fixed += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"plain customer name backfill failed: {b.customer}")

	# Denormalized display copies used by the entry pages and stickers.
	frappe.db.sql(
		"""UPDATE `tabSales Order` so JOIN `tabCustomer` c ON c.name = so.customer
		   SET so.customer_name = c.customer_name"""
	)
	frappe.db.sql(
		"""UPDATE `tabPick List` pl JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id
		   SET pl.custom_customer_name = so.customer_name"""
	)
	frappe.db.sql(
		"""UPDATE `tabDelivery Note` dn JOIN `tabSales Order` so ON so.name = dn.custom_sales_order_id
		   SET dn.custom_dn_so_customer_name = so.customer_name"""
	)
	frappe.db.commit()
	if fixed or renamed:
		print(f"customers: {fixed} names cleaned, {renamed} IDs renamed to name-GST")
