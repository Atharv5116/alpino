"""Purchase Inward warehouses and receipt tolerance (idempotent; re-run on every migrate).

Three pieces of provisioning live here, no business logic:

1. The module warehouses from `constants.MODULE_WAREHOUSES` (QC Hold, QC Sample, Rejected,
   Quarantine) created per Company as leaves under that company's root warehouse group.
   Warehouse.autoname appends " - <abbr>", so the abbreviation is resolved by ERPNext and
   never hard-coded or assumed here, and the parent group is looked up at runtime.
2. Those warehouse names written back onto Purchase Inward Settings so
   `settings.warehouse()` can resolve them. A value an admin already pointed elsewhere is
   left alone, and ONLY the warehouse fields (plus `company`) are ever written --
   see apply_settings_warehouses() for why that matters.
3. The over-receipt tolerance mirrored onto ERPNext Stock Settings. That RELAXES the core
   block but does not implement BR-PI-13 / BR-PI-14 / VAL-PO-11; the module's own guard
   does. See sync_stock_settings() for exactly what the mirror buys and what it does not.

Stock Settings is a site-wide Single, so this module only ever WIDENS it: a tolerance an
admin set higher is kept, and an override role an admin already chose is never replaced.
Everything it does change is logged.
"""

import frappe
from frappe.utils import cint, flt

from alpinos.purchase import constants as C
from alpinos.purchase import settings as purchase_settings

SETTINGS_DOCTYPE = purchase_settings.SETTINGS_DOCTYPE


def _warehouse_fields():
	"""Purchase Inward Settings fieldname -> module warehouse label.

	control_sample_warehouse is deliberately absent until constants grows
	WH_CONTROL_SAMPLE with a MODULE_WAREHOUSES entry. Control samples are RETAINED for
	later verification while QC samples are consumed in testing (BRD 4.1.6), so pointing
	both fields at the QC Sample warehouse would make the two indistinguishable in the
	stock ledger -- and, because get_settings() treats any stored value as admin intent,
	the alias would never self-heal. Leaving the field unset is the honest state.
	"""
	fields = {
		"qc_hold_warehouse": C.WH_QC_HOLD,
		"qc_sample_warehouse": C.WH_QC_SAMPLE,
		"rejected_warehouse": C.WH_REJECTED,
		"quarantine_warehouse": C.WH_QUARANTINE,
	}
	control = getattr(C, "WH_CONTROL_SAMPLE", None)
	if control:
		fields["control_sample_warehouse"] = control
	return fields


WAREHOUSE_FIELDS = _warehouse_fields()


def _log(message):
	print("[purchase.warehouses] {0}".format(message))
	frappe.logger("alpinos.purchase").info(message)


# --- warehouses -------------------------------------------------------------


def _parent_group(company):
	"""The company's root warehouse group, resolved at runtime."""
	groups = frappe.get_all(
		"Warehouse",
		filters={"company": company, "is_group": 1},
		fields=["name", "parent_warehouse"],
		order_by="lft asc",
	)
	for group in groups:
		if not group.parent_warehouse:
			return group.name
	if groups:
		return groups[0].name

	# No group at all on this company: hang off an existing leaf's parent rather than
	# minting a second tree root.
	return frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "parent_warehouse")


def _ensure_warehouse(label, company, parent):
	"""Create the leaf warehouse `label` for `company` unless it already exists."""
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": label, "company": company}, "name")
	if existing:
		return existing

	# Renaming a Company abbr does not rename its warehouses, so the name is only a
	# secondary check behind the (warehouse_name, company) identity above.
	abbr = frappe.get_cached_value("Company", company, "abbr")
	expected = "{0} - {1}".format(label, abbr) if abbr else label
	if frappe.db.exists("Warehouse", expected):
		if frappe.db.get_value("Warehouse", expected, "company") == company:
			return expected
		_log("{0}: warehouse {1} belongs to another company; skipped".format(company, expected))
		return None

	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": label,
			"company": company,
			"parent_warehouse": parent,
			"is_group": 0,
			# Every module warehouse holds stock the BRD keeps out of normal use; this flag
			# is what excludes a warehouse from Pick List availability.
			"is_rejected_warehouse": 1,
		}
	)
	doc.insert(ignore_permissions=True)
	_log("{0}: created warehouse {1} under {2}".format(company, doc.name, parent))
	return doc.name


def provision_warehouses(company):
	"""Create the module warehouses for one company. Returns {label: warehouse name}."""
	parent = _parent_group(company)
	if not parent:
		_log("{0}: no warehouse group to parent the module warehouses; skipped".format(company))
		return {}

	found = {}
	for label in C.MODULE_WAREHOUSES:
		name = _ensure_warehouse(label, company, parent)
		if name:
			found[label] = name
	return found


# --- settings record --------------------------------------------------------


def _settings_installed():
	return bool(frappe.db.exists("DocType", SETTINGS_DOCTYPE))


def _is_single():
	return bool(frappe.get_meta(SETTINGS_DOCTYPE).issingle)


def _stored_settings(company=None):
	"""Whatever is actually PERSISTED for the Settings record -- no doctype defaults.

	frappe.get_single() would synthesise every unset field from the doctype JSON, so this
	module never builds a Document for the Settings record: it reads the raw stored row
	and writes single fields back. See apply_settings_warehouses().
	"""
	if _is_single():
		return dict(frappe.db.get_singles_dict(SETTINGS_DOCTYPE) or {})

	name = _settings_row_name(company)
	if not name:
		return {}
	return dict(frappe.db.get_value(SETTINGS_DOCTYPE, name, "*", as_dict=True) or {})


def _settings_row_name(company):
	"""Existing per-company Settings row, for the non-Single shape only."""
	if _is_single() or not company:
		return None
	return frappe.db.get_value(SETTINGS_DOCTYPE, {"company": company}, "name")


def _settings_target_company(companies):
	"""Company whose warehouses the Settings record carries.

	While the doctype is a Single there is exactly one record, so only one company's
	warehouses can be stored on it.
	"""
	if not _is_single():
		return None

	stored = (frappe.db.get_singles_dict(SETTINGS_DOCTYPE) or {}).get("company")
	if stored in companies:
		return stored
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	if default in companies:
		return default
	return companies[0]


def _write_setting(field, value, row_name=None):
	"""Persist ONE Settings field. Never touches any other field."""
	if _is_single():
		frappe.db.set_single_value(SETTINGS_DOCTYPE, field, value)
	else:
		frappe.db.set_value(SETTINGS_DOCTYPE, row_name, field, value)


def apply_settings_warehouses(company, warehouses):
	"""Write provisioned warehouse names onto the Settings record for `company`.

	Field by field, and only the fields in WAREHOUSE_FIELDS plus `company`. Never
	doc.save(): Purchase Inward Settings is a Single that has never been stored, so
	frappe.get_single() builds it from the doctype JSON defaults and a save would persist
	ALL of them. Those JSON defaults are stale against settings._DEFAULTS -- the shipped
	qc_notification_roles is "QC User / QC Manager" (roles that do not exist on this site,
	so QC notifications would resolve zero recipients and return silently), and the batch,
	RMID and PMID format strings differ too. get_settings() only falls back to _DEFAULTS
	while a field is unset, so writing those strings once would win permanently. Leaving
	every field this module does not own unstored is what keeps _DEFAULTS authoritative.
	"""
	if not _settings_installed():
		return {}

	row_name = None
	if not _is_single():
		row_name = _settings_row_name(company)
		if not row_name:
			# Inserting one would persist the same stale doctype defaults; an admin has to
			# create the record.
			_log(
				"{0}: no {1} record; warehouse write-back skipped".format(company, SETTINGS_DOCTYPE)
			)
			return {}

	stored = _stored_settings(company)
	changed = {}

	if company and not stored.get("company"):
		changed["company"] = company

	for field, label in WAREHOUSE_FIELDS.items():
		wanted = warehouses.get(label)
		if not wanted:
			continue
		current = stored.get(field)
		if current == wanted:
			continue
		# An admin pointed this at a live warehouse of their own; leave it. A dangling link
		# is treated as unset so the field self-heals.
		if current and frappe.db.exists("Warehouse", current):
			continue
		changed[field] = wanted

	for field, value in changed.items():
		_write_setting(field, value, row_name)

	if changed:
		_log("{0}: {1} -> {2}".format(company, SETTINGS_DOCTYPE, changed))
	return changed


# --- Stock Settings tolerance ----------------------------------------------


def _ensure_override_role(role):
	"""The role must exist before Stock Settings can link to it.

	after_migrate ordering across setup modules is not guaranteed, so a bare Role is created
	here rather than waiting for whichever module owns the role matrix; that module's own
	exists-guard will then fill in its description and permissions.
	"""
	if frappe.db.exists("Role", role):
		return True
	try:
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
				"description": C.ROLE_DESCRIPTIONS.get(role, ""),
			}
		).insert(ignore_permissions=True)
		_log("created Role {0} for the over-receipt bypass".format(role))
		return True
	except Exception:
		frappe.log_error(frappe.get_traceback(), "purchase warehouses: override role")
		return False


def override_role_coverage(effective_role):
	"""Which of C.EXCESS_OVERRIDE_ROLES the ERPNext bypass can and cannot reach.

	Returns (covered, uncovered, exposed_users). `exposed_users` are ENABLED users who
	hold an override role but not `effective_role`, so ERPNext will still hard-throw for
	them at Purchase Receipt submit. Administrator is excluded because
	frappe.get_roles("Administrator") returns every role.
	"""
	covered = [r for r in C.EXCESS_OVERRIDE_ROLES if r == effective_role]
	uncovered = [r for r in C.EXCESS_OVERRIDE_ROLES if r != effective_role]

	exposed = []
	if uncovered and effective_role:
		holders = set(
			frappe.get_all(
				"Has Role",
				filters={"parenttype": "User", "role": ("in", uncovered)},
				pluck="parent",
				distinct=True,
			)
		)
		exempt = set(
			frappe.get_all(
				"Has Role",
				filters={"parenttype": "User", "role": effective_role},
				pluck="parent",
				distinct=True,
			)
		)
		candidates = holders - exempt - {"Administrator"}
		if candidates:
			# A disabled user cannot submit anything; listing them only buries the real names.
			candidates &= set(
				frappe.get_all(
					"User",
					filters={"name": ("in", list(candidates)), "enabled": 1},
					pluck="name",
				)
			)
		exposed = sorted(candidates)
	return covered, uncovered, exposed


def _log_override_coverage(effective_role):
	covered, uncovered, exposed = override_role_coverage(effective_role)
	_log(
		"Stock Settings.role_allowed_to_over_deliver_receive = {0}. ERPNext checks this "
		"bypass PER USER (status_updater.check_overflow_with_allowance) and the field holds "
		"exactly ONE role, so only that role -- plus Administrator, whose get_roles() returns "
		"every role -- is spared OverAllowanceError at Purchase Receipt submit. Covered "
		"override roles: {1}. NOT covered: {2}.".format(
			effective_role or "(blank -- every user hard-throws)",
			", ".join(covered) or "none",
			", ".join(uncovered) or "none",
		)
	)
	_log(
		"BR-PI-13 / BR-PI-14 on the Purchase Inward itself are enforced by "
		"PurchaseInward._validate_received_quantities (block_over_receipt / "
		"over_receipt_tolerance_percent, with the allow_excess_qty override tick restricted "
		"to C.EXCESS_OVERRIDE_ROLES by purchase.roles) -- that is the real enforcement "
		"point. It does NOT rescue the uncovered roles downstream: a GRN whose quantity "
		"exceeds the Purchase Order line still hard-fails at Purchase Receipt submit for "
		"everyone outside the one role named above. The remedies are to raise "
		"over_receipt_tolerance_percent on {0} so the mirrored Stock Settings allowance "
		"absorbs the excess, or to give the submitting user that role.".format(SETTINGS_DOCTYPE)
	)
	if exposed:
		_log(
			"enabled users holding an override role but not {0} will still hard-fail an "
			"over-receipt Purchase Receipt submit: {1}".format(effective_role, ", ".join(exposed))
		)


def sync_stock_settings(company=None):
	"""Mirror the module tolerance onto Stock Settings. SITE-WIDE; widens only.

	What this actually buys: with over_delivery_receipt_allowance at 0 and
	role_allowed_to_over_deliver_receive blank, StatusUpdater.check_overflow_with_allowance
	throws OverAllowanceError at Purchase Receipt submit for every user, Administrator
	included. Naming a role does NOT convert that throw into a warning globally -- the check
	is per user (`if role not in frappe.get_roles(): self.limits_crossed_error(...)`,
	erpnext/controllers/status_updater.py:288-327) and the field holds exactly ONE role. So
	holders of that role (and Administrator) get warn_about_bypassing_with_role; everybody
	else still hard-throws. The user ERPNext measures is the one SUBMITTING the Purchase
	Receipt, so the single role named here has to be a role that final-submits the GRN under
	BR-GRN-06 -- otherwise no approved over-receipt can ever be posted at all.

	BR-PI-13 / BR-PI-14 / VAL-PO-11 are therefore enforced by this module, not by ERPNext:
	the real check is PurchaseInward._validate_received_quantities(), which reads
	block_over_receipt and over_receipt_tolerance_percent off Purchase Inward Settings and
	throws or msgprints itself, with the allow_excess_qty override tick restricted to
	C.EXCESS_OVERRIDE_ROLES by purchase.roles. What is set here only keeps the downstream
	Purchase Receipt from hard-failing for the one role ERPNext can be told about: an excess
	the Inward approved still hits OverAllowanceError at GRN submit for any other role,
	unless over_receipt_tolerance_percent is raised far enough to cover it. That gap, and
	the users it exposes, are logged on every run by _log_override_coverage().

	The role named is therefore C.ROLE_ADMIN, not the Store role that physically
	over-receives: Store Receiving may tick Allow Excess Quantity but may not submit a GRN
	(roles.assert_can_submit_grn), so naming it left the bypass on a role that never reaches
	ERPNext's check. Nothing is widened by this -- BR-PI-13 still blocks the UNapproved
	over-receipt upstream, on the Purchase Inward.

	Returns {fieldname: (old, new)} for whatever it actually changed.
	"""
	changed = {}
	if not frappe.db.exists("DocType", "Stock Settings"):
		return changed

	conf = purchase_settings.get_settings(company)
	if not cint(conf.get("sync_stock_settings")):
		return changed

	wanted = flt(conf.get("over_receipt_tolerance_percent"))
	current = flt(frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance"))
	if wanted > current:
		frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", wanted)
		changed["over_delivery_receipt_allowance"] = (current, wanted)
	elif wanted < current:
		_log(
			"Stock Settings.over_delivery_receipt_allowance kept at {0}% (module asks {1}%); "
			"an admin-set allowance is never narrowed here".format(current, wanted)
		)

	# Without a named role every over-receipt is a hard OverAllowanceError, for Administrator
	# too. Only fill it when blank so an admin's own choice of role survives -- plus the
	# module's own former choice, C.ROLE_STORE_MANAGER, which is corrected here.
	#
	# The field holds ONE role and ERPNext tests it against the user who SUBMITS the Purchase
	# Receipt (status_updater.check_overflow_with_allowance), so it must name a role from
	# C.GRN_FINAL_SUBMIT_ROLES. Naming the Store role instead named precisely the role that
	# roles.assert_can_submit_grn forbids from submitting, so an inward that legitimately
	# ticked Allow Excess Quantity (BR-PI-13 / BR-PI-14) died with OverAllowanceError at GRN
	# submit for every non-Administrator and stranded at "GRN Generated" forever. C.ROLE_ADMIN
	# is named explicitly rather than taken from GRN_FINAL_SUBMIT_ROLES[0] by ordering.
	role = C.ROLE_ADMIN
	current_role = frappe.db.get_single_value("Stock Settings", "role_allowed_to_over_deliver_receive")
	effective_role = current_role
	if (not current_role or current_role == C.ROLE_STORE_MANAGER) and _ensure_override_role(role):
		frappe.db.set_single_value("Stock Settings", "role_allowed_to_over_deliver_receive", role)
		changed["role_allowed_to_over_deliver_receive"] = (current_role or "", role)
		effective_role = role
	elif current_role and current_role != role:
		_log(
			"Stock Settings.role_allowed_to_over_deliver_receive kept as {0}; "
			"{1} was not applied".format(current_role, role)
		)

	_log_override_coverage(effective_role)

	if changed:
		_log("Stock Settings (site-wide) changed: {0}".format(changed))
	return changed


# --- entry point ------------------------------------------------------------


def setup_purchase_warehouses():
	"""after_migrate entry point: warehouses, Settings write-back and Stock Settings sync.

	Safe on a fresh site with no Company yet -- it returns early instead of throwing.
	"""
	summary = {"warehouses": {}, "settings": {}, "stock_settings": {}}

	if not frappe.db.exists("DocType", "Warehouse"):
		return summary

	companies = frappe.get_all("Company", pluck="name", order_by="creation asc")
	if not companies:
		return summary

	for company in companies:
		try:
			summary["warehouses"][company] = provision_warehouses(company)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "purchase warehouses: provision")

	if _settings_installed():
		target = _settings_target_company(companies)
		for company in companies:
			if target and company != target:
				_log(
					"{0}: warehouses created but not stored -- {1} is a Single and holds "
					"{2}".format(company, SETTINGS_DOCTYPE, target)
				)
				continue
			try:
				summary["settings"][company] = apply_settings_warehouses(
					company, summary["warehouses"].get(company) or {}
				)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "purchase warehouses: settings")

		try:
			summary["stock_settings"] = sync_stock_settings(target or companies[0])
		except Exception:
			frappe.log_error(frappe.get_traceback(), "purchase warehouses: stock settings")

	return summary
