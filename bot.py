import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from database import Database
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()

WAITING_SENTENCE = 1
pending_vocab = {}  # store vocab data temporarily per user

def fetch_vocab(word: str):
    """Fetch word definition from Free Dictionary API"""
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}"
    response = requests.get(url)
    if response.status_code != 200:
        return None

    data = response.json()[0]
    word_text = data.get("word", word)
    phonetic = data.get("phonetic", "")

    # Get first meaning
    meanings = data.get("meanings", [])
    definition = ""
    examples = []
    part_of_speech = ""

    if meanings:
        first_meaning = meanings[0]
        part_of_speech = first_meaning.get("partOfSpeech", "")
        defs = first_meaning.get("definitions", [])
        if defs:
            definition = defs[0].get("definition", "")
            # Collect examples from all definitions
            for d in defs:
                ex = d.get("example", "")
                if ex and len(examples) < 3:
                    examples.append(ex)

    # Get synonyms
    synonyms = []
    for meaning in meanings:
        for syn in meaning.get("synonyms", []):
            if syn not in synonyms:
                synonyms.append(syn)
        for d in meaning.get("definitions", []):
            for syn in d.get("synonyms", []):
                if syn not in synonyms:
                    synonyms.append(syn)
        if len(synonyms) >= 5:
            break

    return {
        "word": word_text,
        "phonetic": phonetic,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "examples": examples[:3],
        "synonyms": synonyms[:5]
    }

def format_bubble1(vocab_data: dict) -> str:
    """Format the main vocab bubble"""
    word = vocab_data["word"].upper()
    phonetic = f"\n/{vocab_data['phonetic']}/" if vocab_data["phonetic"] else ""
    pos = f" *({vocab_data['part_of_speech']})*" if vocab_data["part_of_speech"] else ""
    definition = vocab_data["definition"]
    synonyms = ", ".join(vocab_data["synonyms"]) if vocab_data["synonyms"] else "—"
    
    examples_text = ""
    for ex in vocab_data["examples"]:
        examples_text += f"• _{ex}_\n"
    if not examples_text:
        examples_text = "• —\n"

    return (
        f"📖 *{word}*{pos}{phonetic}\n\n"
        f"*Definition:*\n{definition}\n\n"
        f"*Synonyms:* {synonyms}\n\n"
        f"*Examples:*\n{examples_text}"
    )

def format_bubble2(user_id: int) -> str:
    """Format the vocab list bubble"""
    vocab_list = db.get_all_vocab(user_id)
    if not vocab_list:
        return "📚 *Your Vocab List*\n\nNo words saved yet\\. Start saving to build your list\\!"

    count = len(vocab_list)
    lines = f"📚 *Your Vocab List* \\({count} words\\)\n\n"
    for word, definition, synonyms in vocab_list[-10:][::-1]:  # show last 10, newest first
        short_def = definition[:50] + "..." if len(definition) > 50 else definition
        syn_preview = synonyms.split(",")[0].strip() if synonyms else ""
        syn_text = f" • _{syn_preview}_" if syn_preview else ""
        lines += f"• *{word}*{syn_text}\n  {short_def}\n\n"

    if count > 10:
        lines += f"_...and {count - 10} more. Use /list to see all._"

    return lines

async def lookup_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle word lookup"""
    user_id = update.effective_user.id
    word = update.message.text.strip().lower()

    # Skip if it looks like a command or sentence
    if word.startswith("/") or len(word.split()) > 2:
        return

    # Check if already in database
    existing = db.get_vocab(user_id, word)
    if existing:
        vocab_data = {
            "word": existing[0],
            "phonetic": "",
            "part_of_speech": "",
            "definition": existing[1],
            "examples": existing[3].split("|||") if existing[3] else [],
            "synonyms": existing[2].split(",") if existing[2] else []
        }
        await update.message.reply_text(
            format_bubble1(vocab_data),
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            format_bubble2(user_id),
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ *\"{word}\"* is already in your vocab list\\!\n\n_Your sentence:_ {existing[4] if existing[4] else '—'}",
            parse_mode="MarkdownV2"
        )
        return

    # Fetch from API
    await update.message.reply_text(f"🔍 Looking up *{word}*...", parse_mode="Markdown")
    vocab_data = fetch_vocab(word)

    if not vocab_data:
        await update.message.reply_text(
            f"❌ Sorry, couldn't find *{word}*. Check the spelling and try again!",
            parse_mode="Markdown"
        )
        return

    # Send bubble 1
    await update.message.reply_text(format_bubble1(vocab_data), parse_mode="Markdown")

    # Send bubble 2
    await update.message.reply_text(format_bubble2(user_id), parse_mode="Markdown")

    # Store pending vocab
    pending_vocab[user_id] = vocab_data

    # Send bubble 3 - prompt for sentence
    await update.message.reply_text(
        f"✏️ *Want to save \"{vocab_data['word']}\"?*\n\n"
        f"Write a sentence using this word to save it to your list\\!\n\n"
        f"_Type /skip to skip saving this word\\._",
        parse_mode="MarkdownV2"
    )

    context.user_data["waiting_for_sentence"] = True
    context.user_data["pending_word"] = word

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # If waiting for a sentence
    if context.user_data.get("waiting_for_sentence"):
        pending_word = context.user_data.get("pending_word")
        vocab_data = pending_vocab.get(user_id)

        if vocab_data and pending_word:
            # Check if vocab word appears in sentence (basic validation)
            if pending_word.lower() not in text.lower():
                await update.message.reply_text(
                    f"⚠️ Your sentence doesn't seem to contain the word *\"{pending_word}\"*\\. Try again\\!\n\n"
                    f"_Or type /skip to skip saving\\._",
                    parse_mode="MarkdownV2"
                )
                return

            # Save to database
            examples_str = "|||".join(vocab_data["examples"])
            synonyms_str = ",".join(vocab_data["synonyms"])
            db.save_vocab(user_id, vocab_data["word"], vocab_data["definition"], synonyms_str, examples_str, text)

            context.user_data["waiting_for_sentence"] = False
            context.user_data["pending_word"] = None
            pending_vocab.pop(user_id, None)

            await update.message.reply_text(
                f"✅ *\"{vocab_data['word']}\"* saved to your vocab list\\!\n\n"
                f"_Your sentence:_ {text}",
                parse_mode="MarkdownV2"
            )
        return

    # Otherwise treat as word lookup
    await lookup_word(update, context)

async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip saving the current word"""
    user_id = update.effective_user.id
    pending_vocab.pop(user_id, None)
    context.user_data["waiting_for_sentence"] = False
    context.user_data["pending_word"] = None
    await update.message.reply_text("⏭️ Skipped. Type another word to look up!")

async def list_vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full vocab list"""
    user_id = update.effective_user.id
    vocab_list = db.get_all_vocab(user_id)

    if not vocab_list:
        await update.message.reply_text("📚 Your vocab list is empty. Start looking up words!")
        return

    text = f"📚 *Your Vocab List* ({len(vocab_list)} words)\n\n"
    for word, definition, synonyms in vocab_list:
        short_def = definition[:60] + "..." if len(definition) > 60 else definition
        syn_preview = synonyms.split(",")[0].strip() if synonyms else ""
        syn_text = f" • _{syn_preview}_" if syn_preview else ""
        text += f"• *{word}*{syn_text}\n  {short_def}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def delete_vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a word from vocab list"""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /delete [word]\nExample: /delete ephemeral")
        return

    word = context.args[0].lower()
    deleted = db.delete_vocab(user_id, word)
    if deleted:
        await update.message.reply_text(f"🗑️ *\"{word}\"* has been removed from your list.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ *\"{word}\"* not found in your list.", parse_mode="Markdown")

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a quiz question"""
    user_id = update.effective_user.id
    quiz_data = db.get_quiz_words(user_id)

    if not quiz_data or len(quiz_data) < 2:
        await update.message.reply_text(
            "📝 You need at least 2 saved words to start a quiz\\! Keep looking up words\\.",
            parse_mode="MarkdownV2"
        )
        return

    import random
    correct = quiz_data[0]
    wrong_options = random.sample(quiz_data[1:], min(3, len(quiz_data) - 1))

    word = correct[0]
    correct_def = correct[1]

    options = [correct_def] + [w[1] for w in wrong_options]
    random.shuffle(options)
    correct_index = options.index(correct_def)

    letters = ["A", "B", "C", "D"]
    options_text = "\n".join([f"{letters[i]}\\) {opt[:60]}{'...' if len(opt) > 60 else ''}" for i, opt in enumerate(options)])

    context.user_data["quiz_answer"] = correct_index
    context.user_data["quiz_word"] = word
    context.user_data["waiting_for_quiz"] = True

    await update.message.reply_text(
        f"🧠 *Quiz Time\\!*\n\nWhat does *\"{word.upper()}\"* mean?\n\n{options_text}\n\n_Reply with A, B, C, or D_",
        parse_mode="MarkdownV2"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to your Vocab Bot!*\n\n"
        "Here's how to use me:\n\n"
        "• Type any English word → get definition, synonyms & examples\n"
        "• Write a sentence using the word → save it to your list\n"
        "• /list — see all your saved words\n"
        "• /quiz — test yourself\n"
        "• /delete [word] — remove a word\n\n"
        "_Start by typing any word you want to learn!_ 🚀",
        parse_mode="Markdown"
    )

def main():
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_vocab))
    app.add_handler(CommandHandler("delete", delete_vocab))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()