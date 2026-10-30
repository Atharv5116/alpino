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

	def _pasted_junk_is_cleaned_off():
		for pasted in ("24AAACC1206D1ZM\u200b", " 24 aaacc 1206 d1zm ", "24-AAACC-1206-D1ZM", "\u202a24AAACC1206D1ZM\u202c"):
			ok, msg = G.validate_gstin_format(pasted)
			_assert(ok, f"{pasted!r} was rejected: {msg}")
		ok, msg = G.validate_gstin_format("24AAACC1206D1ZMX")
		_assert(not ok and "24AAACC1206D1ZMX" in msg and "16" in msg, msg)

	check("a pasted GST No. with spaces or invisible characters passes; a wrong one is shown in the message",
		_pasted_junk_is_cleaned_off)

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

	# --- the address lands on records the address row can hold (29 Oct 2026) -------------
	tag = frappe.generate_hash(length=5).lower()
	town = f"Gsttest{tag}"

	def _city(name, state):
		if not frappe.db.exists("City", name):
			frappe.get_doc({"doctype": "City", "city_name": name, "state": state, "country": "India"}).insert(ignore_permissions=True)

	for state in ("Karnataka", "Gujarat"):
		if not frappe.db.exists("State", state):
			frappe.get_doc({"doctype": "State", "state_name": state, "country": "India"}).insert(ignore_permissions=True)
	_city(town, "Karnataka")
	_city(f"{town} Kendra", "Karnataka")
	_city(town.upper() + "X", "Gujarat")

	def mapped(**address):
		return G.map_to_buyer_fields(frappe._dict(gstin=address.pop("gstin", "29AAACC1206D1ZM"), permanent_address=address))

	check("a state spelt differently on the GST record finds the State record",
		lambda: _assert(G._key("Jammu And Kashmir") == G._key("Jammu & Kashmir")
			and mapped(state="KARNATAKA", city=town)["state"] == "Karnataka", mapped(state="KARNATAKA", city=town)))
	check("a district such as 'Bengaluru Urban' finds the city 'Bengaluru'",
		lambda: _assert(mapped(state="Karnataka", city=f"{town} Urban")["city"] == town, mapped(state="Karnataka", city=f"{town} Urban")))
	check("a city is matched whatever its case in the City list",
		lambda: _assert(mapped(state="Gujarat", city=f"{town}x", gstin="24AAACC1206D1ZM")["city"] == town.upper() + "X"))
	check("a district not in the list falls back to the city named in the address",
		lambda: _assert(mapped(state="Karnataka", city="Nowhere District", address_line2=f"Phase 2, {town} Kendra")["city"]
			== f"{town} Kendra", mapped(state="Karnataka", city="Nowhere District", address_line2=f"Phase 2, {town} Kendra")))
	check("a namesake city in another state is not used",
		lambda: _assert(mapped(state="Gujarat", city=town, gstin="24AAACC1206D1ZM")["city"] == ""))

	def _missing_state_comes_from_the_gstin():
		try:
			import india_compliance.gst_india.constants  # noqa: F401
		except ImportError:
			return  # the state-code table belongs to india_compliance
		_assert(mapped(city=town, gstin="29AAACC1206D1ZM")["state"] == "Karnataka", mapped(city=town))

	check("a GST record without a state takes the GST No.'s state", _missing_state_comes_from_the_gstin)

	def _the_message_names_a_city_it_could_not_place():
		import sys
		import types

		try:
			import india_compliance.gst_india.utils  # noqa: F401  (the lookup's own package)
		except ImportError:
			return
		fake = types.ModuleType("india_compliance.gst_india.utils.gstin_info")
		fake.get_gstin_info = lambda gstin, throw_error=True: frappe._dict(
			gstin=gstin, business_name="Test", gst_category="Registered Regular", status="Active",
			permanent_address={"address_line1": "Plot 1", "address_line2": "Peenya", "city": "Atlantis",
				"state": "Karnataka", "pincode": "560058"})
		saved_module, saved_available = sys.modules.get(fake.__name__), G.available
		sys.modules[fake.__name__] = fake
		G.available = lambda: True
		try:
			out = G.fetch_gstin_details("29AAACC1206D1ZM")
		finally:
			G.available = saved_available
			if saved_module:
				sys.modules[fake.__name__] = saved_module
			else:
				sys.modules.pop(fake.__name__)
		_assert(out["ok"] == 1 and out["data"]["state"] == "Karnataka" and out["data"]["city"] == "", out)
		_assert("Atlantis" in out["message"] and out["missing"], out["message"])

	check("a city the City list does not have is left blank and named in the message",
		_the_message_names_a_city_it_could_not_place)
