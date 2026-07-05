"""Backend for the Attendance Batch pages (list + entry).

The pages are thin clients over Monthly Attendance Batch:
  - attendance_batch_list : ledger of batches with rule-engine tabs
  - attendance_batch_entry: one batch — ingestion, grid, summary, workflow actions
"""

import frappe
from frappe import _
from frappe.utils import get_first_day


@frappe.whitelist()
def get_batches(rule_engine=None, status=None, start=0, page_length=20):
	"""Ledger rows for the list page, newest month first, plus per-engine counts."""
	if not frappe.has_permission("Monthly Attendance Batch", "read"):
		frappe.throw(_("Not permitted to view Attendance Batches."), frappe.PermissionError)

	filters = {}
	if rule_engine and rule_engine != "All":
		filters["rule_engine"] = rule_engine
	if status:
		filters["workflow_state"] = status

	batches = frappe.get_all(
		"Monthly Attendance Batch",
		filters=filters,
		fields=[
			"name",
			"rule_engine",
			"payroll_month",
			"month_title",
			"workflow_state",
			"company",
			"fetched_on",
			"modified",
		],
		order_by="payroll_month desc, rule_engine asc",
		start=int(start),
		page_length=int(page_length) + 1,
	)

	has_more = len(batches) > int(page_length)
	batches = batches[: int(page_length)]

	for b in batches:
		b.row_count = frappe.db.count(
			"Monthly Attendance Batch Row", {"parent": b.name, "parenttype": "Monthly Attendance Batch"}
		)

	counts = dict(
		frappe.db.sql("SELECT rule_engine, COUNT(*) FROM `tabMonthly Attendance Batch` GROUP BY rule_engine")
	)
	counts["All"] = sum(counts.values())

	return {"batches": batches, "counts": counts, "has_more": has_more}


@frappe.whitelist()
def create_batch(rule_engine, payroll_month, company=None):
	"""Create New Entry: one Draft batch per engine + month (+ company)."""
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1)[0].name

	batch = frappe.get_doc(
		{
			"doctype": "Monthly Attendance Batch",
			"rule_engine": rule_engine,
			"payroll_month": get_first_day(payroll_month),
			"company": company,
		}
	)
	batch.insert()
	return batch.name


@frappe.whitelist()
def get_batch(name):
	"""Full batch payload for the entry page: doc + rows + workflow transitions."""
	doc = frappe.get_doc("Monthly Attendance Batch", name)
	doc.check_permission("read")

	from frappe.model.workflow import get_transitions

	try:
		transitions = [t.get("action") for t in get_transitions(doc)]
	except Exception:
		transitions = []

	return {
		"doc": doc.as_dict(),
		"transitions": transitions,
		"is_editable": doc.docstatus == 0 and (doc.workflow_state or "Draft") == "Draft",
	}


@frappe.whitelist()
def populate_batch_rows(name):
	"""Ingestion action (Generate / Fetch / parse upload) for the entry page."""
	doc = frappe.get_doc("Monthly Attendance Batch", name)
	doc.check_permission("write")
	return doc.populate_rows()


@frappe.whitelist()
def apply_batch_action(name, action):
	"""Run a workflow action (Submit for Approval / Approve / Reject / Lock)."""
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Monthly Attendance Batch", name)
	updated = apply_workflow(doc, action)
	return {"workflow_state": updated.get("workflow_state")}
