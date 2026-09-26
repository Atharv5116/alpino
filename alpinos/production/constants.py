"""Vocabularies for the Production masters (Item, BOM, Process, Machine).

One home for every Select option and role name the module uses, so a screen, a
controller and a permission row can never disagree about what the allowed values are.
The Purchase module keeps its own vocabulary the same way (alpinos.purchase.constants).
"""

# --- Item Master -------------------------------------------------------------

MATERIAL_RM = "RM"
MATERIAL_PM = "PM"
MATERIAL_ADDITIVE = "Additive"
MATERIAL_FG = "FG"

#: What an Item is, for production. RM and Additive are consumed into the mix, PM is what
#: the finished mix is packed into, and FG is the finished good itself -- the thing a BOM
#: makes and a Production Order is raised for.
#:
#: "Additive", not "Additive Item": the recipe grid has always used the short form, so the
#: two vocabularies now match and bom_api no longer has to translate between them.
ITEM_MATERIAL_TYPES = (MATERIAL_RM, MATERIAL_PM, MATERIAL_ADDITIVE, MATERIAL_FG)

#: The types a BOM row may hold. An FG is what a BOM MAKES, never a line inside one.
ITEM_COMPONENT_TYPES = (MATERIAL_RM, MATERIAL_PM, MATERIAL_ADDITIVE)

#: Only meaningful on a PM item -- the kind of packaging it is.
PM_CATEGORY_BOX = "BOX"
PM_CATEGORY_POUCH = "POUCH"
PM_CATEGORIES = (PM_CATEGORY_BOX, PM_CATEGORY_POUCH)


# --- BOM Master --------------------------------------------------------------

#: The physical stage a recipe line belongs to. The Job Card print groups its rows by
#: this, so the printed sheet matches the order of work on the floor.
STAGE_BASE_RM = "Base RM"
STAGE_SYREP = "SYREP"
STAGE_POST_BAKE = "Post-Bake"
STAGE_POUCH_FILLING = "Pouch Filling"

BOM_PROCESS_STAGES = (STAGE_BASE_RM, STAGE_SYREP, STAGE_POST_BAKE, STAGE_POUCH_FILLING)

#: How a recipe line is classified. Deliberately the same three words as the Item's own
#: Material Type, minus the "Item" suffix on Additive, because the BOM grid is read
#: alongside the printed Job Card where the short form is what people say out loud.
BOM_MATERIAL_RM = "RM"
BOM_MATERIAL_ADDITIVE = "Additive"
BOM_MATERIAL_PM = "PM"

BOM_MATERIAL_TYPES = (BOM_MATERIAL_RM, BOM_MATERIAL_ADDITIVE, BOM_MATERIAL_PM)

#: BRD: a BOM is written for exactly one batch, so the grid quantities ARE the batch.
BOM_BASE_BATCH_SIZE = 1

#: UOMs whose quantity is read off a scale, so the Job Card prints them to three decimals.
#: "0.5" and "0.500" are the same number but not the same instruction: the first invites an
#: operator to wonder what was rounded away, and 0.005 Kg of an additive is a real dose.
#: Everything else is counted, and a count prints as a whole number.
#: Compared lower-cased, so Kg / KG / kg all land here.
WEIGHED_UOMS = ("kg", "kgs", "kilogram", "kilograms", "gram", "grams", "g", "mg",
                "litre", "litres", "liter", "liters", "l", "ml")


# --- Machine Master ----------------------------------------------------------

MACHINE_ACTIVE = "Active"
MACHINE_UNDER_MAINTENANCE = "Under Maintenance"
MACHINE_INACTIVE = "Inactive"

MACHINE_STATUSES = (MACHINE_ACTIVE, MACHINE_UNDER_MAINTENANCE, MACHINE_INACTIVE)

#: Only an Active machine may be put to work (Machine Master rule 2 / 3).
MACHINE_ASSIGNABLE_STATUSES = (MACHINE_ACTIVE,)

MACHINE_CAPACITY_UOMS = ("KG", "Liters", "Trays", "Pieces")


# --- Production Order --------------------------------------------------------

PO_TYPE_OWN = "Own Production"
PO_TYPE_EXPORT = "Export"
PO_TYPE_WHITE_LABEL = "White Label"

PRODUCTION_TYPES = (PO_TYPE_OWN, PO_TYPE_EXPORT, PO_TYPE_WHITE_LABEL)

#: PO-V04 -- the two types that are made for somebody else, so a Client is required.
PRODUCTION_TYPES_NEEDING_CLIENT = (PO_TYPE_EXPORT, PO_TYPE_WHITE_LABEL)

PO_DRAFT = "Draft"
PO_PENDING_APPROVAL = "Pending Approval"
PO_APPROVED = "Approved"
PO_SENT_TO_STORE = "Sent To Store"
PO_REJECTED = "Rejected"
PO_CANCELLED = "Cancelled"

#: Task 26. The vocabulary only -- WHO may move a PO between these, and whether a Manager
#: skips Pending Approval, is one of the ten decisions still open, so no transition table is
#: written here yet. Listing the statuses costs nothing and lets the field, the list filter
#: and the audit log all read from one place when the rules land.
PO_STATUSES = (PO_DRAFT, PO_PENDING_APPROVAL, PO_APPROVED, PO_SENT_TO_STORE,
               PO_REJECTED, PO_CANCELLED)

#: The Parent is a planning header: it may still be edited while it is one of these.
PO_EDITABLE_STATUSES = (PO_DRAFT, PO_REJECTED)

PO_NAMING_SERIES = "PO-.###"

#: Task D. Who is told when an order reaches the store. Named here rather than in the
#: notification code, so the two screens and the notification cannot drift apart.
STORE_ROLES = ("Store Receiving Manager", "Store Receiving User")

#: Task 27 / 31. A sub order that has not started is still plannable.
SUB_EXECUTION_UNASSIGNED = "Unassigned"
SUB_EXECUTION_ASSIGNED = "Assigned"
SUB_EXECUTION_IN_PROGRESS = "In Progress"
SUB_EXECUTION_COMPLETED = "Completed"
SUB_EXECUTION_STATUSES = (SUB_EXECUTION_UNASSIGNED, SUB_EXECUTION_ASSIGNED,
                          SUB_EXECUTION_IN_PROGRESS, SUB_EXECUTION_COMPLETED)

#: Tasks 29 / 36: the statuses a Parent may be in for its sub orders to be split or merged.
PO_PLANNABLE_STATUSES = (PO_APPROVED, PO_SENT_TO_STORE)

#: Task 5. The grid copied from the BOM onto the order. "Parent" here means the Production
#: Order, not the BOM.
PO_ROW_MATERIAL_TYPES = BOM_MATERIAL_TYPES


# --- Roles -------------------------------------------------------------------

#: Machine Types are the vocabulary every other screen picks from, so only an admin
#: may change them (Machine Master 2.1). Everyone else selects from what exists.
ROLE_PRODUCTION_ADMIN = "Production Admin"
ROLE_PRODUCTION_MANAGER = "Production Manager"
ROLE_PRODUCTION_USER = "Production User"

PRODUCTION_ROLES = (ROLE_PRODUCTION_ADMIN, ROLE_PRODUCTION_MANAGER, ROLE_PRODUCTION_USER)

ROLE_DESCRIPTIONS = {
	ROLE_PRODUCTION_ADMIN: "Owns the production masters: Machine Types, Processes, BOMs.",
	ROLE_PRODUCTION_MANAGER: "Runs production: may add machines and write BOMs and processes.",
	ROLE_PRODUCTION_USER: "Works on the floor: reads the masters, changes none of them.",
}


def select_options(values):
	"""Render a tuple of vocabulary values as a Frappe Select `options` string."""
	return "\n".join(values)
