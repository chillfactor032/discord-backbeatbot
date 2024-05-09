# BackbeatBot's Discord Bot
 
Custom Discord bot that runs on [discord.py](https://discordpy.readthedocs.io/en/stable/). 

New features will get added as needed.

## Features

BackbeatBot's Discord Bot currently implements the following features

- Sets a specified voice channel's name to be the current time. Runs every 10 minutes.

## Running the Bot

Clone the repository first

```
git clone https://github.com/chillfactor032/discord-backbeatbot.git
cd discord-backbeatbot
```

Install requirements, create a config file, then run it. Optionally you may want to create a virtural environemnt.

```
python3 -m pip install -r requirements
python3 discordbot.py -c /path/to/config.json -L INFO
```

## Config File Format

The config is in json format and only has 2 required fields: `discord_token` and `clock_channel_id`.

`discord_token` is the token generated in the [Discord Developer Portal](https://discord.com/developers/applications). If you need help generating one of these discord.py has a [help document](https://discordpy.readthedocs.io/en/stable/discord.html).

`clock_channel_id` is the Discord voice channel id that will get its name updated to the current time. You can get this by right-clicking the channel and clicking "Copy Channel ID". You may need to enable developer mode before this is available. Discord Settings > Advanced > Developer Mode. Note that this value is an integer in the json file.

```
{
    "discord_token": "<DISCORD_TOKEN>",
    "clock_channel_id": 0
}
```

The path to the config file can be specified with the `-c` or `--config` options. If this option is not specified it will look for a file `config.json` in the current working directory.

## Logging

The logging level can be set with the command line `-L` or `--loglevel` options. Valid options are one of the following `INFO, WARNING, ERROR, DEBUG, CRITICAL`. The default log level is `INFO`.


