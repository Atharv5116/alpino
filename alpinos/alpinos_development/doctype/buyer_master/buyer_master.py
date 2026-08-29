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


def _map_customer_type(obm_customer_type):
	"""Customer type is now a Link field; pass the master name directly."""
	return (obm_customer_type or "").strip()


def _customer_is_free(customer_id, doc):
	"""True when this buyer may own that Customer — it is unused, or already ours."""
	if not frappe.db.exists("Customer", customer_id):
		return True
	return not frappe.db.get_value(
		"Buyer Master", {"customer": customer_id, "name": ("!=", doc.name or "")}, "name"
	)


def _customer_id_for_obm(doc):
	"""The Customer ID this buyer should own: GST-based, then site-scoped, then the buyer's own ID.

	One GST entity trades from many sites and each site is its own Buyer Master,
	so only the first can carry the GST-based ID. Deriving it the same way every
	time keeps a Buyer Master export re-importable.
	"""
	biz_name = (doc.customer_business_name or "").strip()
	tax_id = (doc.gst_no or doc.pan_no or "").strip()

	base = f"{biz_name} - {tax_id}" if tax_id else biz_name
	if _customer_is_free(base, doc):
		return base

	site_name = (doc.site_name or "").strip()
	if site_name:
		scoped = f"{biz_name} - {site_name}"
		if _customer_is_free(scoped, doc):
			return scoped

	return f"{biz_name} - {doc.name}" if doc.name else base


def _ensure_customer_for_obm(doc):
	"""Create or refresh ERPNext Customer from business name (no manual Customer pick list)."""
	biz_name = (doc.customer_business_name or "").strip()
	# tax id disambiguates the Customer ID (docname) only; customer_name stays the
	# plain business name shown on Sales Orders, Pick Lists and stickers.
	tax_id = (doc.gst_no or doc.pan_no or "").strip()

	if not biz_name:
		frappe.throw(_("Customer (Business Name) is required."), title=_("Missing business name"))

	unique_id = _customer_id_for_obm(doc)

	# Adopt an existing customer for this GST entity, unless another buyer owns it.
	if not doc.customer and frappe.db.exists("Customer", unique_id) and _customer_is_free(unique_id, doc):
		doc.customer = unique_id

	cg, territory = _selling_defaults()
	if not cg or not territory:
		frappe.throw(
			_("Set Customer Group and Territory in Selling Settings before saving Buyer Master."),
			title=_("Selling Settings"),
		)

	company = _default_company()
	mapped_order_type = _map_customer_type(doc.customer_type)

	parent_customer = None
	if doc.parent_buyer:
		parent_customer = frappe.db.get_value("Buyer Master", doc.parent_buyer, "customer")

	if doc.customer and frappe.db.exists("Customer", doc.customer):
		cust = frappe.get_doc("Customer", doc.customer)
		if cust.customer_name != biz_name:
			cust.customer_name = biz_name
		if mapped_order_type:
			cust.custom_order_type = mapped_order_type
		if doc.gst_type == "Registered Business" and doc.gst_no:
			cust.tax_id = doc.gst_no
		elif doc.gst_type == "Unregistered Business" and doc.pan_no:
			cust.tax_id = doc.pan_no
		if parent_customer:
			cust.parent_customer = parent_customer
		cust.flags.ignore_mandatory = True
		cust.save(ignore_permissions=True)
		# Already-linked customer: keep syncing its fields, but never auto-rename
		# the Customer ID — it stays whatever it was created as.
		return

	cust = frappe.new_doc("Customer")
	cust.customer_name = biz_name
	cust.customer_type = "Company"
	cust.customer_group = cg
	cust.territory = territory
	if mapped_order_type:
		cust.custom_order_type = mapped_order_type
	if doc.gst_type == "Registered Business" and doc.gst_no:
		cust.tax_id = doc.gst_no
	elif doc.gst_type == "Unregistered Business" and doc.pan_no:
		cust.tax_id = doc.pan_no
	if parent_customer:
		cust.parent_customer = parent_customer
	if company:
		cust.append("companies", {"company": company})
	# Docname = "business - GST/PAN" (or the site-scoped fallback); display name
	# stays plain. With no tax id and no collision, leave naming to the site setting.
	force_name = unique_id if (tax_id or unique_id != biz_name) else None
	cust.insert(ignore_permissions=True, set_name=force_name)
	doc.customer = cust.name


class BuyerMaster(Document):
	def validate(self):
		self._migrate_legacy_address_if_empty()
		self._normalize_addresses()
		self._validate_primary_address()
		self._sync_primary_to_flat_fields()
		self._validate_gstin_and_pincodes()

		if self.is_parent and self.parent_buyer:
			frappe.throw(_("A record cannot be both a Parent and a Child."), title=_("Relationship Error"))

		if self.parent_buyer == self.name:
			frappe.throw(_("A record cannot be its own Parent."), title=_("Relationship Error"))

		if self.parent_buyer and frappe.db.exists("Buyer Master", {"parent_buyer": self.name}):
			frappe.throw(
				_("This record is already a Parent to other records and cannot be assigned a Parent."),
				title=_("Relationship Error"),
			)

		_ensure_customer_for_obm(self)

	def _validate_gstin_and_pincodes(self):
		"""GSTIN + PIN format checks, only on new/changed values so legacy bad data doesn't block saves."""
		import re

		gstin_re = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
		before = self.get_doc_before_save()

		new_gst = (self.gst_no or "").strip().upper()
		old_gst = ((before.get("gst_no") if before else "") or "").strip().upper()
		if new_gst and new_gst != old_gst:
			if not gstin_re.match(new_gst):
				frappe.throw(_("Invalid GSTIN format: {0}").format(new_gst), title=_("GST"))
			self.gst_no = new_gst

		old_pins = {}
		if before:
			for r in before.get("addresses") or []:
				old_pins[r.get("name")] = (r.get("pincode") or "").strip()
		for r in self.get("addresses") or []:
			pin = (r.pincode or "").strip()
			if not pin:
				continue
			if r.name and old_pins.get(r.name) == pin:
				continue  # unchanged legacy value
			if not re.fullmatch(r"[1-9][0-9]{5}", pin):
				frappe.throw(
					_("Address row #{0}: invalid PIN Code {1} — must be a 6-digit Indian PIN.").format(r.idx, pin),
					title=_("Address"),
				)

		if self.payment_term in ("Credit", "Partial"):
			self.payment_term_days = (self.payment_term_days or "").strip()
			if not self.payment_term_days:
				frappe.throw(
					_("Days is required when Payment Term is Credit or Partial."),
					title=_("Payment Term"),
				)
		else:
			self.payment_term_days = None

		# GST No must be unique across Buyer Masters (a shared GSTIN spawns the
		# duplicate customer that breaks SO selection). Parent/child sites in one
		# family may share it. Only checked when the GST is set or changed.
		gst = (self.gst_no or "").strip().upper()
		old_gst = ""
		if not self.is_new():
			old_gst = (frappe.db.get_value("Buyer Master", self.name, "gst_no") or "").strip().upper()
		if self.gst_type == "Registered Business" and gst and gst != old_gst:
			my_root = self.parent_buyer or (self.name if self.is_parent else None)
			for other in frappe.get_all(
				"Buyer Master",
				filters={"gst_no": gst, "name": ["!=", self.name or ""]},
				fields=["name", "parent_buyer", "is_parent"],
			):
				other_root = other.parent_buyer or (other.name if other.is_parent else None)
				if my_root and other_root and my_root == other_root:
					continue  # same family, shared GSTIN is fine
				frappe.throw(
					_(
						"GST No {0} is already used by Buyer Master {1}. A GSTIN can belong "
						"to only one buyer (its parent/child sites aside)."
					).format(frappe.bold(gst), frappe.bold(other.name)),
					title=_("Duplicate GST"),
				)

		# Only meaningful once a Customer is linked; a blank one would match every
		# unlinked buyer and raise a bogus duplicate warning.
		filters = {"customer": self.customer}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if self.customer and frappe.db.count("Buyer Master", filters):
			frappe.throw(
				_("Only one Buyer Master is allowed per Customer. Another record already uses {0}.").format(
					frappe.bold(self.customer)
				),
				title=_("Duplicate Buyer Master"),
			)

	def before_insert(self):
		if not self.customer_id:
			self.customer_id = self.name

	def after_insert(self):
		# read_only fields can drop out of the INSERT; force the customer link in now.
		if self.customer:
			frappe.db.set_value(
				"Buyer Master", self.name, "customer", self.customer, update_modified=False
			)
			frappe.db.commit()

	def on_update(self):
		# Create/refresh the Customer's Address + Contact on every save (idempotent).
		from alpinos.sales_order_offline_buyer import sync_obm_to_customer_party

		sync_obm_to_customer_party(self)

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

	def _is_hierarchy_obm(self):
		"""Parent (group) or child (site under a parent) — address rules are relaxed."""
		return bool(self.get("is_parent") or self.get("parent_buyer"))

	def _normalize_addresses(self):
		rows = list(self.get("addresses") or [])
		if not rows:
			if not self._is_hierarchy_obm():
				frappe.throw(_("Add at least one address in the Addresses table."), title=_("Address"))
			return
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
		if self._is_hierarchy_obm():
			return
		if not self.get("addresses"):
			return

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
		rows = list(self.get("addresses") or [])
		if not rows:
			self.address = ""
			self.pincode = ""
			self.country = ""
			self.state = ""
			self.city = ""
			self.area = ""
			self.sub_area = ""
			self.shipping_address = ""
			self.shipping_state = ""
			self.shipping_city = ""
			return

		row = next((r for r in rows if r.get("is_primary")), rows[0])
		self.address = row.address_line or ""
		self.pincode = row.pincode or ""
		self.country = row.country or ""
		self.state = row.state or ""
		self.city = row.city or ""
		self.area = row.area or ""
		self.sub_area = row.sub_area or ""

		# Sync the first is_shipping row into the shipping flat fields when not same-as-primary
		if not self.get("shipping_same_as_profile"):
			sh_row = next((r for r in rows if r.get("is_shipping")), None)
			if sh_row:
				self.shipping_address = sh_row.address_line or ""
				self.shipping_state = sh_row.state or ""
				self.shipping_city = sh_row.city or ""
			else:
				self.shipping_address = ""
				self.shipping_state = ""
				self.shipping_city = ""
