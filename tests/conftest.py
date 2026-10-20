"""pytest 全局配置：在导入 app 之前把数据库/密钥指到临时目录。"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="jf_test_")
os.environ["JF_EDU_DB"] = os.path.join(_tmp, "test.db")
os.environ["JF_SECRET_FILE"] = os.path.join(_tmp, "secret.key")
