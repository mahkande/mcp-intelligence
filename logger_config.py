from loguru import logger
import sys

# Log format for clear pipeline tracing
LOG_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"

logger.remove()
logger.add(sys.stdout, format=LOG_FORMAT, level="DEBUG", enqueue=True, backtrace=True, diagnose=True)

# Optionally, add file logging here if needed
# logger.add("logs/mcp_pipeline.log", rotation="10 MB", retention="10 days", level="DEBUG")

__all__ = ["logger"]
