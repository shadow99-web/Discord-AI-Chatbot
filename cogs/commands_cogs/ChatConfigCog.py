import discord
from discord.ext import commands
import json

from ..common import current_language, instructions, instruc_config, message_history
from bot_utilities.config_loader import load_active_channels


# Define a proper Choice object for the default persona
DEFAULT_PERSONA_CHOICE = discord.app_commands.Choice(
    name=instruc_config.capitalize(),
    value=instruc_config,
)


class ChatConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = load_active_channels

    @commands.hybrid_command(name="toggleactive", description=current_language["toggleactive"])
    @discord.app_commands.choices(persona=[
        discord.app_commands.Choice(name=persona.capitalize(), value=persona)
        for persona in instructions
    ])
    @commands.has_permissions(administrator=True)
    async def toggleactive(self, ctx, persona: discord.app_commands.Choice[str] = DEFAULT_PERSONA_CHOICE):
        # Safely extract the value whether we get a Choice or a plain string
        persona_value = getattr(persona, "value", persona)
        if not persona_value:
            persona_value = instruc_config  # Final fallback

        channel_id = f"{ctx.channel.id}"
        active_channels = self.active_channels()

        if channel_id in active_channels:
            # If channel is already active, deactivate it
            del active_channels[channel_id]
            msg = current_language["toggleactive_msg_1"]
        else:
            # If channel is not active, activate it with the chosen persona
            active_channels[channel_id] = persona_value
            msg = current_language["toggleactive_msg_2"]

        with open("channels.json", "w", encoding='utf-8') as f:
            json.dump(active_channels, f, indent=4)

        await ctx.send(f"{ctx.channel.mention} {msg}", delete_after=3)

    @commands.hybrid_command(name="disableactive", description="Disable the bot in this channel.")
    @commands.has_permissions(administrator=True)
    async def disableactive(self, ctx):
        """A separate command to clearly deactivate a channel without toggling."""
        channel_id = f"{ctx.channel.id}"
        active_channels = self.active_channels()
        if channel_id in active_channels:
            del active_channels[channel_id]
            with open("channels.json", "w", encoding='utf-8') as f:
                json.dump(active_channels, f, indent=4)
            await ctx.send(f"{ctx.channel.mention} has been deactivated.", delete_after=3)
        else:
            await ctx.send(f"{ctx.channel.mention} is not an active channel.", delete_after=3)

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
