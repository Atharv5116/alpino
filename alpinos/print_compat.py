"""Print font: give Frappe v16 prints the font list v15 used.

Frappe 16.51 ships a malformed default print font (frappe/www/printview.py get_font): the
list has an unbalanced quote (`-apple-system"`) and a stray `;` inside the string. That
string goes into every print's `.print-format { font-family: ... }`, so wkhtmltopdf drops
the declaration and falls back to whatever the machine's default is; a Purchase Order came
out in a different face and weight than on v15. v15's list was valid.

When Print Settings and the print format leave the font at Default, this hands back v15's
list instead, so v15 and v16 give wkhtmltopdf the same CSS. A font chosen in Print
Settings or on a print format is left alone, and on v15 nothing changes (its default never
matches). Applied when hooks load, like quotation_obm_patch, so background and bulk PDFs
get it too, not only web requests.
"""

V15_DEFAULT_FONT = 'Inter, "Helvetica Neue", Helvetica, Arial, "Open Sans", sans-serif'


def apply_print_font_fix():
	try:
		import frappe.www.printview as printview
	except Exception:
		return
	original = printview.get_font
	if getattr(original, "_alpinos_v15_font", False):
		return

	def get_font(print_settings, print_format=None, for_legacy=False):
		font = original(print_settings, print_format, for_legacy)
		if "InterVariable" in font and '-apple-system"' in font:
			return V15_DEFAULT_FONT
		return font

	get_font._alpinos_v15_font = True
	printview.get_font = get_font
