"""The page and the font every Purchase module print format prints with.

Print (the browser's own print dialog on the print view) and PDF (wkhtmltopdf on the
server) are two different engines, and the client found they did not match on paper:

* The formats asked for Arial. Windows browsers have it; the server does not, so the PDF
  quietly fell back to DejaVu Sans -- a much wider face -- and dates, names and headings
  wrapped onto extra lines.
* The browser used its own default page margins (about 10 mm); the PDF used Frappe's
  15 mm, so every table in the PDF was 12 mm narrower.

Both now come from here: one embedded font, Alpinos Print Sans (a subset of Liberation Sans,
which has Arial's metrics -- see fonts/README.txt), and one page with 10 mm margins. The font
is embedded as data rather than linked, so the PDF never depends on the server reaching its
own URL.

The formats themselves keep line-height and letter-spacing in whole pixels: wkhtmltopdf
rounds fractional values (the browser does not), which moved every line of a long print.
"""

import base64
import os

FAMILY = "Alpinos Print Sans"
PAGE_MARGIN = "10mm"

_FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_FACES = (("AlpinosPrintSans-Regular", "normal"), ("AlpinosPrintSans-Bold", "bold"))


def font_face_css():
	rules = []
	for face, weight in _FACES:
		with open(os.path.join(_FONT_DIR, face + ".ttf"), "rb") as f:
			data = base64.b64encode(f.read()).decode("ascii")
		# local() must come first, and not only as a courtesy: before handing the page to
		# wkhtmltopdf, frappe.utils.expand_relative_urls rewrites every ": url(...)" to
		# "url(...) !important" -- data: URLs included -- which makes the src descriptor
		# invalid, so the PDF silently fell back to DejaVu Sans. ", url(" is left alone.
		rules.append(
			"@font-face { font-family: '%s'; font-style: normal; font-weight: %s; "
			"src: local('%s'), url(data:font/truetype;base64,%s) format('truetype'); }"
			% (FAMILY, weight, face, data)
		)
	return "\n".join(rules)


def page_head(size="A4"):
	"""The <style> block a module print format starts with.

	`size` is the paper the browser is told to use; None leaves it to the print dialog.
	"""
	m = PAGE_MARGIN
	page = "@page { %smargin: %s; }" % ("size: %s; " % size if size else "", m)
	return "\n".join(
		(
			"<style>",
			font_face_css(),
			# The browser's print dialog takes the page from @page (Margins: Default).
			page,
			# wkhtmltopdf ignores @page and takes its page margins from a top-level
			# .print-format rule instead (frappe.utils.pdf.read_options_from_html). The
			# element itself must not keep them: both engines print with print media, so the
			# @media print rule zeroes them there, and the on-screen preview stays centred.
			".print-format { margin-top: %s; margin-right: %s; margin-bottom: %s; margin-left: %s; }"
			% (m, m, m, m),
			"@media print { .print-format { margin: 0 !important; } }",
			"@media screen { .print-format { margin: auto !important; } }",
			"</style>",
		)
	)
