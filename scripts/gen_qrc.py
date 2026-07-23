"""gen_qrc.py —— 扫描 resources/ 目录，生成 resources.qrc 文件。

用法: python scripts/gen_qrc.py
输出: resources.qrc（项目根目录）
"""

from pathlib import Path

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
OUTPUT_QRC = Path(__file__).resolve().parent.parent / "resources.qrc"

# 不需要打包进 QRC 的文件（用户数据，运行时需要读写）
EXCLUDE = {"epic_skill_config.json"}


def _scan_files(base: Path) -> list[str]:
    """扫描 resources/ 下所有文件，返回相对于项目根目录的路径列表"""
    files = []
    root = RESOURCES_DIR.parent
    for p in sorted(RESOURCES_DIR.rglob("*")):
        if p.is_file() and p.name not in EXCLUDE:
            rel = p.relative_to(root).as_posix()
            files.append(rel)
    return files


def _generate_qrc(files: list[str]) -> str:
    lines = ['<!DOCTYPE RCC>', '<RCC version="1.0">', '  <qresource prefix="/">']
    for f in files:
        lines.append(f'    <file>{f}</file>')
    lines.append('  </qresource>')
    lines.append('</RCC>')
    return "\n".join(lines) + "\n"


def main():
    files = _scan_files(RESOURCES_DIR)
    print(f"发现 {len(files)} 个资源文件")
    qrc_content = _generate_qrc(files)
    OUTPUT_QRC.write_text(qrc_content, encoding="utf-8")
    print(f"已生成 {OUTPUT_QRC}")


if __name__ == "__main__":
    main()
