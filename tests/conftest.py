import os
import tempfile

import pytest


@pytest.fixture(scope="session")
def client():
    """Flask test client backed by an isolated, disposable SQLite DB.

    app.py reads DB_PATH and APP_PASSWORD from the environment (and runs
    init_db()) at module import time, so both must be set *before* `app`
    is imported for the first time.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.environ["DB_PATH"] = db_path
    os.environ["APP_PASSWORD"] = "test-password"

    import app as flask_app

    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as test_client:
        yield test_client

    os.remove(db_path)
