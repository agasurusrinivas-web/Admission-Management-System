"""
Standalone Scheduler Process for Admission Management System (AMS)
Runs the follow-up email notification scheduler as a dedicated background process.
"""

import time
import os
import sys
import logging

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_db_connection
from services.scheduler_service import check_and_process_due_emails, get_now_kolkata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AMS-Scheduler")

def main():
    interval = int(os.getenv("SCHEDULER_INTERVAL", "60").strip())
    logger.info("==================================================")
    logger.info("  AMS Follow-up Email Notification Scheduler Started")
    logger.info(f"  Check interval: {interval} seconds")
    logger.info(f"  Current Time (Asia/Kolkata): {get_now_kolkata()}")
    logger.info("==================================================")

    try:
        while True:
            try:
                due = check_and_process_due_emails(create_db_connection)
                if due > 0:
                    logger.info(f"Processed {due} due notification(s).")
            except Exception as e:
                logger.error(f"Scheduler execution error: {e}")
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")

if __name__ == "__main__":
    main()
