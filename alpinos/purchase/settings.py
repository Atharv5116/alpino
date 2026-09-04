"""Accessors for Purchase Inward Settings, with BRD defaults when unset."""

import frappe
from frappe.utils import cint, flt

from alpinos.purchase import constants as C

_DEFAULTS = {
	"block_over_receipt": 1,
	"over_receipt_tolerance_percent": 0.0,
	"sync_stock_settings": 1,
	"qc_sla_hours": C.QC_SLA_HOURS,
	"qc_escalation_interval_minutes": C.QC_ESCALATION_INTERVAL_MINUTES,
	"notify_qc_on_submit": 1,
	"qc_notification_roles": "\n".join(C.QC_ROLES),
	"rm_pm_batch_format": "{invoice_number}-{inward_date}",
	"fg_batch_format": "{batch_no}-{manufacturing_date}",
	"rmid_format": "RMID-.YYYY.-.#####",
	"pmid_format": "PMID-.YYYY.-.#####",
	"qc_hold_warehouse": None,
	"qc_sample_warehouse": None,
	"rejected_warehouse": None,
	"quarantine_warehouse": None,
	"control_sample_warehouse": None,
}

SETTINGS_DOCTYPE = "Purchase Inward Settings"


def get_settings(company=None):
	"""Settings for `company`, falling back to BRD defaults for anything unset.

	Purchase Inward Settings is a Single, so `company` currently only picks the
	company whose warehouses the record points at; it is accepted so callers read
	naturally and so this can grow a per-company child table without a signature
	change.

	Returns a plain dict, never a Document, so no caller holds a stale Single
	across a commit.
	"""
	values = dict(_DEFAULTS)
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return values

	row = frappe.db.get_singles_dict(SETTINGS_DOCTYPE) or {}
	for key in list(values):
		got = row.get(key)
		if got not in (None, ""):
			values[key] = got
	values["name"] = SETTINGS_DOCTYPE
	return values


def notification_roles(company=None):
	"""Roles notified when an inward is handed to QC (BR-QC-02).

	Roles that do not exist are dropped and the module default is used instead. The
	shipped JSON default used to name "QC User" / "QC Manager" while the roles this
	module actually creates are "Purchase QC User" / "Purchase QC Manager", so the first
	time anyone saved the Settings single (to change the SLA, say) frappe persisted the
	wrong names, qc_recipients() resolved zero users and every QC alert silently stopped.
	Filtering here means a stale stored value cannot switch the alerts off.
	"""
	raw = get_settings(company).get("qc_notification_roles") or ""
	roles = [r.strip() for r in raw.replace(",", "\n").splitlines() if r.strip()]
	known = [r for r in roles if frappe.db.exists("Role", r)]
	if roles and not known:
		frappe.logger("alpinos.purchase").warning(
			f"Purchase Inward Settings names no existing QC notification role ({roles!r}); "
			f"falling back to {list(C.QC_ROLES)!r}"
		)
	return known or list(C.QC_ROLES)


def sla_hours(company=None):
	return flt(get_settings(company).get("qc_sla_hours")) or C.QC_SLA_HOURS


def escalation_minutes(company=None):
	return (
		cint(get_settings(company).get("qc_escalation_interval_minutes"))
		or C.QC_ESCALATION_INTERVAL_MINUTES
	)


#: module warehouse label -> the Purchase Inward Settings field that stores it
WAREHOUSE_KEYS = {
	C.WH_QC_HOLD: "qc_hold_warehouse",
	C.WH_QC_SAMPLE: "qc_sample_warehouse",
	C.WH_REJECTED: "rejected_warehouse",
	C.WH_QUARANTINE: "quarantine_warehouse",
	C.WH_CONTROL_SAMPLE: "control_sample_warehouse",
}


def warehouse(role, company=None):
	"""Resolve one of the module warehouses; None when it has not been provisioned.

	Purchase Inward Settings is a Single, so it can only store ONE company's warehouses.
	warehouses.setup provisions them for every company but writes back only the settings
	company's, which used to leave a second company's GRN reaching for company A's
	"Rejected - A" and failing validation the moment QC rejected anything.

	So the stored value is used only when it actually belongs to `company`; otherwise the
	warehouse provisioned for that company is looked up by its conventional name. A site
	with one company behaves exactly as before.
	"""
	key = WAREHOUSE_KEYS.get(role)
	if not key:
		return None

	stored = get_settings(company).get(key)
	if not company:
		return stored
	if stored and frappe.db.get_value("Warehouse", stored, "company") == company:
		return stored

	abbr = frappe.get_cached_value("Company", company, "abbr")
	candidate = "{0} - {1}".format(role, abbr) if abbr else role
	if frappe.db.exists("Warehouse", candidate):
		return candidate
	# Nothing provisioned for this company yet: the stored value is still better than
	# nothing for a single-company site, and the caller's own validation reports the rest.
	return stored
