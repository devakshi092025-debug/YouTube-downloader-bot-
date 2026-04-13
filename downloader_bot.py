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
    return "🎬 Social Media Downloader Bot is Running! ✅"

@flask_app.route("/health")
def health():
    return "OK", 200

def keep_alive():
    t = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=PORT)
    )
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


def get_video_info(url: str) -> dict:
    try:
        result = subprocess.run([
            "yt-dlp",
            "--no-playlist",
            "-J",
            url
        ], capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
        duration_secs = data.get("duration", 0) or 0
        mins = int(duration_secs // 60)
        secs = int(duration_secs % 60)
        return {
            "title": data.get("title", "Unknown"),
            "duration": f"{mins}m {secs}s",
            "uploader": data.get("uploader", "Unknown")
        }
    except Exception as e:
        log.error(f"get_video_info error: {e}")
        return {
            "title": "Unknown",
            "duration": "Unknown",
            "uploader": "Unknown"
        }


def get_video_formats(url: str) -> list:
    try:
        result = subprocess.run([
            "yt-dlp",
            "--no-playlist",
            "-J",
            url
        ], capture_output=True, text=True, timeout=60)

        data = json.loads(result.stdout)
        formats = []
        seen_heights = set()

        for f in data.get("formats", []):
            height = f.get("height")
            vcodec = f.get("vcodec", "none")

            if not height or vcodec == "none":
                continue
            if height in seen_heights:
                continue

            seen_heights.add(height)
            quality = f"{height}p"
            formats.append({
                "format_id": str(f.get("format_id", "")),
                "quality": quality,
                "ext": "mp4",
                "label": f"📹 {quality}"
            })

        # Sort highest to lowest
        formats.sort(
            key=lambda x: int(x["quality"].replace("p", "")),
            reverse=True
        )

        # Add audio only
        formats.append({
            "format_id": "bestaudio",
            "quality": "audio",
            "ext": "mp3",
            "label": "🎵 Audio Only (MP3)"
        })

        return formats

    except Exception as e:
        log.error(f"get_video_formats error: {e}")
        return []


def download_video(url: str, quality: str, out_path: str) -> bool:
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


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Social Media Video Downloader*\n\n"
        "Send me any video link!\n\n"
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
        "youtube":   "▶️ YouTube",
        "instagram": "📸 Instagram",
        "facebook":  "📘 Facebook",
        "twitter":   "🐦 Twitter/X",
        "tiktok":    "🎵 TikTok"
    }

    status = await update.message.reply_text(
        f"⏳ Fetching {platform_icons[platform]} video info..."
    )

    try:
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

        ctx.user_data["url"] = text
        ctx.user_data["platform"] = platform
        ctx.user_data["formats"] = {f["quality"]: f for f in formats}

        # Build quality buttons 2 per row
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
            f"🎬 *{info['title'][:60]}*\n"
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

        with tempfile.TemporaryDirectory() as tmp:
            ext = "mp3" if quality == "audio" else "mp4"
            out_path = str(Path(tmp) / f"video.{ext}")

            success = await asyncio.to_thread(
                download_video, url, quality, out_path
            )

            # Find actual downloaded file
            files = list(Path(tmp).glob("*"))
            if not files or not success:
                await query.message.reply_text(
                    "❌ Download failed!\n\n"
                    "Try another quality or link."
                )
                return

            actual_file = str(files[0])
            file_size = Path(actual_file).stat().st_size

            if file_size > 50 * 1024 * 1024:
                await query.message.reply_text(
                    f"❌ File too large! "
                    f"({file_size//(1024*1024)}MB > 50MB)\n\n"
                    "Please try a lower quality!"
                )
                return

            await query.message.reply_text("✅ Downloaded! Uploading... ⏫")

            with open(actual_file, "rb") as f:
                if quality == "audio":
                    await ctx.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        caption=(
                            f"🎵 Audio downloaded!\n"
                            f"📦 Size: {file_size//(1024*1024):.1f}MB"
                        )
                    )
                else:
                    await ctx.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=(
                            f"✅ *Downloaded!*\n"
                            f"📺 Quality: {quality}\n"
                            f"📦 Size: {file_size//(1024*1024):.1f}MB"
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
                            
