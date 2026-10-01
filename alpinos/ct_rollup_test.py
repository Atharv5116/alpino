"""Prove the Customer Type rollup MOVES quantities and never creates or loses any.

Run:  bench --site alpinos.test execute alpinos.ct_rollup_test.run
"""
import frappe

from alpinos.dispatch_report_api import get_dispatch_report_data

DATE = "2026-07-22"
R = []


def _check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _cols(payload):
	return {k: v for k, v in (payload["summary"].get("dispatch_by_ct") or {}).items() if v}


def _headings(payload):
	return [c["name"] for c in payload["customer_types"]]


def _item_cols(payload):
	"""Per-item breakdown, so the grid and the summary are checked separately."""
	out = {}
	for it in payload.get("items") or []:
		for col, qty in (it.get("dispatch_by_ct") or {}).items():
			if qty:
				out[col] = out.get(col, 0) + qty
	return out


def run():
	R.clear()
	frappe.set_user("Administrator")

	# The roll-up is what the Group by Parent Customer Type toggle does, so every
	# reading here is taken with it ON. The toggle-OFF view is asserted separately
	# below -- that it does NOT roll up is the whole point of it being a toggle.
	base = get_dispatch_report_data(date=DATE, group_by_parent=1)
	before, headings_before = _cols(base), _headings(base)
	grand_before = base["summary"]["dispatch_total"]
	items_before = _item_cols(base)

	movers = sorted(((v, k) for k, v in before.items() if k != "Other"), reverse=True)
	assert len(movers) >= 2, f"need two columns with data on {DATE}: {before}"
	(child_qty, child), (parent_qty, parent) = movers[0], movers[1]
	print(f"child  = {child!r} ({child_qty})\nparent = {parent!r} ({parent_qty})\n")

	frappe.db.set_value("Alpino Customer Type", child, "parent_customer_type", parent)
	frappe.db.commit()
	frappe.clear_cache()
	try:
		after = get_dispatch_report_data(date=DATE, group_by_parent=1)
		cols, headings = _cols(after), _headings(after)
		items_after = _item_cols(after)

		_check(
			"the child no longer has a column of its own",
			lambda: _assert(child not in cols, f"{child} still carries {cols.get(child)}"),
		)
		_check(
			"the parent absorbed exactly the child's quantity",
			lambda: _assert(
				cols.get(parent) == parent_qty + child_qty,
				f"{cols.get(parent)} != {parent_qty} + {child_qty}",
			),
		)
		_check(
			"the grand total is unchanged, so nothing was created or lost",
			lambda: _assert(
				after["summary"]["dispatch_total"] == grand_before,
				f"{grand_before} -> {after['summary']['dispatch_total']}",
			),
		)
		_check(
			"the child is no longer drawn as a column heading",
			lambda: _assert(child not in headings, "child still in customer_types"),
		)
		_check(
			"every other column is untouched",
			lambda: _assert(
				{k: v for k, v in cols.items() if k != parent}
				== {k: v for k, v in before.items() if k not in (parent, child)},
				"a column that should not have moved changed",
			),
		)
		_check(
			"the per-item grid moved with the summary, not against it",
			lambda: _assert(
				items_after.get(parent, 0) == items_before.get(parent, 0) + items_before.get(child, 0)
				and child not in items_after,
				f"grid: {items_after.get(parent)} vs {items_before.get(parent)}+{items_before.get(child)}",
			),
		)

		# The guard rails on the master itself.
		def _self_parent():
			d = frappe.get_doc("Alpino Customer Type", parent)
			d.parent_customer_type = parent
			d.save(ignore_permissions=True)

		_check("a type cannot be its own parent", lambda: _expect_throw(_self_parent, "own parent"))

		def _two_levels():
			d = frappe.get_doc("Alpino Customer Type", parent)
			d.parent_customer_type = movers[2][1] if len(movers) > 2 else "Other"
			d.save(ignore_permissions=True)

		_check(
			"a type that already has children cannot itself get a parent",
			lambda: _expect_throw(_two_levels, "one level"),
		)
		# The toggle is the ONLY thing that rolls up: with it off, a type that has a
		# parent still reports in its own column. Without this the feature could
		# silently become always-on and every check above would still pass.
		flat = get_dispatch_report_data(date=DATE, group_by_parent=0)
		flat_cols, flat_headings = _cols(flat), _headings(flat)
		_check(
			"with the toggle off the child keeps its own column",
			lambda: _assert(
				flat_cols.get(child) == child_qty,
				f"{child} = {flat_cols.get(child)}, expected {child_qty}",
			),
		)
		_check(
			"with the toggle off the child is still a column heading",
			lambda: _assert(child in flat_headings, "child heading disappeared without the toggle"),
		)
		_check(
			"with the toggle off the parent did NOT absorb the child",
			lambda: _assert(
				flat_cols.get(parent) == parent_qty,
				f"{parent} = {flat_cols.get(parent)}, expected {parent_qty}",
			),
		)
	finally:
		frappe.db.set_value("Alpino Customer Type", child, "parent_customer_type", None)
		frappe.db.commit()
		frappe.clear_cache()

	# The "Other" column is added from the DATA, not the master, so a quantity with no
	# Customer Type (a Material Issue especially) cannot go invisible under the toggle.
	# Exercised directly: on most days nothing lands in Other, so this branch would
	# otherwise ship untested.
	from alpinos.dispatch_report_api import _with_other

	cols_in = [{"name": "A", "abbr": "A"}]
	_check(
		"Other is not added when nothing landed there",
		lambda: _assert([c["name"] for c in _with_other(cols_in, {"X": {"by_ct": {"A": 5}}}, {})] == ["A"]),
	)
	_check(
		"Other is added when a dispatched quantity has no type",
		lambda: _assert(
			[c["name"] for c in _with_other(cols_in, {"X": {"by_ct": {"Other": 3}}}, {})] == ["A", "Other"]
		),
	)
	_check(
		"Other is added when only a PENDING quantity has no type",
		lambda: _assert(
			[c["name"] for c in _with_other(cols_in, {}, {"X": {"by_ct": {"Other": 7}}})] == ["A", "Other"]
		),
	)
	_check(
		"a zero in Other does not draw an empty column",
		lambda: _assert([c["name"] for c in _with_other(cols_in, {"X": {"by_ct": {"Other": 0}}}, {})] == ["A"]),
	)
	_check(
		"the heading list handed in is never mutated",
		lambda: _assert(cols_in == [{"name": "A", "abbr": "A"}], "caller list was mutated"),
	)

	restored = get_dispatch_report_data(date=DATE, group_by_parent=1)
	_check(
		"clearing the parent restores the original columns exactly",
		lambda: _assert(
			_cols(restored) == before and _headings(restored) == headings_before,
			"the report did not return to its original shape",
		),
	)

	width = max(len(r[1]) for r in R)
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print(f"{passed}/{len(R)} passed")
	return R


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _expect_throw(fn, fragment):
	try:
		fn()
	except Exception as e:
		_assert(fragment.lower() in str(e).lower(), f"threw, but lacked {fragment!r}: {str(e)[:160]}")
		return
	raise AssertionError("expected an exception, none raised")
