"""Changes(HP) #56: the Tally P&L Name for an Offline buyer, and its warehouse.

    "Apply this logic only when Channel = Offline, to set the Tally P&L Name based on the
     buyer's Primary Billing State and GST Type.

     Outside Gujarat: Registered Business / Overseas -> B to B IGST Sales Offline
                      Unregistered Business          -> B to C IGST Sales Offline
     Gujarat:         Registered Business / Overseas -> B to B GST Sales Offline
                      Unregistered Business          -> B to C GST Sales Offline

     also set the Tally Warehouse = Offline when Channel = Offline."

Two axes decide it. The state decides GST against IGST, because Alpino bills from Gujarat
and anything leaving the state is interstate. The GST type decides B to B against B to C,
with Overseas sitting on the B to B side -- an export is still a business sale.

Only Offline is touched. Every other channel keeps whatever P&L name it was given, which
matters because the live data has names like "Amazon B to B Sales" and "Zepto Sales" that
this rule knows nothing about and must not overwrite.
"""

import frappe
from frappe import _

HOME_STATE = "Gujarat"
OFFLINE_CHANNEL = "Offline"
OFFLINE_WAREHOUSE = "Offline"

#: (is_home_state, is_business) -> Tally P&L Name
_PL_NAMES = {
	(True, True): "B to B GST Sales Offline",
	(True, False): "B to C GST Sales Offline",
	(False, True): "B to B IGST Sales Offline",
	(False, False): "B to C IGST Sales Offline",
}

#: GST types that bill as business-to-business. Overseas counts: an export is a business sale.
_BUSINESS_GST_TYPES = {"Registered Business", "Overseas"}


def _norm(value):
	return (value or "").strip().lower()


def primary_billing_state(doc):
	"""The state of the buyer's primary billing address.

	The flat `state` field is the synced copy of the primary address, so it is read first;
	the address table is the fallback for a record whose sync has not run.
	"""
	state = (doc.get("state") or "").strip()
	if state:
		return state
	for row in (doc.get("addresses") or []):
		if row.get("is_primary"):
			return (row.get("state") or "").strip()
	return ""


def tally_pl_name_for(state, gst_type):
	"""The P&L name these two values imply, or "" when the state is unknown."""
	if not (state or "").strip():
		return ""
	is_home = _norm(state) == _norm(HOME_STATE)
	is_business = (gst_type or "").strip() in _BUSINESS_GST_TYPES
	return _PL_NAMES[(is_home, is_business)]


def set_tally_fields(doc, method=None):
	"""Buyer Master validate hook: derive the P&L name and warehouse for an Offline buyer."""
	if _norm(doc.get("channel")) != _norm(OFFLINE_CHANNEL):
		return

	name = tally_pl_name_for(primary_billing_state(doc), doc.get("gst_type"))
	if name:
		doc.tally_pl_name = name
	# The warehouse does not depend on the state, only on the channel.
	doc.custom_tally_warehouse = OFFLINE_WAREHOUSE


@frappe.whitelist()
def backfill(apply=0, sample=15):
	"""Report, and optionally apply, the rule across the existing Offline buyers.

	  bench --site SITE execute alpinos.tally_pl_name.backfill
	  bench --site SITE execute alpinos.tally_pl_name.backfill --kwargs "{'apply':1}"
	"""
	apply = int(apply)
	rows = frappe.db.sql(
		"""
		SELECT name, state, gst_type, tally_pl_name, custom_tally_warehouse
		FROM `tabBuyer Master`
		WHERE LOWER(IFNULL(channel, '')) = %(ch)s
		""",
		{"ch": OFFLINE_CHANNEL.lower()}, as_dict=True,
	)

	changes, unknown_state = [], []
	for r in rows:
		want = tally_pl_name_for(r.state, r.gst_type)
		if not want:
			unknown_state.append(r.name)
			continue
		if r.tally_pl_name != want or r.custom_tally_warehouse != OFFLINE_WAREHOUSE:
			changes.append({
				"buyer": r.name,
				"state": r.state,
				"gst_type": r.gst_type,
				"pl_name": f"{r.tally_pl_name or '—'} -> {want}",
				"warehouse": f"{r.custom_tally_warehouse or '—'} -> {OFFLINE_WAREHOUSE}",
				"_want": want,
			})

	if apply:
		for c in changes:
			frappe.db.set_value(
				"Buyer Master", c["buyer"],
				{"tally_pl_name": c["_want"], "custom_tally_warehouse": OFFLINE_WAREHOUSE},
				update_modified=False,
			)
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"offline_buyers": len(rows),
		"to_change": len(changes),
		"no_billing_state": len(unknown_state),
		"sample": [{k: v for k, v in c.items() if not k.startswith("_")} for c in changes[: int(sample)]],
		"no_state_sample": unknown_state[: int(sample)],
	}
