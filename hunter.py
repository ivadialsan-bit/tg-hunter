import asyncio
import json
import os
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

pending_client = None
pending_code_future = None

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
        print(f"Claude error: {e}")
        return 0, '', ''

async def do_auth(code=None):
    global pending_client, pending_code_future
    if pending_client is None:
        pending_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await pending_client.connect()
        await pending_client.send_code_request(PHONE)
        return "CODE_SENT"
    if code:
        await pending_client.sign_in(PHONE, code)
        session = pending_client.session.save()
        await pending_client.disconnect()
        pending_client = None
        print(f"\nSESSION_STRING={session}\n")
        return session
    return "WAITING_CODE"

async def run_hunter():
    if not SESSION_STRING:
        print("No TG_SESSION_STRING")
        return 0
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    since = datetime.now(timezone.utc) - timedelta(hours=2)
    results = []
    for username in CHANNELS:
        try:
            entity = await client.get_entity(username)
            messages = await client.get_messages(entity, limit=30)
            for msg in messages:
                if not isinstance(msg, Message): continue
                if not msg.text or len(msg.text) < 50: continue
                if msg.date < since: continue
                score, reason, category = score_with_claude(msg.text, USER_PROFILE)
                if score >= 30:
                    results.append({"tg_message_id": msg.id, "channel": username,
                        "text": msg.text, "score": score, "score_reason": reason,
                        "category": category, "posted_at": msg.date.isoformat()})
                    print(f"[{username}] score={score} cat={category}")
        except Exception as e:
            print(f"[{username}] error: {e}")
    await client.disconnect()
    if results and TIMEWEB_API:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.post(f"{TIMEWEB_API}/api/opportunities/ingest",
                    json={"items": results}, timeout=30)
                print(f"Ingest: {r.json()}")
        except Exception as e:
            print(f"Ingest error: {e}")
    return len(results)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        query = self.path.split('?')[1] if '?' in self.path else ''
        params = dict(p.split('=') for p in query.split('&') if '=' in p)

        if path == '/health':
            self._respond(200, 'OK')
        elif path == '/auth':
            result = asyncio.run(do_auth())
            self._respond(200, f'Code sent to {PHONE}. Now call /code?v=XXXXX')
        elif path == '/code':
            code = params.get('v', '')
            session = asyncio.run(do_auth(code=code))
            self._respond(200, f'SESSION_STRING={session}\nAdd this to Render env vars!')
        elif path == '/run':
            self._respond(200, 'Hunter started')
            threading.Thread(target=lambda: asyncio.run(run_hunter())).start()
        else:
            self._respond(404, 'Not found')

    def _respond(self, code, text):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode())

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"HTTP server on port {port}")
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()
