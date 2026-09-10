import pytest
from backend.seed import seed


@pytest.fixture(scope="session", autouse=True)
def database():
    seed()
