"""Changes(HP) #46: put the EXISTING Buyer Master IDs in the financial-year format too.

Changes(HP) #40 gave new buyers OBM-<financial year>-<number> (OBM-2627-01027) and left the
older OBM-<calendar year>-<number> IDs alone, which was the call at the time. They now
follow as well: OBM-2026-00678 -> OBM-2627-00678. Only the year segment changes. The
running number is what people quote and what the Sales Orders were raised against, so it is
carried over exactly, which also means no ID can collide with a number already issued.

The rename goes through frappe.rename_doc, so every reference follows it: the Sales Order's
custom_offline_buyer_master and a child's parent_buyer are the only two Link fields pointing
at a Buyer Master, and there are no Dynamic Links. The buyer's Customer is NOT renamed --
its id is its business name plus GSTIN and is quoted outside the system.

	bench --site SITE execute alpinos.buyer_id_reformat.run                       # dry run
	bench --site SITE execute alpinos.buyer_id_reformat.run --kwargs "{'apply':1}"
	bench --site SITE execute alpinos.buyer_id_reformat.run --kwargs "{'apply':1,'sample':0}"
"""

import re

import frappe

# OBM-<4 digits>-<number>. The 4 digits are either a calendar year (2026, to be converted)
# or a financial year already (2627).
_ID = re.compile(r"^OBM-(\d{4})-(\d+)$")


def target_name(name):
	"""The financial-year id for an old one, or None when it is already right / unknown.

	2026 -> 2627. A segment whose halves already run consecutively (2627) is a financial
	year and is left alone. 2021 is the one genuinely ambiguous value -- calendar 2021 or
	financial 2020-21 -- and is reported rather than guessed at.
	"""
	m = _ID.match(name or "")
	if not m:
		return None
	year, number = m.group(1), m.group(2)
	first, second = int(year[:2]), int(year[2:])
	if second == first + 1:
		return None  # already a financial year
	if not 2000 <= int(year) <= 2099:
		return None
	start = int(year)
	return f"OBM-{start % 100:02d}{(start + 1) % 100:02d}-{number}"


def _ambiguous(name):
	"""True for OBM-2021-x, where the year reads as both a calendar and a financial year."""
	m = _ID.match(name or "")
	if not m:
		return False
	year = m.group(1)
	return int(year[2:]) == int(year[:2]) + 1 and 2000 <= int(year) <= 2099 and int(year[:2]) == 20


@frappe.whitelist()
def run(apply=0, sample=25, only=None):
	"""Dry run by default; apply=1 renames. sample caps the pairs listed back (0 = all).

	only: a list of buyer ids to act on instead of every one, for a staged run or to retry
	the ones a run reported under "failed".
	"""
	apply = int(apply)
	sample = int(sample)

	if only:
		if isinstance(only, str):
			only = frappe.parse_json(only)
		names = [n for n in only if frappe.db.exists("Buyer Master", n)]
	else:
		# The LIKE wildcard is doubled: frappe.db.sql hands the query to pymysql for formatting.
		names = frappe.db.sql_list(
			"SELECT name FROM `tabBuyer Master` WHERE name LIKE 'OBM-%%' ORDER BY name"
		)
	pairs, taken, ambiguous = [], [], []
	for old in names:
		if _ambiguous(old):
			ambiguous.append(old)
			continue
		new = target_name(old)
		if not new or new == old:
			continue
		if frappe.db.exists("Buyer Master", new):
			taken.append({"old": old, "new": new})
			continue
		pairs.append({"old": old, "new": new})

	renamed, failed = 0, []
	if apply:
		for pair in pairs:
			try:
				frappe.rename_doc("Buyer Master", pair["old"], pair["new"], force=True, show_alert=False)
				renamed += 1
			except Exception as e:
				failed.append({"old": pair["old"], "new": pair["new"], "error": str(e)[:200]})
		frappe.db.commit()

	return {
		"mode": "APPLY" if apply else "DRY-RUN",
		"buyers": len(names),
		"to_rename": len(pairs),
		"renamed": renamed,
		# A number already carrying the financial-year id: left as it is, never merged.
		"target_taken": taken,
		# OBM-2021-x, which reads as both a calendar and a financial year: decide by hand.
		"ambiguous": ambiguous,
		"failed": failed,
		"sample": pairs if not sample else pairs[:sample],
	}
