# Copyright (c) 2026, Alpinos and contributors
# License: MIT

"""One user's access to one company: the company-wise roles they hold there.

See alpinos.company_scope for the whole picture.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CompanyMembership(Document):
	def validate(self):
		from alpinos.company_scope import access

		scoped = access.scoped_roles()
		seen, keep, wrong = set(), [], []
		for row in self.roles:
			if row.role in seen:
				continue
			seen.add(row.role)
			if row.role not in scoped:
				wrong.append(row.role)
			keep.append(row)
		if wrong:
			frappe.throw(
				_(
					"{0} {1} not a company-wise role. Give it on the User form (it then applies in every company), "
					"or tick 'Company-wise role' on it in Role Permissions Manager first."
				).format(", ".join(frappe.bold(r) for r in wrong), _("is") if len(wrong) == 1 else _("are"))
			)
		self.set("roles", keep)
		if self.is_default:
			frappe.db.set_value(
				"Company Membership",
				{"user": self.user, "is_default": 1, "name": ["!=", self.name or ""]},
				"is_default",
				0,
			)

	def on_update(self):
		self._sync()

	def on_trash(self):
		self.flags.alpinos_deleted = True

	def after_delete(self):
		self._sync()

	def _sync(self):
		from alpinos.company_scope import access, sync

		access.clear_cache(self.user)
		if not self.flags.alpinos_skip_user_sync:
			sync.sync_user(self.user)
