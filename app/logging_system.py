"""
Enhanced logging system for trading card pipeline
Tracks all actions and modifications across UI, DB, file system, and image processing
"""

import json
import logging
import os
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.ext.declarative import declarative_base

from app.database import SessionLocal, get_session

Base = declarative_base()


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
    LEARNING = "learning"


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


class SystemLog(Base):
    """Enhanced system log table for comprehensive pipeline tracking"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, server_default=func.now(), index=True)
    level = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, index=True)
    action = Column(String, nullable=True, index=True)
    message = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    meta_data = Column(Text, nullable=True)  # JSON string with additional context
    session_id = Column(String, nullable=True, index=True)
    user_agent = Column(String, nullable=True)
    image_filename = Column(String, nullable=True, index=True)
    
    def __repr__(self):
        return f"<SystemLog({self.level}: {self.message[:50]}...)>"


class UploadHistory(Base):
    """Track upload history and processing status"""
    __tablename__ = "upload_history"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False, index=True)
    original_path = Column(String, nullable=False)
    upload_timestamp = Column(DateTime, server_default=func.now(), index=True)
    file_size = Column(Integer, nullable=True)
    file_type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="uploaded", index=True)
    # Status: uploaded, processing, pending_verification, verified, failed, archived
    
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
    meta_data = Column(Text, nullable=True)  # JSON string
    
    def __repr__(self):
        return f"<UploadHistory({self.filename}: {self.status})>"


class EnhancedLogger:
    """Enhanced logger for comprehensive pipeline tracking"""
    
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or self._generate_session_id()
        self.setup_python_logging()
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID"""
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    
    def setup_python_logging(self):
        """Setup Python logging to also write to our database"""
        # Add custom SUCCESS level to Python logging
        if not hasattr(logging, 'SUCCESS'):
            logging.SUCCESS = 25  # Between INFO (20) and WARNING (30)
            logging.addLevelName(logging.SUCCESS, 'SUCCESS')
        
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Setup file handler
        log_file = log_dir / f"trading_cards_{datetime.now().strftime('%Y%m%d')}.log"
        
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
        """Log an event to both database and file"""
        try:
            with get_session() as session:
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
                session.commit()
                
                # Also log to Python logger
                self.python_logger.log(
                    getattr(logging, level.value.upper()),
                    f"[{source.value}] {message}"
                )
                
        except Exception as e:
            # Fallback to Python logging if database fails
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
        """Log file upload and return upload history ID"""
        try:
            with get_session() as session:
                upload_entry = UploadHistory(
                    filename=filename,
                    original_path=original_path,
                    file_size=file_size,
                    file_type=file_type,
                    status="uploaded",
                    meta_data=json.dumps(meta_data) if meta_data else None
                )
                session.add(upload_entry)
                session.commit()
                session.refresh(upload_entry)
                
                # Also log as system event
                self.log(
                    LogLevel.INFO,
                    LogSource.FILESYSTEM,
                    f"File uploaded: {filename}",
                    ActionType.UPLOAD,
                    f"File size: {file_size} bytes, Type: {file_type}",
                    meta_data,
                    filename
                )
                
                return upload_entry.id
                
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
        """Update upload history status"""
        try:
            with get_session() as session:
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
                    
                    session.commit()
                    
                    # Log status change
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
    
    def log_processing_start(self, filename: str, method: str = "gpt-4-vision"):
        """Log start of image processing"""
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
        """Log completion of image processing"""
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
        action: str,  # "pass", "fail", "edit"
        card_index: Optional[int] = None,
        modifications: Optional[Dict[str, Any]] = None
    ):
        """Log verification actions"""
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
        else:  # edit
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
    
    def log_database_operation(
        self,
        operation: str,  # "insert", "update", "delete"
        table: str,
        record_info: str,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Log database operations"""
        self.log(
            LogLevel.SUCCESS if success else LogLevel.ERROR,
            LogSource.DATABASE,
            f"Database {operation}: {table} - {record_info}",
            ActionType.CREATE if operation == "insert" else ActionType.UPDATE if operation == "update" else ActionType.DELETE,
            error if error else None,
            {"table": table, "operation": operation}
        )
    
    def log_file_operation(
        self,
        operation: str,  # "move", "delete", "create"
        source_path: str,
        dest_path: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Log file system operations"""
        message = f"File {operation}: {source_path}"
        if dest_path:
            message += f" -> {dest_path}"
        
        self.log(
            LogLevel.SUCCESS if success else LogLevel.ERROR,
            LogSource.FILESYSTEM,
            message,
            ActionType.MOVE if operation == "move" else ActionType.DELETE if operation == "delete" else ActionType.CREATE,
            error if error else None,
            {"source_path": source_path, "dest_path": dest_path}
        )
    
    def log_grid_processing(
        self,
        filename: str,
        stage: str,  # "start", "complete", "fail" 
        cards_detected: Optional[int] = None,
        processing_time: Optional[float] = None,
        error: Optional[str] = None,
        method: str = "enhanced"
    ):
        """Log grid processing operations"""
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
        
        # Update upload status
        if stage == "start":
            self.update_upload_status(filename, "processing")
        elif stage == "complete":
            self.update_upload_status(filename, "pending_verification", cards_detected=cards_detected)
        elif stage == "fail":
            self.update_upload_status(filename, "failed", error_message=error)
    
    def log_gpt_operation(
        self,
        operation_type: str,  # "vision", "value_estimation"
        stage: str,  # "request", "success", "fail"
        filename: Optional[str] = None,
        model: str = "gpt-4o",
        tokens_used: Optional[int] = None,
        processing_time: Optional[float] = None,
        error: Optional[str] = None,
        response_data: Optional[Dict] = None
    ):
        """Log GPT API operations"""
        action_map = {
            ("vision", "request"): ActionType.GPT_VISION_REQUEST,
            ("vision", "success"): ActionType.GPT_VISION_SUCCESS,
            ("vision", "fail"): ActionType.GPT_VISION_FAIL,
            ("value_estimation", "request"): ActionType.GPT_VALUE_REQUEST,
            ("value_estimation", "success"): ActionType.GPT_VALUE_SUCCESS,
            ("value_estimation", "fail"): ActionType.GPT_VALUE_FAIL,
        }
        
        level_map = {
            "request": LogLevel.INFO,
            "success": LogLevel.SUCCESS,
            "fail": LogLevel.ERROR
        }
        
        message = f"GPT {operation_type} {stage}"
        if filename:
            message += f": {filename}"
        
        details = None
        if error:
            details = f"Error: {error}"
        elif tokens_used and processing_time:
            details = f"Tokens: {tokens_used}, Time: {processing_time:.2f}s"
        
        meta_data = {
            "operation_type": operation_type,
            "model": model,
            "tokens_used": tokens_used,
            "processing_time": processing_time,
            "stage": stage
        }
        
        if response_data:
            meta_data["response_summary"] = {
                "cards_detected": response_data.get("cards_detected"),
                "confidence": response_data.get("average_confidence")
            }
        
        self.log(
            level_map[stage],
            LogSource.GPT_VISION,
            message,
            action_map.get((operation_type, stage), ActionType.PROCESS),
            details,
            meta_data,
            filename
        )
    
    def log_action_attempt(
        self,
        action: str,
        source: LogSource,
        filename: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
        details: Optional[str] = None,
        meta_data: Optional[Dict] = None
    ):
        """Log any action attempt with comprehensive error handling"""
        try:
            level = LogLevel.SUCCESS if success else LogLevel.ERROR
            message = f"Action attempted: {action}"
            if filename:
                message += f" on {filename}"
            
            if not success and error:
                message += f" - FAILED: {error}"
            
            # Always attempt to log, even if previous operations failed
            self.log(
                level,
                source,
                message,
                ActionType.SYSTEM_ERROR if not success else ActionType.PROCESS,
                error or details,
                meta_data or {},
                filename
            )
            
        except Exception as log_error:
            # Fallback logging to file if database logging fails
            try:
                fallback_log = {
                    "timestamp": datetime.now().isoformat(),
                    "level": "ERROR" if not success else "SUCCESS",
                    "source": source.value,
                    "action": action,
                    "filename": filename,
                    "success": success,
                    "error": error,
                    "details": details,
                    "log_error": str(log_error)
                }
                
                with open("logs/fallback_actions.log", "a") as f:
                    f.write(json.dumps(fallback_log) + "\n")
                    
            except Exception:
                # Ultimate fallback - print to stderr
                print(f"[LOGGING FAILED] {datetime.now()}: {action} on {filename} - Success: {success}, Error: {error}", file=sys.stderr)
    
    def get_recent_logs(self, limit: int = 100, level: Optional[LogLevel] = None) -> List[Dict[str, Any]]:
        """Get recent log entries"""
        try:
            with get_session() as session:
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
        """Get upload history"""
        try:
            with get_session() as session:
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
    """Initialize logging tables in database"""
    from app.database import engine
    Base.metadata.create_all(bind=engine)


# Convenience functions for common logging scenarios
def log_info(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.INFO, source, message, **kwargs)

def log_success(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.SUCCESS, source, message, **kwargs)

def log_warning(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.WARNING, source, message, **kwargs)

def log_error(source: LogSource, message: str, **kwargs):
    logger.log(LogLevel.ERROR, source, message, **kwargs)