import asyncio
import json
import os
import httpx
import anthropic
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.types import Message
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

API_ID = int(os.environ.get('TG_API_ID', '2040'))
API_HASH = os.environ.get('TG_API_HASH', '')
PHONE = os.environ.get('TG_PHONE', '')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
CLAUDE_PROXY_URL = os.environ.get('CLAUDE_PROXY_URL', '')
TIMEWEB_API = os.environ.get('TIMEWEB_API', '')
CHANNELS = os.environ.get('TG_CHANNELS', '').split(',')
USER_PROFILE = os.environ.get('USER_PROFILE', '')

def score_with_claude(text, profile):
    try:
        claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY, base_url=CLAUDE_PROXY_URL)
        prompt = f"""Ты — AI-ассистент, оценивающий вакансии и проекты для SMM-специалиста.

ПРОФИЛЬ:
{profile}

ПОСТ:
{text}

Оцени 0-100. Категория: вакансия / проект / подряд / партнёрство / нерелевантно.
Ответь ТОЛЬКО JSON: {{"score": 75, "reason": "...", "category": "вакансия"}}"""

        r = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = r.content[0].text.strip().replace('```json','').replace('```','').strip()
        d = json.loads(raw)
        return d.get('score', 0), d.get('reason', ''), d.get('category', '')
    except Exception as e:
        print(f"Claude error: {e}")
        return 0, '', ''

async def run():
    client = TelegramClient('hunter', API_ID, API_HASH)
    await client.start(phone=PHONE)

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    results = []

    for username in CHANNELS:
        username = username.strip()
        if not username:
            continue
        try:
            entity = await client.get_entity(username)
            messages = await client.get_messages(entity, limit=50)
            for msg in messages:
                if not isinstance(msg, Message):
                    continue
                if not msg.text or len(msg.text) < 50:
                    continue
                if msg.date < since:
                    continue
                score, reason, category = score_with_claude(msg.text, USER_PROFILE)
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
                    print(f"[{username}] id={msg.id} score={score} cat={category}")
        except Exception as e:
            print(f"[{username}] error: {e}")

    await client.disconnect()

    if results and TIMEWEB_API:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.post(
                    f"{TIMEWEB_API}/api/opportunities/ingest",
                    json={"items": results},
                    timeout=30
                )
                print(f"Ingest: {r.json()}")
        except Exception as e:
            print(f"Ingest error: {e}")

if __name__ == '__main__':
    asyncio.run(run())
