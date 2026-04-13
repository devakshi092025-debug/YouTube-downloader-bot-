import os
import json
import logging
import asyncio
import threading
import subprocess
import tempfile
from pathlib import Path
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
PORT      = int(os.environ.get("PORT", 8080))

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN not set!")


# ── Keep Alive ────────────────────────────────────────────────────────────────

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "🎬 Downloader Bot Running! ✅", 200

@flask_app.route("/health")
def health():
    return "OK", 200

@flask_app.route("/ping")
def ping():
    return "pong", 200

def keep_alive():
    def run():
        try:
            flask_app.run(
                host="0.0.0.0",
                port=PORT,
                debug=False,
                use_reloader=False
            )
        except Exception as e:
            log.error(f"Flask error: {e}")
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()
    log.info(f"Keep-alive started on port {PORT}")


# ── Utilities ─────────────────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    url = url.lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    elif "instagram.com" in url:
        return "instagram"
    elif "facebook.com" in url or "fb.watch" in url or "fb.com" in url:
        return "facebook"
    elif "twitter.com" in url or "x.com" in url:
        return "twitter"
    elif "tiktok.com" in url:
        return "tiktok"
    else:
        return "unknown"


def format_size(bytes_val):
    """Convert bytes to human readable size"""
    if not bytes_val:
        return "N/A"
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024*1024*1024):.1f}GB"
    elif bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024*1024):.0f}MB"
    else:
        return f"{bytes_val / 1024:.0f}KB"


def get_video_data(url: str) -> dict:
    """Get full video info + all formats with sizes"""
    try:
        result = subprocess.run([
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--extractor-args", "youtube:player_client=android",
            "-J",
            url
        ], capture_output=True, text=True, timeout=60)

        if not result.stdout.strip():
            return None

        data = json.loads(result.stdout)

        # Get basic info
        duration_secs = data.get("duration", 0) or 0
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)

        info = {
            "title": data.get("title", "Unknown"),
            "duration": f"{mins}:{secs:02d}",
            "uploader": data.get("uploader", "Unknown"),
            "thumbnail": data.get("thumbnail", ""),
            "view_count": data.get("view_count", 0),
        }

        # Get formats with sizes
        formats = []
        seen_heights = set()

        for f in data.get("formats", []):
            height = f.get("height")
            vcodec = f.get("vcodec", "none")
            filesize = f.get("filesize") or f.get("filesize_approx") or 0

            if not height or vcodec == "none":
                continue
            if height in seen_heights:
                continue

            seen_heights.add(height)
            quality = f"{height}p"
            formats.append({
                "quality": quality,
                "height": height,
                "filesize": filesize,
                "size_str": format_size(filesize),
                "ext": "mp4"
            })

        # Sort highest to lowest
        formats.sort(key=lambda x: x["height"], reverse=True)

        # Add MP3 audio
        # Try to get audio size
        audio_size = 0
        for f in data.get("formats", []):
            if f.get("acodec", "none") != "none" and f.get("vcodec") == "none":
                audio_size = f.get("filesize") or f.get("filesize_approx") or 0
                if audio_size:
                    break

        formats.append({
            "quality": "audio",
            "height": 0,
            "filesize": audio_size,
            "size_str": format_size(audio_size),
            "ext": "mp3"
        })

        return {"info": info, "formats": formats}

    except Exception as e:
        log.error(f"get_video_data error: {e}")
        return None


def download_video(url: str, quality: str, out_path: str) -> bool:
    try:
        if quality == "audio":
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "--no-warnings",
                "--extractor-args", "youtube:player_client=android",
                "-x", "--audio-format", "mp3",
                "--audio-quality", "0",
                "-o", out_path,
                url
            ]
        else:
            height = quality.replace("p", "")
            cmd = [
                "yt-dlp",
                "--no-playlist",
                "--no-warnings",
                "--extractor-args", "youtube:player_client=android",
                "-f", f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
                "--merge-output-format", "mp4",
                "-o", out_path,
                url
            ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return result.returncode == 0

    except subprocess.TimeoutExpired:
        log.error("Download timed out")
        return False
    except Exception as e:
        log.error(f"Download error: {e}")
        return False


def build_format_text(info: dict, formats: list) -> str:
    """Build YouTube Saver style message with sizes"""
    views = info.get("view_count", 0)
    if views:
        views_str = f"{views:,}"
    else:
        views_str = "N/A"

    text = (
        f"🎬 *{info['title'][:60]}*\n\n"
        f"👤 {info['uploader']}\n"
        f"⏱ {info['duration']}\n\n"
    )

    # Show each quality with size
    for fmt in formats:
        if fmt["quality"] == "audio":
            icon = "✅" if fmt["filesize"] else "🎵"
            text += f"{icon}  MP3:    {fmt['size_str']}\n"
        else:
            icon = "✅" if fmt["filesize"] else "🚀"
            text += f"{icon}  {fmt['quality']}:    {fmt['size_str']}\n"

    text += "\n⬇️ *Select quality to download:*"
    return text


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Video Downloader Bot*\n\n"
        "Send me any video link!\n\n"
        "✅ *Supported:*\n"
        "▶️ YouTube\n"
        "📸 Instagram\n"
        "📘 Facebook\n"
        "🐦 Twitter / X\n"
        "🎵 TikTok\n\n"
        "Just paste a link! 🚀",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "1️⃣ Copy any video link\n"
        "2️⃣ Paste it here\n"
        "3️⃣ See all qualities + file sizes\n"
        "4️⃣ Pick your quality\n"
        "5️⃣ Download! ✅\n\n"
        "📦 Max file: 50MB\n"
        "Files larger than 50MB cannot be sent via Telegram.",
        parse_mode="Markdown"
    )


async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not text.startswith("http"):
        await update.message.reply_text(
            "❌ Please send a valid video URL!\n\n"
            "Example:\n"
            "• https://youtube.com/watch?v=...\n"
            "• https://instagram.com/reel/...\n"
            "• https://tiktok.com/..."
        )
        return

    platform = detect_platform(text)
    if platform == "unknown":
        await update.message.reply_text(
            "❌ Unsupported platform!\n\n"
            "Supported: YouTube, Instagram,\nFacebook, Twitter, TikTok"
        )
        return

    status = await update.message.reply_text("⏳ Fetching video info...")

    try:
        video_data = await asyncio.to_thread(get_video_data, text)

        if not video_data or not video_data.get("formats"):
            await status.edit_text(
                "❌ Could not fetch video!\n\n"
                "• Private video?\n"
                "• Invalid URL?\n\n"
                "Please try another link."
            )
            return

        info    = video_data["info"]
        formats = video_data["formats"]

        # Save data
        ctx.user_data["url"]     = text
        ctx.user_data["formats"] = {f["quality"]: f for f in formats}

        # Build message text with sizes
        msg_text = build_format_text(info, formats)

        # Build quality buttons
        keyboard = []
        row = []
        for fmt in formats:
            if fmt["quality"] == "audio":
                label = "🎵 MP3"
            else:
                label = f"📹 {fmt['quality']}"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"dl_{fmt['quality']}"
            ))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ])

        # Send thumbnail + info
        thumbnail = info.get("thumbnail", "")
        if thumbnail:
            try:
                await status.delete()
                await update.message.reply_photo(
                    photo=thumbnail,
                    caption=msg_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
            except Exception:
                pass

        # Fallback without thumbnail
        await status.edit_text(
            msg_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        log.exception("URL handling failed")
        await status.edit_text(f"❌ Error: {e}")


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        ctx.user_data.clear()
        await query.message.delete()
        return

    if data.startswith("dl_"):
        quality = data[3:]
        url     = ctx.user_data.get("url")
        formats = ctx.user_data.get("formats", {})
        fmt     = formats.get(quality)

        if not url or not fmt:
            await query.message.reply_text(
                "❌ Session expired!\nPlease send the link again."
            )
            return

        label = "MP3" if quality == "audio" else quality

        # Check size warning
        filesize = fmt.get("filesize", 0)
        if filesize and filesize > 50 * 1024 * 1024:
            await query.answer(
                f"⚠️ File is {format_size(filesize)} — may be too large for Telegram!",
                show_alert=True
            )

        await query.message.reply_text(
            f"⏳ *Downloading {label}...*\n\n"
            f"Please wait... ⏱",
            parse_mode="Markdown"
        )

        with tempfile.TemporaryDirectory() as tmp:
            ext      = "mp3" if quality == "audio" else "mp4"
            out_path = str(Path(tmp) / f"video.{ext}")

            success = await asyncio.to_thread(
                download_video, url, quality, out_path
            )

            files = list(Path(tmp).glob("*"))
            if not files or not success:
                await query.message.reply_text(
                    "❌ Download failed!\n\n"
                    "Try another quality."
                )
                return

            actual_file = str(files[0])
            file_size   = Path(actual_file).stat().st_size

            if file_size > 50 * 1024 * 1024:
                await query.message.reply_text(
                    f"❌ File too large!\n"
                    f"Size: {format_size(file_size)} > 50MB\n\n"
                    "Please try a lower quality!"
                )
                return

            with open(actual_file, "rb") as f:
                if quality == "audio":
                    await ctx.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        caption=(
                            f"🎵 *{ctx.user_data.get('formats', {}).get('audio', {}).get('quality', 'MP3')}*\n"
                            f"📦 {format_size(file_size)}"
                        ),
                        parse_mode="Markdown"
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=(
                            f"✅ *{quality}*\n"
                            f"📦 {format_size(file_size)}"
                        ),
                        parse_mode="Markdown",
                        supports_streaming=True
                    )

            await query.message.reply_text("🎉 Done! Enjoy! 🍿")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    keep_alive()
    log.info("Starting Downloader Bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_url
    ))
    log.info("Downloader Bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
        
