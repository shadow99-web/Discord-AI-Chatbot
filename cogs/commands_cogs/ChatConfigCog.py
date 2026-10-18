import discord
from discord.ext import commands
import json

from ..common import current_language, instructions, instruc_config, message_history
from bot_utilities.config_loader import load_active_channels

DEFAULT_PERSONA = instruc_config

class ChatConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = load_active_channels

    @commands.hybrid_command(name="toggleactive", description="Set the active AI persona for this channel.")
    @discord.app_commands.choices(persona=[
        discord.app_commands.Choice(name=p.capitalize(), value=p)
        for p in instructions
    ])
    @commands.has_permissions(administrator=True)
    async def toggleactive(self, ctx, persona: discord.app_commands.Choice[str] = DEFAULT_PERSONA):
        # Get the string value of the choice
        persona_value = getattr(persona, "value", persona) or instruc_config

        channel_id = f"{ctx.channel.id}"
        active_channels = self.active_channels()

        # ALWAYS set the channel (no more toggling off)
        active_channels[channel_id] = persona_value

        with open("channels.json", "w", encoding="utf-8") as f:
            json.dump(active_channels, f, indent=4)

        # Tell the user exactly what was saved
        await ctx.send(f"{ctx.channel.mention} is now active with persona: **{persona_value}**", delete_after=5)

    @commands.hybrid_command(name="disableactive", description="Disable the bot in this channel.")
    @commands.has_permissions(administrator=True)
    async def disableactive(self, ctx):
        channel_id = f"{ctx.channel.id}"
        active_channels = self.active_channels()
        
        if channel_id in active_channels:
            del active_channels[channel_id]
            with open("channels.json", "w", encoding="utf-8") as f:
                json.dump(active_channels, f, indent=4)
            await ctx.send(f"{ctx.channel.mention} has been deactivated.", delete_after=5)
        else:
            await ctx.send(f"{ctx.channel.mention} is already inactive.", delete_after=5)

    @commands.hybrid_command(name="clear", description=current_language["bonk"])
    async def clear(self, ctx):
        key = f"{ctx.author.id}-{ctx.channel.id}"
        try:
            message_history[key].clear()
        except Exception as e:
            await ctx.send(f"⚠️ There is no message history to be cleared \n ```{e}```", delete_after=2)
            return

        await ctx.send("Message history has been cleared", delete_after=4)

async def setup(bot):
    await bot.add_cog(ChatConfigCog(bot))
