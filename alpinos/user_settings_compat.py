"""Changes(HP) #116: Settings > Appearance > Doc View showed "Pinned" after "Floating" was chosen.

Frappe 16's Settings dialog reads the user's own preferences with frappe.client.get_value,
which goes through get_list. A user whose roles do not read User (everyone but System
Manager / HR Manager here) gets only the record's name back, so every preference in the
dialog showed its default: Doc View read "Pinned" although the desk was floating, and the
time zone, notification and list/form toggles showed defaults too. Saving always worked.

This answers that one read: a user asking for their OWN record, and only for the dialog's
preference fields, gets them; every other get_value call goes to Frappe unchanged.
"""

import frappe
from frappe.client import get_value as frappe_get_value

#: The fields Frappe 16's Settings dialog loads (frappe/ui/user_settings_dialog.js).
OWN_SETTINGS_FIELDS = {
	"name",
	"middle_name",
	"username",
	"thread_notify",
	"time_zone",
	"notifications",
	"search_bar",
	"list_sidebar",
	"bulk_actions",
	"view_switcher",
	"form_sidebar",
	"timeline",
	"dashboard",
	"form_navigation_buttons",
	"report_split_view",
	"show_my_space",
	"dock_mode",
}


def _own_record(filters):
	user = frappe.session.user
	if isinstance(filters, str):
		try:
			parsed = frappe.parse_json(filters)
		except Exception:
			parsed = filters
		filters = parsed
	if isinstance(filters, str):
		return filters == user
	if isinstance(filters, dict):
		return list(filters.keys()) == ["name"] and filters.get("name") == user
	return False


@frappe.whitelist()
def get_value(doctype, fieldname, filters=None, as_dict=True, debug=False, parent=None):
	if doctype == "User" and frappe.session.user != "Guest" and _own_record(filters):
		try:
			fields = frappe.parse_json(fieldname)
		except (TypeError, ValueError):
			fields = [fieldname]
		if isinstance(fields, str):
			fields = [fields]
		if isinstance(fields, list) and fields and set(fields) <= OWN_SETTINGS_FIELDS:
			row = frappe.db.get_value("User", frappe.session.user, fields, as_dict=True) or {}
			row["name"] = frappe.session.user
			if frappe.utils.cint(as_dict) or as_dict is True:
				return row
			return [row.get(f) for f in fields] if len(fields) > 1 else row.get(fields[0])
	return frappe_get_value(doctype, fieldname, filters=filters, as_dict=as_dict, debug=debug, parent=parent)
