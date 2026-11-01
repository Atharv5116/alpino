"""Which whitelisted endpoints read data without following the company.

An endpoint "reads" when it - or a function of the same module it calls, at any depth -
calls frappe.get_all / get_list / db.sql / db.get_all / qb. It "follows the company" when
any of those functions uses a company_scope helper, or carries a marker comment saying why
the company does not apply:

    # company-scope: n/a (<reason>)

Run report() for the list; company_scope_test.run_lint fails while any is left.
"""

import ast
import os

import frappe

READS = {
	("frappe", "get_all"), ("frappe", "get_list"), ("frappe.db", "sql"), ("frappe.db", "get_all"),
	("frappe.db", "get_list"), ("frappe.db", "sql_list"), ("frappe", "qb"),
}
HELPERS = {
	"company_filters", "company_filter_list", "company_sql", "tagged_condition", "tagged_names",
	"scope_companies", "assert_company", "has_company_role", "users_with_roles", "current_company",
	"listing", "scope", "restrict_company", "tag_or_filters", "assert_open",
}
MARKER = "company-scope:"
SKIP_DIRS = {"company_scope", "patches", "__pycache__", "tests", "fixtures"}


def _dotted(node):
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
	return ".".join(reversed(parts))


def _is_whitelisted(fn):
	for d in fn.decorator_list:
		target = d.func if isinstance(d, ast.Call) else d
		if _dotted(target).endswith("whitelist"):
			return True
	return False


class _Scan(ast.NodeVisitor):
	def __init__(self):
		self.reads = False
		self.helper = False
		self.calls = set()

	def visit_Call(self, node):
		name = _dotted(node.func)
		head, _, tail = name.rpartition(".")
		if (head, tail) in READS or name.startswith("frappe.qb"):
			self.reads = True
		if tail in HELPERS or name in HELPERS:
			self.helper = True
		if isinstance(node.func, ast.Name):
			self.calls.add(node.func.id)
		self.generic_visit(node)

	def visit_Attribute(self, node):
		if _dotted(node).startswith("frappe.qb"):
			self.reads = True
		self.generic_visit(node)


def _module_functions(tree, source_lines):
	out = {}
	for node in ast.walk(tree):
		if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
			scan = _Scan()
			scan.visit(node)
			text = "\n".join(source_lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
			out.setdefault(node.name, []).append(
				{"node": node, "reads": scan.reads, "helper": scan.helper or MARKER in text, "calls": scan.calls,
				 "whitelisted": _is_whitelisted(node)}
			)
	return out


def _closure(funcs, name, seen=None):
	seen = seen if seen is not None else set()
	if name in seen or name not in funcs:
		return seen
	seen.add(name)
	for f in funcs[name]:
		for callee in f["calls"]:
			_closure(funcs, callee, seen)
	return seen


def report(app_path=None):
	app_path = app_path or frappe.get_app_path("alpinos")
	missing = []
	for root, dirs, files in os.walk(app_path):
		dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
		for file in files:
			if not file.endswith(".py") or file.endswith("_test.py") or file.startswith("test_"):
				continue
			path = os.path.join(root, file)
			source = open(path, encoding="utf-8").read()
			if "whitelist" not in source:
				continue
			try:
				tree = ast.parse(source)
			except SyntaxError:
				continue
			funcs = _module_functions(tree, source.splitlines())
			for name, defs in funcs.items():
				for f in defs:
					if not f["whitelisted"]:
						continue
					reach = _closure(funcs, name)
					reads = any(g["reads"] for n in reach for g in funcs[n])
					follows = any(g["helper"] for n in reach for g in funcs[n])
					if reads and not follows:
						missing.append(
							{"file": os.path.relpath(path, app_path), "line": f["node"].lineno, "function": name}
						)
	return sorted(missing, key=lambda m: (m["file"], m["line"]))


def summary():
	missing = report()
	by_file = {}
	for m in missing:
		by_file.setdefault(m["file"], []).append(m["function"])
	for file, fns in sorted(by_file.items(), key=lambda x: -len(x[1])):
		print(f"{len(fns):3d}  {file}: {', '.join(fns)}")
	print(f"{len(missing)} endpoints read data without following the company")
	return missing
