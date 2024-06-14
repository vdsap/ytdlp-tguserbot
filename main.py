import logging
from telethon import TelegramClient, events
from configparser import ConfigParser



logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)


class Config:
    def __init__(self):
        logging.debug("Init config")
        _config = ConfigParser()
        _config.read("conf.ini")
        self.token = _config["TgBot"]["token"]
        self.api_id = int(_config["TgBot"]["api_id"])
        self.api_hash = _config["TgBot"]["api_hash"]

logging.info("Bot starting")
bot_conf = Config()
bot = TelegramClient('bot', bot_conf.api_id, bot_conf.api_hash).start(bot_token=bot_conf.token)



@bot.on(events.InlineQuery(pattern="https://www.youtube.com/*"))
@bot.on(events.InlineQuery(pattern="https://youtu.be/*"))
async def handler(event):
    builder = event.builder
    logging.debug("InlineQuery")
    await event.answer([builder.article(event.text, text=event.text)])



bot.start()
bot.run_until_disconnected()