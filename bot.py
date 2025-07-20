# bot.py – 3×3 Blindfold Trainer with global Stats & Exit
import os, random
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

# ───────── Config & Helpers ─────────
CORNER_LETTERS = list("ABCDEFGH")
EDGE_LETTERS   = list("IJKLMNOPQRST")
DUP_CHANCE     = 0.15

SHOW_MEMO, WAIT_MATH, WAIT_RECALL_EDGES, WAIT_RECALL_CORNERS = range(4)

# 🧠 to start, 🛑 to exit, 📊 for stats
MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🧠"), KeyboardButton("🛑"), KeyboardButton("📊")]],
    resize_keyboard=True,
)

def rint(a: int, b: int) -> int:
    return random.randint(a, b)

def next_len(n: int, maxn: int, minrnd: int) -> int:
    return n + 1 if n < maxn else rint(minrnd, maxn)

def gen_memo_set(letters: List[str], length: int) -> List[str]:
    memo: List[str] = []
    while len(memo) < length:
        L = random.choice(letters)
        if memo and (L == memo[0] or L == memo[-1]):
            continue
        if L in memo and random.random() > DUP_CHANCE:
            continue
        memo.append(L)
    return memo

def format_feedback(correct: List[str], guess: List[str]):
    c_txt, g_txt = [], []
    hits = 0
    for c, g in zip(correct, guess):
        if c == g:
            hits += 1
            c_txt.append(f"`{c.lower()}`")
            g_txt.append(f"`{g.lower()}`")
        else:
            c_txt.append(f"*{c}*")
            g_txt.append(f"*{(g or '·').upper()}*")
    return (
        f"*Correct*: {' '.join(c_txt)}\n"
        f"*Yours  *: {' '.join(g_txt)}\n"
        f"*Score  *: {hits}/{len(correct)}",
        hits,
    )

async def send_new(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Delete old bot msg and send a new one, store its ID."""
    prev = ctx.user_data.get("msg_id")
    if prev:
        try: await ctx.bot.delete_message(chat_id, prev)
        except: pass
    msg = await ctx.bot.send_message(chat_id, text, **kwargs)
    ctx.user_data["msg_id"] = msg.message_id
    return msg

# ───────── Handlers ─────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/start → welcome screen."""
    ctx.user_data.update(
        level=1,
        corner_len=3,
        edge_len=5,
        msg_id=None,
        correct_letters=0,
        attempted_letters=0,
        puzzles_solved=0,
    )
    await send_new(
        update.effective_chat.id,
        ctx,
        "👋 *Welcome to the 3×3 blind trainer*\n\n"
        "Press 🧠 to generate edge & corner strings,\n"
        "🛑 to exit, or 📊 for stats.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def go_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🧠 → show edges & corners with ‘Let’s go’ button."""
    chat = update.effective_chat.id
    cl = ctx.user_data["corner_len"]
    el = ctx.user_data["edge_len"]
    corners = gen_memo_set(CORNER_LETTERS, cl)
    edges   = gen_memo_set(EDGE_LETTERS, el)
    ctx.user_data.update(corners=corners, edges=edges)

    kb = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton("Let’s go", callback_data="letsgo")
    )
    await send_new(
        chat, ctx,
        f"*Level {ctx.user_data['level']}*\n"
        f"Edges ({el}): `{' '.join(edges)}`\n"
        f"Corners ({cl}): `{' '.join(corners)}`",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=kb,
    )
    return SHOW_MEMO

async def letsgo_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inline ‘Let’s go’ → distraction math."""
    await update.callback_query.answer()
    chat = update.effective_chat.id
    a, b = rint(1000, 9999), rint(1000, 9999)
    ctx.user_data["math_ans"] = a + b

    await send_new(
        chat, ctx,
        "🧮 *Distraction task*\n"
        f"`{a} + {b} = ?`\n\nSend the answer.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return WAIT_MATH

async def handle_math(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Math answer → verdict + prompt for edges."""
    chat = update.effective_chat.id
    try:
        val = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Send a valid number.")
        return WAIT_MATH

    ok = val == ctx.user_data["math_ans"]
    verdict = "✅ Correct!" if ok else f"❌ Incorrect (was {ctx.user_data['math_ans']})"
    await send_new(
        chat, ctx,
        verdict + "\n\nNow send the *edges* string.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return WAIT_RECALL_EDGES

async def handle_edges(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Edges recall → feedback + prompt corners."""
    chat = update.effective_chat.id
    edges = ctx.user_data["edges"]
    guess = update.message.text.strip().upper()
    if len(guess) != len(edges):
        await update.message.reply_text(f"Need {len(edges)} letters for edges.")
        return WAIT_RECALL_EDGES

    fb, hits = format_feedback(edges, list(guess))
    ctx.user_data["correct_letters"]   += hits
    ctx.user_data["attempted_letters"] += len(edges)
    ctx.user_data["last_edge_hits"]     = hits

    await send_new(
        chat, ctx,
        fb + "\n\nNow send the *corners* string.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return WAIT_RECALL_CORNERS

async def handle_corners(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Corners recall → final feedback + stats + back to main."""
    chat = update.effective_chat.id
    corners = ctx.user_data["corners"]
    guess   = update.message.text.strip().upper()
    if len(guess) != len(corners):
        await update.message.reply_text(f"Need {len(corners)} letters for corners.")
        return WAIT_RECALL_CORNERS

    fb, hits = format_feedback(corners, list(guess))
    ctx.user_data["correct_letters"]   += hits
    ctx.user_data["attempted_letters"] += len(corners)

    # full solve = perfect edges + perfect corners
    if (hits == len(corners)
        and ctx.user_data.get("last_edge_hits",0) == len(ctx.user_data["edges"])):
        ctx.user_data["puzzles_solved"] += 1

    acc = ctx.user_data["correct_letters"] * 100 // ctx.user_data["attempted_letters"]

    await send_new(
        chat, ctx,
        fb
        + f"\n\n🎯 *{acc}%* accuracy\n"
        f"🎉 *{ctx.user_data['puzzles_solved']}* full solves\n\n"
        "Press 🧠 for next, 🛑 to quit, 📊 for stats.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )

    ctx.user_data["level"]      += 1
    ctx.user_data["corner_len"] = next_len(ctx.user_data["corner_len"], len(CORNER_LETTERS), 3)
    ctx.user_data["edge_len"]   = next_len(ctx.user_data["edge_len"],   len(EDGE_LETTERS),   5)
    return ConversationHandler.END

async def exit_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """🛑 → always say goodbye."""
    await send_new(
        update.effective_chat.id, ctx,
        "👋 *Goodbye!* Come back anytime with 🧠.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )
    return ConversationHandler.END

async def stats_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """📊 → always show stats."""
    solved = ctx.user_data.get("puzzles_solved", 0)
    await send_new(
        update.effective_chat.id, ctx,
        f"📊 You’ve full‑solved *{solved}* cubes.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=MAIN_KB,
    )

# ───────── Main ─────────
def main():
    TOKEN = os.getenv("BOT_TOKEN") or exit("Set BOT_TOKEN")
    app = (
        Application.builder()
        .token(TOKEN)
        .persistence(PicklePersistence("memo3x3_data"))
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start),
                      MessageHandler(filters.Regex("^🧠$"), go_handler)],
        states={
            SHOW_MEMO: [
                CallbackQueryHandler(letsgo_cb, pattern="^letsgo$"),
            ],
            WAIT_MATH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_math),
            ],
            WAIT_RECALL_EDGES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edges),
            ],
            WAIT_RECALL_CORNERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_corners),
            ],
        },
        fallbacks=[],
        name="memo3x3_conv",
        persistent=True,
    )

    # Global handlers for Exit & Stats
    app.add_handler(MessageHandler(filters.Regex("^🛑$"), exit_handler))
    app.add_handler(MessageHandler(filters.Regex("^📊$"), stats_handler))

    app.add_handler(conv)

    print("Bot running… Ctrl‑C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
