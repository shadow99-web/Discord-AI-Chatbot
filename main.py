import asyncio
import os
import threading
from typing import Any

import aiohttp
from flask import Flask
import discord
from discord.ext import commands
from dotenv import load_dotenv

from cogs import COMMANDS, EVENT_HANDLERS
from bot_utilities.config_loader import config

load_dotenv('.env')

# 1. Initialize Flask web server for 24/7 keep-alive pings (great for Render/hosting)
app = Flask("")

@app.route("/")
def home():
    return "Aesthetic Bot is online and active 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# Grab Render's external URL if available
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")


# 2. Main Bot Class Setup combining AutoSharding, Cogs, and Self-Ping
class AIBot(commands.AutoShardedBot):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if config['AUTO_SHARDING']:
            super().__init__(*args, **kwargs)
        else:
            super().__init__(shard_count=1, *args, **kwargs)
        self.web_session = None

    async def setup_hook(self) -> None:
        # Initialize aiohttp session for self-pinging
        self.web_session = aiohttp.ClientSession()

        # Start the background self-ping loop if RENDER_EXTERNAL_URL is available
        if RENDER_EXTERNAL_URL:
            self.loop.create_task(self.keep_alive_ping())
            print(f"[+] Self-ping keep-alive task initialized for: {RENDER_EXTERNAL_URL}")
        else:
            print("[!] Warning: RENDER_EXTERNAL_URL is not set. Self-ping loop disabled.")

        # Load command cogs
        for cog in COMMANDS:
            cog_name = cog.split('.')[-1]
            discord.client._log.info(f"Loaded Command {cog_name}")
            await self.load_extension(f"{cog}")
            
        # Load event handler cogs
        for cog in EVENT_HANDLERS:
            cog_name = cog.split('.')[-1]
            discord.client._log.info(f"Loaded Event Handler {cog_name}")
            await self.load_extension(f"{cog}")
            
        print('If syncing commands is taking longer than usual you are being ratelimited')
       # await self.tree.sync()
        discord.client._log.info(f"Loaded {len(self.commands)} commands")

    async def keep_alive_ping(self):
        """Pings its own Render external URL every 3 minutes to prevent spin-down."""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                async with self.web_session.get(RENDER_EXTERNAL_URL) as resp:
                    print(f"[Keep-Alive] Self-ping status: {resp.status}")
            except Exception as e:
                print(f"[Keep-Alive] Ping failed: {e}")
            
            # Wait for 3 minutes (180 seconds) before the next ping
            await asyncio.sleep(900)

    async def close(self):
        if self.web_session:
            await self.web_session.close()
        await super().close()


# 3. Instantiate and run the bot
bot = AIBot(command_prefix=[], intents=discord.Intents.all(), help_command=None)

TOKEN = os.getenv('DISCORD_TOKEN')

if TOKEN is None:
    print("\033[31mLooks like you haven't properly set up a Discord token environment variable in the `.env` file.\033[0m")
    TOKEN = input("Please enter your Discord token: ")

if __name__ == "__main__":
    # Start the Flask web server in a background thread before running the bot
    keep_alive()
    
    # Run the Discord bot
    bot.run(TOKEN, reconnect=True)
