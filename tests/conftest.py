import pytest





@pytest.fixture(scope="session")
def session():
    pass

@pytest.fixture(autouse=True)
def _():
    print("____Debut du test_______")
    yield
    print("____Fin du du test_______")