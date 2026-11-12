import os

from .server import serve

if __name__ == "__main__":
    serve(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
