#!/usr/bin/env python3
import os
import sys
import argparse
import requests
import json
import redis
import subprocess
import time
import re
import hashlib
try:
    import boto3
except ImportError:
    boto3 = None
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from utils.telegram import TelegramBot

custom_lib_path = os.path.expanduser("~/pylib")
if os.path.isdir(custom_lib_path) and custom_lib_path not in sys.path:
    sys.path.insert(0, custom_lib_path)

try:
    from dotenv import load_dotenv
    for path in ['.', '..', 'telegram-bot', '../telegram-bot', '/home/sai/AxionOS_Builders/telegram-bot', '/home/sai/AxionOS_Builders']:
        env_file = os.path.join(path, 'private.env')
        if os.path.exists(env_file):
            load_dotenv(dotenv_path=env_file)
            break
except ImportError:
    pass

def escape_markdown_v2(text):
    if not text: return ""
    text = text.replace('\\', '\\\\')
    for char in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(char, f"\\{char}")
    return text

def escape_code(text):
    if not text: return ""
    return text.replace('\\', '\\\\').replace('`', '\\`')

def compute_sha256(filepath):
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def upload_to_r2(filepath, folder):
    access_key = os.environ.get("R2_ACCESS_KEY")
    secret_key = os.environ.get("R2_SECRET_KEY")
    account_id = os.environ.get("R2_ACCOUNT_ID")
    bucket = os.environ.get("R2_BUCKET")
    cdn_domain = os.environ.get("R2_CDN_DOMAIN")

    if not all([access_key, secret_key, account_id, bucket, boto3]):
        return None

    try:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        s3 = boto3.client('s3', endpoint_url=endpoint, 
                         aws_access_key_id=access_key, 
                         aws_secret_access_key=secret_key, 
                         region_name='auto')
        
        filename = os.path.basename(filepath)
        key = f"{folder}/{filename}"
        sha256 = compute_sha256(filepath)
        
        extra_args = {'Metadata': {'sha256': sha256}}
        s3.upload_file(filepath, bucket, key, ExtraArgs=extra_args)
        return f"{cdn_domain}/{key}"
    except:
        return None

def upload_to_gofile(file_path):
    headers = {'User-Agent': 'Mozilla/5.0'}
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504], allowed_methods=frozenset(['POST']))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    try:
        with open(file_path, 'rb') as f:
            resp = session.post("https://upload.gofile.io/uploadFile", files={'file': f}, headers=headers, timeout=600)
            data = resp.json()
            return data['data']['downloadPage'] if data.get('status') == 'ok' else None
    except: return None

def upload_to_pixeldrain(file_path):
    api_key = os.environ.get("PD_API_KEY") or os.environ.get("PIXELDRAIN_API_KEY")
    headers = {'User-Agent': 'Mozilla/5.0'}
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504], allowed_methods=frozenset(['POST']))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    try:
        auth = ("", api_key) if api_key else None
        with open(file_path, 'rb') as f:
            resp = session.post("https://pixeldrain.com/api/file", files={'file': f}, auth=auth, headers=headers, timeout=600)
            data = resp.json()
            if data.get('success') or resp.status_code == 201:
                file_id = data.get('id')
                if file_id:
                    return f"https://pixeldrain.com/u/{file_id}"
            return None
    except Exception as e:
        print(f"Pixeldrain upload error: {e}")
        return None

def get_file_tail(file_path, lines=200):
    try:
        return subprocess.check_output(['tail', '-n', str(lines), file_path]).decode('utf-8', errors='ignore')
    except: return "Error reading log."

def get_error_summary(log_path):
    if not log_path or not os.path.exists(log_path): return None
    try:
        with open(log_path, 'r', errors='ignore') as f:
            lines = f.readlines()[-100:]
        keywords = ["error:", "fatal error:", "failed:", "undefined module"]
        error_lines = []
        for line in lines:
            if any(kw in line.lower() for kw in keywords) and line.strip() not in error_lines:
                error_lines.append(line.strip())
        last_3 = error_lines[-3:]
        if not last_3: return None
        summary = "⚠️ *ERROR SUMMARY*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for err in last_3: summary += f"• `{escape_code(err)}` \n"
        return summary + "━━━━━━━━━━━━━━━━━━━━━━━━"
    except: return None

def record_history(device, user, status, artifacts=None):
    history_file = os.path.expanduser("~/build_history.json")
    record = {"device": device, "user": user, "status": status, "timestamp": int(time.time()), "artifacts": artifacts or {}}
    try:
        history = json.load(open(history_file)) if os.path.exists(history_file) else []
        history.append(record)
        json.dump(history, open(history_file, 'w'), indent=4)
    except: pass

def create_telegram_link(chat_id, topic_id, message_id):
    cid = str(chat_id).replace("-100", "")
    # Use standard message link format. Topic ID is usually not needed in the URL path.
    return f"https://t.me/c/{cid}/{message_id}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', required=True, choices=['started', 'syncing', 'building', 'monitoring', 'success', 'failure', 'aborted'])
    parser.add_argument('--device', required=True)
    parser.add_argument('--build-type', required=True)
    parser.add_argument('--gms', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--chat-id', required=True)
    parser.add_argument('--topic-builder', required=True)
    parser.add_argument('--topic-error-logs', required=True)
    parser.add_argument('--topic-release-json', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--build-url', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--release-status', required=True)
    parser.add_argument('--source-dir', required=True)
    parser.add_argument('--full-clean', default="No")
    parser.add_argument('--upload-cdn', default="No")
    args = parser.parse_args()

    bot = TelegramBot(args.token)
    workspace = os.environ.get('GITHUB_WORKSPACE', '.')
    out_dir = os.path.join(args.source_dir, 'out', 'target', 'product', args.device)
    msg_id_file = os.path.join(workspace, ".build_msg_id")
    user_display = f"@{escape_markdown_v2(args.user)}"

    info_block = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"├ 📱 *Device*  : `{escape_code(args.device)}`\n"
        f"├ 👤 *Trigger* : {user_display}\n"
        f"├ 🧬 *Variant* : `{escape_code(args.gms)}` \\- `{escape_code(args.build_type)}`\n"
        f"└ 🧹 *Clean*   : `{escape_code(args.full_clean)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    redis_url = os.environ.get("REDIS_URL") or "redis://localhost:6379/4"
    try: redis_client = redis.from_url(redis_url, decode_responses=True)
    except: redis_client = None

    def update_redis(s, p=None, m_id=None):
        if not redis_client: return
        try:
            raw = redis_client.get(f"build_status:{args.device}")
            d = json.loads(raw) if raw else {}
        except: d = {}

        d.update({
            "status": s, "device": args.device, "type": args.build_type, 
            "gms": args.gms, "user": args.user, "url": args.build_url, 
            "run_id": args.run_id, "updated_at": int(time.time()),
            "chat_id": args.chat_id, "topic_id": args.topic_builder
        })
        if p: d["progress"] = p
        if m_id: d["message_id"] = m_id
        
        try:
            redis_client.set(f"build_status:{args.device}", json.dumps(d), ex=86400)
            redis_client.set("active_build_device", args.device, ex=86400)
        except: pass

    s_map = {'started': 'Initializing', 'syncing': 'Syncing Source', 'building': 'Starting Build', 'success': 'Completed', 'failure': 'Failed', 'aborted': 'Aborted'}
    
    # Don't overwrite existing progress if just updating status
    if args.status in s_map: 
        update_redis(s_map[args.status])

    if args.status == 'monitoring':
        if not os.path.exists(msg_id_file): return
        msg_id = open(msg_id_file).read().strip()
        last_text = ""
        while True:
            prog, prog_redis = "`Preparing...`", "Preparing"
            p_file = os.path.join(workspace, "progress.txt")
            if os.path.exists(p_file):
                try:
                    line = open(p_file).readlines()[-1].strip()
                    parts = line.split(',')
                    if len(parts) >= 3:
                        pct, counts, desc = int(parts[0]), parts[1], parts[2].lower()
                        if any(x in desc for x in ["signing", "ota zip", "json"]):
                            prog = f"⚙️ `{escape_code(desc.title())}...`"
                            prog_redis = desc.title()
                        elif re.search(r"bootstrap|analyzing|initializing", desc):
                            prog = f"🧬 `{escape_code(desc[:25])}... ({pct}%)`"
                            prog_redis = f"{desc[:25]} ({pct}%)"
                        else:
                            bar = "▰" * (pct // 10) + "▱" * (10 - (pct // 10))
                            prog = f"🚀 *LIVE MONITORING*\n├ `[{bar}]` {pct}%\n└ *Jobs* : `{escape_code(counts)}`"
                            prog_redis = f"{pct}% ({counts})"
                except: pass
            update_redis("Building", prog_redis)
            header = "🔐 *SIGNING*" if "signing" in (locals().get('desc', '')) else "📦 *PACKAGING*" if "ota zip" in (locals().get('desc', '')) else "🔨 *BUILDING*"
            new_text = f"{header}\n{info_block}\n\n{prog}\n\n📊 [VIEW RUN]({args.build_url})"
            if new_text != last_text:
                try:
                    bot.edit_message(args.chat_id, msg_id, new_text, parse_mode='MarkdownV2')
                    last_text = new_text
                except: pass
            time.sleep(10)
        return

    if args.status in ['success', 'failure', 'aborted']:
        if redis_client:
            try:
                redis_client.delete(f"build_status:{args.device}")
                if redis_client.get("active_build_device") == args.device: redis_client.delete("active_build_device")
            except: pass
        if os.path.exists(msg_id_file):
            try:
                mid = open(msg_id_file).read().strip()
                bot.delete_message(args.chat_id, mid)
                os.remove(msg_id_file)
            except: pass

    if args.status == 'started':
        msg = f"🚀 *BUILD INITIALIZED*\n{info_block}\n\n📊 [VIEW RUN]({args.build_url})"
        resp = bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')
        if resp and 'result' in resp: 
            m_id = str(resp['result']['message_id'])
            open(msg_id_file, 'w').write(m_id)
            update_redis("Initializing", m_id=m_id)
    elif args.status == 'aborted':
        record_history(args.device, args.user, "ABORTED")
        bot.send_message(args.chat_id, f"🛑 *BUILD ABORTED*\n{info_block}\n\n📊 [VIEW RUN]({args.build_url})", topic_id=args.topic_builder, parse_mode='MarkdownV2')
    elif args.status == 'failure':
        log_link, log_file = "Not Available", None
        paths = [os.path.join(args.source_dir, 'out', 'error.log'), os.path.join(workspace, 'sign.log'), os.path.join(workspace, 'build.log'), os.path.join(workspace, 'sync.log')]
        for p in paths:
            if os.path.exists(p):
                log_file = p
                break
        summary = get_error_summary(log_file) or ""
        if log_file:
            resp = bot.send_document(args.chat_id, log_file, caption=f"❌ Error Log - {args.device}", topic_id=args.topic_error_logs)
            if resp and 'result' in resp:
                log_link = f"[View Log]({create_telegram_link(args.chat_id, args.topic_error_logs, resp['result']['message_id'])})"
        record_history(args.device, args.user, "FAILURE")
        msg = f"❌ *BUILD FAILED*\n{info_block}\n\n{summary}\n\n📋 *Log* : {log_link}\n📊 [VIEW RUN]({args.build_url})"
        bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2')
    elif args.status == 'success':
        time.sleep(10)
        rom_file = None
        build_log = os.path.join(workspace, "build.log")
        if os.path.exists(build_log):
            for line in reversed(open(build_log).readlines()):
                if "Package Complete:" in line:
                    path = line.split("Package Complete:")[-1].strip()
                    if os.path.exists(path): rom_file = path
                    elif os.path.exists(os.path.join(args.source_dir, path)): rom_file = os.path.join(args.source_dir, path)
                    if rom_file: break
        if not rom_file:
            bot.send_message(args.chat_id, "⚠️ **Success but Artifact Not Found**", topic_id=args.topic_builder)
            return
        
        # Determine upload stream from Redis
        upload_stream = "gofile"
        if redis_client:
            try:
                upload_stream = redis_client.hget("axn:config", "main_upload_stream") or "gofile"
            except Exception as e:
                print(f"Failed to get upload stream from Redis: {e}")

        # Upload function with automatic fallback to Gofile
        def upload_file_with_fallback(file_path):
            if upload_stream == "pixeldrain":
                link = upload_to_pixeldrain(file_path)
                if link:
                    return link
                print(f"⚠️ Pixeldrain upload failed for {file_path}. Falling back to Gofile...")
                return upload_to_gofile(file_path)
            return upload_to_gofile(file_path)

        g_link = upload_file_with_fallback(rom_file) or "Upload Failed"
        cdn_link = upload_to_r2(rom_file, args.device) if args.upload_cdn == "Yes" else None
        
        extras = {}
        for img in ["boot.img", "recovery.img", "vendor_boot.img", "init_boot.img"]:
            p = os.path.join(out_dir, img)
            if os.path.exists(p):
                link = upload_file_with_fallback(p)
                if link: extras[img] = link

        json_url = ""
        # Map variants to their respective output directories
        variant_dir = "VANILLA" if args.gms.upper() == "VANILLA" else "GMS"
        
        gms_p = os.path.join(out_dir, variant_dir, f"{args.device}.json")
        if not os.path.exists(gms_p):
             gms_p = os.path.join(out_dir, f"{args.device}.json")
             
        if os.path.exists(gms_p): 
            json_url = upload_file_with_fallback(gms_p) or ""

        record_history(args.device, args.user, "SUCCESS", artifacts={"rom": g_link, "cdn_rom": cdn_link, **extras, "ota_json": json_url})
        
        btns = []
        # Main ROM Row
        rom_row = [{"text": "💿 DOWNLOAD ROM", "url": g_link}]
        if cdn_link: rom_row.append({"text": "🚀 CDN MIRROR", "url": cdn_link})
        btns.append(rom_row)

        # Image Artifacts
        extra_list = list(extras.items())
        for i in range(0, len(extra_list), 2):
            row = [{"text": f"📥 {extra_list[i][0].upper()}", "url": extra_list[i][1]}]
            if i+1 < len(extra_list): row.append({"text": f"📥 {extra_list[i+1][0].upper()}", "url": extra_list[i+1][1]})
            btns.append(row)
        
        last_row = []
        if json_url: last_row.append({"text": "📄 OTA JSON", "url": json_url})
        last_row.append({"text": "📊 VIEW RUN", "url": args.build_url})
        btns.append(last_row)

        msg = f"✨ *BUILD COMPLETED SUCCESSFULLY*\n{info_block}\n\n📦 *Artifacts are ready:*"
        bot.send_message(args.chat_id, msg, topic_id=args.topic_builder, parse_mode='MarkdownV2', reply_markup={"inline_keyboard": btns})

if __name__ == "__main__":
    main()
