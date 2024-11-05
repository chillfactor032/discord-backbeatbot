import asyncio
import logging.handlers
import os
import json
from threading import Thread
from enum import Enum
from datetime import datetime, timezone
import time
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
    def __init__(self, discord_token, clock_channel_id, live_channel_id, react_channels, react_file, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__("!", intents=intents, **kwargs)
        self.discord_token = discord_token
        self.clock_channel_id = clock_channel_id
        self.live_channel_id = live_channel_id
        self.live_channel = None
        self.admin_user_id = kwargs.get("admin_user_id", 0)
        self.react_channels = react_channels
        self.react_file = react_file
        self.tiktok_username = kwargs.get("tiktok_username", "")
        self.tiktok_channel_id = kwargs.get("tiktok_channel_id", 0)
        self.logger = logging.getLogger(self.__class__.__name__)

    async def on_ready(self):
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        self.live_channel = self.get_channel(self.live_channel_id)
        initial_status = "Mitch is live!" in self.live_channel.name
        self.logger.info(f"Initial Live Status: {initial_status}")
        await self.add_cog(ClockUpdateCog(self, self.clock_channel_id))
        await self.add_cog(CheckTwitchLiveCog(self, initial_status))
        if len(self.react_channels) > 0:
            await self.add_cog(MessageReactsCog(self, self.react_channels, self.react_file))
        if len(self.tiktok_username) > 0:
            await self.add_cog(TikTokLiveCog(self, self.tiktok_username, self.tiktok_channel_id))
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

class MessageReactsCog(commands.Cog, name='Message Reacts'):

    def __init__(self, bot: discord.Client, messages: list, file: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.bot = bot
        self.messages = messages
        self.file = file
        self.record_reactions.start()

    @tasks.loop(minutes=1.0)
    async def record_reactions(self):
        result = {}
        for msgs in self.messages:
            users = []
            try:
                channel = await self.bot.fetch_channel(msgs["channel"])
            except Exception as e:
                self.logger.error(f"Could not fetch channel id [{msgs['channel']}]")
                self.logger.error(e)
                continue
            try:
                message = await channel.fetch_message(msgs["message"])
                for reaction in message.reactions:
                    reactors = [user.name async for user in reaction.users()]
                    users.extend(reactors)
            except Exception as e:
                self.logger.error(f"Could not fetch message [{msgs['message']}]")
                self.logger.error(e)
            users = list(set(users))
            result[msgs["message"]] = users
        try:
            with open(self.file, "w") as f:
                json.dump(result, f)
        except Exception as e:
            self.logger.error("Could not write reactions file")
            self.logger.error(e)

    def cog_unload(self):
        self.record_reactions.cancel()

class TikTokLiveCog(commands.Cog, name='TikTok Live'):

    def __init__(self, bot: discord.Client, tiktok_username, channel_id):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.last_alert_file = ".tiktokalerttime"
        # 12 hours auto reset time since last notification
        self.mins_since_alert_threshold = 60 * 12
        self.bot = bot
        self.tiktok_username = tiktok_username
        self.channel = self.bot.get_channel(channel_id)
        self.url = f"https://www.tiktok.com/api-live/user/room/?aid=1988&uniqueId={self.tiktok_username}&sourceType=54"
        self.check_live.start()

    @tasks.loop(minutes=1.0)
    async def check_live(self):
        prev_start_time = self.read_last_start_time()
        self.logger.debug(f"Checking online status from tiktok: {self.tiktok_username}")
        resp = requests.get(self.url)
        self.logger.debug(f"Live Status HTTP Code: {resp.status_code}")
        self.logger.debug(resp.text)

        if resp.status_code == 200:
            obj = resp.json()
            status = None
            try:
                status = obj["data"]["liveRoom"]["status"]
                start_time = obj["data"]["liveRoom"]["startTime"]
            except KeyError as ke:
                self.logger.error(f"KeyError Looking for TikTok status")
                self.logger.error(ke)
                status = None
                start_time = 0
            if status is not None and start_time is not None:
                # If channen is live AND we havent sent an alert already
                if status != 4:
                    if start_time != prev_start_time:
                        self.logger.info(f"TikTok User {self.tiktok_username} went LIVE")
                        await self.send_live_alert()
                        self.write_last_start_time(start_time)
                    else:
                        # User is live but we already sent a notification
                        self.logger.debug(f"TikTok User {self.tiktok_username} is LIVE: Notification Already Sent ")
                else:
                    # User not live
                    pass
            else:
                self.logger.debug(f"Could not check TikTok Live API due to error")

    def read_last_start_time(self):
        last_start_time = 0
        if not os.path.isfile(self.last_alert_file):
            return 0
        with open(".tiktokalerttime", "r") as f:
            try:
                last_start_time = int(f.read())
            except ValueError as e:
                print("Value Error")
                last_start_time = 0
        return last_start_time

    def write_last_start_time(self, alert_time):
        with open(".tiktokalerttime", "w") as f:
            f.write(str(alert_time))

    async def send_live_alert(self):
        text = "Mitch is live on TikTok now! Join in to catch some awesome beats! <@&1303148537420316693>\nhttps://tiktok.com/@mitchbruzzese/live"
        await self.channel.send(text)

    def cog_unload(self):
        self.check_live.cancel()


class DiscordBotRunner(Thread):

    def __init__(self, discord_token, clock_channel_id, live_channel_id, react_channels, react_file, admin_user_id, tiktok_username, tiktok_channel_id):
        Thread.__init__(self)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.discord_token = discord_token
        self.clock_channel_id = clock_channel_id
        self.live_channel_id = live_channel_id
        self.react_channels = react_channels
        self.react_file = react_file
        self.admin_user_id = admin_user_id
        self.tiktok_username = tiktok_username
        self.tiktok_channel_id = tiktok_channel_id
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
                                self.react_channels,
                                self.react_file,
                                admin_user_id=self.admin_user_id,
                                tiktok_username=self.tiktok_username,
                                tiktok_channel_id=self.tiktok_channel_id)
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
    
    react_channels = config.get("record_reactions", [])
    react_file = config.get("record_reactions_file", None)

    bot = DiscordBotRunner(config["discord_token"], 
                           config["clock_channel_id"], 
                           config["live_channel_id"],
                           react_channels,
                           react_file, 
                           config.get("admin_user_id", 0),
                           config.get("tiktok_username", ""),
                           config.get("tiktok_channel_id", 0))
    
    # Can call bot.run = blocking, bot.start non-blocking
    bot.run()
    logger.info("=== BackbeatBot Discord Bot Shutdown Complete ===")

if __name__ == "__main__":
    main()
