"""after_migrate: Goods Return roles and permissions. Safe to run on every migrate."""

import frappe


def execute():
	from alpinos.goods_return import roles

	roles.setup_roles()
	roles.setup_permissions()
	frappe.db.commit()
