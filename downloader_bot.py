import os
import logging
import asyncio
import threading
import subprocess
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
    return "🎬 Social Media Downloader Bot is Running! ✅"

@flask_app.route("/health")
def health():
    return "OK", 200

def keep_alive():
    t = threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT))
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


def get_video_formats(url: str) -> list:
    """Get all available formats using yt-dlp"""
    try:
        result = subprocess.run([
            "yt-dlp", "--list-formats", "--no-playlist", url
        ], capture_output=True, text=True, timeout=30)

        formats = []
        seen = set()

        for line in result.stdout.split("\n"):
            # Parse format lines
            parts = line.split()
            if len(parts) < 3:
                continue
            fmt_id = parts[0]
            if not fmt_id.isdigit() and fmt_id not in ["ba", "bv", "b"]:
                continue

            # Look for resolution info
            line_lower = line.lower()
            for quality in ["4320p", "2160p", "1440p", "1080p", "720p",
                            "480p", "360p", "240p", "144p"]:
                if quality in line_lower and quality not in seen:
                    seen.add(quality)
                    # Get file extension
                    ext = "mp4"
                    for e in ["mp4", "webm", "mkv"]:
                        if e in line_lower:
                            ext = e
                            break
                    formats.append({
                        "format_id": fmt_id,
                        "quality": quality,
                        "ext": ext,
                        "label": f"📹 {quality} ({ext.upper()})"
                    })

        # Add audio only option
        formats.append({
            "format_id": "bestaudio",
            "quality": "audio",
            "ext": "mp3",
            "label": "🎵 Audio Only (MP3)"
        })

        # Sort by quality
        order = ["4320p", "2160p", "1440p", "1080p",
                 "720p", "480p", "360p", "240p", "144p", "audio"]
        formats.sort(key=lambda x: order.index(x["quality"])
                     if x["quality"] in order else 99)

        return formats

    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        log.error(f"get_video_formats error: {e}")
        return []


def download_video(url: str, quality: str, out_path: str) -> bool:
    """Download video with yt-dlp"""
    try:
        if quality == "audio":
            cmd = [
                "yt-dlp",
                "--no-playlist",
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


def get_video_info(url: str) -> dict:
    """Get video title and thumbnail"""
    try:
        result = subprocess.run([
            "yt-dlp",
            "--no-playlist",
            "--print", "title",
            "--print", "duration_string",
            "--print", "uploader",
            url
        ], capture_output=True, text=True, timeout=30)

        lines = result.stdout.strip().split("\n")
        return {
            "title": lines[0] if len(lines) > 0 else "Unknown",
            "duration": lines[1] if len(lines) > 1 else "Unknown",
            "uploader": lines[2] if len(lines) > 2 else "Unknown"
        }
    except:
        return {"title": "Unknown", "duration": "Unknown", "uploader": "Unknown"}


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Social Media Video Downloader*\n\n"
        "Send me any video link and I will download it!\n\n"
        "✅ *Supported Platforms:*\n"
        "▶️ YouTube\n"
        "📸 Instagram\n"
        "📘 Facebook\n"
        "🐦 Twitter / X\n"
        "🎵 TikTok\n\n"
        "📺 *All available qualities shown:*\n"
        "144p • 240p • 360p • 480p\n"
        "720p • 1080p • 1440p • 2160p\n"
        "🎵 Audio only (MP3)\n\n"
        "Just paste any video link! 🚀",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "1️⃣ Copy any video link\n"
        "2️⃣ Paste it here\n"
        "3️⃣ Bot shows available qualities\n"
        "4️⃣ Pick your quality\n"
        "5️⃣ Download! ✅\n\n"
        "✅ *Supported:*\n"
        "• YouTube (all qualities)\n"
        "• Instagram (reels, posts)\n"
        "• Facebook (videos)\n"
        "• Twitter / X (videos)\n"
        "• TikTok (videos)\n\n"
        "📦 Max Telegram file size: 50MB",
        parse_mode="Markdown"
    )


async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Check if it's a URL
    if not text.startswith("http"):
        await update.message.reply_text(
            "❌ Please send a valid video URL!\n\n"
            "Example:\n"
            "• https://youtube.com/watch?v=...\n"
            "• https://instagram.com/reel/...\n"
            "• https://facebook.com/video/..."
        )
        return

    platform = detect_platform(text)
    if platform == "unknown":
        await update.message.reply_text(
            "❌ Unsupported platform!\n\n"
            "Supported: YouTube, Instagram, Facebook, Twitter, TikTok"
        )
        return

    platform_icons = {
        "youtube": "▶️ YouTube",
        "instagram": "📸 Instagram",
        "facebook": "📘 Facebook",
        "twitter": "🐦 Twitter/X",
        "tiktok": "🎵 TikTok"
    }

    status = await update.message.reply_text(
        f"⏳ Fetching {platform_icons[platform]} video info..."
    )

    try:
        # Get video info and formats
        info = await asyncio.to_thread(get_video_info, text)
        formats = await asyncio.to_thread(get_video_formats, text)

        if not formats:
            await status.edit_text(
                "❌ Could not fetch video formats!\n\n"
                "Possible reasons:\n"
                "• Private video\n"
                "• Invalid URL\n"
                "• Platform blocked\n\n"
                "Please try another link."
            )
            return

        # Save URL for download
        ctx.user_data["url"] = text
        ctx.user_data["platform"] = platform
        ctx.user_data["formats"] = {f["quality"]: f for f in formats}

        # Build quality buttons
        keyboard = []
        row = []
        for fmt in formats:
            row.append(InlineKeyboardButton(
                fmt["label"],
                callback_data=f"dl_{fmt['quality']}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ])

        await status.edit_text(
            f"✅ *Video Found!*\n\n"
            f"🎬 *{info['title'][:50]}*\n"
            f"👤 {info['uploader']}\n"
            f"⏱ Duration: {info['duration']}\n"
            f"📺 Platform: {platform_icons[platform]}\n\n"
            f"*Select quality to download:*",
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
        await query.message.edit_text("❌ Cancelled.")
        return

    if data.startswith("dl_"):
        quality = data[3:]
        url = ctx.user_data.get("url")
        formats = ctx.user_data.get("formats", {})
        fmt = formats.get(quality)

        if not url or not fmt:
            await query.message.reply_text(
                "❌ Session expired. Please send the link again."
            )
            return

        await query.message.edit_text(
            f"⏳ *Downloading {fmt['label']}...*\n\n"
            f"Please wait 1-3 minutes... ⏱",
            parse_mode="Markdown"
        )

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ext = "mp3" if quality == "audio" else "mp4"
            out_path = str(Path(tmp) / f"video.{ext}")

            success = await asyncio.to_thread(
                download_video, url, quality, out_path
            )

            # Find actual downloaded file
            files = list(Path(tmp).glob("*"))
            if not files:
                await query.message.reply_text(
                    "❌ Download failed!\n\n"
                    "Try another quality or link."
                )
                return

            actual_file = str(files[0])
            file_size = Path(actual_file).stat().st_size

            if file_size > 50 * 1024 * 1024:
                await query.message.reply_text(
                    f"❌ File too large for Telegram! ({file_size//(1024*1024)}MB > 50MB)\n\n"
                    "Please try a lower quality!"
                )
                return

            await query.message.reply_text(
                f"✅ Downloaded! Uploading... ⏫"
            )

            with open(actual_file, "rb") as f:
                if quality == "audio":
                    await ctx.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        caption=f"🎵 Audio downloaded!\n📦 Size: {file_size//(1024*1024):.1f}MB"
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=f"✅ *Downloaded!*\n📺 Quality: {quality}\n📦 Size: {file_size//(1024*1024):.1f}MB",
                        parse_mode="Markdown",
                        supports_streaming=True
                    )

            await query.message.reply_text("🎉 Done! Enjoy watching!")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    keep_alive()
    log.info("Starting Social Media Downloader Bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_url
    ))
    log.info("Downloader Bot polling...")
    app.run_polling(drop_pending_updates=True)


main()
  
