import json
import os
import zipfile
from datetime import datetime
import hashlib
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, now_datetime


@frappe.whitelist()
def run_slack_to_raven_import(docname: str) -> dict:
	"""Run the Slack import for a Slack To Raven Import document. Exposed here for a reliable API path."""
	doc = frappe.get_doc("Slack To Raven Import", docname)
	doc.run_import()
	frappe.db.commit()
	doc.reload()
	return {"status": doc.status, "summary": doc.summary}


@frappe.whitelist()
def add_current_user_to_slack_workspace(workspace_name: str = "Slack") -> dict:
	"""
	Add the current user (e.g. Administrator) to the given Raven workspace and to all
	channels in that workspace. Use this after an import if you can't see channels/messages
	in Raven (no need to re-run the full import).
	If the workspace doc is missing but channels still reference it (e.g. deleted after import),
	the workspace is recreated so you can be added.
	"""
	workspace_name = (workspace_name or "Slack").strip()
	# Resolve workspace name to doc name (Raven Workspace uses workspace_name as doc name via autoname)
	workspace_docname = frappe.db.get_value(
		"Raven Workspace", {"workspace_name": workspace_name}, "name"
	) or frappe.db.get_value("Raven Workspace", {"name": workspace_name}, "name") or workspace_name

	if not frappe.db.exists("Raven Workspace", workspace_docname):
		# Channels may still reference this workspace (e.g. workspace doc was deleted after import)
		channel_count = frappe.db.count(
			"Raven Channel", filters={"workspace": workspace_docname, "is_thread": 0}
		)
		if channel_count > 0:
			# Recreate the workspace so Raven can show it and we can add the user
			frappe.get_doc(
				{
					"doctype": "Raven Workspace",
					"workspace_name": workspace_name,
					"type": "Private",
				}
			).insert(ignore_permissions=True)
			workspace_docname = workspace_name
		else:
			frappe.throw(
				_("Raven Workspace '{0}' not found. No channels use it either – run the import first.").format(
					workspace_name
				)
			)

	current_user = frappe.session.user or "Administrator"
	raven_user = frappe.db.get_value("Raven User", {"user": current_user}, "name")
	if not raven_user:
		frappe.throw(
			_("No Raven User found for {0}. Open Raven once or add the Raven User role.").format(current_user)
		)

	# Add as workspace member if not already
	if not frappe.db.exists(
		"Raven Workspace Member", {"workspace": workspace_docname, "user": raven_user}
	):
		frappe.get_doc(
			{
				"doctype": "Raven Workspace Member",
				"workspace": workspace_docname,
				"user": raven_user,
				"is_admin": 1,
			}
		).insert(ignore_permissions=True)

	# Add as member of every channel in this workspace
	channel_ids = frappe.get_all(
		"Raven Channel",
		filters={"workspace": workspace_docname, "is_thread": 0},
		pluck="name",
	)
	now_ts = now_datetime()
	added = 0
	for channel_id in channel_ids:
		if frappe.db.exists(
			"Raven Channel Member", {"channel_id": channel_id, "user_id": raven_user}
		):
			continue
		member_name = frappe.generate_hash(length=12)
		frappe.db.sql(
			"""
			INSERT INTO `tabRaven Channel Member`
			(`name`, `owner`, `creation`, `modified`, `modified_by`, `docstatus`, `idx`,
			 `channel_id`, `user_id`, `is_admin`, `last_visit`, `allow_notifications`)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, 0, %s, 1)
			""",
			(member_name, raven_user, now_ts, now_ts, raven_user, channel_id, raven_user, now_ts),
		)
		added += 1

	frappe.db.commit()
	return {
		"message": _("Added you to workspace and {0} channel(s). Refresh Raven to see them.").format(
			len(channel_ids)
		),
		"workspace": workspace_docname,
		"channels_total": len(channel_ids),
		"channels_joined": added,
	}


@frappe.whitelist()
def import_slack_export(file_url: str, workspace_name: Optional[str] = None) -> Dict:
	"""
	Import a standard Slack export ZIP into Raven.

	This lives in the Alpinos app so that the Raven app itself remains untouched.

	Args:
	    file_url: File URL or relative path to the Slack export ZIP.
	              Examples:
	                - /private/files/slack.zip
	                - /files/slack.zip
	                - slack.zip  (assumed to be in /private/files)
	    workspace_name: Optional Raven Workspace name.
	                    If not provided, a workspace with name "Slack" is used / created.

	Returns:
	    Dict with a short summary of what was imported.
	"""

	if not file_url:
		frappe.throw(_("file_url is required"))

	site_path, abs_path = _resolve_file_path(file_url)
	if not os.path.exists(abs_path):
		frappe.throw(_("Slack export file not found: {0}").format(abs_path))

	# Make import side-effect-light
	prev_in_import = getattr(frappe.flags, "in_import", False)
	prev_in_patch = getattr(frappe.flags, "in_patch", False)
	frappe.flags.in_import = True
	frappe.flags.in_patch = True

	try:
		with zipfile.ZipFile(abs_path, "r") as zf:
			users = _load_json_from_zip(zf, "users.json")
			channels = _load_json_from_zip(zf, "channels.json")

			# Build quick index of JSON message files per channel folder
			channel_files = _build_channel_files_index(zf)

			# 1) Users -> Frappe User + Raven User
			slack_user_to_raven_user = _ensure_users_and_raven_users(users)

			# 2) Workspace
			workspace = _ensure_workspace(workspace_name or "Slack")

			# 2b) Ensure the user running the import is a workspace member (so they see Slack in Raven)
			_ensure_import_user_in_workspace(workspace.name)

			# 3) Channels + members
			slack_channel_to_raven_channel = _ensure_channels_and_members(
				channels, slack_user_to_raven_user, workspace.name
			)

			# 4) Messages (text + system messages, threads, reactions)
			message_counts, message_index = _import_messages(
				zf,
				channels,
				channel_files,
				slack_channel_to_raven_channel,
				slack_user_to_raven_user,
				workspace.name,
			)

			# 5) Pins (after messages so we can resolve message IDs)
			pins_set = _apply_pins(
				channels,
				slack_channel_to_raven_channel,
				message_index,
				workspace.name,
				slack_user_to_raven_user,
			)

		return {
			"status": "success",
			"workspace": workspace.name,
			"users_mapped": len(slack_user_to_raven_user),
			"channels_imported": len(slack_channel_to_raven_channel),
			"messages_imported": message_counts.get("imported", 0),
			"messages_skipped": message_counts.get("skipped", 0),
			"reactions_imported": message_counts.get("reactions_imported", 0),
			"thread_replies_linked": message_counts.get("replies_linked", 0),
			"pinned_messages_set": pins_set,
			"site_path": site_path,
		}
	finally:
		# restore flags
		frappe.flags.in_import = prev_in_import
		frappe.flags.in_patch = prev_in_patch


def _resolve_file_path(file_url: str) -> Tuple[str, str]:
	"""Given a file_url or relative name, resolve to an absolute path within this site."""

	site_path = frappe.get_site_path()

	# Normalize
	if not file_url.startswith("/"):
		# assume private files
		file_url = "/private/files/" + file_url

	if file_url.startswith("/files/") or file_url.startswith("/private/files/"):
		rel = file_url.lstrip("/")
		abs_path = frappe.get_site_path(rel)
	else:
		# Fallback – treat as already relative to site
		abs_path = frappe.get_site_path(file_url.lstrip("/"))

	return site_path, abs_path


def _load_json_from_zip(zf: zipfile.ZipFile, member: str):
	"""Load a JSON file from the zip archive."""
	try:
		with zf.open(member) as f:
			content = f.read()
	except KeyError:
		frappe.throw(_("Required file {0} not found in Slack export").format(member))

	try:
		return json.loads(content)
	except Exception:
		frappe.throw(_("Unable to parse JSON from {0}").format(member))


def _build_channel_files_index(zf: zipfile.ZipFile) -> Dict[str, List[str]]:
	"""
	Create an index: channel_folder_name -> list of JSON message files.

	Slack export layout is typically:
	    users.json
	    channels.json
	    <channel-name>/<YYYY-MM-DD>.json
	    ...
	"""
	index: Dict[str, List[str]] = {}
	for name in zf.namelist():
		# Skip root jsons
		if name in ("users.json", "channels.json", "huddle_transcripts.json"):
			continue
		if not name.endswith(".json"):
			continue
		if "/" not in name:
			continue
		channel_folder, _ = name.split("/", 1)
		index.setdefault(channel_folder, []).append(name)
	return index


def _stable_hex_id(*parts: object) -> str:
	"""Create a deterministic hex id for idempotent inserts."""
	raw = "|".join("" if p is None else str(p) for p in parts)
	return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _slack_message_name(raven_channel: str, slack_ts: str) -> str:
	"""Deterministic Raven Message.name for a Slack message in a channel."""
	return _stable_hex_id("slack_msg", raven_channel, slack_ts)


def _slack_reaction_name(message_name: str, owner: str, reaction: str) -> str:
	"""Deterministic Raven Message Reaction.name for a Slack reaction."""
	return _stable_hex_id("slack_rx", message_name, owner, reaction)


def _ensure_users_and_raven_users(users: List[dict]) -> Dict[str, str]:
	"""
	Ensure Frappe User + Raven User for each Slack user.

	Previously we only handled users that had an email address in Slack, which
	meant messages from users without email were silently skipped. To import the
	full history we now:

	  - Use the real email when available.
	  - Otherwise create a disabled system user with a **synthetic** email
	    derived from the Slack user ID (e.g. slack-U123@slack.local).

	Returns:
	    Mapping: slack_user_id -> raven_user_name (which equals Frappe User.name)
	"""

	slack_to_raven: Dict[str, str] = {}

	# Ensure the "Raven User" role exists; if not, create a simple Role so that
	# adding it to User.roles does not fail with "Could not find Row #1: Role: Raven User".
	raven_role_name = "Raven User"
	if not frappe.db.exists("Role", raven_role_name):
		role_doc = frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": raven_role_name,
				"desk_access": 1,
			}
		)
		role_doc.insert(ignore_permissions=True)

	for u in users:
		slack_id = u.get("id")
		if not slack_id:
			continue

		profile = u.get("profile") or {}
		email = profile.get("email")

		real_name = profile.get("real_name") or profile.get("display_name") or email or slack_id
		first_name = profile.get("first_name") or (real_name.split(" ")[0] if real_name else slack_id)
		last_name = profile.get("last_name") or ""

		is_deleted = cint(u.get("deleted")) == 1

		# If Slack user has no email, create a deterministic synthetic email so that
		# we can still map all their messages to a Frappe User + Raven User.
		synthetic_email = False
		if not email:
			email = f"slack-{slack_id}@slack.local"
			synthetic_email = True

		# 1) Ensure Frappe User
		user_name = frappe.db.get_value("User", {"email": email}, "name")
		if not user_name:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": first_name,
					"last_name": last_name,
					"full_name": real_name,
					"username": u.get("name") or (email.split("@")[0] if email else slack_id),
					"user_type": "System User",
					# Synthetic / deleted users are disabled so they can't log in.
					"enabled": 0 if is_deleted or synthetic_email else 1,
				}
			)
			# Ensure at least one role before insert to avoid "No Roles Specified" validation
			user.append("roles", {"role": raven_role_name})
			# avoid welcome mails
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
			user_name = user.name
		else:
			user = frappe.get_doc("User", user_name)
			# keep existing user.enabled as-is unless Slack explicitly marks deleted
			if is_deleted:
				user.enabled = 0
			if not user.full_name:
				user.full_name = real_name
			user.flags.no_welcome_mail = True
			user.save(ignore_permissions=True)

		# 2) Ensure Raven User role
		existing_roles = {d.role for d in user.get("roles") or []}
		if "Raven User" not in existing_roles:
			user.append("roles", {"role": "Raven User"})
			user.flags.no_welcome_mail = True
			user.save(ignore_permissions=True)

		# 3) Ensure Raven User
		raven_user_name = frappe.db.get_value("Raven User", {"user": user_name}, "name")
		if not raven_user_name:
			raven_user = frappe.get_doc(
				{
					"doctype": "Raven User",
					"user": user_name,
					"full_name": user.full_name or first_name,
					"first_name": first_name,
					"enabled": 0 if is_deleted else 1,
				}
			)
			raven_user.insert(ignore_permissions=True)
			raven_user_name = raven_user.name
		else:
			raven_user = frappe.get_doc("Raven User", raven_user_name)
			raven_user.full_name = raven_user.full_name or user.full_name or first_name
			raven_user.enabled = 0 if is_deleted else 1
			raven_user.save(ignore_permissions=True)

		slack_to_raven[slack_id] = raven_user_name

	return slack_to_raven


def _ensure_workspace(workspace_name: str):
	"""Get or create a Raven Workspace by workspace_name."""

	workspace_name = workspace_name.strip()
	existing_name = frappe.db.get_value("Raven Workspace", {"workspace_name": workspace_name}, "name")
	if existing_name:
		return frappe.get_doc("Raven Workspace", existing_name)

	ws = frappe.get_doc(
		{
			"doctype": "Raven Workspace",
			"workspace_name": workspace_name,
			"type": "Private",
		}
	)
	# Avoid auto-creating owner member during import; we'll manage members explicitly if needed.
	prev_in_patch = getattr(frappe.flags, "in_patch", False)
	frappe.flags.in_patch = True
	try:
		ws.insert(ignore_permissions=True)
	finally:
		frappe.flags.in_patch = prev_in_patch
	return ws


def _ensure_import_user_in_workspace(workspace_name: str) -> None:
	"""
	Add the user running the import as a Raven Workspace Member so they can see
	the workspace and its channels in the Raven dashboard.
	"""
	current_user = frappe.session.user or "Administrator"
	raven_user = frappe.db.get_value("Raven User", {"user": current_user}, "name")
	if not raven_user:
		return
	if frappe.db.exists("Raven Workspace Member", {"workspace": workspace_name, "user": raven_user}):
		return
	frappe.get_doc(
		{
			"doctype": "Raven Workspace Member",
			"workspace": workspace_name,
			"user": raven_user,
			"is_admin": 1,
		}
	).insert(ignore_permissions=True)


def _ensure_channels_and_members(
	channels: List[dict], slack_user_to_raven_user: Dict[str, str], workspace_name: str
) -> Dict[str, str]:
	"""
	Ensure Raven Channel and Channel Members for each Slack channel.

	Returns:
	    Mapping: slack_channel_name -> raven_channel_name

	We intentionally:
	  - Only create channels that have at least one member we can map.
	  - Avoid creating direct-message channels here (Slack export only has public channels).
	"""

	slack_channel_to_raven: Dict[str, str] = {}

	for ch in channels:
		slack_name = ch.get("name")
		if not slack_name:
			continue

		# Build member list in terms of Raven User IDs
		slack_members = ch.get("members") or []
		raven_members = []
		for slack_uid in slack_members:
			raven_uid = slack_user_to_raven_user.get(slack_uid)
			if raven_uid:
				raven_members.append(raven_uid)

		# Ensure the user running the import is a channel member so they can see it in Raven
		import_user = frappe.session.user or "Administrator"
		import_raven_user = frappe.db.get_value("Raven User", {"user": import_user}, "name")
		if import_raven_user and import_raven_user not in raven_members:
			raven_members.append(import_raven_user)

		# If no members can be mapped, skip this channel
		if not raven_members:
			continue

		# Check if channel already exists in this workspace
		# Raven stores non-DM channels as: name = f"{workspace}-{channel_name}"
		existing_channel = frappe.db.get_value(
			"Raven Channel",
			{"channel_name": slack_name.strip().lower().replace(" ", "-"), "workspace": workspace_name},
			"name",
		)

		if existing_channel and frappe.db.exists("Raven Channel", existing_channel):
			channel_doc = frappe.get_doc("Raven Channel", existing_channel)
		else:
			channel_doc = frappe.get_doc(
				{
					"doctype": "Raven Channel",
					"channel_name": slack_name,
					"workspace": workspace_name,
					"type": "Public",
					"channel_description": (ch.get("purpose") or {}).get("value")
					or (ch.get("topic") or {}).get("value")
					or "",
					"is_archived": cint(ch.get("is_archived")) == 1,
				}
			)
			# Avoid auto-adding creator as member; we'll add explicit members below.
			channel_doc.flags.do_not_add_member = True
			channel_doc.flags.in_insert = True
			channel_doc.insert(ignore_permissions=True)

		# Map Slack channel name to Raven channel name
		slack_channel_to_raven[slack_name] = channel_doc.name

		# Create Raven Channel Members via SQL so Raven's after_insert does not run
		# (no "X joined" system messages, no channel lookups that can fail during import).
		now_ts = now_datetime()
		for raven_uid in raven_members:
			if frappe.db.exists("Raven Channel Member", {"channel_id": channel_doc.name, "user_id": raven_uid}):
				continue
			is_admin = 1 if raven_uid == slack_user_to_raven_user.get(ch.get("creator")) else 0
			member_name = frappe.generate_hash(length=12)
			frappe.db.sql(
				"""
				INSERT INTO `tabRaven Channel Member`
				(`name`, `owner`, `creation`, `modified`, `modified_by`, `docstatus`, `idx`,
				 `channel_id`, `user_id`, `is_admin`, `last_visit`, `allow_notifications`)
				VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 1)
				""",
				(member_name, raven_uid, now_ts, now_ts, raven_uid, channel_doc.name, raven_uid, is_admin, now_ts),
			)

	return slack_channel_to_raven


def _import_messages(
	zf: zipfile.ZipFile,
	channels: List[dict],
	channel_files: Dict[str, List[str]],
	slack_channel_to_raven_channel: Dict[str, str],
	slack_user_to_raven_user: Dict[str, str],
	workspace_name: str,
) -> Tuple[Dict[str, int], Dict[Tuple[str, str], str]]:
	"""
	Import messages for each Slack channel into Raven Message.

	Currently:
	  - Imports top-level and system messages as plain text.
	  - Links thread replies using Slack's thread_ts -> Raven linked_message.
	  - Imports per-user reactions as Raven Message Reaction docs.
	"""

	imported = 0
	skipped = 0
	reactions_imported = 0
	replies_linked = 0
	# (slack_channel_name, slack_ts) -> raven_message_name
	message_index: Dict[Tuple[str, str], str] = {}
	pending_replies: List[Tuple[str, str, str]] = []  # (message_name, slack_channel_name, thread_ts)

	# Build a quick lookup so we can map a folder name -> channel metadata from channels.json
	channel_lookup: Dict[str, dict] = {}
	for c in channels:
		if not isinstance(c, dict):
			continue
		if c.get("name"):
			channel_lookup[c["name"]] = c
		if c.get("id"):
			channel_lookup[c["id"]] = c

	# Iterate over actual folders found in the zip, and only process those that match a real channel
	# name from channels.json. This avoids accidentally skipping channels due to any mismatch between
	# channels.json and folder naming, and ignores non-channel folders (e.g. Canvas / FC:* entries).
	for folder_name, files in channel_files.items():
		ch = channel_lookup.get(folder_name)
		if not ch:
			continue

		slack_name = ch.get("name")
		if not slack_name:
			continue

		raven_channel = slack_channel_to_raven_channel.get(slack_name)
		if not raven_channel or not frappe.db.exists("Raven Channel", raven_channel):
			# Create/reuse the channel and members if needed
			channel_doc = _create_raven_channel_and_members(ch, workspace_name, slack_user_to_raven_user)
			if not channel_doc:
				continue
			raven_channel = channel_doc.name
			slack_channel_to_raven_channel[slack_name] = raven_channel

		message_files = sorted(files or [])
		for member_name in message_files:
			try:
				with zf.open(member_name) as f:
					raw = f.read()
				if not raw:
					continue
				day_messages = json.loads(raw)
			except Exception:
				# Malformed JSON for a given day – skip but keep going
				skipped += 1
				continue

			if not isinstance(day_messages, list):
				continue

			for m in day_messages:
				if not isinstance(m, dict):
					continue

				if m.get("type") != "message":
					continue

				slack_user_id = m.get("user")
				slack_ts = m.get("ts")
				thread_ts = m.get("thread_ts")

				# Basic sender mapping – if we don't know the user, skip for now
				raven_user = slack_user_to_raven_user.get(slack_user_id)
				if not raven_user:
					skipped += 1
					continue

				text = m.get("text") or ""
				subtype = m.get("subtype")

				# Map Slack subtype to Raven message_type where possible
				if subtype in ("channel_join", "channel_leave", "channel_topic", "channel_purpose"):
					message_type = "System"
				else:
					message_type = "Text"

				# Determine if this is a thread reply (not the root message)
				linked_message = None
				if thread_ts and thread_ts != slack_ts:
					root_key = (slack_name, thread_ts)
					linked_message = message_index.get(root_key)

				# Very simple HTML wrapping; Slack formatting is not fully converted.
				html_text = _slack_text_to_html(text)

				# Prepare core audit fields
				if slack_ts:
					try:
						seconds = float(slack_ts)
						creation_ts = datetime.fromtimestamp(seconds)
					except Exception:
						creation_ts = now_datetime()
				else:
					creation_ts = now_datetime()

				# Generate a unique name for the message. We avoid the Document.insert()
				# API so that Raven's hooks (after_insert, publish events, AI, etc.)
				# are not triggered during bulk import.
				message_name = _slack_message_name(raven_channel, slack_ts) if slack_ts else frappe.generate_hash(length=12)

				is_reply = 1 if linked_message else 0

				frappe.db.sql(
					"""
					INSERT IGNORE INTO `tabRaven Message`
					(`name`, `owner`, `creation`, `modified`, `modified_by`,
					 `docstatus`, `idx`, `channel_id`, `message_type`,
					 `text`, `json`, `is_reply`, `linked_message`)
					VALUES
					(%s, %s, %s, %s, %s,
					 0, 0, %s, %s,
					 %s, %s, %s, %s)
					""",
					(
						message_name,
						raven_user,
						creation_ts,
						creation_ts,
						raven_user,
						raven_channel,
						message_type,
						html_text,
						json.dumps(m),
						is_reply,
						linked_message,
					),
				)

				# If the row already existed (re-run), rowcount will be 0. Still keep deterministic mapping.
				if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount == 0:
					skipped += 1
				else:
					imported += 1

				# Record mapping for later (threads, pins, etc.)
				if slack_ts:
					message_index[(slack_name, slack_ts)] = message_name

				# Track how many replies we successfully linked
				if linked_message:
					replies_linked += 1
				elif thread_ts and thread_ts != slack_ts:
					# Root may appear later; link in a second pass once root exists.
					pending_replies.append((message_name, slack_name, thread_ts))

				# Import reactions, if present
				for reaction in m.get("reactions") or []:
					reaction_name = reaction.get("name")
					if not reaction_name:
						continue
					for reacting_slack_user in reaction.get("users") or []:
						reacting_raven_user = slack_user_to_raven_user.get(reacting_slack_user)
						if not reacting_raven_user:
							continue

						rx_name = _slack_reaction_name(message_name, reacting_raven_user, reaction_name)
						now_ts = now_datetime()
						frappe.db.sql(
							"""
							INSERT IGNORE INTO `tabRaven Message Reaction`
							(`name`, `owner`, `creation`, `modified`, `modified_by`, `docstatus`, `idx`,
							 `reaction`, `reaction_escaped`, `message`, `channel_id`, `is_custom`)
							VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 0)
							""",
							(
								rx_name,
								reacting_raven_user,
								now_ts,
								now_ts,
								reacting_raven_user,
								reaction_name,
								reaction_name,
								message_name,
								raven_channel,
							),
						)
						if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount:
							reactions_imported += 1

	# Second pass: link replies whose roots were processed later (or already existed).
	# Avoid writing invalid linked_message values (root must exist).
	for msg_name, slack_channel_name, root_ts in pending_replies:
		raven_channel = slack_channel_to_raven_channel.get(slack_channel_name)
		if not raven_channel or not root_ts:
			continue
		root_name = message_index.get((slack_channel_name, root_ts)) or _slack_message_name(raven_channel, root_ts)
		if not frappe.db.exists("Raven Message", root_name):
			continue
		frappe.db.sql(
			"""
			UPDATE `tabRaven Message`
			SET linked_message = %s, is_reply = 1
			WHERE name = %s AND (linked_message IS NULL OR linked_message = '')
			""",
			(root_name, msg_name),
		)
		if getattr(frappe.db, "_cursor", None) and frappe.db._cursor.rowcount:
			replies_linked += 1

	return (
		{
			"imported": imported,
			"skipped": skipped,
			"reactions_imported": reactions_imported,
			"replies_linked": replies_linked,
		},
		message_index,
	)


def _create_raven_channel_and_members(
	ch: dict,
	workspace_name: str,
	slack_user_to_raven_user: Dict[str, str],
):
	"""
	Create a Raven Channel and its members for one Slack channel.
	Returns the channel doc, or None if no members could be mapped (channel not created).
	"""
	slack_name = ch.get("name")
	if not slack_name:
		return None

	slack_members = ch.get("members") or []
	raven_members = []
	for slack_uid in slack_members:
		raven_uid = slack_user_to_raven_user.get(slack_uid)
		if raven_uid:
			raven_members.append(raven_uid)

	import_user = frappe.session.user or "Administrator"
	import_raven_user = frappe.db.get_value("Raven User", {"user": import_user}, "name")
	if import_raven_user and import_raven_user not in raven_members:
		raven_members.append(import_raven_user)

	if not raven_members:
		return None

	# Reuse existing channel in this workspace if it exists (e.g. same name, different doc name in map)
	normalized_name = slack_name.strip().lower().replace(" ", "-")
	existing_name = frappe.db.get_value(
		"Raven Channel",
		{"channel_name": normalized_name, "workspace": workspace_name},
		"name",
	)
	if existing_name and frappe.db.exists("Raven Channel", existing_name):
		return frappe.get_doc("Raven Channel", existing_name)

	channel_doc = frappe.get_doc(
		{
			"doctype": "Raven Channel",
			"channel_name": slack_name,
			"workspace": workspace_name,
			"type": "Public",
			"channel_description": (ch.get("purpose") or {}).get("value")
			or (ch.get("topic") or {}).get("value")
			or "",
			"is_archived": cint(ch.get("is_archived")) == 1,
		}
	)
	channel_doc.flags.do_not_add_member = True
	channel_doc.flags.in_insert = True
	channel_doc.insert(ignore_permissions=True)

	now_ts = now_datetime()
	for raven_uid in raven_members:
		if frappe.db.exists("Raven Channel Member", {"channel_id": channel_doc.name, "user_id": raven_uid}):
			continue
		is_admin = 1 if raven_uid == slack_user_to_raven_user.get(ch.get("creator")) else 0
		member_name = frappe.generate_hash(length=12)
		frappe.db.sql(
			"""
			INSERT INTO `tabRaven Channel Member`
			(`name`, `owner`, `creation`, `modified`, `modified_by`, `docstatus`, `idx`,
			 `channel_id`, `user_id`, `is_admin`, `last_visit`, `allow_notifications`)
			VALUES (%s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, 1)
			""",
			(member_name, raven_uid, now_ts, now_ts, raven_uid, channel_doc.name, raven_uid, is_admin, now_ts),
		)

	return channel_doc


def _apply_pins(
	channels: List[dict],
	slack_channel_to_raven_channel: Dict[str, str],
	message_index: Dict[Tuple[str, str], str],
	workspace_name: str,
	slack_user_to_raven_user: Dict[str, str],
) -> int:
	"""
	Apply pinned messages from channels.json into Raven Pinned Messages.

	Slack channel pins reference messages by their ts; we resolve them using
	the message_index built during message import.

	If a channel is in the mapping but not in the DB, it is created (with members)
	so pins can be applied.
	"""

	pinned_count = 0

	for ch in channels:
		slack_name = ch.get("name")
		if not slack_name:
			continue

		raven_channel = slack_channel_to_raven_channel.get(slack_name)
		if not raven_channel:
			continue

		# Create channel if it does not exist (e.g. was deleted or mapping was stale)
		if not frappe.db.exists("Raven Channel", raven_channel):
			channel_doc = _create_raven_channel_and_members(
				ch, workspace_name, slack_user_to_raven_user
			)
			if not channel_doc:
				continue
			raven_channel = channel_doc.name
			slack_channel_to_raven_channel[slack_name] = raven_channel

		pins = ch.get("pins") or []
		if not pins:
			continue

		# Get existing pinned message IDs from DB (avoid loading channel doc and triggering link validation)
		existing_rows = frappe.db.sql(
			"SELECT message_id FROM `tabRaven Pinned Messages` WHERE parent = %s",
			(raven_channel,),
			as_dict=True,
		)
		existing_pinned = {r["message_id"] for r in existing_rows}
		channel_pinned = 0
		now_ts = now_datetime()

		for pin in pins:
			ts = pin.get("id")
			if not ts:
				continue

			msg_name = message_index.get((slack_name, ts))
			if not msg_name:
				continue

			if msg_name in existing_pinned:
				continue

			# Only link messages that exist (avoids LinkValidationError on re-import or stale refs)
			if not frappe.db.exists("Raven Message", msg_name):
				continue

			row_name = frappe.generate_hash(length=12)
			frappe.db.sql(
				"""
				INSERT INTO `tabRaven Pinned Messages`
				(`name`, `owner`, `creation`, `modified`, `modified_by`, `docstatus`, `idx`,
				 `parent`, `parenttype`, `parentfield`, `message_id`)
				VALUES (%s, %s, %s, %s, %s, 0, 0, %s, 'Raven Channel', 'pinned_messages', %s)
				""",
				(row_name, frappe.session.user or "Administrator", now_ts, now_ts, frappe.session.user or "Administrator", raven_channel, msg_name),
			)
			existing_pinned.add(msg_name)
			channel_pinned += 1
			pinned_count += 1

		if channel_pinned:
			# Update parent's pinned_messages_string (Raven derives it from child table)
			all_msg_ids = frappe.db.sql(
				"SELECT message_id FROM `tabRaven Pinned Messages` WHERE parent = %s ORDER BY creation",
				(raven_channel,),
				as_list=True,
			)
			pinned_str = "\n".join(m[0] for m in all_msg_ids) if all_msg_ids else ""
			frappe.db.sql(
				"UPDATE `tabRaven Channel` SET pinned_messages_string = %s, modified = %s, modified_by = %s WHERE name = %s",
				(pinned_str, now_ts, frappe.session.user or "Administrator", raven_channel),
			)

	return pinned_count


def _slack_text_to_html(text: str) -> str:
	"""Basic conversion of Slack plain text into simple HTML suitable for Raven."""

	if not text:
		return ""

	# For now just preserve newlines and basic escaping.
	escaped = frappe.utils.escape_html(text)
	escaped = escaped.replace("\n", "<br>")
	return f"<p>{escaped}</p>"

