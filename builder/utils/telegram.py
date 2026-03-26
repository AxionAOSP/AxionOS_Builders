import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.api_url = f"https://api.telegram.org/bot{token}"
        
        # Setup Robust Session with Retry Logic
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=2,  # Wait 2s, 4s, 8s, 16s, 32s
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(['GET', 'POST'])
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.timeout = 120  # Seconds

    def send_message(self, chat_id, text, topic_id=None, parse_mode="Markdown"):
        url = f"{self.api_url}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if topic_id:
            data["message_thread_id"] = topic_id
            
        try:
            response = self.session.post(url, data=data, timeout=self.timeout)
            if not response.ok:
                print(f"[Telegram Error] Response: {response.text}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"[Telegram Error] Failed to send message: {e}")
            return None

    def send_document(self, chat_id, file_path, caption=None, topic_id=None, parse_mode="Markdown"):
        url = f"{self.api_url}/sendDocument"
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": parse_mode
        }
        if topic_id:
            data["message_thread_id"] = topic_id

        try:
            with open(file_path, 'rb') as f:
                files = {'document': f}
                response = self.session.post(url, data=data, files=files, timeout=self.timeout)
                if not response.ok:
                    print(f"[Telegram Error] Response: {response.text}")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"[Telegram Error] Failed to send document: {e}")
            return None

    def delete_message(self, chat_id, message_id):
        url = f"{self.api_url}/deleteMessage"
        data = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        try:
            self.session.post(url, data=data, timeout=self.timeout)
        except Exception as e:
            print(f"[Telegram Error] Failed to delete message: {e}")

    def edit_message(self, chat_id, message_id, text, parse_mode="Markdown"):
        url = f"{self.api_url}/editMessageText"
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        try:
            response = self.session.post(url, data=data, timeout=self.timeout)
            if not response.ok:
                print(f"[Telegram Error] Edit Response: {response.text}")
            return response.json()
        except Exception as e:
            print(f"[Telegram Error] Failed to edit message: {e}")
            return None
