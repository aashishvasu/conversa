"""Selfcheck: python -m selfchecks.api"""

from api.sse import sse

assert sse(text="a\nb") == 'data: {"text": "a\\nb"}\n\n'
print("api selfcheck OK")
