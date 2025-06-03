"""
Package initialization for the Flask application.

This file is necessary to treat the 'api' directory as a Python package.
It can be used to define package-level variables or perform initialization tasks.
"""

# Import the main application instance for easier access
from .index import app

# Optional: Initialize any extensions or perform setup tasks
def init_app():
    """Initialize the application with any required setup."""
    # We can add database initialization or other setup here if needed
    pass

# Run initialization when the package is imported
init_app()