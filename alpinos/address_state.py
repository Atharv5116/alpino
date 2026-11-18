"""ERPNext Address: the State spelled the way India Compliance accepts it.

India Compliance (on the site since 16 Nov 2026) refuses an Indian Address whose State is
not one of its own names: "Invalid State - Please select a valid State from available
options". The Buyer Master's State list spells some states differently ("Jammu & Kashmir"
for "Jammu and Kashmir"), so saving such a buyer -- or creating an order that saves the
buyer, its Customer and then its primary Address -- was refused.

Only the ERPNext Address takes India Compliance's spelling, just before India Compliance
checks it. The Buyer Master, its State list and the reports built on them keep their own.
A State that is not a spelling of an Indian state (a city typed as the state) is left as it
is, so India Compliance still points at it.
"""

import re

# Buyer Master State list names that are not a plain spelling of India Compliance's name.
_ALIASES = {"lakshadweep": "Lakshadweep Islands"}


def _key(name):
	return re.sub(r"[^a-z]", "", (name or "").lower().replace("&", "and"))


def _known_states():
	try:
		from india_compliance.gst_india.constants import STATE_NUMBERS
	except ImportError:
		return {}
	return STATE_NUMBERS


def ic_state(state):
	"""India Compliance's name for `state` ("Jammu & Kashmir" -> "Jammu and Kashmir",
	"bihar" -> "Bihar"), or `state` unchanged when it is already right or not a state."""
	known = _known_states()
	if not state or not known or state in known:
		return state
	key = _key(state)
	for name in known:
		if _key(name) == key:
			return name
	return _ALIASES.get(key, state)


def before_validate(doc, method=None):
	if doc.get("country") == "India" and doc.get("state"):
		doc.state = ic_state(doc.state)
