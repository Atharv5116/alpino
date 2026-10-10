"""What a has_permission hook returns when it has no objection.

Frappe v15 reads a hook's answer as: None = no opinion, anything else decides (the first
non-None answer, in reverse hook order, wins). v16 reads every hook and denies on any falsy
answer, None included, so a hook that abstains must say True there. On v15, True would
end the chain early and skip the other hooks, so abstaining stays None.

alpinos hooks only ever deny: they return False, or NO_OBJECTION.
"""

from alpinos.query_compat import IS_V16

NO_OBJECTION = True if IS_V16 else None
