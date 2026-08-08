"""
Simple Auto Backup System - Sends database to owner every 23 hours
"""

import os
import time
import shutil
import logging
from datetime import datetime
import threading
import telebot

logger = logging.getLogger(__name__)

# ============ CONFIG ============
BACKUP_INTERVAL = 23 * 60 * 60  # 23 hours
BACKUP_FOLDER = "backups"

class BackupManager:
    def __init__(self, bot_token, owner_ids, db_file='osint_bot.db'):
        self.bot_token = bot_token
        self.owner_ids = owner_ids
        self.db_file = db_file
        self.bot = None
        self.running = True
        
        # Create backup folder
        if not os.path.exists(BACKUP_FOLDER):
            os.makedirs(BACKUP_FOLDER)
        
        logger.info("✅ Backup Manager initialized")
    
    def start(self):
        """Start backup thread"""
        try:
            self.bot = telebot.TeleBot(self.bot_token, parse_mode='HTML')
            logger.info("✅ Backup bot initialized")
        except Exception as e:
            logger.error(f"❌ Backup bot error: {e}")
            return
        
        # Start backup thread
        backup_thread = threading.Thread(target=self._backup_loop, daemon=True)
        backup_thread.start()
        logger.info(f"🔄 Auto backup every {BACKUP_INTERVAL//3600} hours")
    
    def _backup_loop(self):
        """Main backup loop"""
        # First backup after 5 minutes
        time.sleep(300)
        
        while self.running:
            try:
                self._send_backup()
                logger.info(f"✅ Backup sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                logger.error(f"❌ Backup failed: {e}")
            
            # Wait 23 hours
            for _ in range(BACKUP_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)
    
    def _send_backup(self):
        """Create and send backup to owners"""
        try:
            if not os.path.exists(self.db_file):
                logger.warning(f"⚠️ Database not found: {self.db_file}")
                return
            
            # Create backup copy
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_name = f"backup_{timestamp}.db"
            backup_path = os.path.join(BACKUP_FOLDER, backup_name)
            
            shutil.copy2(self.db_file, backup_path)
            
            # Get file size
            size_mb = os.path.getsize(backup_path) / (1024 * 1024)
            
            # Send to all owners
            for owner_id in self.owner_ids:
                try:
                    with open(backup_path, 'rb') as f:
                        self.bot.send_document(
                            owner_id,
                            f,
                            caption=f"""
📦 <b>DATABASE BACKUP</b>
━━━━━━━━━━━━━━━━━━━━━━━━

📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📊 Size: {size_mb:.2f} MB

💡 Save this file for future use.
"""
                        )
                    logger.info(f"✅ Backup sent to owner {owner_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send to {owner_id}: {e}")
            
            # Delete old backups (keep last 3)
            self._clean_old_backups()
            
        except Exception as e:
            logger.error(f"❌ Backup error: {e}")
    
    def _clean_old_backups(self):
        """Keep only last 3 backups"""
        try:
            files = [f for f in os.listdir(BACKUP_FOLDER) if f.endswith('.db')]
            files.sort(key=lambda x: os.path.getmtime(os.path.join(BACKUP_FOLDER, x)))
            
            while len(files) > 3:
                old = files.pop(0)
                os.remove(os.path.join(BACKUP_FOLDER, old))
                logger.info(f"🗑️ Deleted old backup: {old}")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")
    
    def stop(self):
        """Stop backup thread"""
        self.running = False
        logger.info("🛑 Backup stopped")