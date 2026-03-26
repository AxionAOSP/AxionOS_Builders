#!/usr/bin/env python3
import os
import sys

# === CUSTOM LIBRARY LOADER ===
custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path):
    if custom_lib_path not in sys.path:
        sys.path.insert(0, custom_lib_path)
        print(f"[INIT] Loading custom libraries from: {custom_lib_path}")

import argparse
import glob
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import subprocess
import time
import re
from utils.telegram import TelegramBot

def escape_markdown_v2(text):
    """Escapes all special characters for MarkdownV2 (outside code blocks)"""
    if not text:
        return ""
    # 1. Escape backslash FIRST to avoid escaping the escapes later
    text = text.replace('\\', '\\\\')
    # 2. Escape other special characters
    special_chars = r"_*[]()~`>#+-=|{}.!"
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text

def escape_code(text):
    """Escapes characters for MarkdownV2 inside code blocks"""
    if not text:
        return ""
    return text.replace('\\', '\\\\').replace('`', '\\`')

def upload_to_gofile(file_path):
    print(f"Uploading {file_path} to GoFile...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # Robust Session for Uploads
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=frozenset(['POST'])
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    
    url = "https://upload.gofile.io/uploadFile"

    # 2. Upload
    try:
        with open(file_path, 'rb') as f:
            upload_req = session.post(
                url,
                files={'file': f},
                headers=headers,
                timeout=600 # 10 minutes timeout for large files
            )
            
            try:
                upload_data = upload_req.json()
            except ValueError:
                 print(f"GoFile JSON Error: {upload_req.text}")
                 return None

            if upload_data['status'] == 'ok':
                return upload_data['data']['downloadPage']
            else:
                print(f"GoFile upload failed: {upload_data}")
                return None
    except Exception as e:
        print(f"GoFile Exception: {e}")
        return None

def get_file_tail(file_path, lines=200):
    try:
        result = subprocess.check_output(['tail', '-n', str(lines), file_path])
        return result.decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Error reading log: {e}"

def create_telegram_link(chat_id, topic_id, message_id):
    # Remove -100 prefix for supergroup links
    clean_chat_id = str(chat_id)
    if clean_chat_id.startswith("-100"):
        clean_chat_id = clean_chat_id[4:]
    
    if topic_id:
        return f"https://t.me/c/{clean_chat_id}/{topic_id}/{message_id}"
    return f"https://t.me/c/{clean_chat_id}/{message_id}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', required=True, choices=['started', 'syncing', 'building', 'monitoring', 'success', 'failure', 'aborted'])
    parser.add_argument('--device', required=True)
    parser.add_argument('--build-type', required=True)
    parser.add_argument('--gms', required=True)
    parser.add_argument('--fsgen', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--chat-id', required=True)
    parser.add_argument('--topic-builder', required=True, help="Topic for main notifications")
    parser.add_argument('--topic-error-logs', required=True, help="Topic for Error Logs")
    parser.add_argument('--topic-release-json', required=True, help="Topic for Release JSONs")
    parser.add_argument('--token', required=True)
    parser.add_argument('--build-url', required=True, help="Jenkins Build URL")
    parser.add_argument('--release-status', required=True, help="Release Build (Yes/No)")
    parser.add_argument('--source-dir', required=True, help="AOSP Source Directory")
    parser.add_argument('--install-clean', default="No", help="Install Clean (Yes/No)")
    parser.add_argument('--full-clean', default="No", help="Full Clean (Yes/No)")
    
    args = parser.parse_args()
    bot = TelegramBot(args.token)
    workspace = os.environ.get('WORKSPACE') or os.environ.get('GITHUB_WORKSPACE') or '.'
    out_dir = os.path.join(args.source_dir, 'out', 'target', 'product', args.device)
    msg_id_file = os.path.join(workspace, ".build_msg_id")

    # Always use Tag for User to notify maintainer
    user_display = f"@{escape_markdown_v2(args.user)}"

    # Minimalist Info Block (Tree Style - Expanded)
    # Dynamic Tree Body
    info_block = (
        f"├ *Device:* `{escape_code(args.device)}`\n"
        f"├ *Type:* `{escape_code(args.build_type)}`\n"
        f"├ *GMS:* `{escape_code(args.gms)}`\n"
        f"├ *FSGen:* `{escape_code(args.fsgen)}`\n"
        f"├ *Clean:* `{escape_code(args.install_clean)}`\n"
        f"├ *Full Clean:* `{escape_code(args.full_clean)}`\n"
        f"└ *User:* {user_display}"
    )

    # --- LOGIC HANDLER ---
    
    # 0. MONITORING (Looping Progress Bar)
    if args.status == 'monitoring':
        progress_file = os.path.join(workspace, "progress.txt")
        if not os.path.exists(msg_id_file):
            print("[MONITOR] No message ID found. Exiting.")
            return

        with open(msg_id_file, 'r') as f:
            msg_id = f.read().strip()
        
        if not msg_id: return

        print("[MONITOR] Starting progress loop...")
        last_text = ""
        
        while True:
            # Default text
            progress_display = "`Preparing Build System\\.\\.\\.`"
            
            if os.path.exists(progress_file):
                try:
                    with open(progress_file, 'r') as f:
                        lines = f.readlines()
                        if lines:
                            line = lines[-1].strip()
                            parts = line.split(',')
                            if len(parts) >= 3:
                                pct = int(parts[0])
                                counts = parts[1]
                                desc = parts[2].lower()
                                
                                # Check for Signing/Packaging (Text Only, No Pct)
                                if any(x in desc for x in ["signing target files", "generating ota zip", "generating json"]):
                                    clean_desc = desc.replace('.', '').strip().title()
                                    progress_display = f"⚙️ `{escape_code(clean_desc)}\\.\\.\\.`"
                                # Check for Bootstrap/Setup Phase
                                elif re.search(r"bootstrap|analyzing|initializing|including|finishing|writing packaging|writing legacy", desc):
                                    # Text Mode (No Bar)
                                    clean_desc = desc.strip()[:25]
                                    progress_display = f"🧬 `{escape_code(clean_desc)}\\.\\.\\. ({pct}%)`"
                                else:
                                    # Ninja Build Mode (With Bar)
                                    filled = int(pct / 10)
                                    empty = 10 - filled
                                    bar = "▰" * filled + "▱" * empty
                                    progress_display = f"🚀 *Monitoring*\n├ `[{bar}]` {pct}%\n└ *Jobs*: `{escape_code(counts)}`"
                except: pass
            
            # Dynamic Header based on description
            desc_lower = ""
            try:
                if 'desc' in locals():
                    desc_lower = desc.lower()
            except: pass

            if "signing target files" in desc_lower:
                header = "🔐 *Signing Build*"
            elif "generating ota zip" in desc_lower or "generating json" in desc_lower:
                header = "📦 *Packaging OTA*"
            else:
                header = "🔨 *Building ROM*"

            # Construct Message: Header -> Info -> Progress -> Link
            new_text = (
                f"{header}\n"
                f"{info_block}\n\n"
                f"{progress_display}\n\n"
                f"📊 [View Run]({args.build_url})"
            )
            
            # Update only if text changed
            if new_text != last_text:
                try:
                    bot.edit_message(args.chat_id, msg_id, new_text, parse_mode='MarkdownV2')
                    last_text = new_text
                except Exception as e:
                    print(f"[MONITOR] Edit failed: {e}")
            
            time.sleep(8)
        return

    # 1. PROGRESS UPDATE (Syncing / Building) -> EDIT MESSAGE
    if args.status in ['syncing', 'building']:
        if os.path.exists(msg_id_file):
            try:
                with open(msg_id_file, 'r') as f:
                    old_mid = f.read().strip()
                
                if old_mid:
                    # Escape dots for MarkdownV2: ... -> \\.\\.\\.
                    status_text = "🔄 *Syncing Source\\.\\.\\.*" if args.status == 'syncing' else "🔨 *Building ROM\\.\\.\\.*"
                    msg = (
                        f"{status_text}\n"
                        f"{info_block}\n\n"
                        f"📊 [View Run]({args.build_url})"
                    )
                    bot.edit_message(args.chat_id, old_mid, msg, parse_mode='MarkdownV2')
            except Exception as e:
                print(f"[ERROR] Editing message failed: {e}")
        return

    # 2. FINAL STATUS (Success / Failure / Aborted) -> DELETE OLD & SEND NEW
    if args.status in ['success', 'failure', 'aborted']:
        if os.path.exists(msg_id_file):
            try:
                with open(msg_id_file, 'r') as f:
                    old_mid = f.read().strip()
                if old_mid:
                    print(f"Deleting previous progress message: {old_mid}")
                    bot.delete_message(args.chat_id, old_mid)
                os.remove(msg_id_file)
            except Exception as e:
                print(f"Error deleting previous message: {e}")

    # --- STARTED ---
    if args.status == 'started':
        msg = (
            f"🟢 *Build Started*\n"
            f"{info_block}\n\n"
            f"📊 [View Run]({args.build_url})"
        )
        resp = bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')
        
        # Save Message ID
        if resp and 'result' in resp:
            try:
                with open(msg_id_file, 'w') as f:
                    f.write(str(resp['result']['message_id']))
            except Exception as e:
                print(f"Error saving message ID: {e}")
        return

    # --- ABORTED ---


    # --- ABORTED ---
    if args.status == 'aborted':
        msg = (
            f"⛔ *Build Aborted*\n"
            f"{info_block}\n\n"
            f"📊 [View Run]({args.build_url})"
        )
        bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')
        return

    # --- FAILURE ---
    if args.status == 'failure':
        print("Handling Build Failure...")
        log_link = "Not Available"
        
        # 1. Upload Log to Error Logs Topic
        # Prioritize out/error.log (Root of out)
        error_log_root = os.path.join(args.source_dir, 'out', 'error.log')
        sign_log = os.path.join(workspace, 'sign.log')
        build_log = os.path.join(workspace, 'build.log')
        sync_log = os.path.join(workspace, 'sync.log')
        
        log_file_to_upload = None
        log_caption = f"❌ Error Log \\- {escape_markdown_v2(args.device)}"
        
        # Priority 1: Signing Log (If failed during signing step)
        if os.path.exists(sign_log):
            print("Found sign.log. Tailing it...")
            temp_log = "sign_failure_tail.txt"
            with open(temp_log, 'w') as f:
                f.write(get_file_tail(sign_log, 200))
            log_file_to_upload = temp_log
            log_caption = f"❌ Signing Log \\- {escape_markdown_v2(args.device)}"

        # Priority 2: Standard Error Log
        elif os.path.exists(error_log_root):
            print(f"Found error.log at: {error_log_root}")
            log_file_to_upload = error_log_root
            
        # Priority 3: Build Log (Build Failure)
        elif os.path.exists(build_log):
            print("error.log not found, found build.log. Tailing it...")
            temp_log = "build_failure_tail.txt"
            with open(temp_log, 'w') as f:
                f.write(get_file_tail(build_log, 200))
            log_file_to_upload = temp_log
            log_caption = f"❌ Build Log \\- {escape_markdown_v2(args.device)}"
        
        # Priority 4: Sync Log (Sync Failure)
        elif os.path.exists(sync_log):
             print("error.log and build.log not found, found sync.log. Tailing it...")
             temp_log = "sync_failure_tail.txt"
             with open(temp_log, 'w') as f:
                 f.write(get_file_tail(sync_log, 200))
             log_file_to_upload = temp_log
             log_caption = f"❌ Sync Log \\- {escape_markdown_v2(args.device)}"
        
        if log_file_to_upload:
            resp = bot.send_document(args.chat_id, log_file_to_upload, caption=log_caption, topic_id=args.topic_error_logs, parse_mode='MarkdownV2')
            if resp and 'result' in resp:
                msg_id = resp['result']['message_id']
                log_link = f"[View Log File]({create_telegram_link(args.chat_id, args.topic_error_logs, msg_id)})"
            
            # Clean up temp
            if log_file_to_upload in ["build_failure_tail.txt", "sync_failure_tail.txt", "sign_failure_tail.txt"]:
                os.remove(log_file_to_upload)

        # 2. Send Notification to Builder Topic
        msg = (
            f"❌ *Build Failed*\n"
            f"{info_block}\n\n"
            f"📋 *Log:* {log_link}\n"
            f"📊 [View Run]({args.build_url})"
        )
        bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')
        return

    # --- SUCCESS ---
    print("Handling Build Success...")
    
    if not os.path.exists(out_dir):
        print(f"Error: Output directory not found: {out_dir}")
        bot.send_message(args.chat_id, f"⚠️ Build Success but Output Dir not found: `{out_dir}`", topic_id=args.topic_builder)
        return

    print(f"Searching for ZIPs in: {out_dir}")
    try:
        print(f"Files in dir: {os.listdir(out_dir)}")
    except Exception as e:
        print(f"Error listing dir: {e}")

    # Find ROM
    zip_pattern = os.path.join(out_dir, "AxionOS*.zip")
    files = glob.glob(zip_pattern)
    
    if not files:
        bot.send_message(args.chat_id, f"⚠️ Build Success but ZIP not found in `{out_dir}`", topic_id=args.topic_builder)
        return
    
    rom_file = max(files, key=os.path.getctime)
    rom_name = os.path.basename(rom_file)
    
    # Upload GoFile
    gofile_link = upload_to_gofile(rom_file) or "Upload Failed"
    
    # --- EXTRA ARTIFACTS ---
    extra_files = ["boot.img", "recovery.img", "vendor_boot.img", "dtbo.img"]
    uploaded_extras = {} # Name -> Link
    
    for img_name in extra_files:
        img_path = os.path.join(out_dir, img_name)
        if os.path.exists(img_path):
            print(f"Found extra artifact: {img_name}")
            u_link = upload_to_gofile(img_path)
            if u_link:
                uploaded_extras[img_name] = u_link

    # Handle Release JSON
    json_url = ""
    
    # Determine subdirectory based on GMS variant
    # Variants: Full, Core, Basic, Vanilla
    gms_dir = "VANILLA" if args.gms == "Vanilla" else "GMS"
    
    # Exact Path: out/target/product/<device>/<GMS or VANILLA>/<device>.json
    json_file = os.path.join(out_dir, gms_dir, f"{args.device}.json")

    if os.path.exists(json_file):
        print(f"Found JSON artifact: {json_file}")
        u_link = upload_to_gofile(json_file)
        if u_link:
            json_url = u_link
            # Just upload to GoFile and include in tree, no separate document send
    
    # Final Success Message
    artifacts_block = "📦 *Artifacts*\n"
    
    # Build list of artifact items to render tree correctly
    artifact_items = []
    
    # 1. ROM (Always first)
    artifact_items.append(f"[ROM]({gofile_link})")
    
    # 2. Extras
    for name, link in uploaded_extras.items():
        artifact_items.append(f"[{escape_markdown_v2(name)}]({link})")
        
    # 3. JSON (If exists)
    if json_url:
        artifact_items.append(f"[JSON OTA]({json_url})")
        
    # Render Tree
    for i, item in enumerate(artifact_items):
        is_last = (i == len(artifact_items) - 1)
        prefix = "└ " if is_last else "├ "
        artifacts_block += f"{prefix}{item}\n"

    msg = (
        f"✅ *Build Success*\n"
        f"{info_block}\n\n"
        f"{artifacts_block}"
    )
    bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')

if __name__ == "__main__":
    main()
