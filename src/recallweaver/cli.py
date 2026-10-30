"""RecallWeaver 的命令行入口，提供记忆写入与全文检索命令。"""

# argparse 是 Python 标准库的命令行参数解析器，无需添加额外依赖。
import argparse
# Any 用于标注 recall 返回的字典记录列表中可能包含的不同类型字段。
from typing import Any, Dict, List, Optional, Sequence

# 通过项目对外 API 调用记忆写入和检索，避免 CLI 直接耦合数据库实现。
from recallweaver import api
# 导入统一存储异常，在命令行边界以可读错误信息呈现存储失败。
from recallweaver.errors import StorageError


def build_parser() -> argparse.ArgumentParser:
    """构造并返回包含所有受支持子命令的参数解析器。"""
    # 创建项目主解析器，并按需求提供清晰的简短说明。
    parser = argparse.ArgumentParser(
        description="RecallWeaver CLI - 轻量级AI记忆引擎"
    )

    # 声明子命令解析器集合；required=True 可在未提供命令时直接提示正确用法。
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 定义 add 子命令，用于将一段文本保存为新记忆。
    add_parser = subparsers.add_parser("add", help="保存一条新记忆")
    # 记忆文本必须由调用方明确提供，避免创建内容为空的记录。
    add_parser.add_argument(
        "--content",
        required=True,
        help="需要保存的记忆文本内容",
    )

    # 定义 search 子命令，用于按查询文本搜索已保存的记忆。
    search_parser = subparsers.add_parser("search", help="搜索已有记忆")
    # 查询文本为必填参数，实际语法由数据库 FTS5 检索器解释。
    search_parser.add_argument(
        "--query",
        required=True,
        help="用于全文搜索的查询文本",
    )

    # 返回完成配置的解析器，便于 main 函数及自动化测试复用。
    return parser


def _print_search_results(
    results: List[Dict[str, Any]],
) -> None:
    """按行输出检索结果的 ID、内容和实时分数。"""
    # 空列表代表没有找到符合查询的活动记忆，给出明确的用户提示。
    if not results:
        print("未找到相关记忆")
        return

    # 逐条输出检索器已按 realtime_score 排序的结果及其关键字段。
    for memory in results:
        # 使用 get 获取字段，避免意外缺失的展示字段导致整个命令崩溃。
        memory_id = memory.get("id", "")
        content = memory.get("content", "")
        realtime_score = memory.get("realtime_score", 0.0)
        print(
            f"ID: {memory_id} | 内容: {content} | "
            f"实时分数: {realtime_score}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """解析命令行参数、调用对应 API，并返回进程退出码。

    argv 可由测试传入以避免修改真实进程参数；直接运行模块时则使用
    argparse 默认读取的 sys.argv。
    """
    # 构造解析器并解析参数；必填选项缺失时 argparse 会自动打印帮助并退出。
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        # 根据已解析的子命令分派至对应公开 API。
        if args.command == "add":
            # 保存记忆并显示数据库返回的唯一 ID，方便之后定位该记录。
            memory_id = api.remember(args.content)
            print(f"✅ 记忆已存入，ID: {memory_id}")
            return 0

        if args.command == "search":
            # 调用检索 API；默认上限由 recall 函数的 limit 默认值提供。
            results = api.recall(args.query)
            # 统一委托展示函数处理有结果和无结果两种情况。
            _print_search_results(results)
            return 0

        # 子命令由 argparse 的必需子解析器保证；此分支仅用于防御未来代码变更。
        parser.error(f"不支持的命令：{args.command}")
    except StorageError as exc:
        # 存储错误以 stderr 输出并使用非零退出码，便于脚本或 CI 检测失败。
        parser.exit(status=1, message=f"存储错误：{exc}\n")

    # parser.error 会抛出 SystemExit；此返回仅用于满足静态类型检查器的控制流分析。
    return 2


# 通过 python -m recallweaver.cli 启动命令行工具时执行 main。
if __name__ == "__main__":
    raise SystemExit(main())