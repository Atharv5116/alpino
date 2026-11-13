"""Changes(HP) #107: the Daily Report (template: Aug-26_Daily_Report.xlsx).

One block per Customer Type (one worksheet each in the export, named by its abbreviation:
NT, GT, MT, RL, AM, FK, BK, SW, ZE, ...). In a block:

    rows 1-11   one column per dispatch: Actual Box, Sample Box, Sample Weight, Total Box,
                Gross Weight, Total Units, PO No., Transporter, Party Name, Date, Party Code
                (all from the Pick List)
    SKU rows    Finished Goods in Item sequence, in their Item colour, the quantity each
                dispatch carried, and a TOTAL across
    freebies    Marketing Material in its own section below a divider, only when "Include
                Marketing Freebies" is ticked (the Dispatch Report's switch)

Which dispatches: a submitted Pick List of a submitted Sales Order whose invoice PDF is
fetched and linked, with its Dispatch Date in the range. Each submitted Pick List of an
order is its own column (Part 1, Part 2). An order whose Pick List was cancelled (the order
itself not cancelled) keeps that column, in red, until a new Pick List is submitted for it;
then the new one replaces it.

Customer Type filter: a parent type shows itself and all its child types; a child type only
itself; blank shows every type.
"""

import io

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate, today

from alpinos.company_scope.helpers import company_sql

HEADER_ROWS = (
	("actual_box", "ACTUAL BOX", "custom_actual_box"),
	("sample_box", "SAMPLE BOX", "custom_sample_box"),
	("sample_weight", "SAMPLE WEIGHT", "custom_sample_weight"),
	("total_box", "TOTAL BOX", "custom_total_box"),
	("gross_weight", "GROSS WEIGHT", "custom_gross_weight"),
	("total_units", "TOTAL UNITS", "custom_total_unit"),
	("po_no", "PO NO.", "custom_po_no"),
	("transporter", "TRANSPORTER", "custom_transporter"),
	("party_name", "PARTY NAME", "custom_customer_name"),
	("date", "DATE", "custom_dispatch_date"),
	("party_code", "PARTY CODE", "custom_party_code"),
)
NUMERIC_HEADERS = {"actual_box", "sample_box", "sample_weight", "total_box", "gross_weight", "total_units"}


def _types(customer_type):
	rows = frappe.get_all(
		"Alpino Customer Type",
		fields=["name", "abbreviation", "parent_customer_type", "sequence"],
		order_by="sequence asc, name asc",
	)
	if not customer_type:
		return rows
	return [r for r in rows if r.name == customer_type or r.parent_customer_type == customer_type]


def _dispatches(from_date, to_date, type_names):
	"""Pick List columns: (pick list, order, type, cancelled), oldest dispatch first."""
	if not type_names:
		return []
	return frappe.db.sql(
		"""
		SELECT pl.name AS pick_list, pl.docstatus, so.name AS sales_order, so.order_type AS customer_type,
			pl.custom_actual_box, pl.custom_sample_box, pl.custom_sample_weight, pl.custom_total_box,
			pl.custom_gross_weight, pl.custom_total_unit, COALESCE(NULLIF(pl.custom_po_no, ''), so.po_no) AS custom_po_no,
			pl.custom_transporter, COALESCE(NULLIF(pl.custom_customer_name, ''), so.customer_name) AS custom_customer_name,
			pl.custom_dispatch_date, pl.custom_party_code
		FROM `tabPick List` pl
		INNER JOIN `tabSales Order` so ON so.name = pl.custom_sales_order_id
		WHERE so.docstatus = 1
			AND IFNULL(so.custom_invoice_no, '') <> '' AND IFNULL(so.custom_invoice_pdf, '') <> ''
			AND so.order_type IN %(types)s
			AND pl.custom_dispatch_date BETWEEN %(from)s AND %(to)s
			AND (
				pl.docstatus = 1
				OR (pl.docstatus = 2 AND NOT EXISTS (
					SELECT 1 FROM `tabPick List` p2
					WHERE p2.custom_sales_order_id = so.name AND p2.docstatus = 1))
			)
		""" + company_sql("Sales Order", "so") + """
		ORDER BY pl.custom_dispatch_date ASC, so.name ASC, pl.creation ASC
		""",
		{"types": tuple(type_names), "from": getdate(from_date), "to": getdate(to_date)},
		as_dict=True,
	)


def _quantities(pick_lists):
	"""{pick list: {item: qty}} from the Pick List rows."""
	out = {}
	if not pick_lists:
		return out
	for r in frappe.db.sql(
		"""
		SELECT parent, item_code, SUM(qty) AS qty FROM `tabPick List Item`
		WHERE parent IN %(pls)s GROUP BY parent, item_code
		""",
		{"pls": tuple(pick_lists)},
		as_dict=True,
	):
		out.setdefault(r.parent, {})[r.item_code] = flt(r.qty)
	return out


@frappe.whitelist()
def get_daily_report(from_date=None, to_date=None, customer_type=None, include_marketing_material=0):
	# company-scope: n/a (company_sql is applied to the orders inside _dispatches)
	if not frappe.has_permission("Pick List", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	from alpinos.dispatch_report_api import _get_sequenced_items, _marketing_material_items

	from_date = from_date or today()
	to_date = to_date or from_date
	include_mm = cint(include_marketing_material)
	types = _types(customer_type)
	dispatches = _dispatches(from_date, to_date, [t.name for t in types])
	qty = _quantities([d.pick_list for d in dispatches])
	mm = _marketing_material_items()
	seq = _get_sequenced_items()
	sku_no = dict(frappe.get_all("Item", filters={"custom_sku_no": ("is", "set")}, fields=["name", "custom_sku_no"], as_list=True))
	known = {i.item_code for i in seq}

	blocks = []
	for t in types:
		cols = [d for d in dispatches if d.customer_type == t.name]
		if not cols:
			continue
		moved = set()
		for d in cols:
			moved |= set(qty.get(d.pick_list, {}))
		order = [i for i in seq if i.item_code in moved] + [
			frappe._dict(item_code=ic, item_name=ic, color="", sequence=0) for ic in sorted(moved - known)
		]

		def row(item):
			values = [flt(qty.get(d.pick_list, {}).get(item.item_code)) for d in cols]
			return {
				"item_code": item.item_code,
				"sku_no": sku_no.get(item.item_code) or "",
				"color": item.get("color") or "",
				"values": values,
				"total": flt(sum(values), 3),
			}

		items = [row(i) for i in order if i.item_code not in mm]
		freebies = [row(i) for i in order if i.item_code in mm] if include_mm else []
		columns = []
		for d in cols:
			header = {}
			for key, _label, field in HEADER_ROWS:
				value = d.get(field)
				if key == "date":
					value = formatdate(value, "dd-MM-yyyy") if value else ""
				header[key] = flt(value) if key in NUMERIC_HEADERS else (value or "")
			columns.append(
				{"pick_list": d.pick_list, "sales_order": d.sales_order, "cancelled": cint(d.docstatus) == 2, "header": header}
			)
		totals = {key: flt(sum(c["header"][key] for c in columns), 3) for key in NUMERIC_HEADERS}
		blocks.append(
			{
				"customer_type": t.name,
				"abbreviation": t.abbreviation or t.name[:12],
				"columns": columns,
				"totals": totals,
				"items": items,
				"freebies": freebies,
			}
		)
	return {
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"headers": [{"key": k, "label": l} for k, l, _f in HEADER_ROWS],
		"blocks": blocks,
	}


# ------------------------------------------------------------------------------- export

_BLUE = "FF4472C4"
_YELLOW = "FFFFFF00"
_RED = "FFFFC7CE"


@frappe.whitelist()
def export_daily_report(from_date=None, to_date=None, customer_type=None, include_marketing_material=0):
	"""The report as the template workbook: one sheet per Customer Type, same layout and colours."""
	# company-scope: n/a (the data comes from get_daily_report, which applies the company)
	from openpyxl import Workbook
	from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
	from openpyxl.utils import get_column_letter

	data = get_daily_report(from_date, to_date, customer_type, include_marketing_material)
	wb = Workbook()
	wb.remove(wb.active)
	thin = Side(style="thin", color="FFBFBFBF")
	border = Border(left=thin, right=thin, top=thin, bottom=thin)
	bold = Font(bold=True)

	def fill(rgb):
		return PatternFill("solid", fgColor=rgb)

	def hex_font(color, bold_=False):
		color = (color or "").lstrip("#").upper()
		return Font(color=("FF" + color) if len(color) == 6 else None, bold=bold_)

	if not data["blocks"]:
		ws = wb.create_sheet("Daily Report")
		ws["A1"] = _("No dispatches with a fetched invoice in this range.")
	for block in data["blocks"]:
		ws = wb.create_sheet((block["abbreviation"] or "Sheet")[:31])
		n = len(block["columns"])
		first, last = 5, 4 + n
		last_col = get_column_letter(last)
		# header rows 1-11
		for r, (key, label, _f) in enumerate(HEADER_ROWS, start=1):
			ws.cell(r, 4, label).font = bold
			if key in NUMERIC_HEADERS:
				ws.cell(r, 2, f"=SUM(E{r}:{last_col}{r})").font = bold
			for i, col in enumerate(block["columns"]):
				c = ws.cell(r, first + i, col["header"][key] if col["header"][key] != "" else None)
				c.border = border
				c.alignment = Alignment(horizontal="center")
				if col["cancelled"]:
					c.fill = fill(_RED)
					c.font = Font(color="FFC00000", bold=True)
			if key in ("total_box", "gross_weight", "total_units"):
				for cc in range(4, last + 1):
					ws.cell(r, cc).fill = fill(_BLUE)
					ws.cell(r, cc).font = Font(color="FFFFFFFF", bold=True)
			if key == "date":
				for cc in range(4, last + 1):
					ws.cell(r, cc).fill = fill(_YELLOW)
		ws.cell(10, 1, "SKU NO.").font = bold
		ws.cell(10, 2, "TOTAL").font = bold
		row = len(HEADER_ROWS) + 1
		start_items = row
		for item in block["items"]:
			ws.cell(row, 1, item["sku_no"] or None)
			ws.cell(row, 2, f"=SUM(E{row}:{last_col}{row})")
			ws.cell(row, 4, item["item_code"]).font = hex_font(item["color"])
			for i, v in enumerate(item["values"]):
				c = ws.cell(row, first + i, v or None)
				c.border = border
				if block["columns"][i]["cancelled"]:
					c.fill = fill(_RED)
			row += 1
		if block["freebies"]:
			row += 1  # the divider the template keeps between the two sections
			for cc in range(1, last + 1):
				ws.cell(row - 1, cc).fill = fill("FFD9D9D9")
			ws.cell(row - 1, 4, "MARKETING FREEBIES").font = bold
			for item in block["freebies"]:
				ws.cell(row, 3, f"=SUM(E{row}:{last_col}{row})")
				ws.cell(row, 4, item["item_code"]).font = hex_font(item["color"], True)
				for i, v in enumerate(item["values"]):
					c = ws.cell(row, first + i, v or None)
					c.border = border
					if block["columns"][i]["cancelled"]:
						c.fill = fill(_RED)
				row += 1
		ws.cell(7, 2, f"=SUM(B{start_items}:B{max(start_items, start_items + len(block['items']) - 1)})")
		ws.freeze_panes = "E12"
		widths = {"A": 6, "B": 9, "C": 6, "D": 31}
		for letter, w in widths.items():
			ws.column_dimensions[letter].width = w
		for i in range(n):
			ws.column_dimensions[get_column_letter(first + i)].width = 16
	buf = io.BytesIO()
	wb.save(buf)
	frappe.response["filename"] = f"Daily_Report_{data['from_date']}_{data['to_date']}.xlsx"
	frappe.response["filecontent"] = buf.getvalue()
	frappe.response["type"] = "binary"
