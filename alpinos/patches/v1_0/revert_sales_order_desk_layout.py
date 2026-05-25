"""
Remove compact Sales Order Desk layout (Property Setters: hidden, label, in_list_view,
insert_after on Sales Order family DocTypes), then re-apply Alpinos base setters from
``sales_order_custom_fields`` (SKU labels, order-type options, hidden company, etc.).

``after_migrate`` no longer calls ``setup_sales_order_form_layout`` (see ``hooks.py``),
so the compact Desk layout is not re-applied after migrate.

This patch is listed in ``patches.txt``; Frappe records it in Patch Log so it runs once
per site on ``bench migrate``. Re-add ``setup_sales_order_form_layout`` to
``after_migrate`` if you want the compact layout again.
"""

import frappe


def execute():
	from alpinos.sales_order_form_layout import rollback_sales_order_desk_customizations

	rollback_sales_order_desk_customizations()
