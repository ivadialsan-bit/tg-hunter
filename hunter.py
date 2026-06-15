import asyncio
import json
import os
import sys
import httpx
import anthropic
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

API_ID = int(os.environ.get('TG_API_ID', '2040'))
API_HASH = os.environ.get('TG_API_HASH', '')
PHONE = os.environ.get('TG_PHONE', '')
SESSION_STRING = os.environ.get('TG_SESSION_STRING', '')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
CLAUDE_PROXY_URL = os.environ.get('CLAUDE_PROXY_URL', '')
TIMEWEB_API = os.environ.get('TIMEWEB_API', '')
CHANNELS = [c.strip() for c in os.environ.get('TG_CHANNELS', '').split(',') if c.strip()]
USER_PROFILE = os.environ.get('USER_PROFILE', '')

def log(msg):
    print(msg, flush=True)
    sys.stdout.flush()

def score_with_claude(text, profile):
    try:
        claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY, base_url=CLAUDE_PROXY_URL)
        prompt = f"""Ты — AI-ассистент, оценивающий вакансии и проекты для SMM-специалиста.
ПРОФИЛЬ: {profile}
ПОСТ: {text[:1000]}
Оцени 0-100. Категория: вакансия / проект / подряд / партнёрство / нерелевантно.
Ответь ТОЛЬКО JSON: {{"score": 75, "reason": "...", "category": "вакансия"}}"""
        r = claude.messages.create(model="claude-sonnet-4-6", max_tokens=200,
            messages=[{"role": "user", "content": prompt}])
        raw = r.content[0].text.strip().replace('```json','').replace('```','').strip()
        d = json.loads(raw)
        return d.get('score', 0), d.get('reason', ''), d.get('category', '')
    except Exception as e:
        log(f"Claude error: {e}")
        return 0, '', ''

async def run_hunter():
    log(f"=== HUNTER START === channels: {CHANNELS}")
    if not SESSION_STRING:
        log("ERROR: No TG_SESSION_STRING")
        return 0
    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.connect()
        log("Connected to Telegram OK")
    except Exception as e:
        log(f"Connection error: {e}")
        return 0

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    results = []

    for username in CHANNELS:
        log(f"Scanning [{username}]...")
        try:
            entity = await client.get_entity(username)
            messages = await client.get_messages(entity, limit=30)
            log(f"[{username}] got {len(messages)} messages")
            for msg in messages:
                if not isinstance(msg, Message): continue
                if not msg.text or len(msg.text) < 50: continue
                if msg.date < since: continue
                score, reason, category = score_with_claude(msg.text, USER_PROFILE)
                log(f"[{username}] msg_id={msg.id} score={score} cat={category}")
                if score >= 30:
                    results.append({
                        "tg_message_id": msg.id,
                        "channel": username,
                        "text": msg.text,
                        "score": score,
                        "score_reason": reason,
                        "category": category,
                        "posted_at": msg.date.isoformat()
                    })
        except Exception as e:
            log(f"[{username}] error: {e}")

    await client.disconnect()
    log(f"=== HUNTER DONE === found {len(results)} opportunities")

    if results and TIMEWEB_API:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.post(f"{TIMEWEB_API}/api/opportunities/ingest",
                    json={"items": results}, timeout=30)
                log(f"Ingest result: {r.json()}")
        except Exception as e:
            log(f"Ingest error: {e}")

    return len(results)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        query = self.path.split('?')[1] if '?' in self.path else ''
        params = dict(p.split('=') for p in query.split('&') if '=' in p)

        if path == '/health':
            self._respond(200, 'OK')
        elif path == '/run':
            self._respond(200, 'Hunter started')
            threading.Thread(target=lambda: asyncio.run(run_hunter()), daemon=True).start()
        elif path == '/auth':
            async def send_code():
                c = TelegramClient(StringSession(), API_ID, API_HASH)
                await c.connect()
                await c.send_code_request(PHONE)
                log("Code sent")
            asyncio.run(send_code())
            self._respond(200, f'Code sent to {PHONE}')
        elif path == '/code':
            code = params.get('v', '')
            async def do_signin():
                c = TelegramClient(StringSession(), API_ID, API_HASH)
                await c.connect()
                await c.sign_in(PHONE, code)
                s = c.session.save()
                log(f"SESSION_STRING={s}")
                await c.disconnect()
                return s
            s = asyncio.run(do_signin())
            self._respond(200, f'SESSION_STRING={s}')
        else:
            self._respond(404, 'Not found')

    def _respond(self, code, text):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    log(f"HTTP server on port {port}")
    log(f"SESSION_STRING present: {bool(SESSION_STRING)}")
    log(f"CHANNELS: {CHANNELS}")
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
