"""Broken-image-tolerant PDF download + private-image inlining.

Two problems this fixes for the Sales Order (and any) PDF:

1. Frappe fails the WHOLE PDF when wkhtmltopdf can't load a single image
   ("PDF generation failed because of broken image links").
2. wkhtmltopdf runs as a separate process with no login session, so it cannot
   fetch PRIVATE files (/private/files/...). Item images that show fine in the
   browser (which has the user's session) come out blank in the PDF.

Fix: before generation we (a) inline every local frappe file image as a base64
data URI — read server-side, where private files ARE accessible, so the picture
travels inside the HTML and wkhtmltopdf needs no HTTP fetch — and (b) tell
wkhtmltopdf to ignore any image it still can't load, so one bad image never
fails the document.

Wired via override_whitelisted_methods on download_pdf.
"""

import base64
import mimetypes
import re

import frappe

_patched = False

# <img ... src="URL" ...>
_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)
# the frappe file path inside a (possibly absolute) URL
_FILE_PATH_RE = re.compile(r"(/private/files/[^\s\"'?#]+|/files/[^\s\"'?#]+)")


def _data_uri_for(file_url, cache):
	"""Return a base64 data: URI for a frappe file URL, or None if it can't be
	read. Cached per call so a repeated image is only encoded once."""
	if file_url in cache:
		return cache[file_url]
	result = None
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if name:
			content = frappe.get_doc("File", name).get_content()
			if content:
				if isinstance(content, str):
					content = content.encode("utf-8", "ignore")
				mime = mimetypes.guess_type(file_url)[0] or "image/png"
				result = "data:%s;base64,%s" % (mime, base64.b64encode(content).decode())
	except Exception:
		result = None
	cache[file_url] = result
	return result


def _inline_local_images(html):
	"""Replace <img src> pointing to a local frappe file (public OR private) with
	an inline base64 data URI so wkhtmltopdf renders it without an HTTP fetch."""
	if not html or "<img" not in html:
		return html
	cache = {}

	def repl(m):
		src = m.group(2)
		if src.startswith("data:"):
			return m.group(0)
		path = _FILE_PATH_RE.search(src)
		if not path:
			return m.group(0)
		data_uri = _data_uri_for(path.group(1), cache)
		if not data_uri:
			return m.group(0)
		return m.group(1) + data_uri + m.group(3)

	return _IMG_SRC_RE.sub(repl, html)


def _patch_pdf_once():
	"""Monkey-patch frappe.utils.pdf.prepare_options once so every PDF built in
	this worker inlines local images and tolerates unloadable ones. Idempotent."""
	global _patched
	if _patched:
		return
	import frappe.utils.pdf as fpdf

	_orig_prepare = fpdf.prepare_options

	def prepare_options(html, options):
		html, options = _orig_prepare(html, options)
		html = _inline_local_images(html)
		# ignore = keep going if an image / media resource still can't be fetched.
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
	"""Drop-in for frappe.utils.print_format.download_pdf that inlines local
	images and tolerates broken ones. Called via override_whitelisted_methods."""
	_patch_pdf_once()
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
