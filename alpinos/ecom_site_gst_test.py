"""Site-wise GST and the e-com address write-back (29 Oct 2026). Run on a TEST site only:

	bench --site <test site> execute alpinos.ecom_site_gst_test.run

Builds a small buyer the way Amazon / Swiggy are set up -- a Karnataka parent, a Maharashtra
child state with its own site, and an unrelated buyer that uses the same site name -- and
checks that:

  * an order takes the GSTIN of the master that owns its site inside its OWN buyer, never
    another buyer's and never the parent's bare copy of a child's site;
  * a site claimed by two masters with different GSTINs is reported, not guessed;
  * the write-back leaves picked addresses alone and files a typed one on the master it
    belongs to;
  * a city-less Buyer Address row is not re-created as a new ERPNext Address on every save.

Records are prefixed GSTTEST and stay on the site; each run makes a fresh set.
"""

import hashlib

import frappe

R = []


def check(label, fn):
	try:
		fn()
		R.append(("PASS", label, ""))
	except AssertionError as e:
		R.append(("FAIL", label, str(e)))
	except Exception as e:
		R.append(("ERROR", label, f"{type(e).__name__}: {e}"))


def _assert(cond, msg=""):
	if not cond:
		raise AssertionError(msg)


def _gstin(state_code, seed):
	h = hashlib.md5(str(seed).encode()).hexdigest().upper()
	letters = "".join(chr(65 + (int(c, 16) % 26)) for c in h[:5])
	digits = ("".join(c for c in h if c.isdigit()) + "0000")[:4]
	return f"{state_code}{letters}{digits}A1Z5"


def _customer(name):
	if not frappe.db.exists("Customer", {"customer_name": name}):
		frappe.get_doc({
			"doctype": "Customer", "customer_name": name,
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
		}).insert(ignore_permissions=True)
	return frappe.db.get_value("Customer", {"customer_name": name}, "name")


def _buyer(tag, suffix, business, gst, state, rows, parent=None, is_parent=0):
	cust = _customer(f"GSTTEST-CUST-{tag}-{suffix}")
	doc = frappe.get_doc({
		"doctype": "Buyer Master",
		"customer_business_name": business, "customer": cust,
		"customer_type": frappe.db.get_value("Alpino Customer Type", {}, "name"),
		"channel": "E-com", "appointment_required": 0, "grn_available": 0, "partial_order_allowed": 1,
		"gst_exclusive_buyer": 0, "gst_no": gst, "gst_type": "Registered Business", "level": "N/A",
		"email": "gsttest@example.com", "contact_no": "9999999999", "contact_person": "GSTTEST",
		"state": state, "is_parent": is_parent, "parent_buyer": parent,
		"addresses": [dict(r, country="India") for r in rows],
	})
	doc.insert(ignore_permissions=True)
	doc.reload()
	return doc


def run():
	from alpinos import ecom_sales_order_api as E
	from alpinos import sales_order_offline_buyer as S

	R.clear()
	frappe.set_user("Administrator")
	frappe.flags.in_test = True
	tag = frappe.generate_hash(length=5).upper()
	biz = f"GSTTEST BIZ {tag}"
	ka, mh, gj = _gstin("29", tag + "P"), _gstin("27", tag + "C"), _gstin("24", tag + "U")
	blr = {"site_name": f"GT-BLR-{tag}", "address_line": f"GSTTEST {tag} Plot 1, Hoskote", "city": "Bengaluru",
		"state": "Karnataka", "pincode": "562114", "is_primary": 1, "is_shipping": 1}
	mum = {"site_name": f"GT-MUM-{tag}", "address_line": f"GSTTEST {tag} Building B4, Bhiwandi", "city": "Mumbai",
		"state": "Maharashtra", "pincode": "421302", "is_primary": 1, "is_shipping": 1}
	site = mum["site_name"]

	parent = _buyer(tag, "P", biz, ka, "Karnataka", [blr], is_parent=1)
	child = _buyer(tag, "C", biz, mh, "Maharashtra", [mum], parent=parent.name)
	# An unrelated buyer using the very same site name, in Gujarat.
	stranger = _buyer(tag, "U", f"GSTTEST OTHER {tag}", gj, "Gujarat",
		[dict(mum, address_line=f"GSTTEST {tag} Ring Road, Surat", city="Surat", state="Gujarat", pincode="395003")])

	# --- the GSTIN of the site, inside the order's own buyer ------------------
	check("an order under the parent takes the child state's GSTIN for the child's site",
		lambda: _assert(S._gst_for_site(site, "", customer=parent.customer) == mh, S._gst_for_site(site, "", customer=parent.customer)))
	check("another buyer with the same site name never lends its GSTIN",
		lambda: _assert(S._gst_for_site(site, "", customer=stranger.customer) == gj, S._gst_for_site(site, "", customer=stranger.customer)))
	check("the party GSTIN shown on the entry page follows the same rule",
		lambda: _assert(S.get_party_gstin(parent.customer, site)["shipping_gstin"] == mh, S.get_party_gstin(parent.customer, site)))

	# The old write-back's copy: the child's site on the parent, with no state.
	copy = frappe.get_doc({
		"doctype": "Buyer Address", "parent": parent.name, "parenttype": "Buyer Master", "parentfield": "addresses",
		"idx": 9, "site_name": site, "address_line": mum["address_line"] + ", Mumbai, Maharashtra, 421302", "is_shipping": 0,
	})
	copy.db_insert()
	check("a bare copy of the site on the parent no longer wins the GSTIN",
		lambda: _assert(S._gst_for_site(site, "", customer=parent.customer) == mh, S._gst_for_site(site, "", customer=parent.customer)))

	frappe.db.set_value("Buyer Address", copy.name, "state", "Karnataka")
	check("two complete masters with different GSTINs give no GSTIN rather than a guess",
		lambda: _assert(S._gst_for_site(site, "", customer=parent.customer) == "", S._gst_for_site(site, "", customer=parent.customer)))
	check("the clash names both masters",
		lambda: _assert(sorted(m for m, _g in S.site_gst_conflict(parent.customer, site)) == sorted([parent.name, child.name]),
			S.site_gst_conflict(parent.customer, site)))
	frappe.db.delete("Buyer Address", {"name": copy.name})

	# --- picked or typed -----------------------------------------------------------
	known = frappe.get_all("Buyer Address", filters={"parent": ["in", [parent.name, child.name]]},
		fields=["address_line", "city", "state", "pincode", "country"])
	line = mum["address_line"]
	check("the dropdown's text (line, city, state, pincode) is a known address",
		lambda: _assert(E._address_known(f"{line}, Mumbai, Maharashtra, 421302", known)))
	check("a differently spelt city with the row's pincode is still the same address",
		lambda: _assert(E._address_known(f"{line}, BOMBAY, Maharashtra, 421302, India", known)))
	check("a new address is not known",
		lambda: _assert(not E._address_known(f"GSTTEST {tag} Warehouse 7, Thane, 421302", known)))

	def rows_of(name):
		return frappe.get_all("Buyer Address", filters={"parent": name}, fields=["address_line", "site_name", "state", "pincode"])

	before_p, before_c = len(rows_of(parent.name)), len(rows_of(child.name))
	picked = frappe._dict(customer=parent.customer, custom_site_name=site, custom_billing_gstin=mh,
		custom_billing_address_text=f"{line}, Mumbai, Maharashtra, 421302",
		custom_shipping_address_text=f"{line}, Mumbai, Maharashtra, 421302")
	E._write_back_addresses_to_buyer(picked)
	check("an order whose addresses were picked writes nothing back",
		lambda: _assert((len(rows_of(parent.name)), len(rows_of(child.name))) == (before_p, before_c),
			(len(rows_of(parent.name)), len(rows_of(child.name)))))

	typed = f"GSTTEST {tag} Gala 12, Kalher Village, Thane, 421302"
	E._write_back_addresses_to_buyer(frappe._dict(customer=parent.customer, custom_site_name=site, custom_billing_gstin=mh,
		custom_billing_address_text=f"{line}, Mumbai, Maharashtra, 421302", custom_shipping_address_text=typed))
	added = [r for r in rows_of(child.name) if r.address_line == typed]
	check("a typed shipping address goes to the master that owns the site, not the parent",
		lambda: _assert(len(added) == 1 and len(rows_of(parent.name)) == before_p, (added, len(rows_of(parent.name)))))
	check("it carries the site, the master's state and the pincode from the text",
		lambda: _assert(added and (added[0].site_name, added[0].state, added[0].pincode) == (site, "Maharashtra", "421302"), added))
	check("with the new row on the child, the site's GSTIN is still the child's",
		lambda: _assert(S._gst_for_site(site, "", customer=parent.customer) == mh))

	typed_bill = f"GSTTEST {tag} Office 3, Andheri East, Mumbai, 400069"
	E._write_back_addresses_to_buyer(frappe._dict(customer=parent.customer, custom_site_name=site, custom_billing_gstin=mh,
		custom_billing_address_text=typed_bill, custom_shipping_address_text=typed))
	check("a typed billing address goes to the master whose GSTIN the order bills under",
		lambda: _assert([r.address_line for r in rows_of(child.name)].count(typed_bill) == 1
			and [r.address_line for r in rows_of(parent.name)].count(typed_bill) == 0))
	check("the typed shipping address is not added a second time",
		lambda: _assert([r.address_line for r in rows_of(child.name)].count(typed) == 1))

	# --- city-less rows are not re-created on every save ------------------------
	def address_count(text):
		return frappe.db.sql("""SELECT COUNT(*) FROM tabAddress a JOIN `tabDynamic Link` dl ON dl.parent=a.name
			AND dl.parenttype='Address' AND dl.link_doctype='Customer' WHERE dl.link_name=%s AND a.address_line1=%s""",
			(child.customer, text))[0][0]

	doc = frappe.get_doc("Buyer Master", child.name)
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	first = address_count(typed)
	doc.reload()
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	doc.reload()
	doc.flags.ignore_mandatory = True
	doc.save(ignore_permissions=True)
	check("a row with no city makes one ERPNext Address, however often the buyer is saved",
		lambda: _assert(first == 1 and address_count(typed) == 1, (first, address_count(typed))))

	return _report()


def _report():
	width = max((len(r[1]) for r in R), default=10)
	print("=" * (width + 12))
	print("Site-wise GST and the e-com address write-back")
	print("=" * (width + 12))
	for status, label, detail in R:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print("-" * (width + 12))
	print(f"{sum(1 for r in R if r[0] == 'PASS')}/{len(R)} passed")
	frappe.db.commit()
	return R
