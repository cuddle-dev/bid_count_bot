from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from datetime import datetime
import pytz
import os
import logging
from telegram.error import Conflict
import atexit

# Timezone (Hungary)
tz = pytz.timezone("Europe/Budapest")

# Store user data
user_data = {}
work_session = {"active": False, "start": None, "count_total": 0, "count_by_user": {}}

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def get_today():
    return datetime.now(tz).strftime("%Y-%m-%d")

# Count messages
async def count_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.from_user is None:
        return

    user = update.message.from_user
    user_id = user.id
    name = user.username or user.first_name
    today = get_today()

    # Global session counter (between /start and /finish)
    if work_session["active"]:
        work_session["count_total"] += 1
        work_session["count_by_user"][user_id] = work_session["count_by_user"].get(user_id, 0) + 1

    if user_id not in user_data:
        user_data[user_id] = {
            "name": name,
            "count": 1,
            "date": today
        }
        return

    if user_data[user_id]["date"] != today:
        user_data[user_id]["count"] = 1
        user_data[user_id]["date"] = today
    else:
        user_data[user_id]["count"] += 1

def _format_duration(start: datetime, end: datetime) -> str:
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        seconds = 0
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

# Command: /start (begin session)
async def start_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.from_user is None:
        return
    now = datetime.now(tz)
    work_session["active"] = True
    work_session["start"] = now
    work_session["count_total"] = 0
    work_session["count_by_user"] = {}
    await update.message.reply_text(
        f"Started. Counting job applications from now ({now.strftime('%H:%M:%S')})."
    )

# Command: /finish (end session)
async def finish_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.from_user is None:
        return
    if not work_session["active"] or not work_session["start"]:
        await update.message.reply_text("No active jobs you applied today.")
        return
    now = datetime.now(tz)
    count = work_session["count_total"]
    work_session["active"] = False
    work_session["start"] = None
    await update.message.reply_text(
        f"Finished. Total applied jobs: {count}"
    )

# Command: /count (session count)
async def count_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.message.from_user is None:
        return
    user_id = update.message.from_user.id
    if not work_session["active"] or not work_session["start"]:
        await update.message.reply_text("No active jobs you applied today.")
        return
    now = datetime.now(tz)
    duration = _format_duration(work_session["start"], now)
    mine = work_session["count_by_user"].get(user_id, 0)
    await update.message.reply_text(f"You applied {mine} jobs today.")

# Command: /leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not work_session["start"]:
        await update.message.reply_text("No session yet. Send /start first.")
        return

    counts = work_session["count_by_user"]
    if not counts:
        await update.message.reply_text("No job applications counted since /start yet.")
        return

    sorted_users = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    now = datetime.now(tz)
    duration = _format_duration(work_session["start"], now)

    text = f"🏆 Leaderboard today.\n\n"
    for i, (uid, c) in enumerate(sorted_users[:10], 1):
        name = user_data.get(uid, {}).get("name", str(uid))
        text += f"{i}. {name} — {c} jobs\n"

    await update.message.reply_text(text)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    logger.exception("Unhandled error while processing update", exc_info=err)
    if isinstance(err, Conflict):
        logger.error(
            "Telegram Conflict: another instance is polling this bot token. "
            "Stop the other instance (or switch to webhooks). Shutting down."
        )
        if context.application:
            await context.application.stop()

# MAIN
def acquire_single_instance_lockfile() -> int | None:
    """
    Prevent running multiple local instances (best-effort).
    This does NOT stop conflicts caused by other machines/services.
    """
    lock_path = os.path.join(os.path.dirname(__file__), ".bot.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        return None

    def _cleanup() -> None:
        try:
            os.close(fd)
        finally:
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass

    atexit.register(_cleanup)
    return fd

_lock_fd = acquire_single_instance_lockfile()
if _lock_fd is None:
    raise SystemExit(
        "Another local bot.py instance seems to be running (lock file exists). "
        "Stop it first, or delete .bot.lock if you're sure nothing is running."
    )

app = ApplicationBuilder().token("8506074805:AAELRJ3fSXemSz5-2LyMQqUfwVIA6DgKFaQ").build()

app.add_handler(CommandHandler("start", start_work))
app.add_handler(CommandHandler("finish", finish_work))
app.add_handler(CommandHandler("count", count_session))
app.add_handler(CommandHandler("leaderboard", leaderboard))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, count_messages))
app.add_error_handler(on_error)

print("Bot is running...")
app.run_polling()
