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
	Override Frappe's get_oauth_server to use extended token expiry.
	This is called via override_whitelisted_methods in hooks.py
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
