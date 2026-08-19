"""临时测试插件：补齐缺失的 root fixture（临时目录），仅用于本次验证。"""
import pytest


@pytest.fixture
def root(tmp_path):
    return tmp_path
