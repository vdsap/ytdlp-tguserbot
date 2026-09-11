import aiohttp
import asyncio
import logging
import os
import re
import subprocess
import time
from configparser import ConfigParser

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional, Union

logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)


class ProgressFSInputFile(FSInputFile):
    def __init__(
        self,
        path: Union[str, Path],
        filename: Optional[str] = None,
        chunk_size: int = 512 * 1024,
        progress_callback: Optional[Callable[[int, int], Any]] = None,
    ):
        super().__init__(path=path, filename=filename, chunk_size=chunk_size)
        self.progress_callback = progress_callback
        try:
            self.file_size = os.path.getsize(path)
        except Exception:
            self.file_size = 0

    async def read(self, bot: Bot) -> AsyncGenerator[bytes, None]:
        uploaded = 0
        async for chunk in super().read(bot):
            uploaded += len(chunk)
            if self.progress_callback:
                try:
                    res = self.progress_callback(uploaded, self.file_size)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass
            yield chunk


async def safe_edit_message(msg: Message, text: str):
    try:
        await msg.edit_text(text)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.debug(f"BadRequest editing status message: {e}")
    except TelegramRetryAfter as e:
        logging.warning(f"Telegram retry after {e.retry_after}s when editing message")
    except Exception as e:
        logging.debug(f"Failed to edit status message: {e}")


def get_video_dimensions(filename: str, fallback_info: Optional[dict] = None) -> tuple[Optional[int], Optional[int]]:
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=s=x:p=0',
            filename
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = res.stdout.strip()
        if 'x' in out:
            parts = out.split('x')
            return int(parts[0]), int(parts[1])
    except Exception as e:
        logging.debug(f"ffprobe failed for {filename}: {e}")

    if fallback_info:
        w = fallback_info.get('width')
        h = fallback_info.get('height')
        if w and h:
            return int(w), int(h)
    return None, None


async def extract_thumbnail(thumb_url: Optional[str], video_path: str) -> Optional[str]:
    base_name = os.path.splitext(video_path)[0]
    final_thumb_path = f"{base_name}_thumb.jpg"
    raw_thumb_path = f"{base_name}_thumb.raw"
    loop = asyncio.get_running_loop()

    # 1. Try downloading original thumbnail from YouTube link
    if thumb_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumb_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(raw_thumb_path, "wb") as f:
                            f.write(data)

            if os.path.exists(raw_thumb_path) and os.path.getsize(raw_thumb_path) > 0:
                cmd = [
                    'ffmpeg', '-y', '-i', raw_thumb_path,
                    '-vf', 'scale=w=320:h=320:force_original_aspect_ratio=decrease',
                    '-frames:v', '1', '-update', '1',
                    '-q:v', '2',
                    final_thumb_path
                ]
                await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, check=True))
                if os.path.exists(final_thumb_path) and os.path.getsize(final_thumb_path) <= 200 * 1024:
                    return final_thumb_path
        except Exception as e:
            logging.warning(f"Failed to fetch or process thumbnail from {thumb_url}: {e}")
        finally:
            if os.path.exists(raw_thumb_path):
                try:
                    os.remove(raw_thumb_path)
                except Exception:
                    pass

    # 2. Fallback: extract frame from downloaded video
    if os.path.exists(video_path):
        try:
            cmd = [
                'ffmpeg', '-y', '-ss', '00:00:01',
                '-i', video_path,
                '-vf', 'scale=w=320:h=320:force_original_aspect_ratio=decrease',
                '-frames:v', '1', '-update', '1',
                '-q:v', '2',
                final_thumb_path
            ]
            await loop.run_in_executor(None, lambda: subprocess.run(cmd, capture_output=True, check=True))
            if os.path.exists(final_thumb_path) and os.path.getsize(final_thumb_path) <= 200 * 1024:
                return final_thumb_path
        except Exception as e:
            logging.warning(f"Failed to extract frame thumbnail from {video_path}: {e}")

    return None


class Config:
    def __init__(self):
        logging.info("Init config")
        _config = ConfigParser()
        _config.read("conf.ini")
        self.token = _config["TgBot"]["token"]
        self.api_id = int(_config["TgBot"].get("api_id", 0))
        self.api_hash = _config["TgBot"].get("api_hash", "")
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


DOWNLOAD_DIR = '/var/lib/telegram-bot-api'

ydl_opts = {
    'format': format_yield,
    'restrictfilenames': True,
    'forcefilename': True,
    'outtmpl': f'{DOWNLOAD_DIR}/%(id)s_%(title)s.%(ext)s',
    'socket_timeout': 30,
    'retries': 15,
    'fragment_retries': 15,
    'file_access_retries': 10,
    'extractor_retries': 10,
    'buffersize': 1024 * 16,
    'http_chunk_size': 10485760,  # 10MB chunk for stabler streaming
}

cfg = Config()
dp = Dispatcher()


@dp.message(Command(commands=["start", "help"]))
async def start_func(message: Message):
    user_name = message.from_user.first_name if message.from_user else "User"
    user_id = message.from_user.id if message.from_user else 0
    logging.info(f"/start from {user_name} | {user_id}")
    await message.reply("Hi! Send a YouTube link to download video (up to 2GB).")


@dp.message(F.text.regexp(r'(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)[^\s]+)'))
async def youtube_func(message: Message):
    status_msg = await message.reply("Loading video info...")
    url = message.text.strip()
    logging.info(f"Query: {url}")

    loop = asyncio.get_running_loop()
    thumb_path: Optional[str] = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as yt:
            vid_info = await loop.run_in_executor(None, lambda: yt.extract_info(url, download=False))
            video_format = format_selector(vid_info)
            thumb_url = vid_info.get('thumbnail')
            if not thumb_url and vid_info.get('thumbnails'):
                thumb_url = vid_info['thumbnails'][-1].get('url')

            size_mb = 0
            if isinstance(video_format, dict):
                req = video_format.get('requested_formats', [])
                if len(req) >= 2:
                    v_size = req[0].get('filesize') or req[0].get('filesize_approx') or 0
                    a_size = req[1].get('filesize') or req[1].get('filesize_approx') or 0
                    size_mb = (v_size + a_size) // (1024 * 1024)

            logging.info(f"Estimated size: {size_mb}MB")
            if size_mb > 2000:
                await status_msg.edit_text(f"Video size ~{size_mb}MB > 2000MB, cannot process.")
                return

            last_dl_edit_time = 0.0

            def ytdl_progress_hook(d):
                nonlocal last_dl_edit_time
                status = d.get('status')
                if status == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    now = time.monotonic()
                    if now - last_dl_edit_time >= 2.0:
                        last_dl_edit_time = now
                        if total > 0:
                            percent = downloaded / total * 100
                            dl_mb = downloaded / (1024 * 1024)
                            tot_mb = total / (1024 * 1024)
                            text = f"Downloading from YouTube: {percent:.1f}% ({dl_mb:.1f}/{tot_mb:.1f}MB)"
                        else:
                            dl_mb = downloaded / (1024 * 1024)
                            text = f"Downloading from YouTube: {dl_mb:.1f}MB"
                        asyncio.run_coroutine_threadsafe(safe_edit_message(status_msg, text), loop)
                elif status == 'finished':
                    asyncio.run_coroutine_threadsafe(
                        safe_edit_message(status_msg, "Download finished. Processing video..."),
                        loop
                    )

            download_opts = dict(ydl_opts)
            download_opts['progress_hooks'] = [ytdl_progress_hook]

            await status_msg.edit_text(f"Size ~{size_mb}MB. Downloading video...")
            with yt_dlp.YoutubeDL(download_opts) as yt_dl:
                file_dl = await loop.run_in_executor(None, lambda: yt_dl.extract_info(url, download=True))
                filename = yt_dl.prepare_filename(file_dl)

        if not os.path.exists(filename):
            base_name = os.path.splitext(filename)[0]
            for ext in ['.mp4', '.mkv', '.webm']:
                if os.path.exists(base_name + ext):
                    filename = base_name + ext
                    break

        thumb_path = await extract_thumbnail(thumb_url, filename)
        thumb_file = FSInputFile(thumb_path) if thumb_path and os.path.exists(thumb_path) else None

        real_size_mb = os.path.getsize(filename) // (1024 * 1024)
        await status_msg.edit_text(f"Downloaded ({real_size_mb}MB). Starting upload to Telegram...")

        last_up_edit_time = 0.0
        upload_task: Optional[asyncio.Task] = None

        def upload_progress_callback(uploaded: int, total: int):
            nonlocal last_up_edit_time, upload_task
            now = time.monotonic()
            if total > 0 and (now - last_up_edit_time >= 2.0 or uploaded == total):
                if upload_task is not None and not upload_task.done():
                    return
                last_up_edit_time = now
                percent = uploaded / total * 100
                up_mb = uploaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                text = f"Uploading to Telegram: {percent:.1f}% ({up_mb:.1f}/{total_mb:.1f}MB)"
                upload_task = asyncio.create_task(safe_edit_message(status_msg, text))

        width, height = await loop.run_in_executor(
            None, lambda: get_video_dimensions(filename, file_dl)
        )
        logging.info(f"Video dimensions: width={width}, height={height}")

        video_file = ProgressFSInputFile(
            filename,
            progress_callback=upload_progress_callback
        )
        await message.reply_video(
            video=video_file,
            caption=f"{os.path.basename(filename)} [{real_size_mb}MB]",
            supports_streaming=True,
            width=width,
            height=height,
            thumbnail=thumb_file
        )

        if upload_task is not None and not upload_task.done():
            upload_task.cancel()

        try:
            os.remove(filename)
        except Exception as e:
            logging.error(f"Error removing file {filename}: {e}")

        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception as e:
                logging.error(f"Error removing thumbnail {thumb_path}: {e}")

        await status_msg.delete()
        logging.info(f"Successfully sent and removed: {filename}")

    except Exception as e:
        logging.exception(f"Error processing video: {e}")
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass
        try:
            await status_msg.edit_text(f"Error: {str(e)[:250]}")
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
