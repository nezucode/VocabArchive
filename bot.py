import os
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.ext import CommandHandler
import requests
from database import Database

TOKEN = "7915920710:AAFNhXKxcGoriiRt2Bj1BKLVtcEI3c_y-ow"

db = Database()
pending_vocab = {}

def fetch_vocab(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}"
    response = requests.get(url)
    
    if response.status_code != 200:
        return None
    
    data = response.json()[0]
    meanings = data.get("meanings", [])
    
    definition = ""
    examples = []
    part_of_speech = ""
    synonyms = []

    if meanings:
        first_meaning = meanings[0]
        part_of_speech = first_meaning.get("partOfSpeech", "")
        defs = first_meaning.get("definitions", [])
        if defs:
            definition = defs[0].get("definition", "")
            for d in defs:
                ex = d.get("example", "")
                if ex and len(examples) < 3:
                    examples.append(ex)

    for meaning in meanings:
        for syn in meaning.get("synonyms", []):
            if syn not in synonyms:
                synonyms.append(syn)
        if len(synonyms) >= 5:
            break
    print(data)
    return {
        "word": data.get("word", word),
        "phonetic": data.get("phonetic", ""),
        "part_of_speech": part_of_speech,
        "definition": definition,
        "synonyms": synonyms[:5],
        "examples": examples
    }

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = update.message.text.strip()
    vocab = fetch_vocab(word)

    if not vocab:
        await update.message.reply_text(f"❌ Can't find '{word}'. Check the spelling!")
        return

    synonyms = ", ".join(vocab["synonyms"]) if vocab["synonyms"] else "—"
    examples = "\n".join([f"• {ex}" for ex in vocab["examples"]]) if vocab["examples"] else "• —"

    msg = (
        f"📖 *{vocab['word'].upper()}* ({vocab['part_of_speech']})\n"
        f"{vocab['phonetic']}\n\n"
        f"*Definition:*\n{vocab['definition']}\n\n"
        f"*Synonyms:* {synonyms}\n\n"
        f"*Examples:*\n{examples}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to VocabArchive!\n\n"
        "• Type any English word → get definition, synonyms & examples\n"
        "• /list — see all your saved words\n"
        "• /delete [word] — remove a word\n\n"
        "Start by typing any word! 🚀"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # If waiting for a sentence
    if context.user_data.get("waiting_for_sentence"):
        pending_word = context.user_data.get("pending_word")
        vocab_data = pending_vocab.get(user_id)

        if pending_word.lower() not in text.lower():
            await update.message.reply_text(
                f"⚠️ Your sentence doesn't contain the word '{pending_word}'. Try again!\n\n"
                f"Or type /skip to skip saving."
            )
            return

        examples_str = "|||".join(vocab_data["examples"])
        synonyms_str = ",".join(vocab_data["synonyms"])
        db.save_vocab(user_id, vocab_data["word"], vocab_data["definition"], synonyms_str, examples_str, text)

        context.user_data["waiting_for_sentence"] = False
        context.user_data["pending_word"] = None
        pending_vocab.pop(user_id, None)

        await update.message.reply_text(
            f"✅ *\"{vocab_data['word']}\"* saved!\n\n"
            f"Your sentence: _{text}_\n\n",
            f"/list — see all your saved words\n\n"
            f"/delete [word] — remove a word\n\n",
            parse_mode="Markdown"
        )
        return

    # Check if already saved
    existing = db.get_vocab(user_id, text)
    if existing:
        await update.message.reply_text(
            f"📖 *{existing[0].upper()}*\n\n"
            f"*Definition:* {existing[1]}\n\n"
            f"*Synonyms:* {existing[2] or '—'}\n\n"
            f"*Your sentence:* _{existing[4] or '—'}_",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            f"✅ *\"{text}\"* is already in your vocab list!\n\n"
            f"• /list — see all your saved words\n\n"
            "• /delete [word] — remove a word\n\n",
            parse_mode="Markdown"
        )
        return

    # Fetch from API
    vocab = fetch_vocab(text)
    if not vocab:
        await update.message.reply_text(f"❌ Can't find '{text}'. Check the spelling!")
        return

    synonyms = ", ".join(vocab["synonyms"]) if vocab["synonyms"] else "—"
    examples = "\n".join([f"• {ex}" for ex in vocab["examples"]]) if vocab["examples"] else "• —"

    msg = (
        f"📖 *{vocab['word'].upper()}* ({vocab['part_of_speech']})\n"
        f"{vocab['phonetic']}\n\n"
        f"*Definition:*\n{vocab['definition']}\n\n"
        f"*Synonyms:* {synonyms}\n\n"
        f"*Examples:*\n{examples}"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")

    # Store pending vocab
    pending_vocab[user_id] = vocab
    context.user_data["waiting_for_sentence"] = True
    context.user_data["pending_word"] = vocab["word"]

    await update.message.reply_text(
        f"✏️ *Want to save \"{vocab['word']}\"?*\n\n"
        f"Write a sentence using this word to save it!\n\n"
        f"_Type /skip to skip._",
        parse_mode="Markdown"
    )

async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending_vocab.pop(user_id, None)
    context.user_data["waiting_for_sentence"] = False
    context.user_data["pending_word"] = None
    await update.message.reply_text("⏭️ Skipped! Type another word to look up.")

async def list_vocab(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /delete [word]\nExample: /delete ephemeral")
        return

    word = context.args[0].lower()
    deleted = db.delete_vocab(user_id, word)
    if deleted:
        await update.message.reply_text(f"🗑️ *\"{word}\"* removed from your list.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ *\"{word}\"* not found in your list.", parse_mode="Markdown")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("skip", skip))
app.add_handler(CommandHandler("list", list_vocab))
app.add_handler(CommandHandler("delete", delete_vocab))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot is running...")
app.run_polling()
