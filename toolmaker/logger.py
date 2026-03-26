import logging
from rich.logging import RichHandler
from rich.console import Console

# Create a custom rich console to ensure consistent formatting
console = Console()

def setup_logger(name: str = "dtgs", level: str = "INFO") -> logging.Logger:
    """
    Set up a global logger for the DTGS system using rich for beautiful console output.
    """
    logger = logging.getLogger(name)
    
    # Avoid adding multiple handlers if setup is called multiple times
    if logger.handlers:
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)
        return logger

    # Configure Rich logging handler
    rich_handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_path=False, # We usually don't need the exact file path spamming the logs
        markup=True
    )
    
    rich_handler.setLevel(level)
    
    # We don't need a complex formatting string because Rich handles the timestamp and level columns
    formatter = logging.Formatter("%(message)s")
    rich_handler.setFormatter(formatter)
    
    logger.addHandler(rich_handler)
    logger.setLevel(level)
    
    # Stop propagation to root logger to avoid double logging
    logger.propagate = False
    
    return logger

# Expose a default global logger instance
logger = setup_logger()
