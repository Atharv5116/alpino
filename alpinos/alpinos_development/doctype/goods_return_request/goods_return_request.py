"""Goods Return Request (GRR): the central record of a customer return (FSD Document 1).

Rules live in alpinos.goods_return.request; who may do what in alpinos.goods_return.access.
"""

from frappe.model.document import Document


class GoodsReturnRequest(Document):
	def before_insert(self):
		from alpinos.goods_return.request import before_insert

		before_insert(self)

	def validate(self):
		from alpinos.goods_return.request import validate

		validate(self)

	def before_submit(self):
		from alpinos.goods_return.request import before_submit

		before_submit(self)

	def on_submit(self):
		from alpinos.goods_return.request import on_submit

		on_submit(self)

	def before_cancel(self):
		from alpinos.goods_return.request import before_cancel

		before_cancel(self)

	def on_cancel(self):
		from alpinos.goods_return.request import on_cancel

		on_cancel(self)

	def before_update_after_submit(self):
		from alpinos.goods_return.request import before_update_after_submit

		before_update_after_submit(self)
