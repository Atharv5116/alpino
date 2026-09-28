"""Vocabulary for Material Management: Material Request, Material Issue, Material Return.

Kept apart from alpinos.production.constants so the masters' vocabulary is not edited.
The mapping to ERPNext is:

    Material Request (MR)  = Material Request, type "Material Transfer", Main -> WIP
    Material Issue   (MI)  = Stock Entry, purpose "Material Transfer for Manufacture", Main -> WIP
    Material Return  (MRT) = Stock Entry, purpose "Material Transfer", WIP -> Main
"""

from alpinos.production import constants as C

# --- Sub PO execution statuses added by this module ----------------------------------

SUB_EXECUTION_PENDING_STORE_ISSUE = "Pending Store Issue"
SUB_EXECUTION_READY_TO_RUN = "Ready to Run"

# --- Material Request ---------------------------------------------------------------

MR_DOCTYPE = "Material Request"
MR_TYPE = "Material Transfer"
MR_NAMING_SERIES = "MR-.YYYY.-.#####"

MR_SOURCE_AUTO = "Auto"
MR_SOURCE_MANUAL = "Manual"
MR_SOURCES = (MR_SOURCE_AUTO, MR_SOURCE_MANUAL)

MR_DRAFT = "Draft"
MR_PENDING_ISSUE = "Pending Issue"
MR_PARTIALLY_ISSUED = "Partially Issued"
MR_FULLY_ISSUED = "Fully Issued"
MR_CANCELLED = "Cancelled"
MR_STATUSES = (MR_DRAFT, MR_PENDING_ISSUE, MR_PARTIALLY_ISSUED, MR_FULLY_ISSUED, MR_CANCELLED)

#: An MR a Material Issue may be raised against (and that appears in the MI picker).
MR_ISSUABLE_STATUSES = (MR_PENDING_ISSUE, MR_PARTIALLY_ISSUED)

#: The materials an MR row may carry. An FG is what a Sub PO makes, never what it consumes.
MR_MATERIAL_TYPES = C.ITEM_COMPONENT_TYPES

# --- Stock Entries --------------------------------------------------------------------

SE_DOCTYPE = "Stock Entry"
KIND_ISSUE = "Material Issue"
KIND_RETURN = "Material Return"
ENTRY_KINDS = (KIND_ISSUE, KIND_RETURN)

ISSUE_PURPOSE = "Material Transfer for Manufacture"
RETURN_PURPOSE = "Material Transfer"

MI_NAMING_SERIES = "MI-.YYYY.-.#####"
MRT_NAMING_SERIES = "MRT-.YYYY.-.#####"

SE_DRAFT = "Draft"
SE_SUBMITTED = "Submitted"
SE_CANCELLED = "Cancelled"

RETURN_REASON_OTHER = "Other"
RETURN_REASONS = (
	"Excess Material",
	"Unused Material",
	"Damaged Packaging",
	"Quality Rejection",
	"Machine Spillage",
	"Production Adjustment",
	RETURN_REASON_OTHER,
)

# --- Roles ------------------------------------------------------------------------------

ROLE_STORE_PLANNER = "Store Planner"
ROLE_STORE_USER = "Store User"
ROLE_STORE_MANAGER = "Store Manager"

STORE_MM_ROLES = (ROLE_STORE_PLANNER, ROLE_STORE_USER, ROLE_STORE_MANAGER)

STORE_ROLE_DESCRIPTIONS = {
	ROLE_STORE_PLANNER: "Plans sub orders on the Store Planning board and generates Material Requests.",
	ROLE_STORE_USER: "Creates and submits Material Requests, Material Issues and Material Returns.",
	ROLE_STORE_MANAGER: "Everything a Store User does, plus cancelling and editing after submit.",
}

#: Allowed everything in Material Management, on top of the store roles.
SUPER_ROLES = (C.ROLE_PRODUCTION_ADMIN, C.ROLE_PRODUCTION_MANAGER, "System Manager")

#: Who may create and submit MR / MI / MRT.
STORE_WRITE_ROLES = (ROLE_STORE_USER, ROLE_STORE_MANAGER) + SUPER_ROLES
#: Who may cancel, or edit after submit.
STORE_MANAGE_ROLES = (ROLE_STORE_MANAGER,) + SUPER_ROLES
#: Who may generate the auto MR from a planned sub order.
STORE_PLAN_ROLES = (ROLE_STORE_PLANNER, ROLE_STORE_MANAGER) + SUPER_ROLES
#: Everyone who may open the Material Management screens.
STORE_READ_ROLES = STORE_MM_ROLES + C.PRODUCTION_ROLES + ("System Manager",)

#: Told when an auto MR is generated. The Store Receiving roles are the existing store team
#: (alpinos.production.constants.STORE_ROLES), so they are told as well.
MR_NOTIFY_ROLES = (ROLE_STORE_USER, ROLE_STORE_MANAGER) + tuple(C.STORE_ROLES)

PAGE_LENGTHS = (50, 100, 200)
DEFAULT_PAGE_LENGTH = 50
