import frappe
import requests
from frappe.utils import get_datetime, now_datetime, add_days
import xml.etree.ElementTree as ET

@frappe.whitelist()
def sync_essl_logs(from_date=None, to_date=None, force=False):
    """
    Sync logs from eSSL biometric machine via Web API
    Can be called manually or scheduled.
    """
    if not from_date:
        # Default to last 2 days to catch up
        from_date = add_days(get_datetime(now_datetime()), -2).strftime("%Y-%m-%d 00:00")
    if not to_date:
        to_date = now_datetime()

    # Serial numbers provided by user
    serial_numbers = ["NCD8252100411", "NCD8252100444"]
    
    results = []
    total_synced = 0
    
    for sn in serial_numbers:
        frappe.logger().info(f"Fetching eSSL logs for SN: {sn} from {from_date} to {to_date}")
        response_text = fetch_logs_from_api(sn, from_date, to_date)
        if response_text:
            synced = process_logs(response_text, sn)
            total_synced += synced
            results.append(f"SN {sn}: {synced} logs synced")
        else:
            results.append(f"SN {sn}: Failed to fetch or no response")
    
    return {
        "status": "success",
        "total_synced": total_synced,
        "details": results
    }

def fetch_logs_from_api(serial_number, from_date, to_date):
    url = "http://103.250.149.126:85/iclock/WebAPIService.asmx"
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
      <UserName>API</UserName>
      <UserPassword>Developer@123</UserPassword>
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

def process_logs(response_text, serial_number):
    try:
        # Check for error message in response result first
        if "Unathorised User" in response_text:
            frappe.log_error(f"eSSL API Unauthorised for SN {serial_number}", "eSSL Sync Error")
            return 0
            
        root = ET.fromstring(response_text)
        # SOAP 1.2 namespace
        ns = {'soap': 'http://www.w3.org/2003/05/soap-envelope', 'tns': 'http://tempuri.org/'}
        
        data_list_node = root.find('.//tns:strDataList', ns)
        if data_list_node is None or not data_list_node.text:
            return 0
            
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
        for log in parsed_logs:
            if create_employee_checkin(log["device_id"], log["timestamp_str"], serial_number):
                synced_count += 1
        
        return synced_count
    except Exception as e:
        frappe.log_error(f"Error parsing eSSL logs (SN: {serial_number}): {str(e)}\n\nResponse was: {response_text[:500]}", "eSSL Sync Error")
        return 0

def create_employee_checkin(device_id, timestamp_str, device_name):
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
            return False
            
        try:
            timestamp = get_datetime(timestamp_str)
        except Exception:
            return False
        
        # Prevent duplicates
        if frappe.db.exists("Employee Checkin", {"employee": employee, "time": timestamp}):
            return False
            
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
        
        # Fetch Shift for the employee
        try:
            from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
            shift_details = get_employee_shift(employee, timestamp, consider_default_shift=True)
            if shift_details:
                checkin.shift = shift_details.get("shift_type")
        except Exception:
            pass
            
        # Fetch Warehouse Location coordinates
        warehouse_location = frappe.db.get_value("Shift Location", "Warehouse", ["latitude", "longitude"], as_dict=True)
        if warehouse_location:
            checkin.latitude = warehouse_location.latitude
            checkin.longitude = warehouse_location.longitude
        
        checkin.insert(ignore_permissions=True)
        frappe.db.commit()
        return True
    except Exception as e:
        return False
