import frappe
import json
import requests
from frappe.utils import get_datetime, now_datetime, add_days
import xml.etree.ElementTree as ET

# Defaults used to seed eSSL Settings the first time and as fall-backs when a
# device row leaves the credential fields blank.
DEFAULT_API_URL = "http://103.250.149.126:85/iclock/WebAPIService.asmx"
DEFAULT_USERNAME = "API"
DEFAULT_PASSWORD = "Developer@123"
# Pre-existing devices (serial number -> location category). Seeded once.
DEFAULT_DEVICES = [
	{"serial_number": "NCD8252100411", "category": "Warehouse"},
	{"serial_number": "NCD8252100444", "category": "Warehouse"},
	{"serial_number": "TDBD260200038", "category": "HO"},
	{"serial_number": "TDBD254500435", "category": "HO"},
]


def get_essl_settings():
	"""Return the eSSL Settings single doc, seeding defaults on first use."""
	settings = frappe.get_single("eSSL Settings")
	if not settings.get("devices"):
		settings.api_url = settings.api_url or DEFAULT_API_URL
		for d in DEFAULT_DEVICES:
			settings.append("devices", {
				"serial_number": d["serial_number"],
				"category": d["category"],
				"username": DEFAULT_USERNAME,
				"password": DEFAULT_PASSWORD,
			})
		settings.save(ignore_permissions=True)
		frappe.db.commit()
	return settings


@frappe.whitelist()
def get_essl_devices():
	"""Lightweight list of configured devices for the sync dialog."""
	settings = get_essl_settings()
	return [
		{"serial_number": d.serial_number, "category": d.category}
		for d in settings.devices if d.serial_number
	]


@frappe.whitelist()
def sync_essl_logs(from_date=None, to_date=None, force=False, serial_numbers=None, category=None):
	"""
	Sync logs from eSSL biometric machine via Web API.
	Can be called manually, from the sync dialog, or scheduled.

	serial_numbers : optional JSON list / list of serial numbers to sync.
	category       : optional "HO" / "Warehouse" filter (ignored if blank/"All").
	"""
	if not from_date:
		# Default to last 2 days to catch up
		from_date = add_days(get_datetime(now_datetime()), -2).strftime("%Y-%m-%d 00:00")
	if not to_date:
		to_date = now_datetime()

	if isinstance(serial_numbers, str):
		try:
			serial_numbers = json.loads(serial_numbers)
		except Exception:
			serial_numbers = [serial_numbers] if serial_numbers else None

	settings = get_essl_settings()
	api_url = settings.api_url or DEFAULT_API_URL

	# Resolve which device rows to sync based on the serial/category filters.
	devices = []
	for d in settings.devices:
		if not d.serial_number:
			continue
		if serial_numbers and d.serial_number not in serial_numbers:
			continue
		if category and category != "All" and d.category != category:
			continue
		devices.append(d)

	results = []
	total_synced = 0

	for device in devices:
		sn = device.serial_number
		username = device.username or DEFAULT_USERNAME
		password = device.get_password("password") if device.password else DEFAULT_PASSWORD
		frappe.logger().info(f"Fetching eSSL logs for SN: {sn} ({device.category}) from {from_date} to {to_date}")
		response_text = fetch_logs_from_api(sn, from_date, to_date, api_url, username, password)
		if response_text:
			stats = process_logs(response_text, sn, device.category)
			total_synced += stats["synced"]
			line = f"SN {sn} ({device.category}): {stats['synced']} synced of {stats['fetched']} fetched"
			if stats.get("duplicate"):
				line += f", {stats['duplicate']} already existed"
			if stats.get("unauthorised"):
				line += " — UNAUTHORISED (check username/password)"
			if stats.get("unmatched"):
				line += f" — no matching employee for ID(s): {', '.join(stats['unmatched'])}"
			if stats.get("errors"):
				line += f" — {len(stats['errors'])} FAILED to save (see Error Log): " + "; ".join(stats["errors"][:5])
				if len(stats["errors"]) > 5:
					line += f" … (+{len(stats['errors']) - 5} more)"
			results.append(line)
		else:
			results.append(f"SN {sn} ({device.category}): Failed to fetch or no response")

	if not devices:
		results.append("No matching devices configured for this filter.")

	return {
		"status": "success",
		"total_synced": total_synced,
		"details": results
	}

def fetch_logs_from_api(serial_number, from_date, to_date, api_url=None, username=None, password=None):
	url = api_url or DEFAULT_API_URL
	username = username or DEFAULT_USERNAME
	password = password or DEFAULT_PASSWORD
	headers = {
		'Content-Type': 'application/soap+xml; charset=utf-8'
	}

	# Ensure date format yyyy-MM-dd HH:mm as required by eSSL
	# If to_date is datetime object, format it
	if not isinstance(to_date, str):
		to_date = to_date.strftime("%Y-%m-%d %H:%M")

	body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <GetTransactionsLog xmlns="http://tempuri.org/">
      <FromDateTime>{from_date}</FromDateTime>
      <ToDateTime>{to_date}</ToDateTime>
      <SerialNumber>{serial_number}</SerialNumber>
      <UserName>{username}</UserName>
      <UserPassword>{password}</UserPassword>
      <strDataList></strDataList>
    </GetTransactionsLog>
  </soap12:Body>
</soap12:Envelope>"""

	try:
		response = requests.post(url, data=body, headers=headers, timeout=60)
		if response.status_code == 200:
			return response.text
		else:
			frappe.log_error(f"eSSL API Status Code {response.status_code} for SN {serial_number}", "eSSL Sync Error")
	except Exception as e:
		frappe.log_error(f"eSSL Sync Network Error (SN: {serial_number}): {str(e)}", "eSSL Sync Error")
	return None

def process_logs(response_text, serial_number, category=None):
	try:
		# Check for error message in response result first
		if "Unathorised User" in response_text:
			frappe.log_error(f"eSSL API Unauthorised for SN {serial_number}", "eSSL Sync Error")
			return {"synced": 0, "fetched": 0, "duplicate": 0, "unmatched": [], "unauthorised": True}

		root = ET.fromstring(response_text)
		# SOAP 1.2 namespace
		ns = {'soap': 'http://www.w3.org/2003/05/soap-envelope', 'tns': 'http://tempuri.org/'}

		data_list_node = root.find('.//tns:strDataList', ns)
		if data_list_node is None or not data_list_node.text:
			return {"synced": 0, "fetched": 0, "duplicate": 0, "unmatched": []}

		logs_text = data_list_node.text.strip()
		lines = logs_text.split('\n')

		# Parse and sort logs chronologically before processing
		parsed_logs = []
		for line in lines:
			if not line.strip(): continue
			parts = line.split('\t')
			if len(parts) >= 2:
				parsed_logs.append({
					"device_id": parts[0].strip(),
					"timestamp_str": parts[1].strip()
				})

		# Sort by timestamp string (ISO format YYYY-MM-DD HH:MM:SS)
		parsed_logs.sort(key=lambda x: x["timestamp_str"])

		synced_count = 0
		duplicate_count = 0
		unmatched = set()
		errors = []
		for log in parsed_logs:
			status, detail = create_employee_checkin(log["device_id"], log["timestamp_str"], serial_number, category)
			if status == "created":
				synced_count += 1
			elif status == "duplicate":
				duplicate_count += 1
			elif status == "no_employee":
				unmatched.add(detail or log["device_id"])
			else:
				# "error" / "bad_time" — previously swallowed silently; surface them so a
				# fetched-but-not-created punch is never invisible. Full trace is in Error Log.
				errors.append(detail or f"ID {log['device_id']} @ {log['timestamp_str']}")

		return {
			"synced": synced_count,
			"fetched": len(parsed_logs),
			"duplicate": duplicate_count,
			"unmatched": sorted(unmatched),
			"errors": errors,
		}
	except Exception as e:
		frappe.log_error(f"Error parsing eSSL logs (SN: {serial_number}): {str(e)}\n\nResponse was: {response_text[:500]}", "eSSL Sync Error")
		return {"synced": 0, "fetched": 0, "duplicate": 0, "unmatched": [], "errors": []}

def create_employee_checkin(device_id, timestamp_str, device_name, category=None):
	try:
		employee = frappe.db.get_value("Employee", {"attendance_device_id": device_id}, "name")

		if not employee:
			employee = frappe.db.get_value("Employee", {"employee_number": device_id}, "name")

		if not employee:
			employee = frappe.db.get_value("Employee", {"name": device_id}, "name")

		if not employee:
			try:
				numeric_id = int(device_id)
				patterns = [
					f"EMP-{numeric_id:05d}",
					f"HR-EMP-{numeric_id:05d}",
					f"EMP-{numeric_id}",
					f"HR-EMP-{numeric_id}",
					f"{numeric_id:05d}"
				]
				for p in patterns:
					if frappe.db.exists("Employee", p):
						employee = p
						break
			except ValueError:
				pass

		if not employee:
			return ("no_employee", device_id)

		try:
			timestamp = get_datetime(timestamp_str)
		except Exception:
			return ("bad_time", f"ID {device_id} @ {timestamp_str}: unparseable time")

		# Prevent duplicates
		if frappe.db.exists("Employee Checkin", {"employee": employee, "time": timestamp}):
			return ("duplicate", None)

		# Determine log_type (Alternating IN/OUT day-wise)
		log_date = timestamp.date()
		date_start = f"{log_date} 00:00:00"
		date_end = f"{log_date} 23:59:59"

		existing_logs_count = frappe.db.count("Employee Checkin", {
			"employee": employee,
			"time": ["between", [date_start, date_end]],
			"docstatus": ["!=", 2]
		})

		log_type = "IN" if existing_logs_count % 2 == 0 else "OUT"

		checkin = frappe.new_doc("Employee Checkin")
		checkin.employee = employee
		checkin.time = timestamp
		checkin.log_type = log_type
		checkin.device_id = device_name
		# Location category of the device this punch came from (HO / Warehouse)
		if category:
			checkin.category = category

		# Fetch Shift for the employee
		try:
			from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
			shift_details = get_employee_shift(employee, timestamp, consider_default_shift=True)
			if shift_details:
				checkin.shift = shift_details.get("shift_type")
		except Exception:
			pass

		# Fetch coordinates of the Shift Location matching THIS device's category
		# (HO / Warehouse). Each category maps to a Shift Location of the same name,
		# so punches are tagged with the location they actually came from.
		if category:
			device_location = frappe.db.get_value(
				"Shift Location", category, ["latitude", "longitude"], as_dict=True
			)
			if device_location:
				checkin.latitude = device_location.latitude
				checkin.longitude = device_location.longitude

		checkin.insert(ignore_permissions=True)
		frappe.db.commit()
		return ("created", None)
	except Exception as e:
		frappe.log_error(f"eSSL create checkin failed (device_id={device_id}): {str(e)}", "eSSL Sync Error")
		return ("error", f"ID {device_id} @ {timestamp_str}: {str(e)}")
