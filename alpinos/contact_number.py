"""One rule for every contact number in the app: exactly 10 digits, or blank.

Surrounding spaces are trimmed. Anything else -- letters, a +91 prefix, spaced groups,
9 or 11 digits -- is refused rather than guessed at, because guessing is how a number that
looks fine turns out to be undialable.

Enforced at the `validate` hook rather than on the entry screens, so a record saved from a
module screen, the desk form, an import or the REST API is held to the same rule. A
`length=10` on the column would be the obvious alternative and is deliberately not used:
shrinking a Data column truncates what is already stored.

**Forward-only, and on this site that is not a nicety.** Five submitted Purchase Inwards
already hold an Actual Driver Contact Number that is not 10 digits ("ew", "5", "34",
"rggfe", a 13-digit number). That field is `allow_on_submit`, so Store Receiving goes on
editing those records through `before_update_after_submit` -- which is where this rule is
hooked. A blanket check would make all five permanently unsaveable, over a number the
person saving was not touching. Seven Purchase Orders hold the same kind of value; they
are all submitted, so the older validate-only check never fired on them, but amending one
copies the value into a fresh draft where it would have.

So a value that is already stored is left alone, and only a new or changed one has to
pass. Correcting one still works -- the corrected value is a changed one, and 10 digits.
"""

import re

import frappe
from frappe import _

#: Indian mobile numbers, which is every contact number these screens collect.
CONTACT_DIGITS = 10

_EXACTLY_TEN_DIGITS = re.compile(r"\d{%d}" % CONTACT_DIGITS)


def is_valid(value):
	"""True when `value` is exactly 10 digits, ignoring surrounding spaces."""
	return bool(_EXACTLY_TEN_DIGITS.fullmatch(str(value or "").strip()))


def describe():
	"""The one-line field description, so every screen says the same thing."""
	return _("{0}-digit number.").format(CONTACT_DIGITS)


def _unchanged(doc, fieldname, value, before):
	"""Is this exactly what is already stored? Then it is not this save's business."""
	if before is None:
		return False
	return str(before.get(fieldname) or "").strip() == value


def validate_fields(doc, fields, method=None):
	"""Hold each named field on `doc` to the 10-digit rule.

	`fields` maps fieldname -> the label to use in the message, so the error names the
	field the person is looking at ("Driver Contact Number", not "contact_no").

	Trimming happens on every save, including of an old record: removing stray spaces
	cannot make a stored value worse, and it stops a number failing only because it was
	pasted with a trailing space.
	"""
	# Loaded by document.load_doc_before_save(), which runs before the validate methods,
	# so this is available here. None for a new document, which is the point.
	before = None if doc.is_new() else doc.get_doc_before_save()

	for fieldname, label in fields.items():
		raw = doc.get(fieldname)
		if raw is None:
			continue
		value = str(raw).strip()
		if value != raw:
			doc.set(fieldname, value)
		if not value or is_valid(value):
			continue
		if _unchanged(doc, fieldname, value, before):
			continue
		frappe.throw(
			_("{0} must be a {1}-digit number (digits only). {2} is not.").format(
				_(label), CONTACT_DIGITS, frappe.bold(value)
			),
			title=_("Invalid {0}").format(_(label)),
		)
