"""Install Desk Page ``sales-order-entry-list`` from app JSON (for sites that missed sync)."""

import frappe


def execute():
	frappe.reload_doc("alpinos_development", "page", "sales_order_entry_list", force=True)
