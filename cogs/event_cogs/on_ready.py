import asyncio
from itertools import cycle
import discord
from discord.ext import commands

from bot_utilities.config_loader import config
from ..common import presences_disabled, current_language, presences

class OnReady(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_task_started = False

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} aka {self.bot.user.name} has connected to Discord!")
        invite_link = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(),
            scopes=("bot", "applications.commands")
        )
        print(f"Invite link: {invite_link}")

        if presences_disabled:
            return

        # FIXED: Prevent spawning duplicate background loops if on_ready fires again on gateway reconnect
        if not self.presence_task_started:
            self.presence_task_started = True
            self.bot.loop.create_task(self.change_presence_loop())

    async def change_presence_loop(self):
        presences_cycle = cycle(presences + [current_language.get('help_footer', 'Discord Bot')])
        while True:
            try:
                presence = next(presences_cycle)
                presence_with_count = presence.replace("{guild_count}", str(len(self.bot.guilds)))
                delay = config.get('PRESENCES_CHANGE_DELAY', 8)
                await self.bot.change_presence(activity=discord.Game(name=presence_with_count))
                await asyncio.sleep(delay)
            except Exception as e:
                print(f"Presence loop error: {e}")
                await asyncio.sleep(10)

async def setup(bot):
    await bot.add_cog(OnReady(bot))
    
