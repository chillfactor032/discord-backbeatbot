import asyncio
import logging.handlers
import os
import json
from threading import Thread
from enum import Enum
from datetime import datetime, timezone
import argparse
import signal
import requests
import discord
from discord.ext import tasks, commands

import logging

class ChannelType(Enum):
    GUILD_TEXT = 0
    DM = 1
    GUILD_VOICE = 2
    GROUP_DM = 3
    GUILD_CATEGORY = 4
    GUILD_ANNOUNCEMENT = 5
    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12
    GUILD_STAGE_VOICE = 13
    GUILD_DIRECTORY = 14
    GUILD_FORUM = 15
    GUILD_MEDIA = 16

    @classmethod
    def has_value(cls, value):
        return value in cls._value2member_map_ 

class DiscordBot(commands.Bot):
    def __init__(self, discord_token, clock_channel_id, live_channel_id, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__("!", intents=intents, **kwargs)
        self.discord_token = discord_token
        self.clock_channel_id = clock_channel_id
        self.live_channel_id = live_channel_id
        self.live_channel = None
        self.admin_user_id = kwargs.get("admin_user_id", 0)
        self.logger = logging.getLogger(self.__class__.__name__)

    async def on_ready(self):
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        self.live_channel = self.get_channel(self.live_channel_id)
        initial_status = "Mitch is live!" in self.live_channel.name
        self.logger.info(f"Initial Live Status: {initial_status}")
        await self.add_cog(ClockUpdateCog(self, self.clock_channel_id))
        await self.add_cog(CheckTwitchLiveCog(self, initial_status))
        self.logger.info("=== BackbeatBot Discord Bot Ready ===")

    async def on_message(self, message: discord.Message) -> None:
        # If message is from the bot account, ignore
        if message.author == self.user: return
        if message.channel.type == discord.ChannelType.private and message.author.id == self.admin_user_id:
            if message.content == "!hide_live_channel":
                await message.reply("Hiding the live channel.")
                await self.hide_channel(self.live_channel)
            elif message.content == "!show_live_channel":
                await message.reply("Making the live channel visible.")
                await self.show_channel(self.live_channel)
            else:
                #Unknown command
                await message.reply("I'm not sure what you want.")
            self.logger.info(f"Recv DM From [{message.author.name}]: {message.content}")
        return await super().on_message(message)
    
    async def set_channel_name(self, channel: discord.VoiceChannel, name: str):
        if not channel:
            return
        result = await channel.edit(name=name)

    async def hide_channel(self, channel: discord.VoiceChannel):
        if not channel:
            return
        await self.set_channel_name(channel, "🔴 Mitch isn't live")
        everyone_role = discord.utils.get(channel.guild.roles, name="@everyone")
        if everyone_role is None:
            self.logger.error(f"Could not locate @everyone role in guild [{channel.guild.name}]")
            self.logger.error(f"Could not hide live channel from @everyone")
            return
        perms = channel.overwrites_for(everyone_role)
        perms.view_channel = False
        await channel.set_permissions(everyone_role, overwrite=perms, reason="Not Live")
        

    async def show_channel(self, channel: discord.VoiceChannel):
        if not channel:
            return
        await self.set_channel_name(channel, "🟢 Mitch is live!")
        everyone_role = discord.utils.get(channel.guild.roles, name="@everyone")
        if everyone_role is None:
            self.logger.error(f"Could not locate @everyone role in guild [{channel.guild.name}]")
            self.logger.error(f"Could not hide live channel from @everyone")
            return
        perms = channel.overwrites_for(everyone_role)
        perms.view_channel = None
        await channel.set_permissions(everyone_role, overwrite=perms, reason="Live!")


class CheckTwitchLiveCog(commands.Cog, name='Twitch Live'):

    def __init__(self, bot: DiscordBot, initial_live_status=False):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.bot = bot
        self.url = "https://backbeatbot.com/live_status.php"
        self.live_status = initial_live_status
        self.check_live.start()

    @tasks.loop(minutes=1.0)
    async def check_live(self):
        self.logger.debug(f"Checking online status from backbeatbot.com")
        resp = requests.get(self.url)
        self.logger.debug(f"Live Status HTTP Code: {resp.status_code}")
        self.logger.debug(resp.text)
        if resp.status_code == 200:
            obj = resp.json()
            live = obj.get("live", 0) == 1
            if live != self.live_status:
                if live:
                    self.logger.info("Channel ONLINE event")
                    await self.bot.show_channel(self.bot.live_channel)
                else:
                    self.logger.info("Channel OFFLINE event")
                    await self.bot.hide_channel(self.bot.live_channel)
                self.live_status = live

    def cog_unload(self):
        self.check_live.cancel()

class ClockUpdateCog(commands.Cog, name='Clock Update'):

    def __init__(self, bot: discord.Client, channel_id):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.bot = bot
        self.channel_id = channel_id
        self.channel = bot.get_channel(self.channel_id)
        self.clock_update.start()

    @tasks.loop(minutes=1.0)
    async def clock_update(self):
        if self.channel is None:
            return
        now = datetime.now(timezone.utc)
        if now.minute % 10 != 0:
            return
        new_channel_name = self.get_time_utc(now)
        self.logger.info(f"Edit channel: Id[{self.channel_id}] Name[{new_channel_name}]")
        if await self.channel.edit(name=new_channel_name):
            self.logger.info("Channel edit successful")
        else:
            self.logger.info("Channel edit failed")

    def get_time_utc(self, now=datetime.now(timezone.utc)):
        """Get the formatted channel name with current time"""
        day_str = now.strftime("%a")
        am_pm = now.strftime("%p").lower()
        time_str = now.strftime("%I:%M")
        if time_str[0] == "0":
            time_str = time_str[1:]
        return f"(Now: {day_str} {time_str}{am_pm} UTC)"
    
    def cog_unload(self):
        self.clock_update.cancel()


class DiscordBotRunner(Thread):

    def __init__(self, discord_token, clock_channel_id, live_channel_id, admin_user_id):
        Thread.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.discord_token = discord_token
        self.clock_channel_id = clock_channel_id
        self.live_channel_id = live_channel_id
        self.admin_user_id = admin_user_id
        self.bot = None
        self.loop = asyncio.new_event_loop()
        self._stopping = False
        # Register SIGTERM Handler to gracefully exit via KeyboardInterrupt
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, signum, frame):
        signame = signal.Signals(signum).name
        self.logger.debug(f'Caught Signal {signame} ({signum})')
        self.logger.info(f"Shutdown signal detected.")
        self.close()

    def close(self):
        """Function to quit the Discord bot"""
        self._stopping = True
        if self.bot is not None:
            self.logger.info("Shutting down bot.")
            future = asyncio.run_coroutine_threadsafe(self.bot.close(), self.loop)
            try:
                future.result(10)
            except TimeoutError:
                pass
            self.logger.info("Disconnected successfully.")

    def discord_status(self):
        discord_alive = False
        discord_ready = False
        msg = ""
        if self.bot is not None:
            discord_alive = self.bot.user is not None
            discord_ready = self.bot.is_ready()
        return discord_alive and discord_ready, msg

    def run(self):
        self.logger.info("Starting BackbeatBot Discord Bot")
        self.bot = DiscordBot(self.discord_token, 
                              self.clock_channel_id, 
                              self.live_channel_id,
                              admin_user_id=self.admin_user_id)
        self.loop.run_until_complete(self.bot.start(self.discord_token))


def main():
    # Ensure log directory exists:
    script_dir = os.path.dirname(os.path.realpath(__file__))
    log_dir = os.path.join(script_dir, "logs")
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    log_path = os.path.join(log_dir, "discordbot.log")

    logger = logging.getLogger(__name__)
    parser = argparse.ArgumentParser(
                        prog="BackbeatBot's Discord Bot",
                        description="A simple Discord Bot",
                        epilog='by ChillFacToR032')

    parser.add_argument("-c",
                        "--config",
                        default="config.json",
                        help="Path to a config file. See the README for an example.")

    parser.add_argument("-L",
                        "--loglevel",
                        default="INFO",
                        help="Sets the log level [INFO,ERROR,WARNING,DEBUG]")
    
    args = parser.parse_args()

    # Get log level from command line
    numeric_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    log_handlers = [
        logging.handlers.RotatingFileHandler(filename=log_path, maxBytes=1024*1024*3, backupCount=5),
        logging.StreamHandler()
    ]
    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s - %(message)s', 
                        level=numeric_level,
                        handlers=log_handlers)

    if not os.path.exists(args.config):
        logger.error("Config file doesn't exist. Specify a valid config file.")
        logger.info("Could not load config file. Exiting.")
        return

    config = None
    try: 
        with open(args.config) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error("JSON Decode Error. Specify a valid config file.")
        logger.error(e)
        logger.info("Could not load config file. Exiting.")
        return

    required_fields = ["discord_token","clock_channel_id"]
    for field in required_fields:
        if field not in config.keys():
            logger.info(f"Config file missing required field: [{field}]. Exiting.")
            return
    
    bot = DiscordBotRunner(config["discord_token"], 
                           config["clock_channel_id"], 
                           config["live_channel_id"],
                           config.get("admin_user_id", 0))
    
    # Can call bot.run = blocking, bot.start non-blocking
    bot.run()
    logger.info("=== BackbeatBot Discord Bot Shutdown Complete ===")

if __name__ == "__main__":
    main()
