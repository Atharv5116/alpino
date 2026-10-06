"""doc_events wrappers for the Phase 4+ builders.

hooks.py points at these wrappers rather than at the builders' modules directly, so a
document save never breaks while a builder's module is not deployed yet: a missing module
or function is a no-op. Anything the real handler raises (a validation message) is NOT
swallowed -- it reaches the user exactly as the handler raised it.
"""

import importlib


def _handler(module_name, function_name):
	try:
		module = importlib.import_module(module_name)
	except ModuleNotFoundError as e:
		if e.name == module_name:
			return None
		raise
	fn = getattr(module, function_name, None)
	return fn if callable(fn) else None


def _call(module_name, function_name, doc, method=None):
	fn = _handler(module_name, function_name)
	if fn is None:
		return None
	return fn(doc, method)


def delivery_note_validate(doc, method=None):
	"""Delivery Note validate -> alpinos.production.dispatch_rules.validate_delivery_note."""
	return _call("alpinos.production.dispatch_rules", "validate_delivery_note", doc, method)


def stock_entry_validate(doc, method=None):
	"""Stock Entry validate -> alpinos.production.inventory_rules.validate_negative_and_status.
	The handler itself returns at once for entries it does not own."""
	return _call("alpinos.production.inventory_rules", "validate_negative_and_status", doc, method)
