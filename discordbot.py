import asyncio
import os
import json
from threading import Thread
from enum import Enum
import time
from datetime import datetime, timezone
import argparse
import signal
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
    def __init__(self, discord_token, clock_channel_id, **kwargs):
        intents = discord.Intents.default()
        super().__init__("!", intents=intents, **kwargs)
        self.discord_token = discord_token
        self.clock_channel_id = clock_channel_id
        self.logger = logging.getLogger(self.__class__.__name__)

    async def on_ready(self):
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        await self.add_cog(ClockUpdateCog(self, self.clock_channel_id))
        self.logger.info("=== BackbeatBot Discord Bot Ready ===")

    async def close(self):
        # Maybe custom cleanup here
        await self.remove_cog("Clock Update")
        await super().close()

class DiscordBotRunner(Thread):

    def __init__(self, discord_token, channel_id):
        Thread.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.discord_token = discord_token
        self.clock_channel_id = channel_id
        self.bot = None
        self.runner = asyncio.Runner()
        self.loop = self.runner.get_loop()
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
        self.bot = DiscordBot(self.discord_token, self.clock_channel_id)
        self.runner.run(self.bot.start(self.discord_token))

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

def main():
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

    logging.basicConfig(format='%(asctime)s %(levelname)s %(name)s - %(message)s', level=numeric_level)

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
    
    bot = DiscordBotRunner(config["discord_token"], config["clock_channel_id"])
    # Can call bot.run = blocking, bot.start non-blocking
    bot.run()
    logger.info("=== BackbeatBot Discord Bot Shutdown Complete ===")

if __name__ == "__main__":
    main()
