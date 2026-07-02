"""Invoice PDF integration (spec §5) — Excel-driven.

Workflow (driven from the "Invoice Sync" page):
  1. Download the Accounts Format report as Excel (Invoice No column blank).
  2. Accounts fill the Invoice No against each Sales Order and re-upload the Excel.
  3. process_invoice_excel() reads Sales Order Id <-> Invoice No, stores the invoice number on
     each Sales Order, then (if Drive is configured) fetches the matching PDF
     (filename == Invoice No) from the Drive folder structure  <root> -> <Month>  and attaches
     it. The invoice is shown on the Sales Order only once its status is Dispatched.

Drive note: the shared folder IS the F.Y. folder and contains month sub-folders directly
(April / May / June ...). Configure Drive Root Folder ID = that folder and leave FY Label blank.
Requires google libs in the bench env:  bench pip install google-api-python-client google-auth
Google is lazy-imported so the app loads fine before libs/credentials exist; setting the invoice
number from the Excel works even without Drive configured (only PDF fetch needs it).
"""

import io
import json

import frappe
from frappe import _
from frappe.utils import getdate

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SO_ID_HEADER = "Sales Order Id"
INVOICE_HEADER = "Invoice No"


# ── config / auth ───────────────────────────────────────────────────────────
def _settings():
	return frappe.get_single("Invoice Sync Settings")


def _drive_enabled(s):
	return bool(s.get("enabled") and s.get("service_account_json") and s.get("drive_root_folder_id"))


def _drive_service(s):
	raw = (s.get("service_account_json") or "").strip()
	try:
		info = json.loads(raw)
	except Exception:
		frappe.throw(_("Service Account JSON in Invoice Sync Settings is not valid JSON."))
	try:
		from google.oauth2 import service_account
		from googleapiclient.discovery import build
	except ImportError:
		frappe.throw(_("Google libraries missing. Run: bench pip install google-api-python-client google-auth"))
	creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
	return build("drive", "v3", credentials=creds, cache_discovery=False)


def _month_label(d):
	return getdate(d).strftime("%B")  # e.g. "June"


# ── report rows (shared by the page table + the Excel download) ──────────────
def _report(from_date, to_date, channel=None, customer=None, customer_type=None):
	from alpinos.alpinos_development.report.accounts_format_report.accounts_format_report import execute

	filters = {"from_date": from_date, "to_date": to_date}
	if channel:
		filters["channel"] = channel
	if customer:
		filters["customer"] = customer
	if customer_type:
		filters["customer_type"] = customer_type
	return execute(filters)


@frappe.whitelist()
def get_report_rows(from_date, to_date, channel=None, customer=None, customer_type=None):
	"""Columns + data for the Invoice Sync page table (same content as the Accounts Format report)."""
	columns, data = _report(from_date, to_date, channel, customer, customer_type)
	return {"columns": columns, "data": data}


@frappe.whitelist()
def download_report_excel(from_date, to_date, channel=None, customer=None, customer_type=None):
	"""Stream the Accounts Format rows as an .xlsx (Invoice No column left blank to fill in)."""
	from frappe.utils.xlsxutils import make_xlsx

	columns, data = _report(from_date, to_date, channel, customer, customer_type)
	headers = [c["label"] for c in columns]
	fieldnames = [c["fieldname"] for c in columns]
	rows = [headers]
	for d in data:
		rows.append([d.get(fn) if d.get(fn) is not None else "" for fn in fieldnames])

	xlsx = make_xlsx(rows, "Accounts Format")
	frappe.response["filename"] = f"Accounts_Format_{from_date}_{to_date}.xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"


# ── upload + process ────────────────────────────────────────────────────────
@frappe.whitelist()
def process_invoice_excel(file_url):
	"""Parse the uploaded Excel (Sales Order Id + Invoice No), store the invoice number on each
	Sales Order and, when Drive is configured, fetch & attach the matching invoice PDF."""
	if not file_url:
		frappe.throw(_("No file provided."))
	try:
		import openpyxl
	except ImportError:
		frappe.throw(_("openpyxl is required to read the uploaded Excel."))

	content = _file_content(file_url)
	wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
	ws = wb.active

	rows = list(ws.iter_rows(values_only=True))
	if not rows:
		frappe.throw(_("The uploaded sheet is empty."))
	header = [str(h).strip() if h is not None else "" for h in rows[0]]
	try:
		so_idx = header.index(SO_ID_HEADER)
		inv_idx = header.index(INVOICE_HEADER)
	except ValueError:
		frappe.throw(_("The sheet must have '{0}' and '{1}' columns.").format(SO_ID_HEADER, INVOICE_HEADER))

	# Collapse to one Invoice No per Sales Order (line-level rows repeat the SO).
	mapping = {}
	for r in rows[1:]:
		if len(r) <= so_idx:
			continue
		so_id = str(r[so_idx]).strip() if r[so_idx] is not None else ""
		invoice = str(r[inv_idx]).strip() if len(r) > inv_idx and r[inv_idx] is not None else ""
		if so_id and invoice:
			mapping[so_id] = invoice

	s = _settings()
	drive = None
	if _drive_enabled(s):
		drive = _drive_service(s)
	ext = s.get("pdf_extension") or ".pdf"
	folder_cache = {}

	updated, fetched, missing, skipped = 0, 0, [], []
	for so_id, invoice_no in mapping.items():
		if not frappe.db.exists("Sales Order", so_id):
			skipped.append(f"{so_id} (not found)")
			continue
		frappe.db.set_value("Sales Order", so_id, "custom_invoice_no", invoice_no, update_modified=False)
		updated += 1

		if not drive or frappe.db.get_value("Sales Order", so_id, "custom_invoice_pdf"):
			continue
		so_date = frappe.db.get_value("Sales Order", so_id, "transaction_date")
		month = _month_label(so_date) if so_date else None
		folder = _resolve_month_folder(drive, s.drive_root_folder_id, s.get("fy_label") or "", month, folder_cache)
		if not folder:
			missing.append(f"{invoice_no} (folder {s.get('fy_label') or ''}/{month} not found)")
			continue
		file_id = _find_file(drive, folder, invoice_no, ext)
		if not file_id:
			missing.append(f"{invoice_no} (PDF not found)")
			continue
		from frappe.utils.file_manager import save_file

		f = save_file(f"{invoice_no}{ext}", _download(drive, file_id), "Sales Order", so_id, is_private=1)
		frappe.db.set_value("Sales Order", so_id, "custom_invoice_pdf", f.file_url, update_modified=False)
		fetched += 1

	frappe.db.commit()
	return {
		"invoices_mapped": updated,
		"pdfs_fetched": fetched,
		"drive_configured": bool(drive),
		"missing": missing,
		"skipped": skipped,
	}


def _file_content(file_url):
	row = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if row:
		return frappe.get_doc("File", row).get_content()
	from frappe.utils.file_manager import get_file

	return get_file(file_url)[1]


# ── Drive helpers ───────────────────────────────────────────────────────────
def _child_folder(drive, parent_id, name):
	q = (
		f"'{parent_id}' in parents and name = '{name}' "
		"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
	)
	res = drive.files().list(
		q=q, fields="files(id,name)", pageSize=1,
		supportsAllDrives=True, includeItemsFromAllDrives=True,
	).execute()
	files = res.get("files", [])
	return files[0]["id"] if files else None


def _resolve_month_folder(drive, root_id, fy_label, month, cache):
	"""root (the F.Y. folder) -> month. If fy_label is set, descend through it first."""
	if not month:
		return None
	key = (fy_label, month)
	if key in cache:
		return cache[key]
	parent = root_id
	if fy_label:
		parent = _child_folder(drive, parent, fy_label)
		if not parent:
			cache[key] = None
			return None
	folder = _child_folder(drive, parent, month)
	cache[key] = folder
	return folder


def _find_file(drive, folder_id, invoice_no, ext):
	for name in (f"{invoice_no}{ext}", invoice_no):
		q = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
		res = drive.files().list(
			q=q, fields="files(id,name)", pageSize=1,
			supportsAllDrives=True, includeItemsFromAllDrives=True,
		).execute()
		if res.get("files"):
			return res["files"][0]["id"]
	q = f"'{folder_id}' in parents and name contains '{invoice_no}' and trashed = false"
	res = drive.files().list(
		q=q, fields="files(id,name)", pageSize=1,
		supportsAllDrives=True, includeItemsFromAllDrives=True,
	).execute()
	files = res.get("files", [])
	return files[0]["id"] if files else None


def _download(drive, file_id):
	from googleapiclient.http import MediaIoBaseDownload

	buf = io.BytesIO()
	downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id, supportsAllDrives=True))
	done = False
	while not done:
		_status, done = downloader.next_chunk()
	return buf.getvalue()
