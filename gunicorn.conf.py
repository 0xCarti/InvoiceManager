import os

# Bind to the port provided via the PORT environment variable, defaulting to 5000.
bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"

# Use eventlet workers to support WebSocket connections from Flask-SocketIO.
worker_class = "eventlet"

# Increase the timeout to avoid premature worker restarts while establishing Socket.IO connections.
timeout = 60
