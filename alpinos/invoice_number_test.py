"""The Invoice No read off an uploaded sheet, at any series width.

Run:  bench --site alpinos.test execute alpinos.invoice_number_test.run

Reported 09-10: no invoice could be uploaded once the series reached 10000. The sheet
reader took the last FOUR characters of the cell, which was right while every invoice was
four digits and silently wrong the moment one was five: "10000" became "0000".

The checks are in pairs. The four-digit cases prove the old behaviour is preserved -- this
is a parsing change on a field that thousands of live orders already carry, so "10000 now
works" is only half the claim. The other half is that 9863 still reads 9863.

No fixtures, so nothing to roll back.
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
	_run()
	width = max(len(r[1]) for r in RES)
	for status, label, detail in RES:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in RES if r[0] == 'PASS')}/{len(RES)} passed")
	return RES


def _run():
	from alpinos.invoice_sync import invoice_number as N

	def _five_digits_survive():
		"""The reported fault. Every one of these lost its leading digit."""
		for raw, want in (("10000", "10000"), ("10001", "10001"), ("12345", "12345")):
			got = N(raw)
			_assert(got == want, f"{raw!r} -> {got!r}, expected {want!r}")

	check("a five-digit invoice number is kept whole", _five_digits_survive)

	def _four_digits_are_unchanged():
		"""The series in use until now; thousands of orders carry these."""
		for raw in ("9863", "6057", "0001"):
			got = N(raw)
			_assert(got == raw, f"{raw!r} -> {got!r}, expected it unchanged")

	check("a four-digit invoice number still reads the same", _four_digits_are_unchanged)

	def _six_digits_and_beyond():
		"""The next rollover should not need another fix."""
		_assert(N("100000") == "100000", N("100000"))
		_assert(N("1234567") == "1234567", N("1234567"))

	check("the next rollover needs no further change", _six_digits_and_beyond)

	def _a_prefix_is_still_dropped():
		"""What the four was actually for: "abcd4567" -> "4567"."""
		_assert(N("abcd4567") == "4567", N("abcd4567"))
		_assert(N("INV-10000") == "10000", N("INV-10000"))

	check("a non-numeric prefix is still dropped", _a_prefix_is_still_dropped)

	def _a_pdf_file_name_loses_its_extension():
		"""Changes(HP) #42.3: the cell sometimes holds the PDF's file name."""
		_assert(N("6057.pdf") == "6057", N("6057.pdf"))
		_assert(N("10000.PDF") == "10000", N("10000.PDF"))

	check("a .pdf file name in the cell yields the number", _a_pdf_file_name_loses_its_extension)

	def _the_displayed_format_round_trips():
		"""Somebody pasting the number back as the report prints it."""
		_assert(N("AHF/26-27/10234") == "10234", N("AHF/26-27/10234"))
		_assert(N("AHF/26-27/9863") == "9863", N("AHF/26-27/9863"))

	check("the AHF/<FY>/<number> display format yields the number",
		_the_displayed_format_round_trips)

	def _excel_float_cells():
		"""A numeric cell can arrive as "10000.0".

		The trailing-digit match would otherwise take the single 0 after the point -- a
		quieter version of the same bug, so it is closed here rather than left to be found.
		"""
		_assert(N("10000.0") == "10000", N("10000.0"))
		_assert(N("9863.00") == "9863", N("9863.00"))

	check("a numeric cell arriving as 10000.0 reads as 10000", _excel_float_cells)

	def _nothing_is_still_nothing():
		for raw in ("", "   ", None):
			_assert(N(raw) == "", f"{raw!r} -> {N(raw)!r}")

	check("an empty cell yields nothing, and does not raise", _nothing_is_still_nothing)

	def _a_number_that_is_not_a_number_is_kept_as_typed():
		"""Better to carry it through than to store a slice of it or drop the row.

		The old code turned "6057A" into "057A"; dropping the row would lose it silently.
		"""
		_assert(N("6057A") == "6057A", N("6057A"))

	check("a non-numeric invoice is kept as typed, not sliced",
		_a_number_that_is_not_a_number_is_kept_as_typed)

	def _no_two_numbers_collide_any_more():
		"""The damaging consequence, stated as its own check.

		Under the last-four rule "10001" and "0001" both became "0001" -- a new invoice
		silently taking an old invoice's number. They must now stay distinct.
		"""
		_assert(N("10001") != N("0001"),
			"a five-digit invoice still collapses onto a four-digit one")

	check("a five-digit number no longer collides with a four-digit one",
		_no_two_numbers_collide_any_more)
