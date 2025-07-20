# bot.py – Blindfold Memo Trainer with emoji buttons
import os
import random
from typing import List

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    constants,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

# ────────────── Config & Helpers ──────────────
EXCLUDED = {"A", "R", "E"}
LETTERS = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWX" if c not in EXCLUDED]
DUP_CHANCE = 0.15

SHOW_MEMO, WAIT_MATH, WAIT_RECALL = range(3)

# Emoji buttons: 🧠 to start/go, 🛑 to exit, 📊 for stats
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🧠"), KeyboardButton("🛑"), KeyboardButton("📊")]
    ],
    resize_keyboard=True,
)

def rand_int(a: int, b: int) -> int:
    return random.randint(a, b)

def next_length(n: int) -> int:
    return n + 1 if n < 9 else rand_int(7, 9)

def gen_memo(k: int) -> List[str]:
    memo: List[str] = []
    while len(memo) < k:
        L = random.choice(LETTERS)
        if (
            not memo
            or (
                L != memo[0]
                and L != memo[-1]
                and (L not in memo or random.random() < DUP_CHANCE)
            )
        ):
            memo.append(L)
    return memo

def format_feedback(correct: List[str], guess: List[str]):
    corr_txt, guess_txt = [], []
    score = 0
    for c, g in zip(correct, guess):
        if c == g:
            score += 1
            corr_txt.append(f"`{c.lower()}`")
            guess_txt.append(f"`{g.lower()}`")
        else:
            corr_txt.append(f"*{c}*")
            guess_txt.append(f"*{(g or '·').upper()}*")
    text = (
        f"*Correct*: {' '.join(corr_txt)}\n"
        f"*Yours  *: {' '.join(guess_txt)}\n"
        f"*Score  *: {score}/{len(correct)}"
    )
    return text, score

async def send_new(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Delete previous bot message, send a fresh one, store its ID."""
    old = ctx.user_data.get("msg_id")
    if old:
        try:
            await ctx.bot.delete_message(chat_id, old)
        except:
            pass
    msg = await ctx.bot.send_message(chat_id, text, **kwargs)
    ctx.user_data["msg_id"] = msg.message_id
    return msg

# ────────────── Handlers ──────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Welcome screen with emoji buttons."""
    # reset per-round state (keep stats)
    ctx.user_data.update(
        level=1,
        length=5,
        msg_id=None,
        correct_letters=0,
        attempted_letters=0,
        puzzles_solved=0,
    )
    await send_new(
        update.effective_chat.id,
        ctx,
        "👋 *Welcome to the blind trainer*\n\n"
        "Press 🧠 to begin, 🛑 to quit, or 📊 for stats.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def go_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🧠 → show memo with inline “Let’s go”."""
    chat = update.effective_chat.id
    length = ctx.user_data.get("length", 5)
    memo = gen_memo(length)
    ctx.user_data["memo"] = memo

    kb_inline = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("Let’s go", callback_data="letsgo")
    )

    await send_new(
        chat,
        ctx,
        f"*Level {ctx.user_data.get('level',1)}*  (len {length})\n"
        "`" + " ".join(memo) + "`",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=kb_inline,
    )
    return SHOW_MEMO

async def letsgo_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inline “Let’s go” → distraction task."""
    await update.callback_query.answer()
    chat = update.effective_chat.id
    a, b = rand_int(1000, 9999), rand_int(1000, 9999)
    ctx.user_data["math_ans"] = a + b

    await send_new(
        chat,
        ctx,
        "🧮 *Distraction task*\n"
        f"`{a} + {b} = ?`\n\nSend the answer.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return WAIT_MATH

async def handle_math(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User answers math → verdict + prompt for memo."""
    chat = update.effective_chat.id
    txt = update.message.text.strip()
    try:
        val = int(txt)
    except ValueError:
        await update.message.reply_text("❌ Please send a number.")
        return WAIT_MATH

    correct = ctx.user_data["math_ans"]
    verdict = "✅ Correct!" if val == correct else f"❌ Incorrect (was {correct})"

    await send_new(
        chat,
        ctx,
        verdict + "\n\nNow send the memo string (letters only).",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return WAIT_RECALL

async def handle_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User sends memo → show feedback + stats + back to emoji keyboard."""
    chat = update.effective_chat.id
    memo = ctx.user_data["memo"]
    guess = update.message.text.strip().upper()

    if len(guess) != len(memo):
        await update.message.reply_text(f"Need exactly {len(memo)} letters.")
        return WAIT_RECALL

    fb_text, score = format_feedback(memo, list(guess))
    ctx.user_data["correct_letters"] += score
    ctx.user_data["attempted_letters"] += len(memo)
    if score == len(memo):
        ctx.user_data["puzzles_solved"] += 1

    acc = (
        ctx.user_data["correct_letters"] * 100
        // ctx.user_data["attempted_letters"]
    )

    await send_new(
        chat,
        ctx,
        fb_text
        + f"\n\n🎯 *{acc}%* accuracy\n"
        f"🎉 *{ctx.user_data['puzzles_solved']}* perfect solves\n\n"
        "Press 🧠 to play again, 🛑 to quit, or 📊 for stats.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )

    ctx.user_data["level"] += 1
    ctx.user_data["length"] = next_length(ctx.user_data["length"])
    return ConversationHandler.END

async def exit_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🛑 → goodbye message."""
    await send_new(
        update.effective_chat.id,
        ctx,
        "👋 *Goodbye!* Thanks for training. Press 🧠 to start over anytime.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def stats_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """📊 → show total perfect solves."""
    solved = ctx.user_data.get("puzzles_solved", 0)
    await send_new(
        update.effective_chat.id,
        ctx,
        f"📊 You’ve perfectly solved *{solved}* memo(s).",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )

# ────────────── Main ──────────────
def main():
    token = os.getenv("BOT_TOKEN") or exit("Set BOT_TOKEN")
    app = (
        Application.builder()
        .token(token)
        .persistence(PicklePersistence("memo_data"))
        .build()
    )

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧠$"), go_handler)],
        states={
            SHOW_MEMO: [
                CallbackQueryHandler(letsgo_cb, pattern="^letsgo$"),
                MessageHandler(filters.Regex("^🛑$"), exit_handler),
            ],
            WAIT_MATH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_math),
                MessageHandler(filters.Regex("^🛑$"), exit_handler),
            ],
            WAIT_RECALL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recall),
                MessageHandler(filters.Regex("^🛑$"), exit_handler),
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^🛑$"), exit_handler)],
        name="memo_conv",
        persistent=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^📊$"), stats_handler))
    app.add_handler(CommandHandler("stats", stats_handler))

    print("Bot running… Ctrl‑C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
