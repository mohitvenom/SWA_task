import os
from unittest import mock

from forgeai.config.settings import Settings


@mock.patch.dict(
    os.environ,
    {"FORGEAI_OMNIROUTE_BASE_URL": "http://test", "FORGEAI_GITHUB_TOKEN": "test_token"},
    clear=True,
)
def test_settings_loads_from_env() -> None:
    settings = Settings()
    assert settings.omniroute_base_url == "http://test"
    assert settings.github_token == "test_token"
