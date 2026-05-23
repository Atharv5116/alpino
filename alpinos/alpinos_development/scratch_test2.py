import sys
sys.path.append("/home/frappe/frappe-bench/apps/frappe")
sys.path.append("/home/frappe/frappe-bench/apps/erpnext")
sys.path.append("/home/frappe/frappe-bench/apps/alpinos")

import frappe
frappe.init(site="uaterp.alpino.co.in")
frappe.connect()

pl = frappe.get_doc('Pick List', 'STO-PICK-2026-00014')
print(f"PICK LIST: {pl.name}, STATUS: {pl.status}")
for d in pl.locations:
	print(f"  ITEM: {d.item_code}, QTY: {d.qty}, PICKED: {d.picked_qty}, DELIVERED: {d.delivered_qty}")
