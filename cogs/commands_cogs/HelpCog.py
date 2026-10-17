import discord
from discord.ext import commands

from ..common import current_language


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description=current_language["help"])
    async def help_command(self, ctx):
        embed = discord.Embed(title="Bot Commands", color=0x03a64b)
        
        # FIXED: Using display_avatar.url to safely handle default avatars without crashing
        avatar_url = self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        command_tree = self.bot.commands
        for command in command_tree:
            if command.hidden:
                continue
            command_description = command.description or "No description available"
            embed.add_field(name=command.name,
                            value=command_description, inline=False)

        embed.set_footer(text=f"Made by 🔥shadow </> by ♥️")
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
