"""Korabli `.fxo` shader 容器解析（Lesta `ARIEWIN DX11` 专有格式）。

`res_packages` 里 `shaders/**/*.win.dx11.fxo` 是编译后的 shader，对应 mfm 里填写的
`.fx` 源名（如 `ship_material_indexed.win.dx11.fxo` ↔ `ship_material_indexed.fx`）。

容器结构（2026-08-03 逆向）：
- 头 16B: `ARIEWIN ` + `DX11` + 版本 u32
- @16: 8B 校验/大小
- @24: u32 偏移表（指向各 section）
- Section 含：常量缓冲区(CB)结构定义、shader 参数注释表（UI 名 + 描述）、
  资源绑定（纹理/采样器名）、内嵌 DXBC 字节码（非标准，dxc 无法直接反汇编）

本模块提供实用提取：参数注释表（官方语义描述）、资源绑定、常量结构。
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ARVIEWIN_MAGIC = b"ARIEWIN "


class FxoSections:
    """ARVIEWIN fxo 容器的 section 访问。"""

    def __init__(self, data: bytes):
        self.data = data
        self.sections: List[bytes] = []
        self._parse()

    def _parse(self) -> None:
        d = self.data
        if d[:8] != b"ARIEWIN ":
            raise ValueError(f"不是 ARIEWIN fxo 容器: {d[:8]!r}")
        # 偏移表 @24
        offs: List[int] = []
        pos = 24
        while pos + 4 <= len(d):
            v = struct.unpack_from("<I", d, pos)[0]
            if v == 0 or v >= len(d):
                break
            offs.append(v)
            pos += 4
        # 排序去重，确定各 section 范围
        sorted_offs = sorted(set(offs))
        for i, o in enumerate(sorted_offs):
            end = sorted_offs[i + 1] if i + 1 < len(sorted_offs) else len(d)
            self.sections.append(d[o:end])


def _all_strings(data: bytes, min_len: int = 3) -> List[Tuple[int, str]]:
    """提取所有 ASCII 字符串 (offset, text)。"""
    out = []
    for m in re.finditer(rb'[ -~]{%d,}' % min_len, data):
        out.append((m.start(), m.group().decode("ascii", "replace")))
    return out


def extract_parameter_table(data: bytes) -> List[Tuple[str, str]]:
    """提取 shader 参数注释表 (参数名, 官方描述)。

    参数表嵌在反射数据里，以 "Alpha Reference" 开头。描述为多 token 短语
    （含空格/斜杠/连字符），以此与 CB 结构体的 `name + 类型` 区分。
    """
    marker = data.find(b"Alpha Reference")
    if marker < 0:
        return []
    region = data[marker:marker + 8000]
    strs = _all_strings(region, min_len=2)
    pairs: List[Tuple[str, str]] = []
    i = 0
    while i < len(strs):
        _, s = strs[i]
        s = s.strip()
        # 参数名：驼峰/下划线标识符
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]{1,40}$', s):
            i += 1
            continue
        desc = ""
        if i + 1 < len(strs):
            _, s2 = strs[i + 1]
            s2 = s2.strip()
            # 描述 = 多 token 短语（含空格或 / 或 -）
            if len(s2) >= 6 and (" " in s2 or "/" in s2 or "-" in s2):
                desc = s2
                i += 1
        pairs.append((s, desc))
        i += 1
    # 去重（保持顺序）
    seen = set()
    dedup = []
    for name, desc in pairs:
        key = (name, desc)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((name, desc))
    return dedup


def extract_resource_bindings(data: bytes) -> List[str]:
    """提取资源绑定（纹理/采样器名序列，如 ambientOcclusionMap.materialIdMap.artMap...）。"""
    # 找包含多个已知材质参数的连缀字符串
    result: List[str] = []
    for m in re.finditer(rb'[ -~]{4,}', data):
        s = m.group().decode("ascii", "replace")
        if "." in s and any(k in s for k in ("Map", "Array", "MatIdArr")):
            # 点分隔的名字序列
            parts = s.split(".")
            if len(parts) >= 3 and all(re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', p) for p in parts):
                result.append(s)
    # 去重
    seen = set()
    return [s for s in result if not (s in seen or seen.add(s))]


# ── DXBC 结构（ARVIEWIN 容器内嵌，头被混淆但 chunk 明文）────────────

def find_arswin_passes(data: bytes) -> List[bytes]:
    """定位 fxo 内所有 `ARISWIN DX11` pass 块（shader 子容器）。"""
    out = []
    pos = 0
    while True:
        i = data.find(b"ARISWIN", pos)
        if i == -1:
            break
        nxt = data.find(b"ARISWIN", i + 1)
        end = nxt if nxt != -1 else len(data)
        out.append(data[i:end])
        pos = i + 1
    return out


def parse_dxbc(block: bytes) -> Optional[Dict]:
    """解析一个 ARISWIN 块内嵌的 DXBC。

    布局（2026-08-03 逆向）：'DXBC' 后头部部分字段被混淆，但 chunk 偏移表与
    chunk 数据（RDEF/ISGN/OSGN/SHEX/STAT）明文。返回 chunk 与资源绑定。
    """
    i = block.find(b"DXBC")
    if i == -1:
        return None
    d = block[i:]
    if len(d) < 0x40:
        return None
    num = struct.unpack_from("<I", d, 0x1C)[0]
    if not (1 <= num <= 64):
        return None
    offs = [struct.unpack_from("<I", d, 0x20 + j * 4)[0] for j in range(num)]
    chunks: Dict[str, dict] = {}
    for o in offs:
        if o + 8 > len(d):
            continue
        tag = d[o:o + 4].decode("ascii", "replace")
        sz = struct.unpack_from("<I", d, o + 4)[0]
        chunks[tag] = {"offset": o, "size": sz, "data": d[o + 8:o + 8 + sz]}
    # RDEF 资源绑定
    resources = []
    rdef = chunks.get("RDEF")
    if rdef:
        buf = rdef["data"]
        if len(buf) >= 16:
            cc, cb_off, rc, rd_off = struct.unpack_from("<4I", buf, 0)
            if rc and 0 <= rd_off < len(buf):
                for k in range(rc):
                    base = rd_off + k * 32
                    if base + 16 > len(buf):
                        break
                    name_off, typ, bp, bc = struct.unpack_from("<4I", buf, base)
                    name = ""
                    if 0 <= name_off < len(buf):
                        end = buf.find(b"\x00", name_off)
                        name = buf[name_off:end].decode("utf-8", "replace") if end != -1 else ""
                    resources.append({"name": name, "type": typ, "bind_point": bp, "count": bc})
    return {
        "chunks": {t: {"size": c["size"], "offset": c["offset"]} for t, c in chunks.items()},
        "resources": resources,
        "has_shex": "SHEX" in chunks,
    }


def parse_fxo(data: bytes) -> Dict:
    """完整解析 fxo 容器，返回结构化信息。"""
    sec = FxoSections(data)
    passes = find_arswin_passes(data)
    dxbc_passes = []
    for blk in passes:
        p = parse_dxbc(blk)
        if p:
            dxbc_passes.append(p)
    return {
        "magic": data[:8].decode("ascii", "replace"),
        "version": struct.unpack_from("<I", data, 8)[0],
        "section_count": len(sec.sections),
        "pass_count": len(passes),
        "params": extract_parameter_table(data),
        "resource_bindings": extract_resource_bindings(data),
        "dxbc_passes": dxbc_passes,
    }


def parse_fxo_file(path: str | Path) -> Dict:
    """从文件解析 fxo。"""
    return parse_fxo(Path(path).read_bytes())


# ── Lesta 自定义 shader 字节码（SHEX 内容）─────────────────────────────
#
# 2026-08-03 从 Korabli64.exe FUN_140ae6430（游戏内置反汇编器）逆向：
# - SHEX 数据 = [version u32][指令计数 u32][变长指令流]
# - version 形如 0x00010050（VS）/ 0x00000050（PS），高16位=type，低8位=0x50
# - 指令流按 8 字节 token（u64）组织，指令从 token1（u32[2]）起：
#   opcode = token 低 8 位；操作数散落在后续 token 内（u32/int/浮点立即数）
# - 指令长度表见 _LESTA_OP_LENGTH（FUN_140ae6430 的 lVar21 更新提取，默认 1）
# - opcode 全集 = switch 的 92 个 ∪ exe OP_0x 名字符串 106 个 = 187 个

LESTA_SHADER_OPCODES = (
    0x00, 0x01, 0x04, 0x05, 0x06, 0x08, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
    0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B,
    0x22, 0x24, 0x2C, 0x2D, 0x2E, 0x2F, 0x31, 0x32, 0x33, 0x34, 0x39, 0x3A,
    0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46,
    0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x52, 0x54, 0x55,
    0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61,
    0x62, 0x63, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F,
    0x73, 0x74, 0x75, 0x76, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F,
    0x80, 0x81, 0x83, 0x84, 0x85, 0x86, 0x88, 0x89, 0x8A, 0x8B, 0x8C, 0x8D,
    0x8E, 0x8F, 0x92, 0x94, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9D, 0x9E, 0x9F,
    0xAB, 0xAC, 0xAD, 0xAE, 0xAF, 0xB0, 0xB2, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9,
    0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC2, 0xC3, 0xC8, 0xC9, 0xCA, 0xCB,
    0xCC, 0xCD, 0xCE, 0xCF, 0xD4, 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE,
    0xDF, 0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
    0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF,
)
"""自定义 shader 字节码 opcode 全集（187 个：switch 92 个 ∪ exe OP_0x 名字符串 106 个）。

注意：0x00/0x01/0x22/0x39-0x3F/0x4B/0x4D/0x54/0x5B/0x5C/0x5F/0x67/0x69/0x6B/0x79-0x7F/
0x81/0x83/0x84/0x88-0x8F/0x98-0x9F/0xBC-0xBF/0xC8-0xCF/0xD4/0xD8-0xDF/0xE0-0xEE/0xF2-0xFF
来自 exe 的 OP_0xXX 名字符串表（0x1422F6200 附近），switch 未单独 case（走 default）。
"""

# exe 里 OP_0xXX 名字符串（0x1422F6200 起，106 个）→ opcode 名映射
_LESTA_OP_NAMES = {v: f"OP_0x{v:02X}" for v in range(256)}


def shex_summary(shex: bytes) -> Dict:
    """解析 SHEX 数据头部：[version][计数][指令流]。"""
    if len(shex) < 8:
        return {"valid": False}
    version = struct.unpack_from("<I", shex, 0)[0]
    count = struct.unpack_from("<I", shex, 4)[0]
    stype = (version >> 16) & 0xFF
    return {
        "valid": True,
        "version": f"0x{version:08X}",
        "shader_type": {0: "PS", 1: "VS", 2: "GS", 3: "HS", 4: "DS", 5: "CS"}.get(stype, stype),
        "instruction_count": count,
        "token_bytes": len(shex),
    }


#: 每条指令的 u64 token 长度（从 FUN_140ae6430 的 lVar21 更新提取，含 fall-through 继承；默认 1）
#: 2026-08-03 从 _disasm_full.txt 系统提取
_LESTA_OP_LENGTH = {
    0x04: 2, 0x05: 2, 0x06: 2, 0x08: 2, 0x0B: 2,
    0x0C: 2, 0x0D: 2, 0x0E: 2, 0x0F: 2, 0x10: 2, 0x11: 2, 0x12: 2, 0x13: 2, 0x14: 2,
    0x15: 2, 0x16: 2, 0x17: 2, 0x18: 2, 0x19: 2, 0x1A: 2, 0x1B: 3,
    0x24: 2, 0x2C: 2, 0x2D: 2, 0x2E: 2, 0x2F: 2, 0x31: 2, 0x32: 3, 0x33: 2, 0x34: 2,
    0x40: 2, 0x41: 2, 0x42: 2, 0x43: 4, 0x44: 3, 0x45: 3, 0x46: 3, 0x47: 3, 0x48: 3,
    0x49: 2, 0x4A: 3, 0x4C: 3, 0x4E: 3, 0x4F: 3, 0x52: 3,
    0x55: 2, 0x56: 2, 0x57: 2, 0x58: 2, 0x59: 2, 0x5A: 2, 0x5D: 2, 0x5E: 2,
    0x60: 2, 0x61: 2, 0x62: 2, 0x66: 6, 0x68: 2, 0x6A: 2, 0x6C: 2, 0x6D: 2, 0x6E: 2,
    0x6F: 2, 0x73: 2, 0x74: 2, 0x75: 2, 0x76: 2,
    0x80: 3, 0x85: 2, 0x86: 2, 0x92: 2, 0x94: 2, 0x99: 2,
    0xAB: 2, 0xAC: 2, 0xAD: 2, 0xAE: 2, 0xAF: 2, 0xB0: 2, 0xB2: 2, 0xB5: 2, 0xB6: 2,
    0xB7: 2, 0xB8: 2, 0xB9: 4, 0xBA: 3, 0xBB: 3, 0xC2: 2, 0xC3: 2, 0xEF: 5, 0xF1: 2,
}


def disassemble_shex(shex: bytes, max_insns: int = 200) -> List[Dict]:
    """反汇编 Lesta 自定义 shader 字节码（SHEX 内容）。

    格式（2026-08-03 从游戏内置反汇编器 FUN_140ae6430 逆向）：
    - 数据按 u64（8 字节）token 组织；token0 = [version u32][计数 u32]
    - 指令流从 token1 起：opcode = token 低 8 位
    - 每条指令占用 token 数见 _LESTA_OP_LENGTH（默认 1）
    - 操作数散落在指令的后续 token 内（u32/int/浮点立即数），
      精确的 u32 级操作数拆分仍在精修中（部分指令含浮点立即数）

    返回指令列表 [{idx, opcode, name, known, length, operands:[u64...]}]
    """
    if len(shex) < 8:
        return []
    count = struct.unpack_from("<I", shex, 4)[0]
    n = min(len(shex) // 8, 1 + count)  # token 总数
    idx = 1  # 指令流从 token1 起
    out: List[Dict] = []
    guard = 0
    while idx < n and len(out) < max_insns and guard < 100000:
        guard += 1
        tok = struct.unpack_from("<Q", shex, idx * 8)[0]
        op = tok & 0xFF
        ln = _LESTA_OP_LENGTH.get(op, 1)
        operands = []
        for k in range(1, ln):
            if idx + k < n:
                operands.append(struct.unpack_from("<Q", shex, (idx + k) * 8)[0])
        out.append({
            "idx": idx,
            "opcode": op,
            "name": f"OP_0x{op:02X}",
            "known": op in LESTA_SHADER_OPCODES,
            "length": ln,
            "operands": operands,
        })
        idx += ln
    return out


def disassemble_fxo(data: bytes, max_insns_per_pass: int = 600) -> List[Dict]:
    """反汇编 fxo 容器内所有 pass 的 PS/VS SHEX。

    返回 [{pass_index, has_shex, size, insns:[...], known_ratio}]
    """
    out = []
    for bi, blk in enumerate(find_arswin_passes(data)):
        i = blk.find(b"DXBC")
        if i == -1:
            out.append({"pass_index": bi, "has_shex": False, "insns": [], "known_ratio": 0.0})
            continue
        d = blk[i:]
        try:
            num = struct.unpack_from("<I", d, 0x1C)[0]
        except Exception:
            out.append({"pass_index": bi, "has_shex": False, "insns": [], "known_ratio": 0.0})
            continue
        offs = [struct.unpack_from("<I", d, 0x20 + j * 4)[0] for j in range(min(num, 64))]
        shex = b""
        for o in offs:
            if o + 8 <= len(d) and d[o:o + 4] == b"SHEX":
                sz = struct.unpack_from("<I", d, o + 4)[0]
                shex = d[o + 8:o + 8 + sz]
                break
        if not shex:
            out.append({"pass_index": bi, "has_shex": False, "insns": [], "known_ratio": 0.0})
            continue
        insns = disassemble_shex(shex, max_insns=max_insns_per_pass)
        known = sum(1 for x in insns if x["known"]) if insns else 0
        out.append({
            "pass_index": bi,
            "has_shex": True,
            "size": len(shex),
            "insns": insns,
            "known_ratio": known / len(insns) if insns else 0.0,
        })
    return out
