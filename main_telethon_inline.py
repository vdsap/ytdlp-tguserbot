import logging
import random

import yt_dlp
from telethon import TelegramClient, events
from configparser import ConfigParser
from os import system



logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)


class Config:
    def __init__(self):
        logging.info("Init config")
        _config = ConfigParser()
        _config.read("conf.ini")
        self.token = _config["TgBot"]["token"]
        self.api_id = int(_config["TgBot"]["api_id"])
        self.api_hash = _config["TgBot"]["api_hash"]

def format_selector(ctx):
    formats = ctx.get('formats')[::-1]
    best_video = next(f for f in formats
                        if f['vcodec'] != 'none' and f['acodec'] == 'none' and f['height']<=1080 and f['vcodec'].startswith('avc'))
    audio_ext = {'mp4': 'm4a', 'webm': 'webm'}[best_video['ext']]
    best_audio = next(f for f in formats if (
        f['acodec'] != 'none' and f['vcodec'] == 'none' and f['ext'] == audio_ext))
    result = {
        'format_id': f'{best_video["format_id"]}+{best_audio["format_id"]}',
        'ext': best_video['ext'],
        'requested_formats': [best_video, best_audio],
        'protocol': f'{best_video["protocol"]}+{best_audio["protocol"]}'
    }
    logging.info(f"formats: {result["format_id"]}")
    return result

def format_yield(ctx):
    yield format_selector(ctx)


ydl_opts = {
    'format': format_yield,
    'restrictfilenames':True,
    'forcefilename':True,
}


logging.info("Bot starting")
bot_conf = Config()
bot = TelegramClient('bot', bot_conf.api_id, bot_conf.api_hash).start(bot_token=bot_conf.token)
yt = yt_dlp.YoutubeDL()


@bot.on(events.InlineQuery(pattern="https://www.youtube.com/*"))
@bot.on(events.InlineQuery(pattern="https://youtu.be/*"))
async def handler(event):
    builder = event.builder
    logging.info(f"InlineQuery: {event.text}")
    vid_info = yt.extract_info(event.text, download=False)
    video_format = format_selector(vid_info)
    format_vid = video_format.get('requested_formats')[0]
    format_aud = video_format.get('requested_formats')[1]
    size = (format_vid.get('filesize')+format_aud.get('filesize'))//1024//1024
    logging.info(f"file size: {size}MB")
    if size < 2048:
        with yt_dlp.YoutubeDL(ydl_opts) as yt_dl:
            file_dl = yt_dl.extract_info(event.text)
            filename = yt_dl.prepare_filename(file_dl)
        await event.answer(results=[builder.document(filename)])
        system(f"rm {filename}")



bot.start()
bot.run_until_disconnected()
