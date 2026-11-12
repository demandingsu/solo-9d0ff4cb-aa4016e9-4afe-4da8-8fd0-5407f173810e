"""测试引导：把工程根放入 sys.path。

`python -I` 隔离模式下 cwd 与 PYTHONPATH 都不会进入 sys.path，
而 unittest discover 也不保证先导入 tests 包，因此各测试模块显式导入本模块。
"""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
