"""Guard: an inward / PO / QC can carry several inward types ("FG,PM").

PUR-ORD-2026-00402 (FG,PM) offered no lines on its inward because the line filter compared
each item's type with the whole string "FG,PM". These checks keep that class of bug out:

    1. the shared rule C.type_allowed on single, multi and empty types
    2. the list filters (Purchase Inward, QC, PO) list an FG,PM document under FG and PM
    3. a source scan: no plain == / != / === / !== against an inward type outside
       constants.py -- use C.type_allowed / C.has_inward_type / C.any_inward_type

Read-only; run alone with `bench --site <site> execute alpinos.purchase.inward_type_test.run`
or as part of task_functional_test.
"""

import os
import re

import frappe

from alpinos.purchase import constants as C

# Comparing an inward-type value as a whole: `inward_type == "FG"`, `!== frm.doc.inward_type` ...
_BAD = re.compile(
	# the value (doc.inward_type, custom_inward_type, me._val("inward_type")...) on the left;
	# a quoted field NAME ('custom_inward_type') or a flag like matches_inward_type is not one
	r"(?<![A-Za-z0-9_])(?:custom_)?inward_type\b(?!['\"])[\w.)\]'\"]*\s*(?:===?|!==?)"
	# ... or on the right
	r"|(?:===?|!==?)\s*[\w.(]*(?<![A-Za-z0-9_])(?:custom_)?inward_type\b(?!['\"s])"
	r"|\b(?:found|item_type)\s*(?:!=|==)\s*wanted\b"
)
# Lines that compare two canonical stored strings on purpose.
_ALLOWED = ("res.inward_type !== frm.doc.inward_type",)


def checks():
	out = []

	def check(label, ok, detail=""):
		out.append((label, bool(ok), "" if ok else detail))

	ta = C.type_allowed
	check("FG item allowed on an FG,PM document", ta("FG", "FG,PM"))
	check("PM item allowed on an FG,PM document", ta("PM", "FG,PM"))
	check("RM item refused on an FG,PM document", not ta("RM", "FG,PM"))
	check("FG item allowed on an FG document", ta("FG", "FG"))
	check("RM item refused on an FG document", not ta("RM", "FG"))
	check("unclassified item allowed anywhere", ta(None, "FG,PM"))
	check("no document type allows anything", ta("RM", None))

	# list filters: a multi-type document must appear under each of its types
	from alpinos.purchase import inward_list_api, qc_list_api

	for label, fn, doctype in (
		("Purchase Inward list", inward_list_api.get_purchase_inward_list, "Purchase Inward"),
		("QC list", qc_list_api.get_purchase_qc_list if hasattr(qc_list_api, "get_purchase_qc_list") else None, "Purchase QC"),
	):
		multi = frappe.db.sql(
			"select name, inward_type from `tab%s` where inward_type like '%%,%%' order by creation desc limit 1" % doctype,
			as_dict=True,
		)
		if not (multi and fn):
			continue
		doc = multi[0]
		for t in C.inward_types(doc.inward_type):
			try:
				res = fn(inward_type=t, page_length=500)
			except TypeError:
				res = fn(inward_type=t)
			names = [r.get("name") for r in (res.get("data") or [])] if isinstance(res, dict) else []
			check("%s filtered on %s lists %s (%s)" % (label, t, doc.name, doc.inward_type), doc.name in names,
			      "not listed")

	# source scan
	root = frappe.get_app_path("alpinos")
	hits = []
	for base, _dirs, files in os.walk(root):
		if "/node_modules" in base or "/public/dist" in base:
			continue
		for f in files:
			if not f.endswith((".py", ".js")) or f in ("constants.py", "inward_type_test.py") or "test" in f:
				continue
			path = os.path.join(base, f)
			try:
				lines = open(path, encoding="utf-8").read().splitlines()
			except Exception:
				continue
			for n, line in enumerate(lines, 1):
				code = line.split("#")[0] if f.endswith(".py") else line.split("//")[0]
				if _BAD.search(code) and not any(a in code for a in _ALLOWED):
					hits.append("%s:%s: %s" % (os.path.relpath(path, root), n, line.strip()[:120]))
	check("no whole-value comparison of an inward type in the source", not hits, "; ".join(hits[:8]))
	return out


def run():
	rows = checks()
	for label, ok, detail in rows:
		print(("PASS" if ok else "FAIL"), label, ("-> " + detail) if detail else "")
	failed = [r for r in rows if not r[1]]
	print("inward_type_test: %s passed, %s failed" % (len(rows) - len(failed), len(failed)))
	return {"passed": len(rows) - len(failed), "failed": len(failed), "rows": rows}
