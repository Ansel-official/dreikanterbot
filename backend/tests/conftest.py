"""测试环境初始化：所有环境变量必须在导入 app 之前设置。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "Test-Admin-123456")
os.environ.setdefault("ALLOW_BOOTSTRAP", "false")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_DAYS", "30")
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("WHISPER_CACHE_DIR", str(BACKEND_ROOT / ".test-whisper"))

# CI 使用真实 PostgreSQL/Redis；普通单元测试不设置这两个变量即可跳过集成测试。
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ.setdefault("RUN_INTEGRATION", "1")
if os.environ.get("TEST_REDIS_URL"):
    os.environ["REDIS_URL"] = os.environ["TEST_REDIS_URL"]
