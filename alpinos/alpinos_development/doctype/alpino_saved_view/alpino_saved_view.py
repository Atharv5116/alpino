# Copyright (c) 2026, Alpinos and contributors
# License: MIT
"""One saved screen layout: which columns, in what order, with which filters and sort.

Server-side and per user, so a view survives a different browser or machine — the
localStorage the other list screens use does not.

Only alpinos.invoice_queue_api writes these, always for the session user. The doctype
grants nothing to ordinary roles, so the REST API cannot create one either; validate()
still refuses a view written for somebody else, so one user cannot plant a view (or a
default view) in another user's list.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document


class AlpinoSavedView(Document):
	def validate(self):
		self.view_name = (self.view_name or "").strip()
		if not self.view_name:
			frappe.throw(_("Please name the view."))
		if not self.user:
			self.user = frappe.session.user
		if self.user != frappe.session.user and "System Manager" not in frappe.get_roles():
			frappe.throw(_("A saved view can only be saved for yourself."), frappe.PermissionError)
		self._validate_json("columns_json", list)
		self._validate_json("filters_json", dict)
		self.sort_dir = "asc" if (self.sort_dir or "").lower() == "asc" else "desc"
		self._assert_unique_name()
		self._keep_one_default()

	def _validate_json(self, field, expect):
		raw = self.get(field)
		if not raw:
			self.set(field, json.dumps([] if expect is list else {}))
			return
		try:
			value = json.loads(raw) if isinstance(raw, str) else raw
		except ValueError:
			frappe.throw(_("{0} is not valid JSON.").format(_(field)))
		if not isinstance(value, expect):
			frappe.throw(_("{0} must be a {1}.").format(_(field), expect.__name__))
		self.set(field, json.dumps(value))

	def _assert_unique_name(self):
		"""One name per user per page, so saving again REPLACES rather than piles up."""
		clash = frappe.db.exists(
			"Alpino Saved View",
			{
				"user": self.user,
				"page_route": self.page_route,
				"view_name": self.view_name,
				"name": ("!=", self.name or ""),
			},
		)
		if clash:
			frappe.throw(
				_("You already have a view called {0} on this page.").format(
					frappe.bold(self.view_name)
				)
			)

	def _keep_one_default(self):
		if not self.is_default:
			return
		for other in frappe.get_all(
			"Alpino Saved View",
			filters={
				"user": self.user, "page_route": self.page_route,
				"is_default": 1, "name": ("!=", self.name or ""),
			},
			pluck="name",
		):
			frappe.db.set_value("Alpino Saved View", other, "is_default", 0, update_modified=False)
