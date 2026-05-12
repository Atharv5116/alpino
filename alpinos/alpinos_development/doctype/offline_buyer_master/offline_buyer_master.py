import frappe
from frappe import _
from frappe.model.document import Document


def _selling_defaults():
	ss = frappe.get_single("Selling Settings")
	cg = ss.customer_group
	territory = ss.territory
	if not cg:
		cg = frappe.db.get_value("Customer Group", {}, "name", order_by="lft asc")
	if not territory:
		territory = frappe.db.get_value("Territory", {}, "name", order_by="lft asc")
	return cg, territory


def _default_company():
	c = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if c:
		return c
	return frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")


_OBM_TYPE_TO_ORDER_TYPE = {
	"GENERAL TRADE": "GT",
	"MODERN TRADE": "MT",
	"HORECA TRADE": "HoReCa",
	"NUTRITIONAL TRADE": "GYM & NUTRITION",
	"INSTITUTIONAL TRADE": "MT",
}


def _map_customer_type(obm_customer_type):
	"""Convert OBM customer_type to the Customer/Quotation order_type option set."""
	return _OBM_TYPE_TO_ORDER_TYPE.get((obm_customer_type or "").upper().strip(), "")


def _ensure_customer_for_obm(doc):
	"""Create or refresh ERPNext Customer from business name (no manual Customer pick list)."""
	name = (doc.customer_business_name or "").strip()
	if not name:
		frappe.throw(_("Customer (Business Name) is required."), title=_("Missing business name"))

	cg, territory = _selling_defaults()
	if not cg or not territory:
		frappe.throw(
			_("Set Customer Group and Territory in Selling Settings before saving Offline Buyer Master."),
			title=_("Selling Settings"),
		)

	company = _default_company()
	mapped_order_type = _map_customer_type(doc.customer_type)

	if doc.customer and frappe.db.exists("Customer", doc.customer):
		cust = frappe.get_doc("Customer", doc.customer)
		if cust.customer_name != name:
			cust.customer_name = name
		if mapped_order_type:
			cust.custom_order_type = mapped_order_type
		if doc.gst_type == "Registered Business" and doc.gst_no:
			cust.tax_id = doc.gst_no
		elif doc.gst_type == "Unregistered Business" and doc.pan_no:
			cust.tax_id = doc.pan_no
		cust.save(ignore_permissions=True)
		return

	cust = frappe.new_doc("Customer")
	cust.customer_name = name
	cust.customer_type = "Company"
	cust.customer_group = cg
	cust.territory = territory
	if mapped_order_type:
		cust.custom_order_type = mapped_order_type
	if doc.gst_type == "Registered Business" and doc.gst_no:
		cust.tax_id = doc.gst_no
	elif doc.gst_type == "Unregistered Business" and doc.pan_no:
		cust.tax_id = doc.pan_no
	if company:
		cust.append("companies", {"company": company})
	cust.insert(ignore_permissions=True)
	doc.customer = cust.name


class OfflineBuyerMaster(Document):
	def validate(self):
		self._migrate_legacy_address_if_empty()
		self._normalize_addresses()
		self._validate_primary_address()
		self._sync_primary_to_flat_fields()
		_ensure_customer_for_obm(self)

		if self.payment_term in ("Credit", "Partial"):
			self.payment_term_days = (self.payment_term_days or "").strip()
			if not self.payment_term_days:
				frappe.throw(
					_("Days is required when Payment Term is Credit or Partial."),
					title=_("Payment Term"),
				)
		else:
			self.payment_term_days = None

		filters = {"customer": self.customer}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.count("Offline Buyer Master", filters):
			frappe.throw(
				_("Only one Offline Buyer Master is allowed per Customer. Another record already uses {0}.").format(
					frappe.bold(self.customer)
				),
				title=_("Duplicate Offline Buyer Master"),
			)

	def before_insert(self):
		if not self.customer_id:
			self.customer_id = self.name

	def after_insert(self):
		# read_only fields can be omitted from the INSERT query in some Frappe versions.
		# Force the customer link into DB now that the row exists.
		if self.customer:
			frappe.db.set_value(
				"Offline Buyer Master", self.name, "customer", self.customer, update_modified=False
			)
			frappe.db.commit()

	def _migrate_legacy_address_if_empty(self):
		if self.get("addresses"):
			return
		if not (self.get("address") or self.get("pincode") or self.get("country")):
			return
		self.append(
			"addresses",
			{
				"is_primary": 1,
				"address_line": self.get("address") or "",
				"pincode": self.get("pincode") or "",
				"country": self.get("country") or "",
				"state": self.get("state") or "",
				"city": self.get("city") or "",
				"area": self.get("area") or "",
				"sub_area": self.get("sub_area") or "",
			},
		)

	def _normalize_addresses(self):
		rows = list(self.get("addresses") or [])
		if not rows:
			frappe.throw(_("Add at least one address in the Addresses table."), title=_("Address"))
		prim = [r for r in rows if r.get("is_primary")]
		if len(prim) > 1:
			frappe.throw(_("Mark only one address as Primary."), title=_("Primary address"))
		if not prim:
			rows[0].is_primary = 1

		# If shipping_same_as_profile is checked, clear all is_shipping flags (primary handles it)
		if self.get("shipping_same_as_profile"):
			for r in rows:
				r.is_shipping = 0

	def _validate_primary_address(self):
		def nonempty(val):
			if val is None:
				return False
			return bool(str(val).strip())

		row = next((r for r in self.addresses if r.get("is_primary")), self.addresses[0])
		for fname, label in (
			("address_line", _("Address")),
			("pincode", _("Pincode")),
			("country", _("Country")),
			("state", _("State")),
			("city", _("City")),
		):
			if not nonempty(row.get(fname)):
				frappe.throw(
					_("{0} is required on the primary address row.").format(label),
					title=_("Primary address"),
				)

	def _sync_primary_to_flat_fields(self):
		row = next((r for r in self.addresses if r.get("is_primary")), self.addresses[0])
		self.address = row.address_line or ""
		self.pincode = row.pincode or ""
		self.country = row.country or ""
		self.state = row.state or ""
		self.city = row.city or ""
		self.area = row.area or ""
		self.sub_area = row.sub_area or ""

		# Sync the first is_shipping row into the shipping flat fields when not same-as-primary
		if not self.get("shipping_same_as_profile"):
			sh_row = next((r for r in self.addresses if r.get("is_shipping")), None)
			if sh_row:
				self.shipping_address = sh_row.address_line or ""
				self.shipping_state = sh_row.state or ""
				self.shipping_city = sh_row.city or ""
