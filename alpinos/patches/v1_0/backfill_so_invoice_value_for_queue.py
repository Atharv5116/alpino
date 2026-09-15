"""Fill Total Invoice Value on orders picked or dispatched before it was maintained.

Changes(HP) #42: the Order Fulfilment Report showed Invoice Amount 0 on those orders.
The report now reads submitted Delivery Notes live, but the stored value is still what
the Sales Order screens and a not-yet-dispatched order show, so it is filled once here
with the same rule the hooks use (alpinos.so_invoice_value.backfill). Only that derived
field is written, without touching the order's modified time.
"""

from alpinos.so_invoice_value import backfill


def execute():
	backfill(apply=1)
