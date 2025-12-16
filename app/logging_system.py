"""Logging system for trading card pipeline Uses a separate database in logs/
directory to keep system logs isolated from card data."""

import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (Column, DateTime, Integer, String, Text, create_engine,
                        func)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Separate database for logging (in logs directory)
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
LOGS_DB_PATH = LOGS_DIR / "system_logs.db"
LOGS_DATABASE_URL = f"sqlite:///{LOGS_DB_PATH}"

# Create separate engine and session for logs database
logs_engine = create_engine(LOGS_DATABASE_URL, connect_args={"check_same_thread": False})
LogsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=logs_engine)

LogsBase = declarative_base()


@contextmanager
def get_logs_session():
    """Get a session for the logs database."""
    session = LogsSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogSource(str, Enum):
    UI = "ui"
    API = "api"
    DATABASE = "database"
    FILESYSTEM = "filesystem"
    IMAGE_PROCESSING = "image_processing"
    GPT_VISION = "gpt_vision"
    VERIFICATION = "verification"
    SYSTEM = "system"


class ActionType(str, Enum):
    # File Operations
    FILE_UPLOAD = "file_upload"
    FILE_MOVE = "file_move"
    FILE_DELETE = "file_delete"
    FILE_CREATE = "file_create"

    # Processing Operations
    PROCESS_START = "process_start"
    PROCESS_COMPLETE = "process_complete"
    PROCESS_FAIL = "process_fail"

    # Grid Processing
    GRID_PROCESS_START = "grid_process_start"
    GRID_PROCESS_COMPLETE = "grid_process_complete"
    GRID_PROCESS_FAIL = "grid_process_fail"

    # GPT Operations
    GPT_VISION_REQUEST = "gpt_vision_request"
    GPT_VISION_SUCCESS = "gpt_vision_success"
    GPT_VISION_FAIL = "gpt_vision_fail"
    GPT_VALUE_REQUEST = "gpt_value_request"
    GPT_VALUE_SUCCESS = "gpt_value_success"
    GPT_VALUE_FAIL = "gpt_value_fail"

    # Verification Operations
    VERIFY_PASS = "verify_pass"
    VERIFY_FAIL = "verify_fail"
    VERIFY_EDIT = "verify_edit"
    VERIFY_REPROCESS = "verify_reprocess"

    # Database Operations
    DB_INSERT = "db_insert"
    DB_UPDATE = "db_update"
    DB_DELETE = "db_delete"
    DB_QUERY = "db_query"

    # System Operations
    SYSTEM_START = "system_start"
    SYSTEM_ERROR = "system_error"
    BACKUP_CREATE = "backup_create"

    # Legacy support
    UPLOAD = "upload"
    PROCESS = "process"
    VERIFY = "verify"
    IMPORT = "import"
    DELETE = "delete"
    EDIT = "edit"
    MOVE = "move"
    CREATE = "create"
    UPDATE = "update"
    REPROCESS = "reprocess"
    FAIL = "fail"
    PASS = "pass"


class SystemLog(LogsBase):
    """System log table in logs database."""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    level = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    action = Column(String, nullable=True, index=True)
    message = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    meta_data = Column(Text, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    user_agent = Column(String, nullable=True)
    image_filename = Column(String, nullable=True, index=True)

    def __repr__(self):
        return f"<SystemLog({self.level}: {self.message[:50]}...)>"


class UploadHistory(LogsBase):
    """Upload history table in logs database."""
    __tablename__ = "upload_history"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, index=True)
    original_path = Column(String, nullable=False)
    upload_timestamp = Column(DateTime, server_default=func.now(), index=True)
    file_size = Column(Integer, nullable=True)
    file_type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="uploaded", index=True)

    # Processing tracking
    processing_started = Column(DateTime, nullable=True)
    processing_completed = Column(DateTime, nullable=True)
    cards_detected = Column(Integer, nullable=True, default=0)
    cards_verified = Column(Integer, nullable=True, default=0)
    cards_imported = Column(Integer, nullable=True, default=0)

    # Error tracking
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)

    # Additional meta_data
    meta_data = Column(Text, nullable=True)

    def __repr__(self):
        return f"<UploadHistory({self.filename}: {self.status})>"


class EnhancedLogger:
    """Logger for pipeline tracking using separate logs database."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or self._generate_session_id()
        self.setup_python_logging()

    def _generate_session_id(self) -> str:
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"

    def setup_python_logging(self):
        if not hasattr(logging, 'SUCCESS'):
            logging.SUCCESS = 25
            logging.addLevelName(logging.SUCCESS, 'SUCCESS')

        LOGS_DIR.mkdir(exist_ok=True)
        log_file = LOGS_DIR / f"trading_cards_{datetime.now().strftime('%Y%m%d')}.log"

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )

        self.python_logger = logging.getLogger('trading_cards')

    def log(
        self,
        level: LogLevel,
        source: LogSource,
        message: str,
        action: Optional[ActionType] = None,
        details: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
        image_filename: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        try:
            with get_logs_session() as session:
                log_entry = SystemLog(
                    level=level.value,
                    source=source.value,
                    action=action.value if action else None,
                    message=message,
                    details=details,
                    meta_data=json.dumps(meta_data) if meta_data else None,
                    session_id=self.session_id,
                    user_agent=user_agent,
                    image_filename=image_filename
                )
                session.add(log_entry)

                self.python_logger.log(
                    getattr(logging, level.value.upper()),
                    f"[{source.value}] {message}"
                )

        except Exception as e:
            self.python_logger.error(f"Failed to log to database: {e}")
            self.python_logger.log(
                getattr(logging, level.value.upper()),
                f"[{source.value}] {message}"
            )

    def log_upload(
        self,
        filename: str,
        original_path: str,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None
    ) -> int:
        try:
            with get_logs_session() as session:
                upload_entry = UploadHistory(
                    filename=filename,
                    original_path=original_path,
                    file_size=file_size,
                    file_type=file_type,
                    status="uploaded",
                    meta_data=json.dumps(meta_data) if meta_data else None
                )
                session.add(upload_entry)
                session.flush()
                upload_id = upload_entry.id

                self.log(
                    LogLevel.INFO,
                    LogSource.FILESYSTEM,
                    f"File uploaded: {filename}",
                    ActionType.UPLOAD,
                    f"File size: {file_size} bytes, Type: {file_type}",
                    meta_data,
                    filename
                )

                return upload_id

        except Exception as e:
            self.log(
                LogLevel.ERROR,
                LogSource.SYSTEM,
                f"Failed to log upload for {filename}",
                details=str(e),
                image_filename=filename
            )
            return -1

    def update_upload_status(
        self,
        filename: str,
        status: str,
        cards_detected: Optional[int] = None,
        cards_verified: Optional[int] = None,
        cards_imported: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        try:
            with get_logs_session() as session:
                upload = session.query(UploadHistory).filter(
                    UploadHistory.filename == filename
                ).first()

                if upload:
                    upload.status = status

                    if status == "processing":
                        upload.processing_started = datetime.now()
                    elif status in ["pending_verification", "verified", "failed"]:
                        upload.processing_completed = datetime.now()

                    if cards_detected is not None:
                        upload.cards_detected = cards_detected
                    if cards_verified is not None:
                        upload.cards_verified = cards_verified
                    if cards_imported is not None:
                        upload.cards_imported = cards_imported
                    if error_message:
                        upload.error_message = error_message
                        upload.retry_count += 1

                    self.log(
                        LogLevel.INFO if status != "failed" else LogLevel.ERROR,
                        LogSource.SYSTEM,
                        f"Upload status changed: {filename} -> {status}",
                        ActionType.UPDATE,
                        error_message,
                        {
                            "cards_detected": cards_detected,
                            "cards_verified": cards_verified,
                            "cards_imported": cards_imported
                        },
                        filename
                    )

        except Exception as e:
            self.log(
                LogLevel.ERROR,
                LogSource.SYSTEM,
                f"Failed to update upload status for {filename}",
                details=str(e),
                image_filename=filename
            )

    def log_processing_start(self, filename: str, method: str = "gpt-5.2-vision"):
        self.update_upload_status(filename, "processing")
        self.log(
            LogLevel.INFO,
            LogSource.IMAGE_PROCESSING,
            f"Started processing: {filename}",
            ActionType.PROCESS,
            f"Using method: {method}",
            {"method": method},
            filename
        )

    def log_processing_complete(
        self,
        filename: str,
        cards_detected: int,
        processing_time: Optional[float] = None
    ):
        self.update_upload_status(filename, "pending_verification", cards_detected=cards_detected)
        self.log(
            LogLevel.SUCCESS,
            LogSource.IMAGE_PROCESSING,
            f"Processing completed: {filename}",
            ActionType.PROCESS,
            f"Detected {cards_detected} cards" + (f" in {processing_time:.2f}s" if processing_time else ""),
            {"cards_detected": cards_detected, "processing_time": processing_time},
            filename
        )

    def log_verification_action(
        self,
        filename: str,
        action: str,
        card_index: Optional[int] = None,
        modifications: Optional[Dict[str, Any]] = None
    ):
        action_type = ActionType.PASS if action == "pass" else ActionType.FAIL if action == "fail" else ActionType.EDIT

        if action == "pass":
            if card_index is not None:
                message = f"Single card passed: {filename} (card {card_index})"
            else:
                message = f"All cards passed: {filename}"
                self.update_upload_status(filename, "verified")
        elif action == "fail":
            if card_index is not None:
                message = f"Single card failed: {filename} (card {card_index})"
            else:
                message = f"All cards failed: {filename}"
                self.update_upload_status(filename, "failed")
        else:
            message = f"Card data edited: {filename}" + (f" (card {card_index})" if card_index is not None else "")

        self.log(
            LogLevel.SUCCESS if action == "pass" else LogLevel.WARNING if action == "fail" else LogLevel.INFO,
            LogSource.VERIFICATION,
            message,
            action_type,
            json.dumps(modifications) if modifications else None,
            {"card_index": card_index, "modifications": modifications},
            filename
        )

    def log_file_operation(
        self,
        operation: str,
        source_path: str,
        dest_path: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Log file operations like move, delete, create."""
        action_map = {
            "move": ActionType.FILE_MOVE,
            "delete": ActionType.FILE_DELETE,
            "create": ActionType.FILE_CREATE,
            "upload": ActionType.FILE_UPLOAD
        }
        action = action_map.get(operation, ActionType.MOVE)
        level = LogLevel.INFO if success else LogLevel.ERROR

        filename = Path(source_path).name if source_path else None
        message = f"File {operation}: {filename}"
        if dest_path:
            message += f" -> {Path(dest_path).name}"
        if not success and error:
            message += f" (failed: {error})"

        self.log(
            level,
            LogSource.FILESYSTEM,
            message,
            action,
            error,
            {"source": source_path, "dest": dest_path, "operation": operation},
            filename
        )

    def log_grid_processing(
        self,
        filename: str,
        stage: str,
        cards_detected: Optional[int] = None,
        processing_time: Optional[float] = None,
        error: Optional[str] = None,
        method: str = "enhanced"
    ):
        action_map = {
            "start": ActionType.GRID_PROCESS_START,
            "complete": ActionType.GRID_PROCESS_COMPLETE,
            "fail": ActionType.GRID_PROCESS_FAIL
        }

        level_map = {
            "start": LogLevel.INFO,
            "complete": LogLevel.SUCCESS,
            "fail": LogLevel.ERROR
        }

        message = f"Grid processing {stage}: {filename}"
        if cards_detected is not None:
            message += f" ({cards_detected} cards)"

        details = None
        if error:
            details = f"Error: {error}"
        elif processing_time:
            details = f"Processing time: {processing_time:.2f}s"

        meta_data = {
            "method": method,
            "cards_detected": cards_detected,
            "processing_time": processing_time,
            "stage": stage
        }

        self.log(
            level_map[stage],
            LogSource.IMAGE_PROCESSING,
            message,
            action_map[stage],
            details,
            meta_data,
            filename
        )

        if stage == "start":
            self.update_upload_status(filename, "processing")
        elif stage == "complete":
            self.update_upload_status(filename, "pending_verification", cards_detected=cards_detected)
        elif stage == "fail":
            self.update_upload_status(filename, "failed", error_message=error)

    def get_recent_logs(self, limit: int = 100, level: Optional[LogLevel] = None) -> List[Dict[str, Any]]:
        try:
            with get_logs_session() as session:
                query = session.query(SystemLog)

                if level:
                    query = query.filter(SystemLog.level == level.value)

                logs = query.order_by(SystemLog.timestamp.desc()).limit(limit).all()

                return [
                    {
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat(),
                        "level": log.level,
                        "source": log.source,
                        "action": log.action,
                        "message": log.message,
                        "details": log.details,
                        "meta_data": json.loads(log.meta_data) if log.meta_data else None,
                        "image_filename": log.image_filename
                    }
                    for log in logs
                ]
        except Exception as e:
            self.python_logger.error(f"Failed to retrieve logs: {e}")
            return []

    def get_upload_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with get_logs_session() as session:
                uploads = session.query(UploadHistory).order_by(
                    UploadHistory.upload_timestamp.desc()
                ).limit(limit).all()

                return [
                    {
                        "id": upload.id,
                        "filename": upload.filename,
                        "original_path": upload.original_path,
                        "upload_timestamp": upload.upload_timestamp.isoformat(),
                        "file_size": upload.file_size,
                        "file_type": upload.file_type,
                        "status": upload.status,
                        "processing_started": upload.processing_started.isoformat() if upload.processing_started else None,
                        "processing_completed": upload.processing_completed.isoformat() if upload.processing_completed else None,
                        "cards_detected": upload.cards_detected,
                        "cards_verified": upload.cards_verified,
                        "cards_imported": upload.cards_imported,
                        "error_message": upload.error_message,
                        "retry_count": upload.retry_count,
                        "meta_data": json.loads(upload.meta_data) if upload.meta_data else None
                    }
                    for upload in uploads
                ]
        except Exception as e:
            self.python_logger.error(f"Failed to retrieve upload history: {e}")
            return []


# Global logger instance
logger = EnhancedLogger()


def init_logging_tables():
    """Initialize logging tables in logs database."""
    LogsBase.metadata.create_all(bind=logs_engine)


# Convenience functions
def log_info(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.INFO, source, message, **kwargs)

def log_success(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.SUCCESS, source, message, **kwargs)

def log_warning(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.WARNING, source, message, **kwargs)

def log_error(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.ERROR, source, message, **kwargs)
