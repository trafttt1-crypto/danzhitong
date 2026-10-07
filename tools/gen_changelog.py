# -*- coding: utf-8 -*-
"""从 config/version.py 生成根目录的 CHANGELOG.md。

更新日志只在 config/version.py 里维护一份（界面、接口、文档都从那里读），
发版后跑一次本脚本，CHANGELOG.md 就和界面里的「更新日志」保持一致：

    python tools/gen_changelog.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.version import CHANGELOG, PRODUCT_NAME  # noqa: E402


def render():
    lines = ["# 更新日志", "",
             "%s 的版本变更记录。版本号遵循语义化版本：主版本 = 不兼容的变化，"
             "次版本 = 新增功能，修订 = 只修问题。" % PRODUCT_NAME, "",
             "> 本文件由 `tools/gen_changelog.py` 从 `config/version.py` 生成，请改那里，不要直接改这里。", ""]
    for rel in CHANGELOG:
        lines.append("## v%s · %s · %s" % (rel["version"], rel["date"], rel["title"]))
        lines.append("")
        lines.extend("- " + it for it in rel["items"])
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    path = os.path.join(ROOT, "CHANGELOG.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render())
    print("已生成", path)
