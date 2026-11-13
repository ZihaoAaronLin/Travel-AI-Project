"""只读执行模型写的 SQL（query_kb）。目标：什么都改不了、跑不死、出错时告诉模型该怎么改。

每次查询开一个新连接，层层设防（ROADMAP 第 2 阶段，每层都有攻击测试）：
1. mode=ro 只读打开：真正碰到库文件的写操作在这一层就会失败
2. PRAGMA query_only = ON：连接级的只读开关；要在装 authorizer 之前执行，装上之后 PRAGMA 也会被拒
3. authorizer 白名单：只放行 SELECT / READ / FUNCTION / RECURSIVE。DROP、建临时表、ATTACH、PRAGMA、
   VACUUM INTO 写文件，都在编译阶段就被拒——实际上大多数攻击是被这一层最先挡下的
4. 一次一条语句：sqlite3 的 execute 本身拒绝多条
5. progress handler：超过 timeout_s 就中断（无限递归的 CTE）
6. 行数上限：最多取 max_rows 行，多了标 truncated
7. 不返回结果列的语句一律拒绝：空串、纯注释能「成功」执行却什么也不返回，模型会误以为「查了，没有」
"""

import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel

Cell = str | int | float | None

_ALLOWED = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)
_HOW_TO_FIX = (
    "只允许一条只读的 SELECT 查询（可以用 WITH / WITH RECURSIVE）；"
    "表名和列名用 describe_schema 查。"
)


class QueryRejected(Exception):
    """查询被拒。消息是写给模型看的：为什么被拒、该怎么改。"""


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list[Cell]]
    truncated: bool  # 结果比 max_rows 多，只给了前 max_rows 行


class TableSchema(BaseModel):
    name: str
    columns: list[str]


class ReadOnlyKB:
    def __init__(self, path: Path, max_rows: int = 200, timeout_s: float = 0.5):
        self.path = Path(path)
        # 先检查再连：mode=ro 不会建新文件，但报错信息不如这里清楚
        if not self.path.is_file():
            raise FileNotFoundError(f"找不到 {self.path}：先运行 uv run python scripts/build_db.py")
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def query(self, sql: str) -> QueryResult:
        conn = self._connect(guarded=True)
        try:
            cursor = conn.execute(sql)
            if cursor.description is None:
                raise QueryRejected(f"这条语句不返回任何结果列。{_HOW_TO_FIX}")
            columns = [col[0] for col in cursor.description]
            fetched = cursor.fetchmany(self.max_rows + 1)  # 多取一行，才知道有没有被截断
        except sqlite3.Error as err:
            raise QueryRejected(self._explain(err)) from None
        finally:
            conn.close()
        rows = [[_cell(value) for value in row] for row in fetched[: self.max_rows]]
        return QueryResult(columns=columns, rows=rows, truncated=len(fetched) > self.max_rows)

    def schema(self) -> list[TableSchema]:
        """表和列。authorizer 连读 PRAGMA 都拦，所以这里用不装 authorizer 的只读连接。"""
        conn = self._connect(guarded=False)
        try:
            names = [
                name
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return [
                TableSchema(
                    name=name,
                    columns=[
                        col
                        for (col,) in conn.execute(
                            "SELECT name FROM pragma_table_info(?) ORDER BY cid", (name,)
                        )
                    ],
                )
                for name in names
            ]
        finally:
            conn.close()

    def _connect(self, guarded: bool) -> sqlite3.Connection:
        # as_uri 会把路径里的 ? # % 转义，不会被当成 URI 参数
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        if guarded:
            conn.set_authorizer(_authorize)
            deadline = time.monotonic() + self.timeout_s
            # 每执行 1000 条虚拟机指令问一次：返回非 0 就中断当前语句
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return conn

    def _explain(self, err: sqlite3.Error) -> str:
        if "interrupted" in str(err):
            return (
                f"查询超时（超过 {self.timeout_s} 秒）被中断：缩小日期范围，"
                "或者给递归 CTE 加上终止条件。"
            )
        return f"查询被拒绝（{err}）。{_HOW_TO_FIX}"


def _authorize(action: int, *_details) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


def _cell(value) -> Cell:
    # 库里没有 BLOB 列，但模型可以用 x'00ff' 之类的写法造出来；转成十六进制文本，结果才能序列化
    return value.hex() if isinstance(value, bytes) else value
