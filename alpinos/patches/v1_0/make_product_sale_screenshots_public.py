"""One-time backfill: existing Alpino Product Sale screenshots (payment
screenshots uploaded before the public-by-default hook) become public files.
New uploads are handled by the File after_insert hook in product_sale_files."""

from alpinos.product_sale_files import publish_existing_files


def execute():
	publish_existing_files()
