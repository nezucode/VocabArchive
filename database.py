import sqlite3
import random
from datetime import datetime

class Database:
    def __init__(self, db_path="vocab.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vocab (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    word TEXT NOT NULL,
                    definition TEXT,
                    synonyms TEXT,
                    examples TEXT,
                    user_sentence TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_quizzed TIMESTAMP,
                    UNIQUE(user_id, word)
                )
            """)
            conn.commit()

    def save_vocab(self, user_id, word, definition, synonyms, examples, user_sentence):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO vocab 
                (user_id, word, definition, synonyms, examples, user_sentence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, word.lower(), definition, synonyms, examples, user_sentence))
            conn.commit()

    def get_vocab(self, user_id, word):
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT word, definition, synonyms, examples, user_sentence
                FROM vocab WHERE user_id = ? AND word = ?
            """, (user_id, word.lower()))
            return cursor.fetchone()

    def get_all_vocab(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT word, definition, synonyms
                FROM vocab WHERE user_id = ?
                ORDER BY created_at ASC
            """, (user_id,))
            return cursor.fetchall()

    def delete_vocab(self, user_id, word):
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM vocab WHERE user_id = ? AND word = ?
            """, (user_id, word.lower()))
            conn.commit()
            return cursor.rowcount > 0

    def get_quiz_words(self, user_id):
        """Get words for quiz, prioritizing least recently quizzed"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT word, definition FROM vocab 
                WHERE user_id = ?
                ORDER BY last_quizzed ASC NULLS FIRST
                LIMIT 10
            """, (user_id,))
            words = cursor.fetchall()
            if words:
                random.shuffle(words)
            return words

    def update_last_quizzed(self, user_id, word):
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE vocab SET last_quizzed = CURRENT_TIMESTAMP
                WHERE user_id = ? AND word = ?
            """, (user_id, word.lower()))
            conn.commit()