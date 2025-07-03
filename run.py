import os
import sys
from app import create_app

app, socketio = create_app(sys.argv)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True, debug=True)
