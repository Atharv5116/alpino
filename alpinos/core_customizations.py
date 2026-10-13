"""Changes made to standard ERPNext doctypes by hand on a site, kept as customisations.

On UAT, Customer and Item were turned into trees by editing the DocType itself (developer
mode): fields lft, rgt, is_group, old_parent and parent_customer / parent_item, plus
is_tree. Buyer Master writes the buyer hierarchy into Customer.parent_customer (236
customers carry one on UAT). An ERPNext update replaces those DocType records with the
stock definition -- v16 did -- and the fields vanish from the form and the API while the
values sit unseen in the table.

This puts the same fields back as Custom Fields and is_tree as Property Setters, only on a
site whose table already has the parent column (so the tree existed there) and only when
the doctype no longer declares the field (so a site where the hand edit still stands, v15
UAT, is left exactly as it is). Runs after migrate; idempotent.
"""

import frappe

_TREES = {
	"Customer": ("parent_customer", "portal_users"),
	"Item": ("parent_item", "total_projected_qty"),
}


def _tree_fields(doctype, parent_field, insert_after):
	return [
		{"fieldname": "lft", "label": "Left", "fieldtype": "Int", "hidden": 1, "read_only": 1, "no_copy": 1, "insert_after": insert_after},
		{"fieldname": "rgt", "label": "Right", "fieldtype": "Int", "hidden": 1, "read_only": 1, "no_copy": 1, "insert_after": "lft"},
		{"fieldname": "is_group", "label": "Is Group", "fieldtype": "Check", "insert_after": "rgt"},
		{"fieldname": "old_parent", "label": "Old Parent", "fieldtype": "Link", "options": doctype, "insert_after": "is_group"},
		{"fieldname": parent_field, "label": f"Parent {doctype}", "fieldtype": "Link", "options": doctype, "ignore_user_permissions": 1, "insert_after": "old_parent"},
	]


def keep_hand_made_trees():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for doctype, (parent_field, insert_after) in _TREES.items():
		if not frappe.db.has_column(doctype, parent_field):
			continue  # this site never had the tree
		meta = frappe.get_meta(doctype)
		missing = [f for f in _tree_fields(doctype, parent_field, insert_after) if not meta.has_field(f["fieldname"])]
		if not missing:
			continue  # the hand edit (or an earlier run) still declares every field
		for df in missing:
			create_custom_field(doctype, df)
		make_property_setter(doctype, None, "is_tree", "1", "Check", for_doctype=True, validate_fields_for_doctype=False)
		make_property_setter(doctype, None, "nsm_parent_field", parent_field, "Data", for_doctype=True, validate_fields_for_doctype=False)
		frappe.clear_cache(doctype=doctype)
		print(f"{doctype}: tree fields kept as customisations ({', '.join(f['fieldname'] for f in missing)})")


_V15_CELL_RULE_MARK = "/* alpinos: v15 print cells */"
_V15_CELL_RULE = (
	_V15_CELL_RULE_MARK
	+ "\n.print-format td, .print-format th { vertical-align: top !important; padding: 6px !important; }"
	+ "\n/* alpinos: end */\n"
)


def keep_v15_print_cells():
	"""v16 only: the site's own print formats lay out as they did on v15.

	v15's standard print stylesheet forced every table cell to `vertical-align: top;
	padding: 6px` with !important, which silently overrode the padding and centring the
	alpinos print formats write inline. v16 dropped the !important, so those inline rules
	took effect: taller rows, a centred logo, and a Quotation that spilled onto a second
	page. v16's InterVariable font still wraps a few long lines at different words; pinning
	v15's family does not help, since v16's PDF renderer does not load that font. Appending the v15 rule to each custom format's CSS (which Frappe adds after
	everything else) brings back the layout the formats were designed and checked against.
	Runs last in after_migrate, after the steps that rebuild these formats; idempotent.
	"""
	from alpinos.query_compat import IS_V16

	if not IS_V16:
		return
	for name, css in frappe.get_all(
		"Print Format",
		filters={"standard": "No", "disabled": 0, "print_format_type": "Jinja"},
		fields=["name", "css"],
		as_list=True,
	):
		css = css or ""
		if _V15_CELL_RULE in css:
			continue
		if _V15_CELL_RULE_MARK in css:  # an older version of the block: replace it
			start = css.index(_V15_CELL_RULE_MARK)
			end_mark = css.find("/* alpinos: end */", start)
			end = css.find("\n", end_mark) + 1 if end_mark != -1 else css.find("}", start) + 1
			css = css[:start].rstrip("\n") + css[end:]
		frappe.db.set_value("Print Format", name, "css", css + "\n" + _V15_CELL_RULE, update_modified=False)


def keep_v15_hidden_empty_fields():
	"""v16 only: forms hide read-only fields that have no value, as they did on v15.

	Frappe 15 always hid them. Frappe 16 made it a System Setting, "Hide Empty Read-Only
	Fields", whose default (on) only reaches new sites: a migrated site has no stored value,
	reads it as off, and every form fills up with empty read-only fields (Reporting Person,
	onboarding and request fields...). Set it once, when it has never been set, so an
	administrator who turns it off later keeps that choice.
	"""
	from alpinos.query_compat import IS_V16

	if not IS_V16 or not frappe.get_meta("System Settings").has_field("hide_empty_read_only_fields"):
		return
	if frappe.db.sql(
		"select 1 from `tabSingles` where doctype = 'System Settings' and field = 'hide_empty_read_only_fields'"
	):
		return
	frappe.db.set_single_value("System Settings", "hide_empty_read_only_fields", 1)
	frappe.db.set_default("hide_empty_read_only_fields", "1")
	print("System Settings: Hide Empty Read-Only Fields on, as Frappe 15 behaved")


# Standard notifications that Frappe 15 shipped but never sent, and that Frappe 16 turned on.
_V15_SILENT_NOTIFICATIONS = (
	# ERPNext 15's recipient row used a key Notification no longer reads, so it had no recipient;
	# ERPNext 16 sends it to the creator of every Material Request that gets (partly) received.
	"Material Request Receipt Notification",
)


def keep_v15_silent_notifications():
	"""v16 only: keep standard notifications quiet that sent nothing on v15. Runs on every
	migrate, because ERPNext re-imports its standard notifications when their file changes."""
	from alpinos.query_compat import IS_V16

	if not IS_V16:
		return
	for name in _V15_SILENT_NOTIFICATIONS:
		if frappe.db.get_value("Notification", name, "enabled"):
			frappe.db.set_value("Notification", name, "enabled", 0, update_modified=False)
			print(f"Notification {name!r} disabled: it sent nothing on v15")


def keep_v15_optional_expense_payable():
	"""v16 only: an Expense Claim saves without a Payable Account, as on v15.

	HRMS 16 made payable_account mandatory unless the claim is paid (v15 never required it;
	every claim here has it empty, as they are settled through payroll), and the default it
	fills, the company's Payroll Payable, is not of account type Payable, so HRMS's own filter
	clears it again: no employee could save a claim. Clear the new mandatory rule; an
	accounts team that sets a Payable-type default account can still fill it.
	"""
	from alpinos.query_compat import IS_V16
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if not IS_V16 or not frappe.get_meta("Expense Claim").get_field("payable_account"):
		return
	if frappe.get_meta("Expense Claim").get_field("payable_account").mandatory_depends_on:
		make_property_setter(
			"Expense Claim", "payable_account", "mandatory_depends_on", "", "Code",
			validate_fields_for_doctype=False,
		)
		frappe.clear_cache(doctype="Expense Claim")
		print("Expense Claim: Payable Account optional again, as on v15")
