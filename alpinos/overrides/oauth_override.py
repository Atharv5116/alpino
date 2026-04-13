"""
OAuth Token Expiry Override for Raven Mobile App
This override increases the OAuth token expiry time to prevent
authentication errors in the Raven mobile app after 1 hour.

The Raven mobile app has a bug where it only refreshes tokens when
they have 10 minutes or less remaining, but checks every 5 minutes.
This causes tokens to expire before refresh happens.

Solution: Increase token expiry from 1 hour (3600s) to 7 days (604800s)
This gives the mobile app plenty of time to refresh tokens.
"""

import frappe
from oauthlib.openid.connect.core.endpoints.pre_configured import Server as WebApplicationServer
from frappe.oauth import OAuthWebRequestValidator


def get_oauth_server_with_extended_token_expiry():
	"""
	Replacement function for frappe.integrations.oauth2.get_oauth_server
	with extended token expiry for Raven mobile app.
	"""
	if not getattr(frappe.local, "oauth_server", None):
		oauth_validator = OAuthWebRequestValidator()
		# Set token expiry to 7 days (604800 seconds) instead of default 1 hour (3600 seconds)
		# This prevents Raven mobile app authentication errors
		token_expires_in = 604800  # 7 days
		frappe.local.oauth_server = WebApplicationServer(
			oauth_validator, 
			token_expires_in=token_expires_in
		)
	
	return frappe.local.oauth_server


def patch_oauth_server():
	"""
	Monkey-patch the get_oauth_server function to use extended token expiry.
	This is called on every request via before_request hook.
	Lightweight check ensures minimal overhead.
	"""
	import frappe.integrations.oauth2
	
	# Only patch if not already patched (avoids redundant work on each request)
	if frappe.integrations.oauth2.get_oauth_server is not get_oauth_server_with_extended_token_expiry:
		frappe.integrations.oauth2.get_oauth_server = get_oauth_server_with_extended_token_expiry
