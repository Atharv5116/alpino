import frappe
from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote

class CustomDeliveryNote(DeliveryNote):
	def validate(self):
		_original_get_doc = frappe.get_doc
		_original_get_all = frappe.get_all

		def _custom_get_doc(*args, **kwargs):
			doctype = None
			name = None
			if args:
				if isinstance(args[0], str):
					doctype = args[0]
					if len(args) > 1:
						name = args[1]
				elif isinstance(args[0], dict):
					doctype = args[0].get("doctype")
					name = args[0].get("name")
			
			if not doctype and kwargs:
				doctype = kwargs.get("doctype")
				name = kwargs.get("name")

			if doctype == "Sales Order Item" and name:
				if not frappe.db.exists("Sales Order Item", name):
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						if frappe.db.exists(custom_doctype, name):
							custom_doc = _original_get_doc(custom_doctype, name)
							custom_doc.doctype = "Sales Order Item"
							
							item_details = frappe.db.get_value(
								"Item",
								custom_doc.item_code,
								["item_group", "item_name", "brand", "description", "stock_uom"],
								as_dict=True,
							) or {}
							for key, val in item_details.items():
								if not getattr(custom_doc, key, None):
									setattr(custom_doc, key, val)

							if not getattr(custom_doc, "uom", None):
								custom_doc.uom = custom_doc.stock_uom or "Nos"
							if not getattr(custom_doc, "conversion_factor", None):
								custom_doc.conversion_factor = 1.0
							if not getattr(custom_doc, "stock_uom", None):
								custom_doc.stock_uom = custom_doc.uom
							if not getattr(custom_doc, "rate", None):
								custom_doc.rate = 0.0
							if not getattr(custom_doc, "delivered_qty", None):
								custom_doc.delivered_qty = 0.0
							if not getattr(custom_doc, "delivered_by_supplier", None):
								custom_doc.delivered_by_supplier = 0
							return custom_doc
					return None
			return _original_get_doc(*args, **kwargs)

		def _custom_get_all(*args, **kwargs):
			doctype = args[0] if args else kwargs.get("doctype")
			filters = kwargs.get("filters")
			if doctype == "Sales Order Item" and filters and "name" in filters:
				name_filter = filters["name"]
				names_to_query = []
				if isinstance(name_filter, (list, tuple)):
					if len(name_filter) == 2 and name_filter[0] == "in" and isinstance(name_filter[1], (list, tuple)):
						names_to_query = list(name_filter[1])
					elif len(name_filter) == 2 and isinstance(name_filter[1], str):
						names_to_query = [name_filter[1]]
				elif isinstance(name_filter, str):
					names_to_query = [name_filter]

				results = _original_get_all(*args, **kwargs)
				found_names = {r.name if hasattr(r, "name") else r.get("name") for r in results}
				missing_names = [n for n in names_to_query if n not in found_names]

				if missing_names:
					fields = kwargs.get("fields") or ["name"]
					fields_list = fields if isinstance(fields, list) else [fields]
					custom_results = []
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						missing_in_custom = [n for n in missing_names if frappe.db.exists(custom_doctype, n)]
						if missing_in_custom:
							valid_fields = [f.fieldname for f in frappe.get_meta(custom_doctype).fields] + ["name", "parent"]
							query_fields = [f for f in fields_list if f in valid_fields]
							custom_records = _original_get_all(
								custom_doctype,
								filters={"name": ("in", missing_in_custom)},
								fields=query_fields
							)
							for r in custom_records:
								for f in fields_list:
									if f not in r:
										r[f] = 1.0 if f == "conversion_factor" else (0.0 if f in ["rate", "qty", "delivered_qty"] else None)
							custom_results.extend(custom_records)
					results.extend(custom_results)
				return results
			return _original_get_all(*args, **kwargs)

		frappe.get_doc = _custom_get_doc
		frappe.get_all = _custom_get_all

		try:
			super().validate()
		finally:
			frappe.get_doc = _original_get_doc
			frappe.get_all = _original_get_all

	def on_submit(self):
		_original_get_doc = frappe.get_doc
		_original_get_all = frappe.get_all

		def _custom_get_doc(*args, **kwargs):
			doctype = None
			name = None
			if args:
				if isinstance(args[0], str):
					doctype = args[0]
					if len(args) > 1:
						name = args[1]
				elif isinstance(args[0], dict):
					doctype = args[0].get("doctype")
					name = args[0].get("name")
			
			if not doctype and kwargs:
				doctype = kwargs.get("doctype")
				name = kwargs.get("name")

			if doctype == "Sales Order Item" and name:
				if not frappe.db.exists("Sales Order Item", name):
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						if frappe.db.exists(custom_doctype, name):
							custom_doc = _original_get_doc(custom_doctype, name)
							custom_doc.doctype = "Sales Order Item"
							
							item_details = frappe.db.get_value(
								"Item",
								custom_doc.item_code,
								["item_group", "item_name", "brand", "description", "stock_uom"],
								as_dict=True,
							) or {}
							for key, val in item_details.items():
								if not getattr(custom_doc, key, None):
									setattr(custom_doc, key, val)

							if not getattr(custom_doc, "uom", None):
								custom_doc.uom = custom_doc.stock_uom or "Nos"
							if not getattr(custom_doc, "conversion_factor", None):
								custom_doc.conversion_factor = 1.0
							if not getattr(custom_doc, "stock_uom", None):
								custom_doc.stock_uom = custom_doc.uom
							if not getattr(custom_doc, "rate", None):
								custom_doc.rate = 0.0
							if not getattr(custom_doc, "delivered_qty", None):
								custom_doc.delivered_qty = 0.0
							if not getattr(custom_doc, "delivered_by_supplier", None):
								custom_doc.delivered_by_supplier = 0
							return custom_doc
					return None
			return _original_get_doc(*args, **kwargs)

		def _custom_get_all(*args, **kwargs):
			doctype = args[0] if args else kwargs.get("doctype")
			filters = kwargs.get("filters")
			if doctype == "Sales Order Item" and filters and "name" in filters:
				name_filter = filters["name"]
				names_to_query = []
				if isinstance(name_filter, (list, tuple)):
					if len(name_filter) == 2 and name_filter[0] == "in" and isinstance(name_filter[1], (list, tuple)):
						names_to_query = list(name_filter[1])
					elif len(name_filter) == 2 and isinstance(name_filter[1], str):
						names_to_query = [name_filter[1]]
				elif isinstance(name_filter, str):
					names_to_query = [name_filter]

				results = _original_get_all(*args, **kwargs)
				found_names = {r.name if hasattr(r, "name") else r.get("name") for r in results}
				missing_names = [n for n in names_to_query if n not in found_names]

				if missing_names:
					fields = kwargs.get("fields") or ["name"]
					fields_list = fields if isinstance(fields, list) else [fields]
					custom_results = []
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						missing_in_custom = [n for n in missing_names if frappe.db.exists(custom_doctype, n)]
						if missing_in_custom:
							valid_fields = [f.fieldname for f in frappe.get_meta(custom_doctype).fields] + ["name", "parent"]
							query_fields = [f for f in fields_list if f in valid_fields]
							custom_records = _original_get_all(
								custom_doctype,
								filters={"name": ("in", missing_in_custom)},
								fields=query_fields
							)
							for r in custom_records:
								for f in fields_list:
									if f not in r:
										r[f] = 1.0 if f == "conversion_factor" else (0.0 if f in ["rate", "qty", "delivered_qty"] else None)
							custom_results.extend(custom_records)
					results.extend(custom_results)
				return results
			return _original_get_all(*args, **kwargs)

		frappe.get_doc = _custom_get_doc
		frappe.get_all = _custom_get_all

		try:
			super().on_submit()
		finally:
			frappe.get_doc = _original_get_doc
			frappe.get_all = _original_get_all

	def on_cancel(self):
		_original_get_doc = frappe.get_doc
		_original_get_all = frappe.get_all

		def _custom_get_doc(*args, **kwargs):
			doctype = None
			name = None
			if args:
				if isinstance(args[0], str):
					doctype = args[0]
					if len(args) > 1:
						name = args[1]
				elif isinstance(args[0], dict):
					doctype = args[0].get("doctype")
					name = args[0].get("name")
			
			if not doctype and kwargs:
				doctype = kwargs.get("doctype")
				name = kwargs.get("name")

			if doctype == "Sales Order Item" and name:
				if not frappe.db.exists("Sales Order Item", name):
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						if frappe.db.exists(custom_doctype, name):
							custom_doc = _original_get_doc(custom_doctype, name)
							custom_doc.doctype = "Sales Order Item"
							
							item_details = frappe.db.get_value(
								"Item",
								custom_doc.item_code,
								["item_group", "item_name", "brand", "description", "stock_uom"],
								as_dict=True,
							) or {}
							for key, val in item_details.items():
								if not getattr(custom_doc, key, None):
									setattr(custom_doc, key, val)

							if not getattr(custom_doc, "uom", None):
								custom_doc.uom = custom_doc.stock_uom or "Nos"
							if not getattr(custom_doc, "conversion_factor", None):
								custom_doc.conversion_factor = 1.0
							if not getattr(custom_doc, "stock_uom", None):
								custom_doc.stock_uom = custom_doc.uom
							if not getattr(custom_doc, "rate", None):
								custom_doc.rate = 0.0
							if not getattr(custom_doc, "delivered_qty", None):
								custom_doc.delivered_qty = 0.0
							if not getattr(custom_doc, "delivered_by_supplier", None):
								custom_doc.delivered_by_supplier = 0
							return custom_doc
					return None
			return _original_get_doc(*args, **kwargs)

		def _custom_get_all(*args, **kwargs):
			doctype = args[0] if args else kwargs.get("doctype")
			filters = kwargs.get("filters")
			if doctype == "Sales Order Item" and filters and "name" in filters:
				name_filter = filters["name"]
				names_to_query = []
				if isinstance(name_filter, (list, tuple)):
					if len(name_filter) == 2 and name_filter[0] == "in" and isinstance(name_filter[1], (list, tuple)):
						names_to_query = list(name_filter[1])
					elif len(name_filter) == 2 and isinstance(name_filter[1], str):
						names_to_query = [name_filter[1]]
				elif isinstance(name_filter, str):
					names_to_query = [name_filter]

				results = _original_get_all(*args, **kwargs)
				found_names = {r.name if hasattr(r, "name") else r.get("name") for r in results}
				missing_names = [n for n in names_to_query if n not in found_names]

				if missing_names:
					fields = kwargs.get("fields") or ["name"]
					fields_list = fields if isinstance(fields, list) else [fields]
					custom_results = []
					for custom_doctype in [
						"Sales Order Marketing Freebie",
						"Sales Order Scheme Item",
						"Sales Order Additional Units Item"
					]:
						missing_in_custom = [n for n in missing_names if frappe.db.exists(custom_doctype, n)]
						if missing_in_custom:
							valid_fields = [f.fieldname for f in frappe.get_meta(custom_doctype).fields] + ["name", "parent"]
							query_fields = [f for f in fields_list if f in valid_fields]
							custom_records = _original_get_all(
								custom_doctype,
								filters={"name": ("in", missing_in_custom)},
								fields=query_fields
							)
							for r in custom_records:
								for f in fields_list:
									if f not in r:
										r[f] = 1.0 if f == "conversion_factor" else (0.0 if f in ["rate", "qty", "delivered_qty"] else None)
							custom_results.extend(custom_records)
					results.extend(custom_results)
				return results
			return _original_get_all(*args, **kwargs)

		frappe.get_doc = _custom_get_doc
		frappe.get_all = _custom_get_all

		try:
			super().on_cancel()
		finally:
			frappe.get_doc = _original_get_doc
			frappe.get_all = _original_get_all
