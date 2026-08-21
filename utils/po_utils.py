"""
po_utils.py —— PO 文件处理共用工具。

从 localization_service 与 database_service 中抽取的重复逻辑：
- join_po_multiline: 合并 PO 多行 msgstr 续行格式为单行
"""

from __future__ import annotations


def join_po_multiline(text: str) -> str:
    """将 PO 文件中 msgstr 的多行续行格式合并为单行。

    PO 格式中长翻译会拆成：
        msgstr ""
        "第一行内容"
        "第二行内容"
    本函数将其合并为：
        msgstr "第一行内容第二行内容"

    供 localization_service（解析 JSON 映射）与 database_service
    （导入 po_translations 表）共用，消除两处逐字重复的实现。
    """
    lines = text.splitlines(keepends=True)
    result = []
    in_msgstr = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('msgstr '):
            in_msgstr = True
            result.append(line)
        elif in_msgstr and stripped.startswith('"') \
                and not stripped.startswith('msgid ') \
                and not stripped.startswith('msgstr '):
            # 续行：去掉首尾引号，内容追加到上一行
            if result and result[-1].strip().startswith('msgstr ""'):
                # msgstr "" 后第一个续行：替换 msgstr "" 为 msgstr "内容"
                content = stripped[1:-1]
                result[-1] = f'msgstr "{content}"\n'
            elif result:
                # 后续续行：追加内容到上一行的 msgstr 中
                content = stripped[1:-1]
                last = result[-1]
                if last.strip().startswith('msgstr "') and last.strip().endswith('"'):
                    result[-1] = last.rstrip('\n')[:-1] + content + '"\n'
        else:
            in_msgstr = False
            result.append(line)
    return ''.join(result)
