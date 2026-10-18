import discord
import asyncio
from discord.ext import commands

from bot_utilities.response_utils import split_response
from bot_utilities.ai_utils import generate_response
from bot_utilities.config_loader import config, load_active_channels
from ..common import allow_dm, trigger_words, replied_messages, smart_mention, message_history, MAX_HISTORY, instructions


class OnMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = load_active_channels
        self.instructions = instructions

    async def process_message(self, message):
        active_channels = self.active_channels()
        string_channel_id = f"{message.channel.id}"
        
        # FIXED: Safely check message reference without crashing on uncached messages
        is_replied = False
        if message.reference and message.reference.resolved:
            if hasattr(message.reference.resolved, "author") and message.reference.resolved.author == self.bot.user:
                is_replied = smart_mention

        is_dm_channel = isinstance(message.channel, discord.DMChannel)
        is_active_channel = string_channel_id in active_channels
        is_allowed_dm = allow_dm and is_dm_channel
        contains_trigger_word = any(word in message.content for word in trigger_words)
        is_bot_mentioned = self.bot.user.mentioned_in(message) and smart_mention and not message.mention_everyone
        bot_name_in_message = self.bot.user.name.lower() in message.content.lower() and smart_mention

        if not (is_active_channel or is_allowed_dm or contains_trigger_word or is_bot_mentioned or is_replied or bot_name_in_message):
            return

        instruc_config = active_channels.get(string_channel_id, config.get('DEFAULT_INSTRUCTION', 'assist'))
        # Safe instruction lookup fallback
        selected_instruction = self.instructions.get(instruc_config, list(self.instructions.values())[0] if self.instructions else "")
        prompt_instructions = selected_instruction
        channel_id = message.channel.id
        key = f"{message.author.id}-{channel_id}"
        message_history[key] = message_history.get(key, [])
        message_history[key] = message_history[key][-MAX_HISTORY:]
        message_history[key].append({"role": "user", "content": message.content})

        async with message.channel.typing():
            response = await self.generate_response(prompt_instructions, message_history[key])

        message_history[key].append({"role": "model", "content": response})

        await self.send_response(message, response)

    async def generate_response(self, instructions, history):
        return await generate_response(instructions=instructions, history=history)

    async def send_response(self, message, response):
        # 🚀 TTS logic removed entirely for maximum speed and zero voice channel overhead
        if response is not None:
            for chunk in split_response(response):
                try:
                    await message.reply(chunk, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
                except Exception:
                    await message.channel.send("I apologize for any inconvenience caused. It seems that there was an error preventing the delivery of my message.")
        else:
            await message.reply("I apologize for any inconvenience caused. It seems that there was an error preventing the delivery of my message.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user and message.reference:
            if message.reference.message_id:
                replied_messages[message.reference.message_id] = message
                if len(replied_messages) > 5:
                    oldest_message_id = min(replied_messages.keys())
                    del replied_messages[oldest_message_id]

        if message.stickers or message.author.bot:
            return

        # Safe message reference check for filter guard
        if message.reference and message.reference.resolved:
            resolved = message.reference.resolved
            if hasattr(resolved, "author") and resolved.author != self.bot.user:
                return
            if hasattr(resolved, "embeds") and resolved.embeds:
                return

        await self.process_message(message)

async def setup(bot):
    await bot.add_cog(OnMessage(bot))
    
