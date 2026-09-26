"""``wreader`` -- a terminal based novel reader.

Module layout:

* :mod:`wreader.cli`         -- command line entry point and argument parsing
* :mod:`wreader.library`     -- book import, storage and lookup
* :mod:`wreader.reader`      -- curses based paged reading experience
* :mod:`wreader.stats`       -- reading statistics and achievement definitions
* :mod:`wreader.achievements` -- event driven achievements: state, unlocks, file lock
* :mod:`wreader.config`      -- user configuration handling
* :mod:`wreader.toc`         -- chapter table detection and its cache
* :mod:`wreader.transfer`    -- the ``werd data`` bundle: export and merge reading history
* :mod:`wreader.lock`        -- the file lock the state stores share
* :mod:`wreader.env`         -- environment probes behind the achievements
* :mod:`wreader.geo`         -- optional geo lookup behind the achievements
"""

# 包的语义化版本号，被 CLI 的 --version 选项和打包元数据引用
__version__ = "0.1.0"

# 声明 `from wreader import *` 时对外导出的名字，这里只暴露版本号
__all__ = ["__version__"]
