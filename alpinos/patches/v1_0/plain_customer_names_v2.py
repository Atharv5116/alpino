"""Customer naming split, second pass.

v1 (plain_customer_names) only cleaned customers linked to a Buyer Master.
UAT still shows "Business - GST" display names — customers created before the
buyer link existed (or with a broken link) were missed. This pass:

1. Buyer-linked customers: customer_name -> plain business name, docname ->
   "business - GST/PAN" (same as v1; idempotent).
2. Any other customer whose customer_name ends with " - <its own tax_id>":
   strip the suffix from customer_name and move it into the docname instead.
3. Refresh the denormalized display copies on SO / PL / DN.

Safe to run on sites where v1 already ran (everything no-ops)."""

import frappe


def _clean(customer_id, plain_name, tax_id):
	"""name-tax docname + plain display name for one customer. Rename runs FIRST:
	ERPNext's Customer.after_rename resets customer_name to the new docname when
	naming is "By Customer Name", so the plain name must be written after it.
	Returns (fixed, renamed)."""
	fixed = renamed = 0
	target = f"{plain_name} - {tax_id}" if tax_id else plain_name
	if customer_id != target and not frappe.db.exists("Customer", target):
		frappe.rename_doc("Customer", customer_id, target, force=True)
		customer_id = target
		renamed = 1
	if frappe.db.get_value("Customer", customer_id, "customer_name") != plain_name:
		frappe.db.set_value("Customer", customer_id, "customer_name", plain_name, update_modified=False)
		fixed = 1
	return fixed, renamed


def execute():
	fixed = renamed = 0

	# Pass 1 — buyer-linked customers (canonical source: the Buyer Master).
	for b in frappe.get_all(
		"Buyer Master",
		filters={"customer": ["is", "set"]},
		fields=["name", "customer", "customer_business_name", "gst_no", "pan_no"],
	):
		biz = (b.customer_business_name or "").strip()
		tax = (b.gst_no or b.pan_no or "").strip()
		if not biz or not frappe.db.exists("Customer", b.customer):
			continue
		try:
			f, r = _clean(b.customer, biz, tax)
			fixed += f
			renamed += r
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"customer name cleanup failed: {b.customer}")

	# Pass 2 — every remaining customer carrying its own tax id in the name.
	for c in frappe.get_all(
		"Customer",
		filters={"tax_id": ["is", "set"]},
		fields=["name", "customer_name", "tax_id"],
	):
		tax = (c.tax_id or "").strip()
		suffix = f" - {tax}"
		if not tax or not (c.customer_name or "").endswith(suffix):
			continue
		plain = c.customer_name[: -len(suffix)].strip()
		if not plain:
			continue
		try:
			f, r = _clean(c.name, plain, tax)
			fixed += f
			renamed += r
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"customer name cleanup failed: {c.name}")

	# Pass 3 — refresh display copies used by the entry pages and stickers.
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
	print(f"customers v2: {fixed} names cleaned, {renamed} IDs renamed")
