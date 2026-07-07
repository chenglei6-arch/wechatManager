"""wx-mcp: WeChat MCP Server for Claude"""
import argparse
import logging
import sys

from wx_mcp.server import main as server_main


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WeChat MCP Server — let Claude read and send WeChat messages",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="显示版本号并退出",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启详细调试日志",
    )
    args = parser.parse_args()

    if args.version:
        from wx_mcp import __version__

        print(f"wx-mcp {__version__}")
        sys.exit(0)

    if args.debug:
        root = logging.getLogger("wx-mcp")
        root.setLevel(logging.DEBUG)
        for h in root.handlers:
            h.setLevel(logging.DEBUG)

    server_main()


if __name__ == "__main__":
    main()
