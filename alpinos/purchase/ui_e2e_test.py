"""End-to-end through the DATA-ENTRY SURFACES, as the roles that use them.

    bench --site alpinos.test execute alpinos.purchase.ui_e2e_test.run

WHY THIS EXISTS SEPARATELY FROM e2e_test
----------------------------------------
`e2e_test` drives documents: frappe.get_doc, .save(), .submit(). It was 38/38 green while
the Purchase Inward screen showed no items at all, because it never once called
`get_purchase_order_items` -- the single endpoint that screen's grid is built from. A
tested-looking module had its main surface entirely uncovered.

So this suite calls only what a browser calls, and in the same shapes:

    * the page's own whitelisted endpoints, taken from each page's `method:` calls
    * frappe.client.insert / get / save / submit, which is how the entry pages persist
    * the pages' SAVE PATTERN, verbatim: fetch the doc, shallow-merge a payload whose
      child arrays REPLACE the server's, then save. That merge is where the row-identity
      defect lived, and only replaying it can catch the next one.

AND AS THE REAL ROLE, NOT ADMINISTRATOR
---------------------------------------
Administrator's get_roles() returns every role, so a permission gate that refuses the
Store team is invisible to a test run as Administrator. Each stage here runs as a user
holding only that stage's roles, which is the other half of why a screen can fail while
the suite passes.

Nothing is mocked and nothing is rolled back on success: the chain it builds is a real
one, so a failure can be opened in the browser afterwards.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, flt, now_datetime, today

from alpinos.purchase import constants as C
from alpinos.purchase import e2e_test as H

R = []
_STEP = [0]


def _log(state, label, detail=""):
	R.append((state, label, detail))


def step(label, fn):
	"""Run one UI call. Any exception is the failure -- this suite asserts no errors."""
	_STEP[0] += 1
	try:
		out = fn()
		_log("PASS", f"{_STEP[0]:02d}. {label}")
		return out
	except Exception as e:
		_log("FAIL", f"{_STEP[0]:02d}. {label}", f"{type(e).__name__}: {frappe.utils.strip_html(str(e))[:260]}")
		raise


def check(label, ok, detail=""):
	_STEP[0] += 1
	_log("PASS" if ok else "FAIL", f"{_STEP[0]:02d}. {label}", "" if ok else detail)


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	have = {r.role for r in u.roles}
	for role in roles:
		if role not in have and frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.save(ignore_permissions=True)
	frappe.db.commit()
	return email


def _as(email):
	frappe.set_user(email)


# ----------------------------------------------------------- page save pattern


def _page_save(doctype, name, payload):
	"""The entry pages' save, verbatim: client.get -> shallow merge -> client.save.

	Object.assign is shallow, so a child array in `payload` REPLACES the server's. Any
	child row arriving without its `name` is a new row to Frappe, which deletes and
	re-inserts the lot under fresh hashes and orphans anything referencing them.
	"""
	server = frappe.client.get(doctype, name)
	merged = dict(server)
	merged.update(payload)
	merged["doctype"] = doctype
	merged["name"] = name
	doc = frappe.get_doc(merged)
	doc.flags.ignore_permissions = False
	doc.save()
	return doc


def run():
	R.clear()
	_STEP[0] = 0
	frappe.set_user("Administrator")
	H.SEQ = H._seq()
	H.COMPANY = H._company()

	purchaser = _user("uie2e-purchase@example.com", list(C.PURCHASE_ROLES) + ["Purchase User"])
	storeman = _user("uie2e-store@example.com", list(C.STORE_ROLES))
	qc_user = _user("uie2e-qc@example.com", list(C.QC_ROLES))
	accountant = _user("uie2e-accounts@example.com", list(C.ACCOUNTS_ROLES))
	approver = _user("uie2e-approver@example.com", [C.ROLE_PURCHASE_MANAGER, "Purchase Manager"])
	admin = _user("uie2e-admin@example.com", [C.ROLE_ADMIN])

	supplier = H.ensure_supplier()
	item = H.ensure_item(f"PITEST-UIE-{H.SEQ}")
	warehouse = H._warehouse()
	# Unique per RUN, not per SEQ. The chain is committed on success, so a second run
	# reusing the invoice number is refused by VAL-PI-15 -- correctly, which made the
	# suite pass once and then abort at step 16 for a reason that was nothing to do with
	# the code under test.
	tag = f"{H.SEQ}-{frappe.generate_hash(length=6)}"
	frappe.db.commit()

	try:
		# ============================== 1. Purchase Order entry page ==========
		_as(purchaser)

		po_payload = {
			# The page now sends this from frappe.defaults; mirrored here so the replay
			# matches what the browser posts.
			"company": frappe.db.get_single_value("Global Defaults", "default_company"),
			"custom_inward_type": C.INWARD_RM,
			"supplier": supplier,
			"transaction_date": today(),
			"schedule_date": add_days(today(), 7),
			"set_warehouse": warehouse,
			"custom_supplier_order_no": f"UIE-SO-{tag}",
			"custom_vehicle_no": "GJ-05-UI-0001",
			"custom_driver_contact_no": "9000000021",
			"custom_direct_purchase_invoice": 0,
			"items": [
				{
					"item_code": item,
					"qty": 100,
					"price_list_rate": 50,
					"discount_percentage": 0,
					"schedule_date": add_days(today(), 7),
					"warehouse": warehouse,
				}
			],
		}
		po = step(
			"PO entry page: frappe.client.insert creates the order",
			lambda: frappe.client.insert(dict({"doctype": "Purchase Order"}, **po_payload)),
		)
		po_name = po["name"]
		rows_before = [r["name"] for r in frappe.client.get("Purchase Order", po_name)["items"]]

		# The page maps this.items, whose rows carry `name` once loaded from the server.
		# Rebuilding the payload from the server doc is what the browser actually posts on
		# a second save; reusing the insert payload would replay the OLD nameless shape.
		po_resave = dict(po_payload)
		po_resave["items"] = [
			{
				"name": r["name"],
				"item_code": r["item_code"],
				"qty": flt(r["qty"]),
				"price_list_rate": flt(r["price_list_rate"]),
				"discount_percentage": flt(r["discount_percentage"]),
				"schedule_date": r["schedule_date"],
				"warehouse": r["warehouse"],
				"custom_item_remarks": r.get("custom_item_remarks"),
			}
			for r in frappe.client.get("Purchase Order", po_name)["items"]
		]
		step(
			"PO entry page: re-save through client.get + merge (the page's own pattern)",
			lambda: _page_save("Purchase Order", po_name, po_resave),
		)
		rows_after = [r["name"] for r in frappe.client.get("Purchase Order", po_name)["items"]]
		check(
			"PO item row identity survives the page's save",
			rows_before == rows_after,
			f"{len(set(rows_before) & set(rows_after))} of {len(rows_before)} names kept; "
			"Purchase Inward Item.po_detail stores these, so churn breaks pending-qty lookup",
		)

		# ============================== 2. PO approval (BRD 3) ================
		actions = step(
			"PO page: get_available_actions as the purchase team",
			lambda: frappe.call(
				"alpinos.purchase.purchase_order_approval.get_available_actions",
				purchase_order=po_name,
			),
		)
		check(
			"Submit for Approval is offered to the purchase team",
			any(a["action"] == "Submit for Approval" for a in actions["actions"]),
			str(actions),
		)
		step(
			"PO page: perform_action Submit for Approval",
			lambda: frappe.call(
				"alpinos.purchase.purchase_order_approval.perform_action",
				purchase_order=po_name,
				action="Submit for Approval",
			),
		)

		_as(approver)
		step(
			"PO page: perform_action Approve as the approver",
			lambda: frappe.call(
				"alpinos.purchase.purchase_order_approval.perform_action",
				purchase_order=po_name,
				action="Approve",
				remarks="Checked against the quotation.",
			),
		)
		_as(purchaser)
		step(
			"PO page: perform_action Send to Supplier as the purchase team",
			lambda: frappe.call(
				"alpinos.purchase.purchase_order_approval.perform_action",
				purchase_order=po_name,
				action="Send to Supplier",
			),
		)
		info = frappe.call(
			"alpinos.purchase.purchase_order_approval.get_available_actions",
			purchase_order=po_name,
		)
		check(
			"BRD 1.4 Create Purchase Inward is now offered (status Sent to Supplier)",
			info["status"] == C.PO_SENT_TO_SUPPLIER and not info["direct_purchase_invoice"],
			str(info),
		)

		# ============================== 3. Inward list page ===================
		step(
			"Inward list page: get_filter_options",
			lambda: frappe.call("alpinos.purchase.inward_list_api.get_filter_options"),
		)
		step(
			"Inward list page: get_purchase_inward_list",
			lambda: frappe.call("alpinos.purchase.inward_list_api.get_purchase_inward_list"),
		)

		# ============================== 4. Inward entry page ==================
		fetched = step(
			"Inward entry page: get_purchase_order_items (the grid's only source)",
			lambda: frappe.call(
				"alpinos.purchase.inward_api.get_purchase_order_items", purchase_order=po_name
			),
		)
		check(
			"the grid is offered the pending line, with an explained skip payload",
			len(fetched["items"]) == 1
			and isinstance(fetched["skipped"], dict)
			and "unmatched_available" in fetched,
			f"items={len(fetched['items'])} skipped={fetched.get('skipped')!r}",
		)
		check(
			"pending equals ordered on the first inward",
			flt(fetched["items"][0]["pending_qty"]) == 100.0,
			str(fetched["items"][0]),
		)

		step(
			"Inward entry page: validate_creation (the live form warning)",
			lambda: frappe.call(
				"alpinos.purchase.inward_api.validate_creation",
				purchase_order=po_name,
				invoice_number=f"UIE-INV-{tag}",
			),
		)

		inward_payload = {
			"purchase_order": po_name,
			"invoice_number": f"UIE-INV-{tag}",
			"invoice_date": today(),
			"challan_no": f"UIE-CH-{tag}",
			"gross_weight": 1200,
			"inward_datetime": str(now_datetime()).split(".")[0],
			"items": [
				{
					"item_code": row["item_code"],
					"po_detail": row["po_detail"],
					"received_qty": 0,
				}
				for row in fetched["items"]
			],
		}
		inward = step(
			"Inward entry page: client.insert saves the draft",
			lambda: frappe.client.insert(
				dict({"doctype": "Purchase Inward"}, **inward_payload)
			),
		)
		inw_name = inward["name"]

		ctx = step(
			"Inward entry page: get_form_context drives the buttons",
			lambda: frappe.call(
				"alpinos.purchase.inward_api.get_form_context", purchase_inward=inw_name
			),
		)
		check("form context reports the draft actions", bool(ctx.get("actions")), str(ctx)[:160])

		step(
			"Inward entry page: run_action submit",
			lambda: frappe.call(
				"alpinos.purchase.inward_api.run_action",
				purchase_inward=inw_name,
				action="submit",
			),
		)

		# ---- 5. Store receiving, as the STORE user, through the page's save ---
		_as(storeman)
		inw_rows_before = [r["name"] for r in frappe.client.get("Purchase Inward", inw_name)["items"]]
		receiving = {
			"actual_arrival_datetime": str(now_datetime()).split(".")[0],
			"vehicle_details_verified": 1,
			"actual_vehicle_no": "GJ-05-UI-9999",
			"actual_driver_contact_no": "9000000022",
			"receiving_remarks": "Received in full, seal intact.",
			# Every field the page's collect_doc sends, not a subset. Omitting one blanks
			# it, and a blanked Purchase-owned field (item_remarks, mrp, usp) reads as the
			# Store team editing the Purchase header -- assert_section_edits_allowed is
			# change-based, so an unfaithful payload fails for the wrong reason.
			"items": [
				{
					"name": r["name"],
					"item_code": r["item_code"],
					"po_detail": r["po_detail"],
					"received_qty": 100,
					"target_warehouse": warehouse,
					"batch_no": r.get("batch_no"),
					"manufacturing_date": today(),
					"mrp": flt(r.get("mrp")),
					"usp": r.get("usp"),
					"item_remarks": r.get("item_remarks"),
				}
				for r in frappe.client.get("Purchase Inward", inw_name)["items"]
			],
		}
		step(
			"Inward entry page: Store records the receipt through the page's save",
			lambda: _page_save("Purchase Inward", inw_name, receiving),
		)
		inw_rows_after = [r["name"] for r in frappe.client.get("Purchase Inward", inw_name)["items"]]
		check(
			"inward item row identity survives an after-submit save",
			inw_rows_before == inw_rows_after,
			f"{len(set(inw_rows_before) & set(inw_rows_after))} of {len(inw_rows_before)} kept",
		)
		fresh = frappe.client.get("Purchase Inward", inw_name)
		check(
			"order_qty is still the ordered quantity after that save",
			flt(fresh["items"][0]["order_qty"]) == 100.0,
			f"order_qty={fresh['items'][0]['order_qty']} pending={fresh['items'][0]['pending_qty']}",
		)

		ctx = frappe.call(
			"alpinos.purchase.inward_api.get_form_context", purchase_inward=inw_name
		)
		sfq = [a for a in ctx["actions"] if a.get("action") == "submit_for_qc"]
		check(
			"Submit for QC is enabled for Store once the receipt is recorded",
			bool(sfq) and sfq[0].get("enabled"),
			str(sfq),
		)
		step(
			"Inward entry page: run_action submit_for_qc",
			lambda: frappe.call(
				"alpinos.purchase.inward_api.run_action",
				purchase_inward=inw_name,
				action="submit_for_qc",
			),
		)
		qc_name = frappe.db.get_value("Purchase Inward", inw_name, "purchase_qc")
		check("a Purchase QC was raised", bool(qc_name), f"purchase_qc={qc_name!r}")

		# ============================== 6. QC list + entry pages ==============
		_as(qc_user)
		step(
			"QC list page: get_filter_options",
			lambda: frappe.call("alpinos.purchase.qc_list_api.get_filter_options"),
		)
		qc_list = step(
			"QC list page: get_purchase_qc_list",
			lambda: frappe.call("alpinos.purchase.qc_list_api.get_purchase_qc_list"),
		)
		check(
			"the new QC appears on the QC list screen",
			qc_name in [r.get("name") for r in qc_list.get("data") or []],
			f"total={qc_list.get('total')} returned={len(qc_list.get('data') or [])}",
		)
		step(
			"QC list page: start_qc",
			lambda: frappe.call(
				"alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.start_qc",
				purchase_qc=qc_name,
			),
		)

		qc_doc = step(
			"QC entry page: client.get loads the inspection",
			lambda: frappe.client.get("Purchase QC", qc_name),
		)
		qc_rows_before = [r["name"] for r in qc_doc["items"]]
		qc_payload = {
			"vehicle_inspection_done": 1,
			"material_inspection_done": 1,
			"packaging_inspection_done": 1,
			"sample_testing_done": 1,
			"vehicle_inspection": [{"vehicle_condition": C.CONDITION_GOOD}],
			"material_inspection": [
				{"item_code": item, "material_condition": C.CONDITION_GOOD}
			],
			"packaging_inspection": [
				{"item_code": item, "packaging_condition": C.CONDITION_GOOD}
			],
			"sample_testing": [{"item_code": item, "sample_qty": 1}],
			"items": [
				{
					"name": r["name"],
					"item_code": r["item_code"],
					"received_qty": r["received_qty"],
					"approved_qty": r["received_qty"],
					"rejected_qty": 0,
				}
				for r in qc_doc["items"]
			],
		}
		step(
			"QC entry page: client.save records the inspections and the decision",
			lambda: _page_save("Purchase QC", qc_name, qc_payload),
		)
		qc_rows_after = [
			r["name"] for r in frappe.client.get("Purchase QC", qc_name)["items"]
		]
		check(
			"QC decision row identity survives the page's save",
			qc_rows_before == qc_rows_after,
			f"{len(set(qc_rows_before) & set(qc_rows_after))} of {len(qc_rows_before)} kept",
		)
		step(
			"QC entry page: complete_qc",
			lambda: frappe.call(
				"alpinos.alpinos_development.doctype.purchase_qc.purchase_qc.complete_qc",
				purchase_qc=qc_name,
			),
		)

		# ============================== 7. GRN list + detail ==================
		grn_name = frappe.db.get_value("Purchase Inward", inw_name, "purchase_receipt")
		check("a Draft GRN was generated", bool(grn_name), f"purchase_receipt={grn_name!r}")

		_as(purchaser)
		step(
			"GRN list page: get_filter_options",
			lambda: frappe.call("alpinos.purchase.grn_list_api.get_filter_options"),
		)
		grn_list = step(
			"GRN list page: get_grn_list",
			lambda: frappe.call("alpinos.purchase.grn_list_api.get_grn_list"),
		)
		check(
			"the Draft GRN appears on the GRN list screen",
			grn_name in [r.get("name") for r in (grn_list.get("data") or grn_list.get("rows") or [])],
			f"keys={list(grn_list)[:5]} total={grn_list.get('total')}",
		)
		step(
			"GRN detail page: client.get loads the receipt",
			lambda: frappe.client.get("Purchase Receipt", grn_name),
		)

		_as(admin)
		step(
			"GRN detail page: client.submit final-submits as Admin (BR-GRN-06)",
			lambda: frappe.client.submit(frappe.client.get("Purchase Receipt", grn_name)),
		)
		check(
			"the GRN reached docstatus 1",
			frappe.db.get_value("Purchase Receipt", grn_name, "docstatus") == 1,
			str(frappe.db.get_value("Purchase Receipt", grn_name, "docstatus")),
		)

		# ============================== 8. Purchase Invoice (BRD 6) ===========
		_as(purchaser)
		invoice = step(
			"Invoice: create_from_grn",
			lambda: frappe.call(
				"alpinos.purchase.purchase_invoice.create_from_grn", purchase_receipt=grn_name
			),
		)
		# create_from_grn returns a Document, and Document has no __getitem__ -- reading it
		# like a dict is what aborted the run above.
		inv_name = invoice.name
		check(
			"the invoice is linked to its GRN and Inward",
			invoice.custom_grn == grn_name and invoice.custom_purchase_inward == inw_name,
			f"grn={invoice.custom_grn} inward={invoice.custom_purchase_inward}",
		)

		step(
			"Invoice: Purchase Team fills and submits it",
			lambda: _page_save(
				"Purchase Invoice",
				inv_name,
				{
					"bill_no": f"UIE-SUPP-{tag}",
					"bill_date": today(),
					"custom_invoice_attachment": "/files/supplier-invoice.pdf",
					"custom_invoice_remarks": "Full receipt, no shortage.",
				},
			),
		)
		step(
			"Invoice: client.submit hands it to Accounts",
			lambda: frappe.client.submit(frappe.client.get("Purchase Invoice", inv_name)),
		)
		billed = flt(
			frappe.db.get_value("Purchase Invoice", inv_name, "rounded_total")
			or frappe.db.get_value("Purchase Invoice", inv_name, "grand_total")
		)
		check(
			"the invoice is Pending Payment with the full amount outstanding",
			frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")
			== C.UNF_PENDING_PAYMENT,
			str(frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")),
		)

		_as(accountant)
		half = round(billed / 2.0, 2)
		step(
			"Invoice: Accounts records a part payment",
			lambda: frappe.call(
				"alpinos.purchase.purchase_invoice.add_payment",
				purchase_invoice=inv_name,
				payment_type=C.UNF_PAYMENT_SUPPLIER,
				payment_amount=half,
				payment_date=today(),
				payment_mode="NEFT",
				reference_number="UTR-UIE-1",
			),
		)
		check(
			"the invoice is Partially Paid",
			frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")
			== C.UNF_PARTIALLY_PAID,
			str(frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")),
		)
		step(
			"Invoice: Accounts records the balance",
			lambda: frappe.call(
				"alpinos.purchase.purchase_invoice.add_payment",
				purchase_invoice=inv_name,
				payment_type=C.UNF_PAYMENT_SUPPLIER,
				payment_amount=billed - half,
				payment_date=today(),
				payment_mode="Cash",
			),
		)
		check(
			"BR-UNF-06 the invoice closes as Completed",
			frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")
			== C.UNF_COMPLETED,
			str(frappe.db.get_value("Purchase Invoice", inv_name, "custom_unified_status")),
		)

		# ============================== 9. nothing orphaned ===================
		frappe.set_user("Administrator")
		live_inward_rows = {
			r.name for r in frappe.get_all("Purchase Inward Item", filters={"parent": inw_name})
		}
		qc_refs = frappe.get_all(
			"Purchase QC Item",
			filters={"parent": qc_name},
			fields=["purchase_inward_item"],
			pluck="purchase_inward_item",
		)
		orphaned_qc = [r for r in qc_refs if r and r not in live_inward_rows]
		check(
			"no Purchase QC row points at an inward line that no longer exists",
			not orphaned_qc,
			str(orphaned_qc),
		)
		pr_refs = frappe.get_all(
			"Purchase Receipt Item",
			filters={"parent": grn_name},
			fields=["custom_purchase_inward_item"],
			pluck="custom_purchase_inward_item",
		)
		orphaned_pr = [r for r in pr_refs if r and r not in live_inward_rows]
		check(
			"no GRN line points at an inward line that no longer exists",
			not orphaned_pr,
			str(orphaned_pr),
		)

		frappe.db.commit()
		print(
			f"\nchain built: PO {po_name} -> PIW {inw_name} -> PQC {qc_name} "
			f"-> GRN {grn_name} -> PINV {inv_name}"
		)
	except Exception as e:
		# Without this the suite printed "41/41 passed" after stopping dead at step 41 --
		# the outer except swallowed the error and every completed step still read green.
		# A run that did not reach the end is a FAILED run and has to say so.
		_log(
			"FAIL",
			f"{_STEP[0] + 1:02d}. run aborted before the end of the chain",
			f"{type(e).__name__}: {frappe.utils.strip_html(str(e))[:260]}",
		)
		frappe.db.rollback()
	finally:
		frappe.set_user("Administrator")

	width = max(len(r[1]) for r in R) if R else 10
	print("\nPurchase chain, end to end through the data-entry surfaces")
	print("=" * (width + 26))
	for state, label, detail in R:
		print(f"[{state}] {label.ljust(width)}  {detail}")
	passed = sum(1 for r in R if r[0] == "PASS")
	print("-" * (width + 26))
	print(f"{passed}/{len(R)} passed")
	return R
