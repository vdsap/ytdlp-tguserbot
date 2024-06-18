import logging

import yt_dlp
from pyrogram import Client, filters
from configparser import ConfigParser
from os import remove
import datetime


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
bot = Client('bot', api_id=bot_conf.api_id, api_hash=bot_conf.api_hash, bot_token=bot_conf.token)
yt = yt_dlp.YoutubeDL()

async def progress(current, total, message, dtime):
    if (datetime.datetime.now() - dtime).total_seconds()%2 < 0.2:
        await message.edit_caption(f"{current * 100 / total:.0f}% | {current}/{total}")

@bot.on_message(filters.command(["start", "help"]))
async def start_func(client, message):
    await message.reply_text('Hi, send video_url to start\nI can send videos only smaller 2GB',quote=True)
    logging.info(f"/start from {message.from_user.first_name} | {message.from_user.id}")

@bot.on_message(filters.regex("https://www.youtube.com/"))
@bot.on_message(filters.regex("https://youtu.be/*"))
@bot.on_message(filters.regex("https://youtube.com/*"))
async def youtube_func(client, message):
    mes = await message.reply("Loading video info...",quote=True)
    url = message.text
    logging.info(f"Query: {message.text}")
    vid_info = yt.extract_info(url, download=False)
    video_format = format_selector(vid_info)
    format_vid = video_format.get('requested_formats')[0]
    format_aud = video_format.get('requested_formats')[1]
    size = (format_vid.get('filesize')+format_aud.get('filesize'))//1024//1024
    logging.info(f"File size: {size}MB")
    if size < 2048:
        await mes.edit(f"Video size {size}MB < 2048MB, downloading video...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as yt_dl:
                file_dl = yt_dl.extract_info(url)
                filename = yt_dl.prepare_filename(file_dl)
        except Exception as e:
            await mes.edit(e)
        await mes.edit(f'File size: {size}MB\nSending video...')
        dtime = datetime.datetime.now()
        mes_cap = await message.reply_video(filename,caption=f'File size: {size}MB\nSending video...',progress=progress, progress_args=(mes,dtime,),quote=True)
        await mes_cap.edit_caption(f'{filename} [{size}MB]')
        remove(filename)
        await mes.delete()
        logging.info('Uploaded')
    else:
        logging.warning("File > 2GB")
        await mes.delete()
        await message.reply("Video size > 2GB, can't process")


bot.run()
