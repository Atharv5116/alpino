"""Item sequence management: shift existing items to keep custom_sequence contiguous."""

import frappe


def reorder_on_insert(doc, method=None):
	"""Shift sequences to make room before a new item is inserted."""
	seq = doc.custom_sequence
	if not seq:
		return

	frappe.db.sql(
		"""
		UPDATE `tabItem`
		SET custom_sequence = custom_sequence + 1
		WHERE custom_sequence >= %s
		""",
		(seq,),
	)


def reorder_on_save(doc, method=None):
	"""Shift sequences when an existing item's sequence changes."""
	new_seq = doc.custom_sequence
	if not new_seq:
		return

	old_seq = frappe.db.get_value("Item", doc.name, "custom_sequence")
	if not old_seq or old_seq == new_seq:
		return

	if new_seq < old_seq:
		# Moving earlier: shift items in [new_seq, old_seq-1] up by 1
		frappe.db.sql(
			"""
			UPDATE `tabItem`
			SET custom_sequence = custom_sequence + 1
			WHERE custom_sequence >= %s AND custom_sequence < %s AND name != %s
			""",
			(new_seq, old_seq, doc.name),
		)
	else:
		# Moving later: shift items in (old_seq, new_seq] down by 1
		frappe.db.sql(
			"""
			UPDATE `tabItem`
			SET custom_sequence = custom_sequence - 1
			WHERE custom_sequence > %s AND custom_sequence <= %s AND name != %s
			""",
			(old_seq, new_seq, doc.name),
		)
