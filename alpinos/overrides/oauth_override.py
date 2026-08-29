"""Extend OAuth token expiry for the Raven mobile app.

Raven refreshes tokens only when 10 minutes or less remain but checks every 5 minutes,
so the default 1-hour tokens expire before a refresh fires. Bump expiry to 7 days.
"""

import frappe
from oauthlib.openid.connect.core.endpoints.pre_configured import Server as WebApplicationServer
from frappe.oauth import OAuthWebRequestValidator


def get_oauth_server_with_extended_token_expiry():
	"""Replacement for frappe.integrations.oauth2.get_oauth_server with extended token expiry."""
	if not getattr(frappe.local, "oauth_server", None):
		oauth_validator = OAuthWebRequestValidator()
		token_expires_in = 604800  # 7 days
		frappe.local.oauth_server = WebApplicationServer(
			oauth_validator, 
			token_expires_in=token_expires_in
		)
	
	return frappe.local.oauth_server


def patch_oauth_server():
	"""Monkey-patch get_oauth_server to use extended token expiry; runs on every request via before_request."""
	import frappe.integrations.oauth2

	if frappe.integrations.oauth2.get_oauth_server is not get_oauth_server_with_extended_token_expiry:
		frappe.integrations.oauth2.get_oauth_server = get_oauth_server_with_extended_token_expiry
