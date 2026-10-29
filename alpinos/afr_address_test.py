"""Accounts Format Report: City / State / PIN code read from the printed address (29 Oct 2026).

	bench --site <test site> execute alpinos.afr_address_test.run

Real addresses from the orders where the report used to show another place than the one it
printed beside it.
"""

from alpinos.alpinos_development.report.accounts_format_report.accounts_format_report import (
	_GST_STATE,
	_scp_from_free_text,
)

CASES = [
	# text, expected (city, state, pincode)
	("SCOOTSY LOGISTICS PRIVATE LIMITED, Global loginfra park, Bangihati more, NH-2, Old delhi road, "
	 "PO- Mallickpara, PS- Srirampur KOLKATA, westebengal, 712203",
	 ("PS- Srirampur KOLKATA", "West Bengal", "712203")),
	("No 5,,6th Sector, HSR Layout, Bengaluru - 560102 Karnataka (29)", ("Bengaluru", "Karnataka", "560102")),
	("Plot 3, Walajabad block, Kanchipuram, Tamil Nadu - 631604", ("Kanchipuram", "Tamil Nadu", "631604")),
	("Some Building, Bhiwandi, Dist Thane, Bhiwandi, Maharashtra, 421302, India", ("Bhiwandi", "Maharashtra", "421302")),
	("Amazon Retail India Private Limited L R, Khatian No. 871, Shimla, Sreerampore, Hooghly, 712203, India",
	 ("Hooghly", "West Bengal", "712203")),
	("Shop 4, Delhi Gate Road, Surat 395003", ("Surat", "Gujarat", "395003")),
	("KHNOOR ROAD KHASRA NO 425, 426 & 428 JAMMU-180003,India", ("JAMMU", "Jammu and Kashmir", "180003")),
	("Survey 70/1A, Chinnambedu village, Ponneri Taluk, Tiruvallur District CHENNAI, Tamilnadu, 601206",
	 ("CHENNAI", "Tamil Nadu", "601206")),
	("Khasra 12, Khairpur Sheikhan, Teh- Rajpura Dist- Patiala, Punjab 140417", ("Patiala", "Punjab", "140417")),
	("Unit 2, Hingna, NAGPUR, Mahrashtra, 441122", ("NAGPUR", "Maharashtra", "441122")),
	("Silvassa, Dadra and Nagar Haveli, and Diu, Daman Diu, - 396230",
	 ("Silvassa", "Dadra and Nagar Haveli and Daman and Diu", "396230")),
	("Pudur Village, Medchal Mandel, Hyderabad, Telangana 501401", ("Hyderabad", "Telangana", "501401")),
	("SCOOTSY LOGISTICS PRIVATE LIMITED", ("", "", "")),
]


def run():
	results = []
	for text, want in CASES:
		got = _scp_from_free_text(text)
		got = (got["city"], got["state"], got["pincode"])
		results.append(("PASS" if got == want else "FAIL", text[-55:], "" if got == want else f"got {got}, want {want}"))
	gst_ok = _GST_STATE.get("29") == "Karnataka" and _GST_STATE.get("33") == "Tamil Nadu"
	results.append(("PASS" if gst_ok else "FAIL", "a billing address with no place takes its GSTIN's state", ""))
	width = max(len(r[1]) for r in results)
	for status, label, detail in results:
		print(f"[{status}] {label.ljust(width)}  {detail}")
	print(f"{sum(1 for r in results if r[0] == 'PASS')}/{len(results)} passed")
	return results
