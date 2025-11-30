"""
Logging configuration - delegates to main.py setup
"""
import logging

def setup_logger(name: str, **kwargs):
    """Get logger configured in main.py"""
    return logging.getLogger(name)

def get_logger(name: str):
    """Get logger configured in main.py"""
    return logging.getLogger(name)