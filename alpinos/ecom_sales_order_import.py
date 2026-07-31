"""
E-Commerce Sales Order — Excel/CSV bulk import.

One row per SKU line; order-level columns (customer, PO, dates, flags, addresses)
repeat on each line and rows are grouped into one order by PO Number + Customer.

Import routes every group through the real create_ecom_sales_order API, so channel
= E-com, the buyer flags, Margin% -> Selling Price, PO-uniqueness / GSTIN / margin
validations and the buyer-catalogue write-back all apply exactly as the entry page.
Each order commits on its own; a failed order is rolled back and reported without
blocking the rest.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from alpinos.ecom_sales_order_api import create_ecom_sales_order
from alpinos.sales_order_offline_buyer import get_offline_buyer_for_customer

# Column order for the template (header row). Keep labels stable — the importer
# matches on these (case-insensitive, trimmed).
COLUMNS = [
	"Customer", "Customer Type", "PO Number", "PO Date", "PO Expiry Date",
	"Dispatch Date", "Delivery By Date", "Site Name",
	"Billing Address", "Billing GSTIN", "Shipping Address", "Shipping GSTIN",
	"Appointment Required", "GRN Available", "Partial Order Allowed", "GST-Exclusive Buyer",
	"Freebies (Entire PO Free)",
	"SKU", "Qty", "MRP", "Margin %",
]

_EXAMPLE = [
	"EXAMPLE — delete this row", "", "PO-1001", "2026-07-14", "",
	"2026-07-16", "", "Surat Store",
	"12 Ring Road, Surat", "24AAACC1206D1ZM", "12 Ring Road, Surat", "24AAACC1206D1ZM",
	"Yes", "Yes", "Yes", "No",
	"No",
	"ITEM-001", 30, 100, 10,
]


# ---------------------------------------------------------------------------
# Template download
# ---------------------------------------------------------------------------
@frappe.whitelist()
def download_ecom_import_template():
	"""Stream an .xlsx template (header row + one example row) for download."""
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	from frappe.utils.xlsxutils import make_xlsx

	xlsx = make_xlsx([COLUMNS, _EXAMPLE], "E-Com SO Import")
	frappe.response["filename"] = "ecom_sales_order_import_template.xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
@frappe.whitelist()
def import_ecom_sales_orders(file_url):
	"""Read an uploaded Excel/CSV and create one E-Com Sales Order per PO group.
	Returns {created: [...], errors: [...], total_orders: n}."""
	if not frappe.has_permission("Sales Order", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	rows = _read_uploaded_rows(file_url)
	return _orders_from_rows(rows)


def _read_uploaded_rows(file_url):
	"""Return the sheet as a list of header-keyed dicts (blank/example rows dropped)."""
	if not file_url:
		frappe.throw(_("No file provided."))
	if file_url.lower().endswith(".csv"):
		from frappe.utils.file_manager import get_file
		from frappe.utils.csvutils import read_csv_content

		_, content = get_file(file_url)
		table = read_csv_content(content)
	else:
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

		table = read_xlsx_file_from_attached_file(file_url=file_url)

	table = [r for r in (table or []) if any((c not in (None, "")) for c in r)]
	if len(table) < 2:
		frappe.throw(_("The file has no data rows."))

	header = [str(h or "").strip() for h in table[0]]
	rows = []
	for raw in table[1:]:
		row = {header[i]: raw[i] for i in range(min(len(header), len(raw)))}
		rows.append(row)
	return rows


def _get(row, label, default=""):
	"""Case-insensitive column read."""
	for k, v in row.items():
		if (k or "").strip().lower() == label.lower():
			return v if v is not None else default
	return default


def _yn(val, default=0):
	if val in (None, ""):
		return cint(default)
	return 1 if str(val).strip().lower() in ("yes", "y", "1", "true", "x", "t") else 0


def _date(val):
	if val in (None, ""):
		return None
	try:
		return str(getdate(val))
	except Exception:
		return None


def _resolve_customer(val):
	val = (str(val) if val is not None else "").strip()
	if not val:
		return None
	if frappe.db.exists("Customer", val):
		return val
	c = frappe.db.get_value("Customer", {"customer_name": val}, "name")
	if c:
		return c
	return frappe.db.get_value("Buyer Master", {"customer_business_name": val}, "customer")


def _orders_from_rows(rows):
	"""Group rows by (customer, PO Number) and create one SO per group.
	Extracted from the file-read layer so it can be unit-tested with plain dicts."""
	# Preserve first-seen order of groups.
	groups = {}
	order_keys = []
	for row in rows:
		cust_label = str(_get(row, "Customer") or "").strip()
		sku = str(_get(row, "SKU") or "").strip()
		# Skip the example row and any line with no customer/SKU.
		if not cust_label or not sku or cust_label.lower().startswith("example"):
			continue
		key = (cust_label, str(_get(row, "PO Number") or "").strip())
		if key not in groups:
			groups[key] = []
			order_keys.append(key)
		groups[key].append(row)

	results = {"created": [], "errors": [], "total_orders": len(order_keys)}
	for key in order_keys:
		cust_label, po_number = key
		grp = groups[key]
		try:
			results["created"].append(_create_one_order(cust_label, po_number, grp))
		except Exception as e:
			frappe.db.rollback()
			results["errors"].append({"po_number": po_number, "customer": cust_label, "error": str(e)})
	return results


def _create_one_order(cust_label, po_number, grp):
	first = grp[0]
	customer = _resolve_customer(cust_label)
	if not customer:
		frappe.throw(_("Customer '{0}' not found (needs a Buyer Master).").format(cust_label))

	buyer = get_offline_buyer_for_customer(customer) or {}
	order_type = str(_get(first, "Customer Type") or "").strip() or buyer.get("customer_type")
	is_freebie = _yn(_get(first, "Freebies (Entire PO Free)"), 0)

	flags = {
		"appointment_required": _yn(_get(first, "Appointment Required"), buyer.get("appointment_required")),
		"grn_available": _yn(_get(first, "GRN Available"), buyer.get("grn_available")),
		"partial_order_allowed": _yn(_get(first, "Partial Order Allowed"), buyer.get("partial_order_allowed")),
		"gst_exclusive_buyer": _yn(_get(first, "GST-Exclusive Buyer"), buyer.get("gst_exclusive_buyer")),
	}

	items = []
	for row in grp:
		sku = str(_get(row, "SKU") or "").strip()
		qty = flt(_get(row, "Qty"))
		if not sku or qty <= 0:
			continue
		mrp = 0.0 if is_freebie else flt(_get(row, "MRP"))
		margin = 0.0 if is_freebie else flt(_get(row, "Margin %"))
		items.append({
			"item_code": sku,
			"qty": qty,
			"custom_customer_mrp": mrp,
			"custom_selling_price": flt(mrp * (1 - margin / 100.0), 2),
			"margin_percent": margin,
			"custom_gst_percent": flt(frappe.db.get_value("Item", sku, "custom_gst_percent")),
		})
	if not items:
		frappe.throw(_("No valid SKU lines."))

	out = create_ecom_sales_order(
		customer=customer,
		order_type=order_type,
		company="",
		items=frappe.as_json(items),
		flags=frappe.as_json(flags),
		po_number=po_number,
		po_date=_date(_get(first, "PO Date")),
		po_expiry_date=_date(_get(first, "PO Expiry Date")),
		delivery_by_date=_date(_get(first, "Delivery By Date")),
		dispatch_date=_date(_get(first, "Dispatch Date")),
		billing_gstin=str(_get(first, "Billing GSTIN") or "").strip(),
		shipping_gstin=str(_get(first, "Shipping GSTIN") or "").strip(),
		billing_address=str(_get(first, "Billing Address") or "").strip(),
		shipping_address=str(_get(first, "Shipping Address") or "").strip(),
		site_name=str(_get(first, "Site Name") or "").strip(),
		is_freebie_po=is_freebie,
		submit_now=1,
	)
	return {"po_number": po_number, "customer": customer, "sales_order": out["name"]}
