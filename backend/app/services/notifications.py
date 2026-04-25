import apprise
from loguru import logger
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db import models
import json


class NotificationService:
    def __init__(self):
        self.apobj = apprise.Apprise()

    def _load_urls(self, db: Session):
        """Loads notification URLs from settings"""
        self.apobj.clear()
        setting = (
            db.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "notification_urls")
            .first()
        )
        if setting and setting.value:
            try:
                urls = json.loads(setting.value)
                for url in urls:
                    if url.strip():
                        self.apobj.add(url.strip())
            except Exception as e:
                logger.error(f"Failed to parse notification URLs: {e}")

    def notify(self, title: str, body: str, notify_type: str = "info"):
        """Sends a notification to all configured services"""
        db = SessionLocal()
        try:
            self._load_urls(db)
            if len(self.apobj) == 0:
                logger.debug("No notification services configured, skipping.")
                return

            self.apobj.notify(
                title=f"[TapeHoard] {title}", body=body, notify_type=notify_type
            )
            logger.info(f"Sent notification: {title}")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
        finally:
            db.close()

    def test_notification(self, url: str) -> bool:
        """Tests a single Apprise URL"""
        try:
            ap = apprise.Apprise()
            ap.add(url)
            result = ap.notify(
                title="[TapeHoard] Test Notification",
                body="This is a test notification from your TapeHoard instance. If you see this, your configuration is correct!",
                notify_type="info",
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Test notification failed for {url}: {e}")
            return False


notification_manager = NotificationService()
