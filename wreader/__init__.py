"""``wreader`` -- a terminal based novel reader.

Module layout:

* :mod:`wreader.cli`         -- command line entry point and argument parsing
* :mod:`wreader.library`     -- book import, storage and lookup
* :mod:`wreader.reader`      -- curses based paged reading experience
* :mod:`wreader.translator`  -- translation back-ends
* :mod:`wreader.vocab`       -- vocabulary notebook
* :mod:`wreader.stats`       -- reading statistics and achievement definitions
* :mod:`wreader.achievements` -- event driven achievements: state, unlocks, file lock
* :mod:`wreader.config`      -- user configuration handling
"""

# 包的语义化版本号，被 CLI 的 --version 选项和打包元数据引用
__version__ = "0.1.0"

# 声明 `from wreader import *` 时对外导出的名字，这里只暴露版本号
__all__ = ["__version__"]
