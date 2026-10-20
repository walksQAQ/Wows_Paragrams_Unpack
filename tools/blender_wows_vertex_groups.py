# -*- coding: utf-8 -*-
"""blender_wows_vertex_groups.py —— 在 Blender 里把 GLB 的权重还原成顶点组（**不建骨架**）。

本工具配套「Wows Paragrams Unpack」的 GLB 导出（**关掉了**「导出骨骼顶点组」的模式，
或 ``GlbRenderOptions(export_skins=False)``；默认是开启的，Blender 里直接有顶点组）：

  导出的 GLB 没有 glTF skin/joints（所以 Blender 里没有 Armature、没有 Icosphere
  骨骼球），但每个蒙皮网格仍保留了：
    - ``_JOINTS_0``  （FLOAT VEC4，逐顶点骨骼索引，指向 bone_palette）
    - ``_WEIGHTS_0`` （FLOAT VEC4，逐顶点权重，已归一化）
    - ``mesh.extras.bone_palette``（骨骼名表，如 ["Root_BlendBone", "Rotate_Y_BlendBone"]）

  Blender 的 glTF 导入器只会把「带 skin 的 JOINTS_0/WEIGHTS_0」变成顶点组，
  无 skin 时它们只是自定义属性。本脚本按上面的数据重建真正的顶点组
  （名字 = bone_palette 里的 visual 骨骼名），**不创建任何骨架/骨骼对象**。

用法（三选一）：
  1. Blender → Scripting 工作区 → 打开本文件 → Run Script（对当前场景已导入的对象生效）
  2. 命令行：blender --background --python tools/blender_wows_vertex_groups.py -- model.glb
  3. 命令行（已导入过的 .blend）：blender --background model.blend --python tools/blender_wows_vertex_groups.py

可选参数（放在 `--` 之后）：``--keep-attrs`` 保留 _JOINTS_0/_WEIGHTS_0 属性。
"""

import sys

import bpy

_ATTR_JOINTS = "_JOINTS_0"
_ATTR_WEIGHTS = "_WEIGHTS_0"
_PALETTE_KEY = "bone_palette"


def _palette(obj):
    """网格自定义属性里的骨骼名表（导出时写在 mesh.extras.bone_palette）。"""
    palette = obj.data.get(_PALETTE_KEY)
    return list(palette) if palette else []


def rebuild_vertex_groups(keep_attrs: bool = False, verbose: bool = True) -> int:
    """给场景里所有带 ``_JOINTS_0`` 的网格重建顶点组，返回处理的网格数。"""
    done = 0
    for obj in bpy.data.objects:
        if obj.type != "MESH" or _ATTR_JOINTS not in obj.data.attributes:
            continue
        palette = _palette(obj)
        if not palette:
            if verbose:
                print(f"[跳过] {obj.name}: 缺少 {_PALETTE_KEY}（无法命名顶点组）")
            continue

        groups = {}
        for name in palette:
            groups[name] = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
        # 重建前先清空这些组已有的权重（重复运行时不会叠加）
        idx_by_name = {g.name: g.index for g in obj.vertex_groups}
        for v in obj.data.vertices:
            for ge in list(v.groups):
                if ge.group in idx_by_name.values():
                    obj.vertex_groups[ge.group].remove([v.index])

        # ⚠️ 必须在建组之后才取属性句柄：`vertex_groups.new()` 会重建网格
        # CustomData，之前拿到的 attributes 引用会失效（读出来是空的）。
        if _ATTR_JOINTS not in obj.data.attributes:
            if verbose:
                print(f"[跳过] {obj.name}: 缺少 {_ATTR_JOINTS}")
            continue
        ja = obj.data.attributes[_ATTR_JOINTS]
        wa = obj.data.attributes.get(_ATTR_WEIGHTS)
        if wa is None or len(ja.data) != len(obj.data.vertices) \
                or len(wa.data) != len(obj.data.vertices):
            if verbose:
                print(f"[跳过] {obj.name}: 属性长度与顶点数不一致")
            continue

        assigned = 0
        for vi, (jd, wd) in enumerate(zip(ja.data, wa.data)):
            ids = [int(round(c)) for c in jd.color]
            ws = list(wd.color)
            total = sum(w for w in ws[:4] if w > 1e-6)
            if total <= 1e-6:
                continue
            for slot in range(4):
                w = ws[slot] / total
                if w <= 1e-6:
                    continue
                gi = ids[slot]
                if gi < 0 or gi >= len(palette):
                    continue
                groups[palette[gi]].add([vi], w, 'ADD')
                assigned += 1

        if not keep_attrs:
            obj.data.attributes.remove(obj.data.attributes[_ATTR_JOINTS])
            if _ATTR_WEIGHTS in obj.data.attributes:
                obj.data.attributes.remove(obj.data.attributes[_ATTR_WEIGHTS])
            if obj.data.get(_PALETTE_KEY):
                del obj.data[_PALETTE_KEY]
        done += 1
        if verbose:
            print(f"[顶点组] {obj.name}: {len(palette)} 组 / {assigned} 次权重赋值 / "
                  f"{len(obj.data.vertices)} 顶点")
    if verbose:
        print(f"完成：{done} 个网格已重建顶点组（未创建骨架）")
    return done


def _load_glb_if_given(filepath: str) -> None:
    """命令行传入 .glb 时导入（场景里已有本工具的目标数据就不重复导入）。"""
    if not filepath or not filepath.lower().endswith((".glb", ".gltf")):
        return
    has_target = any(o.type == "MESH" and _ATTR_JOINTS in o.data.attributes
                     for o in bpy.data.objects)
    if has_target:
        return
    if bpy.context.mode != 'OBJECT':          # 默认场景停在物体模式，安全起见确认
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.import_scene.gltf(filepath=filepath)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    keep = "--keep-attrs" in argv
    target = next((a for a in argv if a.lower().endswith((".glb", ".gltf"))), "")
    _load_glb_if_given(target)
    rebuild_vertex_groups(keep_attrs=keep)


if __name__ == "__main__":
    main()
