import asyncio
import logging
import os
import re
from configparser import ConfigParser

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)


class Config:
    def __init__(self):
        logging.info("Init config")
        _config = ConfigParser()
        _config.read("conf.ini")
        self.token = _config["TgBot"]["token"]
        self.api_id = int(_config["TgBot"].get("api_id", 0))
        self.api_hash = _config["TgBot"].get("api_hash", "")
        # telegram-bot-api URL can be configured or defaulted to container name
        self.api_server = _config["TgBot"].get("api_server", "http://telegram-bot-api:8081")


def format_selector(ctx):
    formats = ctx.get('formats', [])[::-1]
    best_video = next(
        (f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') == 'none'
         and f.get('height') and f['height'] <= 1080 and f.get('vcodec', '').startswith('avc')),
        None
    )
    if not best_video:
        best_video = next(
            (f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') == 'none' and f.get('height') and f['height'] <= 1080),
            None
        )

    if not best_video:
        return 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'

    audio_ext = {'mp4': 'm4a', 'webm': 'webm'}.get(best_video.get('ext'), 'm4a')
    best_audio = next(
        (f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('ext') == audio_ext),
        None
    )
    if not best_audio:
        best_audio = next((f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none'), None)

    if not best_audio:
        return f"{best_video['format_id']}+bestaudio/best"

    result = {
        'format_id': f"{best_video['format_id']}+{best_audio['format_id']}",
        'ext': best_video.get('ext', 'mp4'),
        'requested_formats': [best_video, best_audio],
        'protocol': f"{best_video.get('protocol', '')}+{best_audio.get('protocol', '')}",
    }
    logging.info(f"formats: {result['format_id']}")
    return result


def format_yield(ctx):
    yield format_selector(ctx)


ydl_opts = {
    'format': format_yield,
    'restrictfilenames': True,
    'forcefilename': True,
    'outtmpl': '/usr/src/app/%(title)s.%(ext)s',
}

cfg = Config()
dp = Dispatcher()


@dp.message(Command(commands=["start", "help"]))
async def start_func(message: Message):
    user_name = message.from_user.first_name if message.from_user else "User"
    user_id = message.from_user.id if message.from_user else 0
    logging.info(f"/start from {user_name} | {user_id}")
    await message.reply("Hi, send a YouTube URL to download.\nLocal bot API allows files up to 2000MB.")


@dp.message(F.text.regexp(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[^\s]+)'))
async def youtube_func(message: Message):
    status_msg = await message.reply("Loading video info...")
    url = message.text.strip()
    logging.info(f"Query: {url}")

    loop = asyncio.get_running_loop()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as yt:
            vid_info = await loop.run_in_executor(None, lambda: yt.extract_info(url, download=False))
            video_format = format_selector(vid_info)

            size_mb = 0
            if isinstance(video_format, dict):
                req = video_format.get('requested_formats', [])
                if len(req) >= 2:
                    v_size = req[0].get('filesize') or req[0].get('filesize_approx') or 0
                    a_size = req[1].get('filesize') or req[1].get('filesize_approx') or 0
                    size_mb = (v_size + a_size) // (1024 * 1024)

            logging.info(f"Calculated size: {size_mb}MB")

            if size_mb > 2000:
                await status_msg.edit_text("Video size is larger than 2000MB, cannot process.")
                return

            await status_msg.edit_text(f"Video size ~{size_mb}MB. Downloading...")
            file_dl = await loop.run_in_executor(None, lambda: yt.extract_info(url, download=True))
            filename = yt.prepare_filename(file_dl)

        if not os.path.exists(filename):
            # Try finding downloaded file if ext differed
            base_name = os.path.splitext(filename)[0]
            for ext in ['.mp4', '.mkv', '.webm']:
                if os.path.exists(base_name + ext):
                    filename = base_name + ext
                    break

        real_size_mb = os.path.getsize(filename) // (1024 * 1024)
        await status_msg.edit_text(f"File size: {real_size_mb}MB\nUploading video to Telegram via local Bot API...")

        video_file = FSInputFile(filename)
        await message.reply_video(
            video=video_file,
            caption=f"{os.path.basename(filename)} [{real_size_mb}MB]"
        )
        try:
            os.remove(filename)
        except Exception as e:
            logging.error(f"Error removing file {filename}: {e}")

        await status_msg.delete()
        logging.info(f"Successfully uploaded: {filename}")

    except Exception as e:
        logging.exception(f"Error processing video: {e}")
        try:
            await status_msg.edit_text(f"Error: {str(e)[:200]}")
        except Exception:
            pass


async def main():
    logging.info(f"Bot starting with server {cfg.api_server}")
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(cfg.api_server, is_local=True)
    )
    bot = Bot(
        token=cfg.token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
