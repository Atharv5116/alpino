"""Buyer Order Request page (doc Section 2): /order-request?token=..., no login."""

import frappe

no_cache = 1


def get_context(context):
	from alpinos.offline_sales.order_link import MSG_LINK_INACTIVE, MSG_NO_PRODUCTS, LinkRefused, page_context

	context.no_breadcrumbs = True
	context.show_sidebar = False
	context.title = "Order Request"
	token = frappe.form_dict.get("token") or ""
	context.refused_message = MSG_LINK_INACTIVE
	context.no_products = MSG_NO_PRODUCTS
	# a browser also logged in to the ERP: its POSTs need the session's CSRF token or Frappe answers
	# "Invalid Request" (a buyer with no login has none and is not checked). Read it before
	# page_context, whose set_user("Administrator") swaps the session data out.
	context.session_csrf = (frappe.session.data.get("csrf_token") or "") if frappe.session.user != "Guest" else ""
	try:
		data = page_context(token)
	except LinkRefused:
		# one page for every failure (deactivated, expired, superseded, invalid, buyer
		# inactive or cancelled): no customer, address, price or product data (doc 7.1)
		context.refused = True
		frappe.local.response["http_status_code"] = 403
		return context
	context.refused = False
	context.order_token = token.strip().lower()
	context.page_data = frappe.as_json(data)
	return context
