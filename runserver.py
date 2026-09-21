import os

from storage import app

if __name__ == "__main__":
    debug = os.environ.get('FLASK_DEBUG') == '1'
    app.run(host="0.0.0.0", port=5006, debug=debug)
