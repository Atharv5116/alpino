"""Goods Return Management, Document 1 of 3 (Goods Return Operational Management).

Phase A: what FSD sections 1 and 2 define.

  * the two roles: Goods Return Coordinator and Goods Return Executive (2.2.1);
  * the Goods Return Reason master;
  * the Goods Return Request (GRR), one form for Offline and E-Commerce (1.8.2), with its
    Return Handling Type (1.5) and the two-level channel rule (2.3): Coordinator AND a
    role of the request's channel, checked on save, submit and cancel.

Return GRN, discrepancies, Supplementary requests, condition, disposal, the Return
Warehouse, stock, closure, notifications and reports follow with sections 3 to 10.
"""

COORDINATOR = "Goods Return Coordinator"
EXECUTIVE = "Goods Return Executive"

REQUEST = "Goods Return Request"
REQUEST_ITEM = "Goods Return Request Item"
REASON = "Goods Return Reason"

RETURN_TO_AHFPL = "Return to AHFPL"
CUSTOMER_SITE_DISPOSAL = "Customer-Site Disposal"
REDISTRIBUTION = "Customer-to-Customer Redistribution"
HANDLING_TYPES = (RETURN_TO_AHFPL, CUSTOMER_SITE_DISPOSAL, REDISTRIBUTION)

NORMAL = "Normal"
SUPPLEMENTARY = "Supplementary"
