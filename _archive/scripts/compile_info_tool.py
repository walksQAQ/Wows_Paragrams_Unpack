"""
compile.info 解码工具
====================
将 WoWs 的 compile.info 文件（base64 → zlib 解压）解码并输出原始数据。

用法:
    python _archive/compile_info_tool.py <compile.info 路径>
"""

import base64
import re
import sys
import zlib


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    filepath = sys.argv[1]

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 只去除 <content_info> 标签，保留其他原始内容
    content = re.sub(r'</?content_info>', '', content)

    # base64 解码（自动忽略空白字符）
    raw = base64.b64decode(content)

    # zlib 解压
    decompressed = zlib.decompress(raw)

    # 输出原始字节解码后的文本（保留原有换行/格式）
    print(decompressed.decode('utf-8'))


if __name__ == '__main__':
    main()
