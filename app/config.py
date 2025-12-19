import os
from dotenv import load_dotenv
from pathlib import Path


class Config:
    """
    Centralized configuration management for the trading cards application.
    Loads environment variables and validates required settings.
    """

    def __init__(self, env_file=None):
        # Load environment-specific .env file
        if env_file:
            load_dotenv(env_file)
        else:
            # Try to load environment-specific file first
            environment = os.getenv('ENVIRONMENT', 'development')
            env_path = Path(f'.env.{environment}')

            if env_path.exists():
                load_dotenv(env_path)
            else:
                # Fall back to default .env
                load_dotenv()

        # Core configuration
        self.environment = os.getenv('ENVIRONMENT', 'development')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.openai_model = os.getenv('OPENAI_MODEL', 'gpt-5.2')
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///cards/verified/trading_cards.db')

        # Security configuration
        self.jwt_secret = os.getenv('JWT_SECRET')
        self.jwt_expiration = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

        # Server configuration
        self.server_port = int(os.getenv('SERVER_PORT', '3001'))
        self.server_host = os.getenv('SERVER_HOST', 'localhost')

        # Redis configuration (optional)
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

        # API configuration
        self.rate_limit_enabled = os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true'
        self.rate_limit_max = int(os.getenv('RATE_LIMIT_MAX', '100'))
        self.rate_limit_window_ms = int(os.getenv('RATE_LIMIT_WINDOW_MS', '900000'))  # 15 minutes

        # File paths
        self.cards_dir = os.getenv('CARDS_DIR', 'cards')
        self.logs_dir = os.getenv('LOGS_DIR', 'logs')

        # Validate configuration
        self.validate()

    def validate(self):
        """
        Validate required configuration based on environment.
        Raises ValueError if required settings are missing.
        """
        errors = []

        # OpenAI API key is always required
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required but not set")

        # JWT secret is required for production
        if self.environment == 'production':
            if not self.jwt_secret:
                errors.append("JWT_SECRET is required for production environment")
            elif len(self.jwt_secret) < 32:
                errors.append("JWT_SECRET must be at least 32 characters for security")

        # Database URL validation
        if not self.database_url:
            errors.append("DATABASE_URL is required but not set")

        # Check if using PostgreSQL in production
        if self.environment == 'production' and not self.database_url.startswith('postgresql'):
            errors.append("PostgreSQL is recommended for production (DATABASE_URL should start with 'postgresql://')")

        if errors:
            error_message = "\n".join([f"  - {error}" for error in errors])
            raise ValueError(f"Configuration validation failed:\n{error_message}")

    def is_development(self):
        """Check if running in development mode."""
        return self.environment == 'development'

    def is_production(self):
        """Check if running in production mode."""
        return self.environment == 'production'

    def is_test(self):
        """Check if running in test mode."""
        return self.environment == 'test'

    def __repr__(self):
        """String representation (masks sensitive data)."""
        return f"""Config(
  environment={self.environment}
  openai_api_key={'***' + self.openai_api_key[-8:] if self.openai_api_key else 'NOT SET'}
  openai_model={self.openai_model}
  database_url={self._mask_database_url()}
  jwt_secret={'***SET***' if self.jwt_secret else 'NOT SET'}
  server={self.server_host}:{self.server_port}
  rate_limit_enabled={self.rate_limit_enabled}
)"""

    def _mask_database_url(self):
        """Mask password in database URL for logging."""
        if not self.database_url:
            return 'NOT SET'

        # Simple masking for display
        if '@' in self.database_url:
            parts = self.database_url.split('@')
            if ':' in parts[0]:
                proto_user_pass = parts[0].rsplit(':', 1)
                return f"{proto_user_pass[0]}:***@{parts[1]}"

        return self.database_url


# Global config instance
_config = None


def get_config(reload=False):
    """
    Get the global configuration instance.

    Args:
        reload: If True, reload configuration from environment

    Returns:
        Config instance
    """
    global _config

    if _config is None or reload:
        _config = Config()

    return _config


if __name__ == '__main__':
    # Test configuration loading
    try:
        config = get_config()
        print("Configuration loaded successfully:")
        print(config)
    except ValueError as e:
        print(f"Configuration error: {e}")
