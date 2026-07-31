"""Repair standard child-table columns on Buyer * tables (UAT).

The aborted rename migrate on UAT left Buyer child tables without their
standard child columns, so loading any Buyer Master dies with
"Unknown column 'parent' in 'WHERE'". frappe.db.updatedb (previous repair
attempt) only reconciles DocField columns, never the standard ones — this
patch adds them explicitly. Idempotent; a no-op on healthy sites."""

import frappe

CHILD_TABLES = ("tabBuyer Address", "tabBuyer Margin", "tabBuyer Item")

STANDARD_COLUMNS = {
	"parent": "varchar(140)",
	"parentfield": "varchar(140)",
	"parenttype": "varchar(140)",
	"idx": "int(8) NOT NULL DEFAULT 0",
}


def execute():
	for table in CHILD_TABLES:
		if not frappe.db.sql("SHOW TABLES LIKE %s", table):
			continue
		existing = {r[0] for r in frappe.db.sql(f"DESCRIBE `{table}`")}
		added = []
		for col, spec in STANDARD_COLUMNS.items():
			if col not in existing:
				frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {spec}")
				added.append(col)
		if "parent" in added:
			indexes = {r[2] for r in frappe.db.sql(f"SHOW INDEX FROM `{table}`")}
			if "parent" not in indexes:
				frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX parent (`parent`)")
		if added:
			print(f"{table}: added {', '.join(added)}")
	frappe.db.commit()
