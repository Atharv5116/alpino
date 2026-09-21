"""Correct the values old dispatches carry, now that free rows are no longer priced.

Delivery Notes made before 76685a8 priced Marketing Freebies / Scheme / Additional Units
rows from the Item Price list, so their totals ran above the order's. Each such note is
re-priced on its own lines (free rows to 0, totals re-derived), which keeps a part
delivery at its own share, and the Post Dispatch rows copied from it follow
(alpinos.dn_free_row_repricing).

The order's stored Total Invoice Value is then restated on every picked or dispatched
order with the rule 76685a8 introduced -- the dispatched share of each order line at the
order's own rates -- since backfill_so_invoice_value_for_queue filled it with the old
rule (the sum of the notes' totals). Only derived value fields are written; no modified
time moves and no ledger entry changes.
"""

from alpinos.dn_free_row_repricing import run
from alpinos.so_invoice_value import backfill


def execute():
	run(apply=1)
	backfill(apply=1)
