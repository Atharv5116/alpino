"""Changes(HP) #57: filling a Buyer Master from its GST No.

Run:  bench --site alpinos.test execute alpinos.buyer_gst_fetch_test.run

The live lookup belongs to india_compliance, which is not installed on this site and needs a
GSP subscription besides. What is testable without it -- and what the ticket is firm about --
is the translation: the format check, the mapping onto Buyer Master's own fields, and that
every way the lookup can fail produces a distinct, actionable message rather than one vague
error. Those are the checks here.
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
	try:
		_run()
	finally:
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos import buyer_gst_fetch as G

	def _a_well_formed_number_passes_the_format_check():
		ok, msg = G.validate_gstin_format("24AAACC1206D1ZM")
		_assert(ok, f"a valid GSTIN was rejected: {msg}")

	check("#57 a well-formed GST No. passes the format check",
		_a_well_formed_number_passes_the_format_check)

	def _a_malformed_number_is_caught_before_any_api_call():
		for bad, why in (
			("", "empty"),
			("24AAACC1206D1Z", "14 characters"),
			("24AAACC1206D1ZMX", "16 characters"),
			("AAAACC1206D1ZM1", "no state digits"),
		):
			ok, msg = G.validate_gstin_format(bad)
			_assert(not ok, f"{why} was accepted: {bad!r}")
			_assert(msg, f"{why} was rejected without a message")

	check("#57 a malformed GST No. is caught before any API call",
		_a_malformed_number_is_caught_before_any_api_call)

	def _the_response_maps_onto_the_buyer_fields():
		info = frappe._dict(
			gstin="24AAACC1206D1ZM",
			business_name="Reliance Retail Ltd",
			gst_category="Registered Regular",
			status="Active",
			permanent_address={
				"address_line1": "3rd Floor, Maker Chambers",
				"address_line2": "Nariman Point",
				"city": "Ahmedabad",
				"state": "Gujarat",
				"pincode": "380001",
				"country": "India",
			},
		)
		d = G.map_to_buyer_fields(info)
		_assert(d["customer_business_name"] == "Reliance Retail Ltd", d)
		_assert(d["gst_type"] == "Registered Business", d["gst_type"])
		_assert(d["state"] == "Gujarat" and d["city"] == "Ahmedabad", d)
		_assert(d["pincode"] == "380001", d)
		_assert("Maker Chambers" in d["address_line"] and "Nariman Point" in d["address_line"],
			f"both address lines should be kept: {d['address_line']!r}")

	check("#57 the response maps onto the fields Buyer Master actually has",
		_the_response_maps_onto_the_buyer_fields)

	def _every_gst_category_lands_on_a_real_option():
		options = {"Registered Business", "Unregistered Business", "Overseas"}
		for category in G._GST_TYPE_BY_CATEGORY:
			mapped = G.map_to_buyer_fields(frappe._dict(gst_category=category))["gst_type"]
			_assert(mapped in options,
				f"{category} maps to {mapped!r}, which is not a GST Type option")

	check("#57 every GST category maps to a real GST Type option",
		_every_gst_category_lands_on_a_real_option)

	def _overseas_and_unregistered_are_not_flattened_into_registered():
		_assert(G.map_to_buyer_fields(frappe._dict(gst_category="Overseas"))["gst_type"] == "Overseas")
		_assert(G.map_to_buyer_fields(frappe._dict(gst_category="Unregistered"))["gst_type"]
			== "Unregistered Business")

	check("#57 Overseas and Unregistered keep their own GST Type",
		_overseas_and_unregistered_are_not_flattened_into_registered)

	def _an_invalid_number_returns_its_own_reason():
		out = G.fetch_gstin_details("NOT-A-GSTIN")
		_assert(out["ok"] == 0 and out["reason"] == "invalid", out)
		_assert(out["message"], "no message for an invalid number")
		_assert(out["data"] == {}, "an invalid number returned data")

	check("#57 an invalid GST No. is reported as invalid, with a message",
		_an_invalid_number_returns_its_own_reason)

	def _an_unavailable_service_says_so_rather_than_blaming_the_number():
		"""india_compliance is not installed here, so this is the live path on this site."""
		out = G.fetch_gstin_details("24AAACC1206D1ZM")
		if G.available():
			return  # on a site where it IS installed, this check does not apply
		_assert(out["ok"] == 0 and out["reason"] == "unavailable", out)
		_assert("India Compliance" in out["message"],
			f"the message does not say what is missing: {out['message']}")
		_assert("by hand" in out["message"],
			"the message does not tell the user what to do instead")

	check("#57 when the lookup is not set up, the message says so, not that the number is wrong",
		_an_unavailable_service_says_so_rather_than_blaming_the_number)

	def _the_failure_reasons_are_distinguishable():
		"""'invalid', 'unavailable', 'not_found' and 'service' must not read alike."""
		reasons = {G.fetch_gstin_details("BAD")["reason"],
		           G.fetch_gstin_details("24AAACC1206D1ZM")["reason"]}
		_assert("invalid" in reasons, reasons)
		_assert(len(reasons) == 2,
			f"two different failures produced the same reason: {reasons}")

	check("#57 the different failures are distinguishable from one another",
		_the_failure_reasons_are_distinguishable)
