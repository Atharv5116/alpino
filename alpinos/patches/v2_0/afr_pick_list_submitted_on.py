"""Changes(HP) #110: Submitted On for Pick Lists submitted before the field existed, from the
Version that recorded the submission (docstatus 0 -> 1). One with no such Version is left blank."""

import frappe


def execute():
	from alpinos.afr_export import setup

	setup()
	if not frappe.db.has_column("Pick List", "custom_submitted_on"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabPick List` pl
		JOIN (
			SELECT v.docname, MIN(v.creation) AS submitted
			FROM `tabVersion` v
			WHERE v.ref_doctype = 'Pick List' AND v.data LIKE '%%["docstatus",0,1]%%'
			GROUP BY v.docname
		) s ON s.docname = pl.name
		SET pl.custom_submitted_on = s.submitted
		WHERE pl.docstatus >= 1 AND pl.custom_submitted_on IS NULL
		"""
	)
