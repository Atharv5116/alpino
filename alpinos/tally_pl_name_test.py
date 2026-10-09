"""Changes(HP) #56: the Tally P&L Name for an Offline buyer, and its warehouse.

Run:  bench --site alpinos.test execute alpinos.tally_pl_name_test.run

Two axes decide it. State decides GST against IGST, because Alpino bills from Gujarat.
GST type decides B to B against B to C, with Overseas on the B to B side. The rule applies
only to Offline, which is the part most worth guarding: the live data carries names like
"Amazon B to B Sales" that this rule knows nothing about. Fixtures roll back.
"""

import frappe

RES = []


def check(label, fn):
	try:
		fn()
		RES.append(("PASS", label, ""))
	except AssertionError as e:
		RES.append(("FAIL", label, str(e)))
	except Exception as e:
		RES.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def run():
	RES.clear()
	frappe.set_user("Administrator")
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None
	try:
		_run()
	finally:
		frappe.db.commit = real_commit
		frappe.db.rollback()
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import tally_pl_name as T

	def _doc(channel="Offline", state="Gujarat", gst_type="Registered Business", **kw):
		return frappe._dict(channel=channel, state=state, gst_type=gst_type,
			tally_pl_name=kw.get("tally_pl_name"), custom_tally_warehouse=kw.get("warehouse"),
			addresses=kw.get("addresses") or [])

	def _the_four_combinations_from_the_ticket():
		cases = [
			("Maharashtra", "Registered Business", "B to B IGST Sales Offline"),
			("Maharashtra", "Overseas", "B to B IGST Sales Offline"),
			("Maharashtra", "Unregistered Business", "B to C IGST Sales Offline"),
			("Gujarat", "Registered Business", "B to B GST Sales Offline"),
			("Gujarat", "Overseas", "B to B GST Sales Offline"),
			("Gujarat", "Unregistered Business", "B to C GST Sales Offline"),
		]
		for state, gst, want in cases:
			got = T.tally_pl_name_for(state, gst)
			_assert(got == want, f"{state} + {gst} gave {got!r}, expected {want!r}")

	check("#56 every combination the ticket lists resolves as written",
		_the_four_combinations_from_the_ticket)

	def _overseas_bills_as_business():
		_assert(T.tally_pl_name_for("Kerala", "Overseas").startswith("B to B"),
			"Overseas was treated as B to C; an export is still a business sale")

	check("#56 Overseas bills as business, not consumer", _overseas_bills_as_business)

	def _the_home_state_is_matched_however_it_is_cased():
		for spelling in ("Gujarat", "gujarat", "  GUJARAT  "):
			got = T.tally_pl_name_for(spelling, "Registered Business")
			_assert(got == "B to B GST Sales Offline",
				f"{spelling!r} was treated as interstate: {got}")

	check("#56 the home state is recognised whatever its spelling",
		_the_home_state_is_matched_however_it_is_cased)

	def _an_offline_buyer_gets_both_fields():
		doc = _doc(state="Delhi", gst_type="Unregistered Business")
		T.set_tally_fields(doc)
		_assert(doc.tally_pl_name == "B to C IGST Sales Offline", doc.tally_pl_name)
		_assert(doc.custom_tally_warehouse == "Offline", doc.custom_tally_warehouse)

	check("#56 an Offline buyer gets the P&L name and the Offline warehouse",
		_an_offline_buyer_gets_both_fields)

	def _another_channel_is_left_completely_alone():
		doc = _doc(channel="E-com", state="Delhi", gst_type="Registered Business",
			tally_pl_name="Amazon B to B Sales", warehouse="T24")
		T.set_tally_fields(doc)
		_assert(doc.tally_pl_name == "Amazon B to B Sales",
			f"an E-com buyer's P&L name was overwritten: {doc.tally_pl_name}")
		_assert(doc.custom_tally_warehouse == "T24",
			f"an E-com buyer's warehouse was overwritten: {doc.custom_tally_warehouse}")

	check("#56 a buyer on another channel keeps the name it was given",
		_another_channel_is_left_completely_alone)

	def _the_address_table_is_the_fallback_for_the_state():
		doc = _doc(state="", gst_type="Registered Business", addresses=[
			frappe._dict(is_primary=0, state="Karnataka"),
			frappe._dict(is_primary=1, state="Gujarat"),
		])
		_assert(T.primary_billing_state(doc) == "Gujarat",
			"the primary address was not used when the flat field is empty")
		T.set_tally_fields(doc)
		_assert(doc.tally_pl_name == "B to B GST Sales Offline", doc.tally_pl_name)

	check("#56 the primary billing address supplies the state when the flat field is empty",
		_the_address_table_is_the_fallback_for_the_state)

	def _no_state_means_no_guess():
		doc = _doc(state="", gst_type="Registered Business", tally_pl_name="Existing Name")
		T.set_tally_fields(doc)
		_assert(doc.tally_pl_name == "Existing Name",
			f"a P&L name was invented without a state: {doc.tally_pl_name}")
		_assert(doc.custom_tally_warehouse == "Offline",
			"the warehouse depends only on the channel and should still be set")

	check("#56 with no billing state the P&L name is left alone, warehouse still set",
		_no_state_means_no_guess)

	def _the_backfill_reports_before_it_writes():
		out = T.backfill(apply=0)
		_assert(out["mode"] == "DRY-RUN", out["mode"])
		_assert(out["offline_buyers"] >= 0 and "to_change" in out, out)

	check("#56 the backfill reports before it writes", _the_backfill_reports_before_it_writes)
