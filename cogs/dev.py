# dev.py
# pyright: reportInvalidTypeForm=false
"""Internal dev commands"""

import asyncio
from datetime import datetime
import importlib
import os
import re
import sqlite3
import sys
from typing import List

import discord
from discord.ext import bridge, commands
from discord.ext.bridge import BridgeOption
from humanfriendly import format_timespan

from database import cooldowns
from resources import emojis, exceptions, logs, settings, views


EVENT_REDUCTION_TYPES = [
    'Text commands',
    'Slash commands',
]

MSG_NOT_DEV = 'You are not allowed to use this command.'

class DevCog(commands.Cog):
    """Cog class containing internal dev commands"""
    def __init__(self, bot: bridge.AutoShardedBot):
        self.bot = bot

    default_member_permissions=discord.Permissions(administrator=True)

    # Bridge commands
    @bridge.bridge_group(name='dev', description='Development commands', invoke_without_command=True)
    @commands.bot_has_permissions(send_messages=True)
    async def dev_group(self, ctx: bridge.BridgeContext):
        """Dev command group"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        await ctx.respond(
            f'**Dev commands**\n'
            f'{emojis.BP} `{ctx.prefix}dev cache`\n'
            f'{emojis.BP} `{ctx.prefix}dev consolidate`\n'
            f'{emojis.BP} `{ctx.prefix}dev emoji-check`\n'
            f'{emojis.BP} `{ctx.prefix}dev event-reductions`, `er`\n'
            f'{emojis.BP} `{ctx.prefix}dev leave-server <server id>`\n'
            f'{emojis.BP} `{ctx.prefix}dev post-message`, `pm` `<message id> <channel id> <embed title>`\n'
            f'{emojis.BP} `{ctx.prefix}dev reload <modules>`\n'
            f'{emojis.BP} `{ctx.prefix}dev server-list`\n'
            f'{emojis.BP} `{ctx.prefix}dev support`\n'
            f'{emojis.BP} `{ctx.prefix}dev shutdown`\n'
        )

    @dev_group.command(name='reload', description='Reloads cogs or modules', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True)
    async def dev_reload(
        self,
        ctx: bridge.BridgeContext,
        *,
        modules: BridgeOption(str, description='Cogs or modules to reload'),
    ) -> None:
        """Reloads cogs or modules"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        modules = modules.split(' ')
        actions = []
        for module in modules:
            name_found = False
            cog_name = f'cogs.{module}' if not 'cogs.' in module else module
            try:
                cog_status = self.bot.reload_extension(cog_name)
            except:
                cog_status = 'Error'
            if cog_status is None:
                actions.append(f'+ Extension \'{cog_name}\' reloaded.')
                name_found = True
            if not name_found:
                for module_name in sys.modules.copy():
                    if module == module_name:
                        module = sys.modules.get(module_name)
                        if module is not None:
                            importlib.reload(module)
                            actions.append(f'+ Module \'{module_name}\' reloaded.')
                            name_found = True
            if not name_found:
                actions.append(f'- No loaded cog or module with the name \'{module}\' found.')

        message = ''
        for action in actions:
            message = f'{message}\n{action}'
        await ctx.respond(f'```diff\n{message}\n```')

    @dev_group.command(name='emoji-check', aliases=('emoji','emojis'),
                       description='Check the availabilty of all emojis in emojis.py', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    async def dev_emoji_check(self, ctx: bridge.BridgeContext) -> None:
        """Check the availabilty of all emojis in emojis.py"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        all_emojis = {}
        for attribute_name in dir(emojis):
            attribute_value = getattr(emojis, attribute_name)
            if isinstance(attribute_value, str):
                if attribute_value.startswith('<'):
                    all_emojis[attribute_name] = attribute_value
        missing_emojis = {}
        invalid_emojis = {}
        for attribute_name, emoji_string in all_emojis.items():
            emoji_id_match = re.search(r'<a?:.+:(\d+)>', emoji_string)
            if not emoji_id_match:
                invalid_emojis[attribute_name] = emoji_string
                continue
            emoji = self.bot.get_emoji(int(emoji_id_match.group(1)))
            if emoji is None:
                missing_emojis[attribute_name] = emoji_string
        if not missing_emojis and not invalid_emojis:
            description = '_All emojis in `emojis.py` are valid and available._'
        else:
            description = (
                '- _Invalid emojis have an error in their definition in `emojis.py`._\n'
                '- _Missing emojis are valid but not found on Discord. Upload them to a server Navchi can see and set '
                'the correct IDs in `emojis.py`._\n'
            )
        if invalid_emojis:
            description = f'{description}\n\n**Invalid emojis**'
            for attribute_name, emoji_string in invalid_emojis.items():
                description = f'{description}\n- {emoji_string} `{attribute_name}`'
        if missing_emojis:
            description = f'{description}\n\n**Missing emojis**'
            for attribute_name, emoji_string in missing_emojis.items():
                description = f'{description}\n- {emoji_string} `{attribute_name}`'
        if len(description) >= 4096:
            description = f'{description[:4050]}\n- ... too many errors, what are you even doing?'
        embed = discord.Embed(
            title = 'Emoji check',
            description = description,
        )
        await ctx.respond(embed=embed)


    @dev_group.command(name='event-reductions', aliases=('er',), description='Manage global event reductions',
                       guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    async def dev_event_reductions(self, ctx: bridge.BridgeContext) -> None:
        """Manage global event reductions"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        all_cooldowns = list(await cooldowns.get_all_cooldowns())
        view = views.DevEventReductionsView(ctx, self.bot, all_cooldowns, embed_dev_event_reductions)
        embed = await embed_dev_event_reductions(all_cooldowns)
        interaction = await ctx.respond(embed=embed, view=view)
        view.interaction = interaction

    @dev_group.command(name='backup', description='Manually backup the database of Navchi', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True)
    async def dev_backup(self, ctx: bridge.BridgeContext) -> None:
        """Manually backup the database of Navchi"""
        ctx_author_name = ctx.author.global_name if ctx.author.global_name is not None else ctx.author.name
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        view = views.ConfirmCancelView(ctx, styles=[discord.ButtonStyle.blurple, discord.ButtonStyle.grey])
        interaction = await ctx.respond(
            f'This will back up the database to `navchi_db_backup.db`. You can continue using Navchi while doing this.\n'
            f'**If the target file exists, it will be overwritten!**\n\n'
            f'Proceed?',
            view=view,
        )
        view.interaction_message = interaction
        await view.wait()
        if view.value is None:
            await interaction.edit(f'**{ctx_author_name}**, you didn\'t answer in time.')
        elif view.value != 'confirm':
            await interaction.edit(view=None)
            await interaction.edit('Backup aborted.')
        else:
            start_time = datetime.utcnow()
            interaction = await ctx.respond('Starting backup...')
            backup_db_file = os.path.join(settings.BOT_DIR, 'database/navchi_db_backup.db')
            navchi_backup_db = sqlite3.connect(backup_db_file)
            settings.NAVCHI_DB.backup(navchi_backup_db)
            navchi_backup_db.close()
            time_taken = datetime.utcnow() - start_time
            await interaction.edit(f'Backup finished after {format_timespan(time_taken)}')

    @dev_group.command(name='post-message', aliases=('pm',),
                       description='Sends the content of a message to a channel in an embed', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    async def dev_post_message(
        self,
        ctx: bridge.BridgeContext,
        message_id: BridgeOption(str, description='Message ID of the message IN THIS CHANNEL with the content'),
        channel_id: BridgeOption(str, description='Channel ID of the channel where the message is sent to'),
        *,
        embed_title: BridgeOption(str, description='Title of the embed', max_length=256),
    ) -> None:
        """Sends the content of a message to a channel in an embed"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        ctx_author_name = ctx.author.global_name if ctx.author.global_name is not None else ctx.author.name
        await self.bot.wait_until_ready()
        try:
            message_id = int(message_id)
        except ValueError:
            await ctx.respond('The message ID is not a valid number.', ephemeral=True)
            return
        try:
            channel_id = int(channel_id)
        except ValueError:
            await ctx.respond('The channel ID is not a valid number.', ephemeral=True)
            return
        try:
            message = await ctx.channel.fetch_message(message_id)
        except:
            await ctx.respond(
                f'No message with that message ID found.\n'
                f'Note that the message needs to be in **this** channel!',
                ephemeral=True
            )
            return
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except:
            await ctx.respond('No channel with that channel ID found.', ephemeral=True)
            return
        embed = discord.Embed(
            title = embed_title,
            description = message.content
        )
        view = views.ConfirmCancelView(ctx, styles=[discord.ButtonStyle.blurple, discord.ButtonStyle.grey])
        interaction = await ctx.respond(
            f'I will send the following embed to the channel `{channel.name}`. Proceed?',
            view=view,
            embed=embed
        )
        view.interaction_message = interaction
        await view.wait()
        if view.value is None:
            await interaction.edit(view=None)
            answer = f'**{ctx_author_name}**, you didn\'t answer in time.'
        elif view.value == 'confirm':
            await channel.send(embed=embed)
            await interaction.edit(view=None)
            answer = 'Message sent.'
        else:
            await interaction.edit(view=None)
            answer = 'Sending aborted.'
        if ctx.is_app:
            await ctx.followup.send(answer)
        else:
            await ctx.send(answer)

    @dev_group.command(name='support', description='Link to the dev support server', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True)
    async def dev_support(self, ctx: bridge.BridgeContext):
        """Link to the dev support server"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        await ctx.respond(
            f'Got some issues or questions running Navchi? Feel free to join the Navchi dev support server:\n'
            f'https://discord.gg/Kz2Vz2K4gy'
        )

    @dev_group.command(name='shutdown', description='Shuts down the bot', guild_ids=settings.DEV_GUILDS)
    @commands.bot_has_permissions(send_messages=True)
    async def dev_shutdown(self, ctx: bridge.BridgeContext):
        """Shuts down the bot"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        ctx_author_name = ctx.author.global_name if ctx.author.global_name is not None else ctx.author.name
        aborted = confirmed = timeout = False
        answer = f'**{ctx_author_name}**, are you **SURE**?'
        if ctx.is_app:
            view = views.ConfirmCancelView(ctx, styles=[discord.ButtonStyle.red, discord.ButtonStyle.grey])
            interaction = await ctx.respond(answer, view=view)
            view.interaction_message = interaction
            await view.wait()
            if view.value is None:
                timeout = True
            elif view.value == 'confirm':
                confirmed = True
            else:
                aborted = True
        else:
            def check(m: discord.Message) -> bool:
                return m.author == ctx.author and m.channel == ctx.channel

            interaction = await ctx.respond(f'{answer} `[yes/no]`')
            try:
                answer = await self.bot.wait_for('message', check=check, timeout=30)
            except asyncio.TimeoutError:
                timeout = True
            if answer.content.lower() in ['yes','y']:
                confirmed = True
            else:
                aborted = True
        if timeout:
            await interaction.edit(interaction, content=f'**{ctx_author_name}**, you didn\'t answer in time.', view=None)
        elif confirmed:
            await interaction.edit(content='Shutting down.', view=None)
            await self.bot.close()
        else:
            await interaction.edit(content='Shutdown aborted.', view=None)

    @dev_group.command(name='cache', description='Shows messagecache size', guild_ids=settings.DEV_GUILDS)
    async def dev_cache(self, ctx: bridge.BridgeContext):
        """Shows message cache size"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        from cache import messages
        cache_size = sys.getsizeof(messages._MESSAGE_CACHE)
        channel_count = len(messages._MESSAGE_CACHE)
        message_count = 0
        for channel_messages in messages._MESSAGE_CACHE.values():
            message_count += len(channel_messages)
            cache_size += sys.getsizeof(channel_messages)
            for message in channel_messages:
                cache_size += sys.getsizeof(message)
        await ctx.respond(
            f'Cache size: {cache_size / 1024:,.2f} KB\n'
            f'Channel count: {channel_count:,}\n'
            f'Message count: {message_count:,}\n'
        )

    @dev_group.command(name='server-list', aliases=('servers',), description='List all servers the bot is in',
                       guild_ids=settings.DEV_GUILDS)
    async def dev_server_list(self, ctx: bridge.BridgeContext):
        """List all servers the bot is inname"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        description = ''
        guilds = sorted(self.bot.guilds, key=lambda guild: guild.name)
        for guild in guilds:
            if len(description) > 4000:
                description = f'{description}\n{emojis.BP} ... and more'
                break
            else:
                description = f'{description}\n{emojis.BP} {guild.name} (`{guild.id}`)'

        embed = discord.Embed(
            color = settings.EMBED_COLOR,
            title = 'SERVER LIST',
            description = description.strip(),
        )
        await ctx.respond(embed=embed)

    @dev_group.command(name='consolidate', description='Consolidates tracking records older than 28 days manually',
                       guild_ids=settings.DEV_GUILDS)
    async def dev_consolidate(self, ctx: bridge.BridgeContext):
        """Consolidates tracking records older than 28 days manually"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        await ctx.defer()
        from datetime import datetime
        import asyncio
        from humanfriendly import format_timespan
        from database import tracking, users
        start_time = datetime.utcnow().replace(microsecond=0)
        log_entry_count = 0
        try:
            old_log_entries = await tracking.get_old_log_entries(28)
        except exceptions.NoDataFoundError:
            await ctx.respond('Nothing to do.')
            return
        entries = {}
        for log_entry in old_log_entries:
            date_time = log_entry.date_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            key = (log_entry.user_id, log_entry.guild_id, log_entry.command, date_time)
            amount = entries.get(key, 0)
            entries[key] = amount + 1
            log_entry_count += 1
        for key, amount in entries.items():
            user_id, guild_id, command, date_time = key
            summary_log_entry = await tracking.insert_log_summary(user_id, guild_id, command, date_time, amount)
            date_time_min = date_time.replace(hour=0, minute=0, second=0, microsecond=0)
            date_time_max = date_time.replace(hour=23, minute=59, second=59, microsecond=999999)
            await tracking.delete_log_entries(user_id, guild_id, command, date_time_min, date_time_max)
            await asyncio.sleep(0.01)
        cur = settings.NAVCHI_DB.cursor()
        cur.execute('VACUUM')
        end_time = datetime.utcnow().replace(microsecond=0)
        time_passed = end_time - start_time
        logs.logger.info(f'Consolidated {log_entry_count:,} log entries in {format_timespan(time_passed)} manually.')
        await ctx.respond(f'Consolidated {log_entry_count:,} log entries in {format_timespan(time_passed)}.')

    @dev_group.command(name='leave-server', description='Removes Navchi from a specific guild', guild_ids=settings.DEV_GUILDS)
    async def dev_leave_server(
        self,
        ctx: bridge.BridgeContext,
        guild_id: BridgeOption(str, description='ID of the server you want to leave'),
    ) -> None:
        """Removes Navchi from a specific guild"""
        if ctx.author.id not in settings.DEV_IDS:
            if ctx.is_app: await ctx.respond(MSG_NOT_DEV, ephemeral=True)
            return
        try:
            guild_id = int(guild_id)
        except:
            await ctx.respond('Invalid ID.')
            return
        guild_to_leave = self.bot.get_guild(guild_id)
        if guild_to_leave is None:
            await ctx.respond('No server found with that ID.')
            return
        view = views.ConfirmCancelView(ctx, styles=[discord.ButtonStyle.blurple, discord.ButtonStyle.grey])
        interaction = await ctx.respond(
            f'Remove Navchi from **{guild_to_leave.name}** (`{guild_to_leave.id}`)?',
            view=view
        )
        view.interaction_message = interaction
        await view.wait()
        if view.value is None:
            await ctx.followup.send(f'**{ctx.author.name}**, you didn\'t answer in time.', ephemeral=True)
        elif view.value == 'confirm':
            try:
                await guild_to_leave.leave()
            except Exception as error:
                await ctx.respond(
                    f'Leaving the server failed with the following error:\n'
                    f'```\n{error}\n```'
                )
            await interaction.edit(content=f'Removed Navchi from **{guild_to_leave.name}** (`{guild_to_leave.id}`).',
                                   view=None)
        else:
            await interaction.edit(content='Aborted.', view=None)


def setup(bot):
    bot.add_cog(DevCog(bot))


# --- Embeds ---
async def embed_dev_event_reductions(all_cooldowns: List[cooldowns.Cooldown]) -> discord.Embed:
    """Event reductions embed"""
    reductions_slash = reductions_text = ''
    for cooldown in all_cooldowns:
        if cooldown.event_reduction_slash > 0:
            event_reduction_slash = f'**`{cooldown.event_reduction_slash}`**%'
        else:
            event_reduction_slash = f'`{cooldown.event_reduction_slash}`%'
        reductions_slash = f'{reductions_slash}\n{emojis.BP} {cooldown.activity}: {event_reduction_slash}'
        if cooldown.event_reduction_mention > 0:
            event_reduction_text = f'**`{cooldown.event_reduction_mention}`**%'
        else:
            event_reduction_text = f'`{cooldown.event_reduction_mention}`%'
        reductions_text = f'{reductions_text}\n{emojis.BP} {cooldown.activity}: {event_reduction_text}'
    embed = discord.Embed(
        color = settings.EMBED_COLOR,
        title = 'EVENT REDUCTION SETTINGS',
    )
    embed.add_field(name='SLASH COMMANDS', value=reductions_slash, inline=False)
    embed.add_field(name='TEXT & MENTION COMMANDS', value=reductions_text, inline=False)
    return embed
