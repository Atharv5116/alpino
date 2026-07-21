"""Broken-image-tolerant PDF download.

Frappe fails the WHOLE PDF when wkhtmltopdf can't load a single image
("PDF generation failed because of broken image links") — a private or
deleted item image (custom_product_image on the Sales Order print) takes the
whole document down. Frappe ships the `load-error-handling: ignore` option
commented out and blocks it from meta tags, so the only way in is to add it to
the wkhtmltopdf options before generation.

This wraps the download_pdf endpoint (wired via override_whitelisted_methods)
and tells wkhtmltopdf to IGNORE images it can't load, so the PDF still renders
(without the unreachable image) instead of erroring out.
"""

import frappe

_patched = False


def _patch_ignore_broken_images():
	"""Monkey-patch frappe.utils.pdf.prepare_options once so every PDF built in
	this worker tolerates unloadable images. Idempotent."""
	global _patched
	if _patched:
		return
	import frappe.utils.pdf as fpdf

	_orig_prepare = fpdf.prepare_options

	def prepare_options(html, options):
		html, options = _orig_prepare(html, options)
		# ignore = keep going when an image / media resource can't be fetched.
		options.setdefault("load-error-handling", "ignore")
		options.setdefault("load-media-error-handling", "ignore")
		return html, options

	fpdf.prepare_options = prepare_options
	_patched = True


@frappe.whitelist()
def download_pdf(
	doctype,
	name,
	format=None,
	doc=None,
	no_letterhead=0,
	language=None,
	letterhead=None,
	pdf_generator=None,
):
	"""Drop-in for frappe.utils.print_format.download_pdf that tolerates broken
	images. Called instead of the core method via override_whitelisted_methods."""
	_patch_ignore_broken_images()
	from frappe.utils.print_format import download_pdf as _orig_download_pdf

	return _orig_download_pdf(
		doctype,
		name,
		format=format,
		doc=doc,
		no_letterhead=no_letterhead,
		language=language,
		letterhead=letterhead,
		pdf_generator=pdf_generator,
	)
