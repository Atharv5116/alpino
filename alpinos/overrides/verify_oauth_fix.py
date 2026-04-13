import frappe


@frappe.whitelist()
def verify():
	"""Run with: bench --site alpinos.local execute alpinos.overrides.verify_oauth_fix.verify"""
	from alpinos.overrides.oauth_override import patch_oauth_server, get_oauth_server_with_extended_token_expiry
	patch_oauth_server()
	
	import frappe.integrations.oauth2
	
	# Check if the function is patched
	is_patched = frappe.integrations.oauth2.get_oauth_server is get_oauth_server_with_extended_token_expiry
	
	# Create the server and check expires_in
	server = frappe.integrations.oauth2.get_oauth_server()
	
	# Check the token endpoint's bearer token generator
	from oauthlib.oauth2.rfc6749.tokens import BearerToken
	for attr_name in dir(server):
		attr = getattr(server, attr_name, None)
		if isinstance(attr, BearerToken):
			expires_in = attr.expires_in
			return {
				"status": "OK" if expires_in == 604800 else "FAILED",
				"is_patched": is_patched,
				"expires_in_seconds": expires_in,
				"expires_in_days": expires_in / 86400 if expires_in else None,
			}
	
	# Fallback: check _params on endpoints
	for endpoint_name in ['_access_token', '_token']:
		endpoint = getattr(server, endpoint_name, None)
		if endpoint and hasattr(endpoint, 'tokens'):
			for token_type in endpoint.tokens:
				bt = endpoint.tokens[token_type]
				if isinstance(bt, BearerToken):
					return {
						"status": "OK" if bt.expires_in == 604800 else "FAILED",
						"is_patched": is_patched,
						"expires_in_seconds": bt.expires_in,
						"expires_in_days": bt.expires_in / 86400 if bt.expires_in else None,
					}
	
	return {"status": "UNKNOWN", "is_patched": is_patched, "note": "Could not find BearerToken on server object"}
