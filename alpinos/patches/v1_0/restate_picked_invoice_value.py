"""Restate Total Invoice Value on orders sitting on a pick list the warehouse cut down.

Before anything is dispatched the value is the picked share of the order. It was measured
against the pick list row, so a row cut from 30 to 20 read as fully picked: the Order
Fulfilment Report showed the whole order as invoiced (Difference 0) while Undispatched
listed the removed quantity. The rule now measures against the ordered quantity
(alpinos.so_invoice_value.picked_by_line); this refreshes the stored figure once with it.
Dispatched orders recompute to the value they already hold. Only that derived field is
written, without touching the order's modified time.
"""

from alpinos.so_invoice_value import backfill


def execute():
	backfill(apply=1)
