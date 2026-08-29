# Alpinos — Code Architecture

How the `alpinos` app is built, and how it extends ERPNext / HRMS / Frappe **without editing those apps**. Read this before adding a feature so your change lands in the right layer and follows the framework rules the app already relies on.

- App: `alpinos` (title *Alpinos Development*), a custom Frappe app on ERPNext + HRMS.
- Domain: sales-order entry & dispatch, buyer/customer masters, pick list → delivery note flow, attendance/HR, onboarding, invoicing.
- Everything below is wired from one file — [`alpinos/hooks.py`](../alpinos/hooks.py). Start there.

---

## 1. The golden rule: never edit ERPNext/HRMS/Frappe

No JSON or Python in the vendor apps is touched. Every customization lands through one of the framework's designed extension points, all registered in `hooks.py`. The mechanisms, in order of how you should reach for them (cleanest first):

| # | Mechanism | Hook | Use it for |
|---|---|---|---|
| 1 | **Doc-event handler** | `doc_events` | Add a validation / side effect on a doctype's lifecycle (validate, on_submit, …) |
| 2 | **Controller subclass** | `override_doctype_class` | Change how a doctype *behaves* (override a method, drop a stock check) |
| 3 | **Custom field / property setter** | `after_migrate` + `fixtures` | Add fields / tweak field properties on a core doctype |
| 4 | **Whitelisted-method override** | `override_whitelisted_methods` | Replace a specific server endpoint |
| 5 | **Monkey-patch** | `boot_session` / `before_request` | Last resort — patch a vendor *function* the above can't reach |

Prefer 1–3. Reach for 4–5 only when the change can't be expressed as a subclass or field.

---

## 2. Extension mechanisms in this app

### 2.1 Doc-event handlers (`doc_events`) — the workhorse

Map a doctype's lifecycle event to one dotted path, or a **list** of them that run in order. This is where most business rules live.

The **Sales Order `validate`** is the canonical example — an ordered 8-function pipeline:

```python
"Sales Order": {
    "validate": [
        "alpinos.sales_order_offline_buyer.validate_...",
        "alpinos.sales_order_offline_buyer.sync_sales_order_offline_buyer_fields",
        "alpinos.sales_order_api.validate_sales_order_pricing",
        "alpinos.sales_order_api.validate_so_freebies_and_box_multiples",
        "alpinos.ecom_sales_order_api.validate_ecom_sales_order",
        "alpinos.dispatch_date_utils.validate_dispatch_date_on_save",
        "alpinos.workflow_engine.sales_order_validate",
        "alpinos.qty_flow.sales_order_qty_remarks",
    ],
    "on_submit":  "alpinos.workflow_engine.sales_order_on_submit",
    "on_cancel":  "alpinos.workflow_engine.sales_order_on_cancel",
}
```

Handler signature is always `def handler(doc, method=None)`. Convention: files named `*_hooks.py` (e.g. `pick_list_hooks.py`, `delivery_note_hooks.py`) hold these handlers; feature modules (`sales_order_api.py`, `workflow_engine.py`) also expose them. Other doctypes hooked include Pick List, Delivery Note, Attendance, Attendance Request, Leave Application, Employee Checkin (`after_insert → attendance_healer.heal_on_checkin`), Quotation, Opportunity, Stock Entry, Batch, Item, Employee Onboarding.

### 2.2 Controller subclasses (`override_doctype_class`)

Replace a doctype's Python controller with a subclass, so `frappe.get_doc`/save/submit instantiate ours. Twelve are registered. The idiom is **extend-and-delegate**:

```python
class CustomAttendanceRequest(HRMSAttendanceRequest):
    def validate(self):
        self._apply_single_day_or_range()   # our rules first
        super().validate()                   # then the stock rules
        self._enforce_mandatory_punches()    # then more of ours
```

Two sub-patterns appear:
- **Add rules** around `super()` (most files).
- **Drop a stock check** by overriding a method to a `pass`/`return` no-op — e.g. `sales_order_override.validate_party_address` (addresses come from Buyer Master, not the standard party link); `attendance_request_override.validate_request_overlap` (multiple same-day requests are allowed).

The subclasses live in [`alpinos/overrides/`](../alpinos/overrides/) (one exception: `Expense Claim` → `customize_expense_claim.ExpenseClaimOverride`). Full map: `overrides/` — Sales Order, Pick List, Delivery Note, Attendance Request, Employee Checkin, Leave Application, Shift Request, Interview, Job Applicant, Job Opening, Employee Onboarding, User.

### 2.3 Custom fields, property setters, patches (schema without editing core)

The app never edits a core doctype's JSON. Schema changes are **code-owned and re-applied on every `bench migrate`**, not carried as static fixtures. Three layers:

1. **Programmatic custom fields via `after_migrate`** — the primary mechanism. ~18 `*_custom_fields.py` modules each declare `{ "DocType": [ dict(fieldname=…, fieldtype=…, insert_after=…), … ] }` and call `create_custom_fields(fields, update=True)`. `update=True` makes it idempotent (re-runnable every migrate), so **the field definitions in code are the single source of truth**. These modules also do things fixtures can't: delete stale fields, force a fieldtype change in the DB, prune `field_order`, or conditionally skip a block. Entry points are listed in the `after_migrate` array in `hooks.py`.
2. **Property setters** — override one attribute of a standard field (hide, relabel, relax `reqd`) without touching the DocField. Programmatic via a shared `update_property_setter(...)` helper, plus `fixtures/property_setter.json` (264 rows).
3. **Patches** (`patches.txt` + `patches/`) — run **once per site**, split into `[pre_model_sync]` / `[post_model_sync]`. For ordering-sensitive fixes (e.g. delete a Select field before a fixture recreates it as a Link), renames, and one-off data backfills.

**Fixtures vs programmatic** is a deliberate choice here: `fixtures/custom_field.json` carries only ~21 fields (Employee Onboarding, Interview, Pick List Item, Expense Claim, Stock Entry); *everything else* is programmatic. Known gotcha: **fixtures re-sync *after* patches every migrate**, so a delete-patch alone won't remove a fixtured field — remove the fixture entry too.

### 2.4 Whitelisted-method overrides (`override_whitelisted_methods`)

Remap a vendor endpoint to ours (same signature):
- `frappe.utils.print_format.download_pdf → alpinos.pdf_tolerant.download_pdf` (tolerate broken image links)
- `erpnext.accounts.party.get_party_details → alpinos.item_details.get_party_details`
- `erpnext.stock.get_item_details.get_item_details → alpinos.item_details.get_item_details`
- `erpnext.crm...opportunity.make_quotation → alpinos.opportunity_make_quotation.make_quotation`

### 2.5 Monkey-patches (the riskiest layer — flagged deliberately)

A few changes can't be a subclass or a field, so they replace a vendor *function* at import/boot/request time. These depend on load order and are re-applied via `boot_session` / `before_request` for safety:

- **`employee_checkin_override._apply_checkout_reason_patch`** — swaps HRMS's strict IN/OUT pairing for a first-log→last-log span rule. Must patch **both** `employee_checkin` *and* the copies re-imported into `shift_type.py` (auto-attendance imports them by name), or it's a no-op. Applied at import + `boot_session`.
- **`interview_override`** — rebinds `Interview.on_submit` and fixes an HRMS `update_job_applicant_status` signature. Applied at import + `boot_session` + `after_migrate`.
- **`oauth_override`** — extends Raven mobile OAuth token expiry 1h → 7d. Applied per request via `before_request`. Self-test in `verify_oauth_fix.py`.
- **`delivery_note_override`** — a *scoped, self-reverting* patch: inside `validate`/`on_submit`/`on_cancel` it temporarily rebinds `frappe.get_doc`/`frappe.get_all` to resolve custom SO-child rows as `Sales Order Item`, then restores them in a `finally`. Not thread-safe under concurrent DN processing.

### 2.6 Other hooks in use
- **`permission_query_conditions` / `has_permission`** — row-level visibility for Pick List, Delivery Note, Salary Slip. ⚠️ `get_all`/`db.sql`/`get_value` bypass these — test as a restricted user.
- **`doctype_js` / `doctype_list_js`** — attach client scripts to standard forms/lists (User, Sales Order, Quotation, Pick List, Item). ⚠️ changes need `bench clear-cache`, not just restart/build.
- **`jinja.methods`** — expose print/website helpers (`alpinos.utils.*`). Each entry must point at a *function*, exposed under its own name.
- **`scheduler_events`** — background jobs (see §6).
- **`app_include_js` / `app_include_css`** — desk-wide assets (`alpinos_pages.css`, sales-order hub, item row colors, list prefs).

---

## 3. Repository layout & naming conventions

```
alpinos/
├── hooks.py                     # the wiring map — read first
├── *_api.py                     # @frappe.whitelist() RPC endpoints (shared service layer)
├── *_hooks.py                   # doc_event handlers
├── *_custom_fields.py           # schema setup (create_custom_fields, after_migrate)
├── *_client_script.py           # JS pushed onto standard doctype forms
├── *_workflow_setup.py          # programmatic Workflow / Workflow State records
├── *_override.py, overrides/    # controller subclasses + monkey-patches
├── workflow_engine.py           # the custom SO→PL→DN status engine
├── config/                      # desk config
├── patches.txt, patches/        # one-per-site migrations
├── public/                      # css + js (doctype_js, list_js, app_include)
├── fixtures/                    # custom_field.json (21) + property_setter.json (264)
└── alpinos_development/
    ├── doctype/                 # ~50 custom doctypes (the app's own data models)
    ├── page/                    # ~22 custom SPA-style desk pages
    └── report/                  # ~11 Script Reports
```

Naming tells you the layer: `*_api.py` = whitelisted endpoints, `*_hooks.py` = doc-event handlers, `*_custom_fields.py` = schema, `*_client_script.py` = client JS, `*_override.py`/`overrides/` = subclasses, `*_workflow_setup.py` = workflow records. Test files: `e2e_*`, `*_test`.

---

## 4. Custom doctypes (the app's own data models)

~50 doctypes under `alpinos_development/doctype/`, grouped by domain. Highlights:

- **Buyer / customer:** `buyer_master` (`OBM-.YYYY.-.#####`) with child `buyer_address` (site/address book), `buyer_item`/`buyer_margin` (per-buyer pricing); `alpino_customer_type` (channel + abbreviation, drives the dispatch-report columns); `channel`, `state`, `city` masters.
- **Sales / dispatch:** `post_dispatch` (+ `post_dispatch_grn_item`) for post-delivery/GRN tracking; SO child tables `sales_order_marketing_freebie`, `sales_order_scheme_item`, `sales_order_additional_units_item`, `sales_order_sticker_attachment`; `product_bundle_mapping`; `alpino_product_sale` (direct sale).
- **Attendance / HR:** `monthly_attendance_batch` (submittable) + `monthly_attendance_batch_row`; `attendance_request_detail` / `attendance_request_log` (child tables on Attendance Request); `essl_settings` (single) + `essl_device`; `work_from_home_request`; `late_entry_threshold`; `employee_checkin_log` (audit).
- **Onboarding:** `branch_policy_access`, `policy`/`policy_child`, `experience`/`qualification_child`/`language_child`.
- **Config / integration:** `invoice_sync_settings` (single), `invoice_sync_log`, `field_change_log` (generic audit).

---

## 5. Desk pages — the SPA-in-a-page pattern

~22 custom pages under `alpinos_development/page/`. These are **not** standard doctype forms; each is a hand-built single-page app inside a desk page. The shared contract:

1. `page.json` registers `module: "Alpinos Development"` + route.
2. `frappe.pages['<route>'].on_page_load = wrapper => { frappe.ui.make_app_page(...) }`.
3. `page.main.html(frappe.render_template('<page_name>'))` drops in a co-located `.html` skeleton, then `new SomeController(page)` runs `setup()`.
4. Inputs are **Frappe controls**, not raw HTML: `frappe.ui.form.make_control({ df: {fieldtype, fieldname, options}, parent, render_input: true })` — so desk styling and Link lookups come free.
5. Fresh-per-visit state: build in `on_page_load`, re-read `frappe.route_options` and prefill/clear in `on_page_show`.
6. Server calls go to `alpinos.*` whitelisted methods via `frappe.call({ method, args, callback })` (JSON) or `window.open('/api/method/…')` (file downloads).

Key pages: `sales_order_entry` / `_view` / `_list`, `ecom_sales_order_entry`, `pick_list_entry` / `pick_list_list`, `delivery_note_entry`, `dispatch_report`, `post_delivery_queue`, `invoice_sync`, `offline_buyer_catalog`, `attendance_batch_entry`. The `*_import` pages (`sales_order_import`, `stock_entry_import`) are thin shims that bounce to Frappe's native Data Import.

---

## 6. Whitelisted RPC surface (API layer)

Two families, both reached by `page JS → frappe.call('alpinos.….fn') → @frappe.whitelist() function`:

- **Shared service modules** (`*_api.py`, `sales_order_offline_buyer.py`) — reusable, called from many pages: `sales_order_api`, `ecom_sales_order_api`, `sales_order_offline_buyer` (buyer/address resolution), `pick_list_api`, `post_delivery_api`, `dispatch_report_api`, `delivery_note_api`.
- **Page-private controllers** (`page/<x>/<x>.py`) — load/save/submit for one page only, addressed by full dotted path (`alpinos.alpinos_development.page.pick_list_entry.pick_list_entry.<fn>`).

Three recurring shapes: **link-field query providers** (decorated `@frappe.validate_and_sanitize_search_inputs`, wired via `frm.set_query`), **client scripts** injected from `*_client_script.py` onto standard forms, and **admin/console-only** whitelisted helpers (`backfill_*`, `report_*`) with no UI caller.

---

## 7. Reports

Eleven **Script Reports** (never Query Reports), all `is_standard: Yes`, module *Alpinos Development*, none prepared/background. `execute(filters)` returns `(columns, data)`. Three idioms:
- **Thin dispatcher** — `execute` normalizes `filters = frappe._dict(...)` and delegates to `get_columns()` + `get_data`/`_get_data` (Accounts Format Report, Attendance Summary).
- **Shared-engine wrapper** — the four qty-flow reports (Opp→Qtn, Qtn→SO, SO→PL, PL→DN) are 4-line files calling `alpinos.qty_flow_report.run("<stage>", filters)`.
- **Core-report reuse** — Stock Balance wraps ERPNext's `StockBalanceReport`; Alpinos Shift Attendance is a None-safe fork of the core report.

Columns are static, or built **dynamically from the filter range** (Attendance Summary emits one `day_<n>` column per calendar day).

---

## 8. Automation & background jobs

- **`scheduler_events`**: `daily` (onboarding emails, reporting-manager role sync, dispatch refresh, SO notifications) + `cron`: eSSL sync `*/5`, auto-attendance `*/30`, missing-checkin alert `30 11 * * *`, Default-Present marking `15 1 * * *`.
- **`workflow_engine.py`** — the custom Sales Order → Pick List → Delivery Note status engine (driven from `doc_events` + the SO-view page's nine action states), separate from Frappe's Workflow doctype.
- **`*_workflow_setup.py`** — programmatically create Workflow / Workflow State / Workflow Action records in `after_migrate` (idempotent).
- **Attendance cluster** — `attendance_scheduler` (periodic auto-attendance), `attendance_request_automation` + `attendance_request_override` (request rules & marking), `attendance_healer` (recompute a day from all its punches on late check-ins), `default_present` (mark flagged employees Present daily).

---

## 9. Conventions & gotchas (learned the hard way)

- **`after_migrate` owns schema.** Add a field → add it to a `*_custom_fields.py` `setup_*` and let `create_custom_fields(update=True)` re-assert it. Don't hand-edit the site DB.
- **Fixtures re-sync after patches.** A delete-patch alone won't remove a fixtured field — drop the fixture entry too.
- **`doctype_js` changes need `bench clear-cache`** (not just restart/build).
- **Permission hooks are bypassed** by `get_all` / `db.sql` / `db.get_value` — test row-level rules as a restricted user.
- **Prefer subclass + `super()`** over monkey-patching. If you must patch a vendor function, re-apply it via `boot_session` and patch every module that re-imported the name (see the checkin/shift_type case).
- **Deploy after a schema change:** `bench migrate` (custom fields + property setters + patches), then `bench build` (SPA pages/JS), then `bench restart`.
