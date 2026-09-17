"""WSGI entrypoint for gunicorn.

Exposes the Dash app's underlying Flask server as `application` so gunicorn
can load it with: gunicorn 'wsgi:application'.

dashboard.py inserts src/ onto sys.path itself, so importing it is enough.

ASCII/English only.
"""

from dashboard import app

application = app.server
