"""after_migrate setup for Inventory / Dispatch / Reports (registered by Groundwork as
alpinos.production.inventory_setup.setup_inventory). Additive and idempotent:

1. Stock Entry custom field custom_inventory_reference (which Production Transfer /
   Inventory Adjustment posted the entry).
2. Stock Entry.custom_entry_kind options: APPENDS "Production Transfer" and "Inventory
   Adjustment" through a property setter, keeping every option already there (the Custom
   Field itself, owned by material_fields, is not edited).
3. Page roles for this module's pages (only ever adds roles).
4. Print Format "Production Summary" (end-of-day, rendered from the report data by
   production_reports.production_summary_html). Kept disabled so it never shows in a
   document's print menu; the template stays editable in the desk.
5. One index for the heavy reports (12.4).
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from alpinos.production import inventory_common as IC

SUMMARY_PF_NAME = "Production Summary"
SUMMARY_PF_DOCTYPE = "Production Order"

INVENTORY_PAGES = ("production_inventory", "production_transfer_list", "production_transfer_entry",
                   "inventory_adjustment_list", "inventory_adjustment_entry")
DISPATCH_PAGES = ("dispatch_tracking",)
REPORT_PAGES = ("production_reports",)


def setup_inventory():
	for step in (_stock_entry_fields, _entry_kind_options, _page_roles, _print_format, _indexes):
		try:
			step()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Inventory setup: {step.__name__}")
	frappe.db.commit()


def _stock_entry_fields():
	insert_after = "custom_return_reason_all" if IC.has_field("Stock Entry", "custom_return_reason_all") \
		else "stock_entry_type"
	create_custom_fields({
		"Stock Entry": [{
			"fieldname": IC.REFERENCE_FIELD,
			"label": "Inventory Reference",
			"fieldtype": "Data",
			"insert_after": insert_after,
			"read_only": 1,
			"no_copy": 1,
			"description": "The Production Transfer / Inventory Adjustment that posted this entry.",
		}],
	}, update=True)


def _entry_kind_options():
	meta = frappe.get_meta("Stock Entry")
	df = meta.get_field("custom_entry_kind")
	if not df:
		return
	options = (df.options or "").split("\n")
	missing = [k for k in IC.OWN_KINDS if k not in options]
	if not missing:
		return
	while len(options) > 1 and not options[-1].strip():
		options.pop()
	make_property_setter("Stock Entry", "custom_entry_kind", "options", "\n".join(options + missing),
	                     "Text", validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Stock Entry")


def _add_roles(pages, roles):
	for page in pages:
		if not frappe.db.exists("Page", page):
			continue
		doc = frappe.get_doc("Page", page)
		have = {row.role for row in doc.roles}
		missing = sorted(r for r in set(roles) - have if frappe.db.exists("Role", r))
		if not missing:
			continue
		for role in missing:
			doc.append("roles", {"role": role})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)


def _page_roles():
	_add_roles(INVENTORY_PAGES, IC.INVENTORY_READ_ROLES)
	_add_roles(DISPATCH_PAGES, IC.DISPATCH_READ_ROLES)
	_add_roles(REPORT_PAGES, IC.REPORT_ROLES)


def _indexes():
	frappe.db.add_index("Stock Entry", ["purpose", "posting_date"], "alp_se_purpose_date")


SUMMARY_HTML = """
<style>
	.ps-title { text-align: center; font-size: 15pt; font-weight: 700; margin: 0 0 2px; }
	.ps-sub { text-align: center; font-size: 8.5pt; color: #555; margin: 0 0 10px; }
	table.ps { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
	table.ps th, table.ps td { border: 1px solid #000; padding: 3px 5px; font-size: 8.5pt; }
	table.ps th { background: #eee; text-align: left; }
	table.ps td.n, table.ps th.n { text-align: right; white-space: nowrap; }
	table.ps tr.tot td { font-weight: 700; background: #f6f6f6; }
	.ps-sign { margin-top: 24px; width: 100%; }
	.ps-sign td { height: 46px; vertical-align: bottom; font-size: 8pt; width: 33%; }
</style>
<div class="ps-title">PRODUCTION SUMMARY</div>
<div class="ps-sub">{{ company or "" }} &middot; {{ frappe.format(from_date, {"fieldtype": "Date"}) }}
	{% if from_date != to_date %} to {{ frappe.format(to_date, {"fieldtype": "Date"}) }}{% endif %}
	{% if shift %} &middot; Shift: {{ shift }}{% endif %}</div>
<table class="ps">
	<thead><tr>
		<th>Date</th><th>Shift</th><th class="n">RM Consumed (KG)</th><th class="n">Baked Output (KG)</th>
		<th class="n">FG Produced (Pcs)</th><th class="n">FG Produced (KG)</th>
		<th class="n">Factory Yield %</th><th class="n">Downtime (Min)</th><th class="n">Wastage (KG)</th>
	</tr></thead>
	<tbody>
	{% for r in rows %}
		<tr>
			<td>{{ frappe.format(r.date, {"fieldtype": "Date"}) }}</td><td>{{ r.shift or "-" }}</td>
			<td class="n">{{ "%.3f"|format(r.rm_kg or 0) }}</td><td class="n">{{ "%.3f"|format(r.baked_kg or 0) }}</td>
			<td class="n">{{ "%.0f"|format(r.fg_pcs or 0) }}</td><td class="n">{{ "%.3f"|format(r.fg_kg or 0) }}</td>
			<td class="n">{{ ("%.2f"|format(r.yield_pct)) if r.yield_pct is not none else "-" }}</td>
			<td class="n">{{ "%.0f"|format(r.downtime_min or 0) }}</td><td class="n">{{ "%.3f"|format(r.wastage_kg or 0) }}</td>
		</tr>
	{% else %}
		<tr><td colspan="9" style="text-align:center;">No production recorded for this period.</td></tr>
	{% endfor %}
		<tr class="tot">
			<td colspan="2">Total</td>
			<td class="n">{{ "%.3f"|format(totals.rm_kg or 0) }}</td><td class="n">{{ "%.3f"|format(totals.baked_kg or 0) }}</td>
			<td class="n">{{ "%.0f"|format(totals.fg_pcs or 0) }}</td><td class="n">{{ "%.3f"|format(totals.fg_kg or 0) }}</td>
			<td class="n">{{ ("%.2f"|format(totals.yield_pct)) if totals.yield_pct is not none else "-" }}</td>
			<td class="n">{{ "%.0f"|format(totals.downtime_min or 0) }}</td><td class="n">{{ "%.3f"|format(totals.wastage_kg or 0) }}</td>
		</tr>
	</tbody>
</table>
<div style="font-size:8pt;color:#555;">Printed by {{ printed_by }} on {{ frappe.format(printed_on, {"fieldtype": "Datetime"}) }}.
Yield = FG produced (KG) / RM + Additive consumed (KG).</div>
<table class="ps-sign"><tr>
	<td>Production Supervisor</td><td>Production Manager</td><td>Plant Head</td>
</tr></table>
"""


def summary_template():
	return SUMMARY_HTML


def _print_format():
	if not frappe.db.exists("DocType", SUMMARY_PF_DOCTYPE):
		return
	fields = {"doc_type": SUMMARY_PF_DOCTYPE, "print_format_type": "Jinja", "custom_format": 1,
	          "standard": "No", "disabled": 1, "module": "Alpinos Development"}
	if frappe.db.exists("Print Format", SUMMARY_PF_NAME):
		# Never overwrite a template someone has edited in the desk; only fill a blank one.
		pf = frappe.get_doc("Print Format", SUMMARY_PF_NAME)
		if not (pf.html or "").strip():
			pf.html = SUMMARY_HTML
			pf.flags.ignore_permissions = True
			pf.save(ignore_permissions=True)
		return
	pf = frappe.new_doc("Print Format")
	pf.name = SUMMARY_PF_NAME
	pf.update(fields)
	pf.html = SUMMARY_HTML
	pf.flags.ignore_permissions = True
	pf.insert(ignore_permissions=True)
