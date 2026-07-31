import frappe

from alpinos.qty_flow_report import run


def execute(filters=None):
	return run("quo_so", filters)
