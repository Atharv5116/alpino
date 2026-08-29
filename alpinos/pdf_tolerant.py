"""Broken-image-tolerant PDF download + private-image inlining."""

import base64
import mimetypes
import os
import re
from html import unescape as html_unescape
from urllib.parse import unquote

import frappe

_patched = False

_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(r'\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
# match up to a query/fragment, not the first space (filenames can have spaces)
_FILE_PATH_RE = re.compile(r"(/(?:private/)?files/[^?#]+)")


def _url_variants(file_url):
	variants = []
	for v in (file_url, html_unescape(file_url)):
		for w in (v, unquote(v)):
			if w and w not in variants:
				variants.append(w)
	return variants


def _disk_path(file_url):
	if file_url.startswith("/private/files/"):
		return frappe.get_site_path("private", "files", file_url.split("/private/files/", 1)[1])
	if file_url.startswith("/files/"):
		return frappe.get_site_path("public", "files", file_url.split("/files/", 1)[1])
	return None


def _file_url_exists(file_url):
	for fu in _url_variants(file_url):
		try:
			if frappe.db.exists("File", {"file_url": fu}):
				return True
		except Exception:
			pass
		try:
			p = _disk_path(fu)
			if p and os.path.isfile(p):
				return True
		except Exception:
			pass
	return False


def first_existing_file_url(candidates):
	for url in candidates:
		if url and _file_url_exists(url):
			return url
	return None


def _read_file_bytes(file_url):
	variants = _url_variants(file_url)
	# via the File doc
	for fu in variants:
		try:
			name = frappe.db.get_value("File", {"file_url": fu}, "name")
			if name:
				content = frappe.get_doc("File", name).get_content()
				if content:
					return content
		except Exception:
			pass
	# direct disk read as a fallback
	for fu in variants:
		try:
			p = _disk_path(fu)
			if p and os.path.isfile(p):
				with open(p, "rb") as f:
					return f.read()
		except Exception:
			pass
	return None


def _data_uri_for(file_url, cache):
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
	"""Inline local frappe images as data URIs, dropping unreadable ones."""
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
			return tag
		data_uri = _data_uri_for(path.group(1), cache)
		if data_uri:
			return tag[: sm.start(1)] + data_uri + tag[sm.end(1) :]
		dropped.append(src)
		return ""  # drop unreadable local image so the PDF still builds

	out = _IMG_TAG_RE.sub(repl, html)
	if dropped:
		frappe.logger("alpinos").info(
			"PDF: skipped %d broken image link(s): %s" % (len(dropped), ", ".join(dropped[:5]))
		)
	return out


def _patch_pdf_once():
	"""Patch frappe.utils.pdf.prepare_options once to inline images and tolerate broken ones."""
	global _patched
	if _patched:
		return
	import frappe.utils.pdf as fpdf

	_orig_prepare = fpdf.prepare_options

	def prepare_options(html, options):
		html, options = _orig_prepare(html, options)
		html = _process_images(html)
		# keep going if an image/media resource can't be fetched
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
	"""Drop-in for print_format.download_pdf that inlines images and tolerates broken ones."""
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
