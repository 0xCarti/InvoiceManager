import sys
from app import create_app

app, socketio = create_app(sys.argv)

if __name__ == "__main__":
    socketio.run(app, allow_unsafe_werkzeug=True)
