// Centralized error handling utility

class ErrorHandler {
  static contexts = {
    FETCH_CARDS: 'fetchCards',
    FETCH_PENDING: 'fetchPendingCards',
    SAVE_PROGRESS: 'saveProgress',
    PASS_CARD: 'passCard',
    FAIL_CARD: 'failCard',
    UNDO: 'undo',
    REPROCESS: 'reprocess',
    FETCH_HISTORY: 'fetchHistory',
    FETCH_OPTIONS: 'fetchOptions',
    DELETE: 'delete',
    UPDATE: 'update'
  };

  static errorMessages = {
    NETWORK: 'Network error. Please check your connection.',
    SERVER: 'Server error. Please try again.',
    NOT_FOUND: 'Resource not found.',
    VALIDATION: 'Invalid data. Please check your inputs.',
    UNKNOWN: 'An unexpected error occurred.'
  };

  /**
   * Handle an error with context-aware logging and optional notifications
   * @param {Error} error - The error object
   * @param {string} context - Context where error occurred (use ErrorHandler.contexts)
   * @param {Object} options - Configuration options
   * @param {boolean} options.silent - Don't show user notification (default: false)
   * @param {boolean} options.retry - Indicate if retry is possible (default: false)
   * @param {string} options.userMessage - Custom message for user
   * @param {Function} options.addNotification - Notification function from context
   * @param {Object} options.metadata - Additional metadata for logging
   */
  static handle(error, context, options = {}) {
    const {
      silent = false,
      retry = false,
      userMessage,
      addNotification,
      metadata = {}
    } = options;

    // Log to console with full context
    const logData = {
      context,
      error: error.message,
      stack: error.stack,
      metadata,
      timestamp: new Date().toISOString()
    };

    console.error(`[ErrorHandler:${context}]`, logData);

    // Send to server for monitoring (async, non-blocking)
    this.logToServer(logData).catch(() => {
      // Silently fail if server logging fails
    });

    // User notification
    if (!silent && addNotification) {
      const message = userMessage || this.getErrorMessage(error, context);
      const type = retry ? 'warning' : 'error';
      const duration = retry ? 5000 : 0; // Persistent for errors, auto-dismiss for warnings

      addNotification(message, type, duration);
    }

    return {
      shouldRetry: retry,
      context,
      error
    };
  }

  /**
   * Get user-friendly error message based on error type and context
   */
  static getErrorMessage(error, context) {
    // Network errors
    if (error.message.toLowerCase().includes('fetch') ||
        error.message.toLowerCase().includes('network')) {
      return this.errorMessages.NETWORK;
    }

    // 404 errors
    if (error.message.includes('404')) {
      return this.errorMessages.NOT_FOUND;
    }

    // Validation errors
    if (error.message.toLowerCase().includes('invalid') ||
        error.message.toLowerCase().includes('validation')) {
      return this.errorMessages.VALIDATION;
    }

    // Context-specific messages
    switch (context) {
      case this.contexts.FETCH_CARDS:
        return 'Failed to load cards. Please refresh the page.';
      case this.contexts.FETCH_PENDING:
        return 'Failed to load pending cards.';
      case this.contexts.SAVE_PROGRESS:
        return 'Failed to save changes. Your work is preserved locally.';
      case this.contexts.PASS_CARD:
        return 'Failed to verify card. Please try again.';
      case this.contexts.FAIL_CARD:
        return 'Failed to reject card. Please try again.';
      case this.contexts.UNDO:
        return 'Failed to undo action. Please try again.';
      case this.contexts.DELETE:
        return 'Failed to delete. Please try again.';
      case this.contexts.UPDATE:
        return 'Failed to update. Please try again.';
      default:
        return this.errorMessages.UNKNOWN;
    }
  }

  /**
   * Log error to server for monitoring
   */
  static async logToServer(logData) {
    try {
      await fetch('http://localhost:3001/api/log-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(logData)
      });
    } catch (_) {
      // Silently fail - don't throw errors from error handler
    }
  }

  /**
   * Handle async function with automatic error handling
   * Useful wrapper for try-catch blocks
   */
  static async wrap(fn, context, options = {}) {
    try {
      return await fn();
    } catch (error) {
      this.handle(error, context, options);
      throw error; // Re-throw so caller can handle if needed
    }
  }

  /**
   * Create a safe async function that handles errors automatically
   */
  static safe(fn, context, options = {}) {
    return async (...args) => {
      try {
        return await fn(...args);
      } catch (error) {
        this.handle(error, context, options);
        return null; // Return null on error instead of throwing
      }
    };
  }
}

export default ErrorHandler;
