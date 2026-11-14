import os

from flask import request


def public_url(path):
    base = os.environ.get('APP_URL') or request.url_root.rstrip('/')
    return base.rstrip('/') + '/' + path.lstrip('/')
