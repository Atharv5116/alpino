import subprocess
import os
import frappe

def check_pl():
	pl_name = "STO-PICK-2026-00018"
	found = False
	for dt in ["Pick List", "Pick List Entry"]:
		try:
			if frappe.db.exists(dt, pl_name):
				print(f"EXISTS:{dt}")
				found = True
				break
		except Exception as e:
			pass
	if not found:
		print("ABSENT")

def run():
	sites_dir = "/home/frappe/frappe-bench/sites"
	candidate_sites = []
	for name in os.listdir(sites_dir):
		path = os.path.join(sites_dir, name)
		if os.path.isdir(path) and name not in ["assets", "languages"]:
			if os.path.exists(os.path.join(path, "site_config.json")):
				candidate_sites.append(name)
	
	print(f"Checking {len(candidate_sites)} sites via bench execute check_pl...")
	for site in candidate_sites:
		cmd = ["bench", "--site", site, "execute", "alpinos.alpinos_development.scratch_test.check_pl"]
		res = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/frappe/frappe-bench")
		stdout = res.stdout.strip()
		stderr = res.stderr.strip()
		print(f"Site: {site} | RC: {res.returncode} | STDOUT: {stdout}")
		if stderr:
			print(f"  STDERR: {stderr}")
