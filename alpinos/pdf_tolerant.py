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
import os
import re
from urllib.parse import unquote

import frappe

_patched = False

# a whole <img ...> tag, and the src="..." attribute inside one
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(r'\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
# the frappe file path inside a (possibly absolute) URL. The filename may contain
# spaces and other characters (e.g. "/files/Dark Chocolate Oats_2 KG front.jpeg"),
# so match everything up to a query/fragment — NOT up to the first space, which would
# truncate the path and make the image un-resolvable (then dropped as "broken").
_FILE_PATH_RE = re.compile(r"(/(?:private/)?files/[^?#]+)")


def _read_file_bytes(file_url):
	"""Return the raw bytes for a frappe file URL, or None if it can't be read.
	Tries the File doc first (handles private + DB-stored content), then a direct
	disk read (the File doc may be missing while the file still exists). The URL may
	arrive percent-encoded (…/Dark%20Chocolate…) or with literal spaces, and the
	stored File.file_url uses literal spaces, so try both forms."""
	candidates = [file_url]
	decoded = unquote(file_url)
	if decoded != file_url:
		candidates.append(decoded)
	# 1) via the File doc (raw + url-decoded)
	for fu in candidates:
		try:
			name = frappe.db.get_value("File", {"file_url": fu}, "name")
			if name:
				content = frappe.get_doc("File", name).get_content()
				if content:
					return content
		except Exception:
			pass
	# 2) direct disk read as a fallback (decoded path)
	for fu in candidates:
		try:
			if fu.startswith("/private/files/"):
				path = frappe.get_site_path("private", "files", fu.split("/private/files/", 1)[1])
			elif fu.startswith("/files/"):
				path = frappe.get_site_path("public", "files", fu.split("/files/", 1)[1])
			else:
				continue
			if os.path.isfile(path):
				with open(path, "rb") as f:
					return f.read()
		except Exception:
			pass
	return None


def _data_uri_for(file_url, cache):
	"""Return a base64 data: URI for a frappe file URL, or None if it can't be
	read. Cached per call so a repeated image is only encoded once."""
	if file_url in cache:
		return cache[file_url]
	result = None
	content = _read_file_bytes(file_url)
	if content:
		if isinstance(content, str):
			content = content.encode("utf-8", "ignore")
		mime = mimetypes.guess_type(file_url)[0] or "image/png"
		result = "data:%s;base64,%s" % (mime, base64.b64encode(content).decode())
	cache[file_url] = result
	return result


def _process_images(html):
	"""Make every <img> safe for wkhtmltopdf so a bad image can never fail the PDF:

	* local frappe file (public OR private) -> inline it as a base64 data URI, so no
	  HTTP fetch is needed (private files aren't reachable from wkhtmltopdf's session);
	* local frappe file that can't be read (deleted / missing File doc) -> DROP the
	  <img> tag, since an unreachable link is exactly what triggers the
	  "broken image links" failure;
	* anything else (already-inlined data: URIs, genuinely remote URLs) -> left as-is
	  and covered by the load-error-handling=ignore option below.
	"""
	if not html or "<img" not in html:
		return html
	cache = {}
	dropped = []

	def repl(m):
		tag = m.group(0)
		sm = _SRC_ATTR_RE.search(tag)
		if not sm:
			return tag
		src = sm.group(1)
		if src.startswith("data:"):
			return tag
		path = _FILE_PATH_RE.search(src)
		if not path:
			return tag  # not a local frappe file; leave it for load-error-handling
		data_uri = _data_uri_for(path.group(1), cache)
		if data_uri:
			return tag[: sm.start(1)] + data_uri + tag[sm.end(1) :]
		dropped.append(src)
		return ""  # broken/unreadable local image -> drop so the PDF still builds

	out = _IMG_TAG_RE.sub(repl, html)
	if dropped:
		frappe.logger("alpinos").info(
			"PDF: skipped %d broken image link(s): %s" % (len(dropped), ", ".join(dropped[:5]))
		)
	return out


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
		html = _process_images(html)
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
