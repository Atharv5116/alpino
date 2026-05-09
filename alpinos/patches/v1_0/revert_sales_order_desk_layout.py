"""
Remove compact Sales Order Desk layout (Property Setters: hidden, label, in_list_view
on Sales Order family DocTypes), then re-apply Alpinos base setters from
``sales_order_custom_fields`` (SKU labels, order-type options, hidden company, etc.).

**Before** ``bench migrate`` with this patch queued:

1. Remove ``alpinos.sales_order_form_layout.setup_sales_order_form_layout`` from
   ``after_migrate`` in ``hooks.py``. Otherwise ``after_migrate`` will recreate the
   Desk layout as soon as migrate finishes.

Optional: add the hook line back later if you want the compact layout again.

To run once via migrate, append to ``hooks.py`` ``patches``::

	"alpinos.patches.v1_0.revert_sales_order_desk_layout.execute",

Frappe records it in Patch Log so it only executes once per site.
"""

import frappe


def execute():
	from alpinos.sales_order_form_layout import rollback_sales_order_desk_customizations

	rollback_sales_order_desk_customizations()
