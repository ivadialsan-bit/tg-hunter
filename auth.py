import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
import os

API_ID = int(os.environ.get('TG_API_ID', '2040'))
API_HASH = os.environ.get('TG_API_HASH', 'b18441a1ff607e10a989891a5462e627')
PHONE = os.environ.get('TG_PHONE', '')

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(phone=PHONE)
    print("\n\nTG_SESSION_STRING=" + client.session.save() + "\n\n")
    await client.disconnect()

asyncio.run(main())
