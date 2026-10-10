import sys
import os

# Add root directory to sys.path so modules (database, models, routers, etc.) resolve properly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
