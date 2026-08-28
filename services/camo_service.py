"""camouflages.xml 解析 + 舰船可切换涂装列表（对齐 wows-toolkit camouflage.rs）。

数据源：包根 `camouflages.xml`（<data> 含 <camouflages.xml>/<colorschemes.xml>/<shipgroups.xml>）。

- CamouflageEntry：一条 camo 定义（名称、按部件分类贴图、colorScheme、每部件 UV 变换、船组/目标舰）。
- CamoSchemeInfo：某艘船的一个可切换涂装（id/显示名/uv 变换/来源），含「无/无涂装」=id 0。
- list_camos(ship)：按 ship 索引（model_folder / game_key）匹配 shipGroups/targetShip，返回该船可切换列表。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace


def _dir_name(model_path: str) -> str:
    """从 .model 路径取目录名（末段）。"""
    if not model_path:
        return ""
    if "/" in model_path:
        return model_path.rsplit("/", 2)[-2]
    return model_path



# ── 数据结构 ─────────────────────────────────────────────


@dataclass
class ColorScheme:
    name: str
    colors: list[list[float]] = field(default_factory=lambda: [[0.0] * 4 for _ in range(4)])


@dataclass
class UvTransform:
    scale: tuple[float, float] = (1.0, 1.0)
    offset: tuple[float, float] = (0.0, 0.0)


@dataclass
class CamouflageEntry:
    name: str
    realm: str = ""
    tiled: bool = False
    use_color_scheme: bool = False
    textures: dict[str, str] = field(default_factory=dict)        # 部件分类 -> 贴图路径
    color_scheme: str | None = None
    color_schemes: list[str] = field(default_factory=list)   # 全部颜色方案名（一个 camo 可有多个配色）
    colors: list | None = None      # 当前选中配色 4×[r,g,b,a]（0-255），供 CPU 上色
    uv_transforms: dict[str, UvTransform] = field(default_factory=dict)
    ship_groups: list[str] = field(default_factory=list)
    target_ships: list[str] = field(default_factory=list)
    display_name: str = ""          # 本地化显示名（如 IDS_* 提取）


@dataclass
class CamoSchemeInfo:
    id: int
    display_name: str
    raw_name: str
    origin: str                      # "mat"(贴图层) / "model"(独立建模变体) / "none"(无涂装)
    use_color_scheme: bool = False
    uv_transforms: dict[str, UvTransform] = field(default_factory=dict)
    icon_path: str = ""              # data 相对路径（camo_thumbs/...）
    model_replace: dict = field(default_factory=dict)   # 皮肤变体：原始 .model 路径 → 替换路径
    model_folder: str = ""           # 替换后的船体几何目录（如 FSB101_Aquitaine_White）
    skin: dict = field(default_factory=dict)            # 皮肤完整数据：hull_config/nodes_config/peculiarity_models
    entry: CamouflageEntry | None = None


# ── 部件分类（对齐 wows-toolkit classify_part_category） ─────


def classify_part_category(mfm_stem: str) -> str:
    """把 mfm 名分类为 camo 部件（tile=船体 / deckhouse / bulge / gun / torpedo / director / plane / misc / glass / wire / net）。"""
    lower = mfm_stem.lower()
    if lower.endswith("_hull"):
        return "tile"
    if lower.endswith("_deckhouse"):
        return "deckhouse"
    if "_bulge" in lower:
        return "bulge"
    if "glass" in lower:
        return "glass"
    if lower.endswith("_wire"):
        return "wire"
    if "_alpha" in lower or "razlom" in lower:
        return "net"
    code = mfm_stem.encode("latin-1", "ignore")
    if len(mfm_stem) >= 3 and mfm_stem[0].isascii() and mfm_stem[0].isupper():
        fam = mfm_stem[1].upper()
        if fam == "G":
            return "torpedo" if mfm_stem[1:3].upper() == "GT" else "gun"
        if fam in ("D", "F"):
            return "director"
        if fam == "A":
            return "plane"
        if fam == "R":
            return "misc"
    if "_hull" in lower:
        return "tile"
    return "tile"


# ── 解析 ──────────────────────────────────────────────────


def _child_text(node: ET.Element, tag: str) -> str | None:
    c = node.find(tag)
    return (c.text or "").strip() if c is not None else None


def _parse_uv(node: ET.Element) -> UvTransform:
    def _v(tag):
        t = node.find(tag)
        if t is None or not t.text:
            return None
        parts = t.text.split()
        try:
            return [float(x) for x in parts]
        except ValueError:
            return None
    sx = _v("scale")
    ox = _v("offset")
    scale = (sx[0], sx[1]) if sx and len(sx) >= 2 else (1.0, 1.0)
    offset = (ox[0], ox[1]) if ox and len(ox) >= 2 else (0.0, 0.0)
    return UvTransform(scale, offset)


def parse_camouflages(data: bytes) -> dict:
    """返回 {entries: {name: [CamouflageEntry,...]}, color_schemes: {name: ColorScheme}, ship_groups: {group: set ships}}。"""
    root = ET.fromstring(data)
    entries: dict[str, list[CamouflageEntry]] = {}
    color_schemes: dict[str, ColorScheme] = {}
    ship_groups: dict[str, set[str]] = {}

    # shipgroups.xml
    for sg in root.iter("shipgroups.xml"):
        for group in sg:
            if not isinstance(group.tag, str):
                continue
            ships_txt = _child_text(group, "ships") or ""
            ship_groups[group.tag] = set(ships_txt.split())

    # colorschemes.xml：每个分组节点即一个 colorScheme（children color0..3）
    for cs in root.iter("colorschemes.xml"):
        for grp in cs:
            if not isinstance(grp.tag, str):
                continue
            name = grp.tag
            colors = [[0.0] * 4 for _ in range(4)]
            for i in range(4):
                c = grp.find(f"color{i}")
                if c is not None and c.text:
                    parts = c.text.split()
                    if len(parts) >= 4:
                        try:
                            colors[i] = [float(x) for x in parts[:4]]
                        except ValueError:
                            pass
            color_schemes[name] = ColorScheme(name=name, colors=colors)

    # camouflages.xml 条目
    for cams in root.iter("camouflages.xml"):
        for cn in cams:
            if not isinstance(cn.tag, str) or cn.tag != "camouflage":
                continue
            name = _child_text(cn, "name") or ""
            if not name:
                continue
            realm = _child_text(cn, "realm") or ""
            # 一个 camo 可有多个 <colorSchemes>（不同配色），每个取其首词为方案名
            camo_schemes: list[str] = []
            for cs_el in cn.findall("colorSchemes"):
                _t = (cs_el.text or "").strip()
                _n = _t.split()[0] if _t else ""
                if _n:
                    camo_schemes.append(_n)
            color_scheme = camo_schemes[0] if camo_schemes else None
            # tiled 由 <tiled> 元素决定；缺省为 false（整船涂装按 black_passthrough 处理）
            tiled = (_child_text(cn, "tiled") or "").strip().lower() in ("true", "1", "yes")
            use_color_scheme = bool(camo_schemes)

            textures: dict[str, str] = {}
            tx = cn.find("Textures")
            if tx is not None:
                for child in tx:
                    if not isinstance(child.tag, str):
                        continue
                    tag = child.tag.lower()
                    if tag.endswith("_mgn") or tag.endswith("_animmap"):
                        continue
                    p = (child.text or "").strip()
                    if p:
                        textures[tag] = p

            uv_transforms: dict[str, UvTransform] = {}
            uv = cn.find("UV")
            if uv is not None:
                for child in uv:
                    if not isinstance(child.tag, str):
                        continue
                    uv_transforms[child.tag.lower()] = _parse_uv(child)

            ship_groups_camo = (_child_text(cn, "shipGroups") or "").split()
            target_ships = [
                (t.text or "").strip()
                for t in cn.iter("targetShip") if isinstance(t.tag, str) and t.text and t.text.strip()
            ]

            entries.setdefault(name, []).append(CamouflageEntry(
                name=name, realm=realm, tiled=tiled, use_color_scheme=use_color_scheme,
                textures=textures, color_scheme=color_scheme, color_schemes=camo_schemes,
                uv_transforms=uv_transforms, ship_groups=ship_groups_camo,
                target_ships=target_ships,
            ))

    return {"entries": entries, "color_schemes": color_schemes, "ship_groups": ship_groups}


# ── 服务 ──────────────────────────────────────────────────


class CamoService:
    """包装 camouflages.xml 解析，为舰船枚举可切换涂装。

    DB 优先：若传入 cache(assets_cache_service) + bin_folder，则从 assets_data.db 的
    camouflages/camouflage_color_schemes/camo_ship_groups 重建；否则回退现场解包 camouflages.xml。
    额外纳入 exteriors 中 typeinfo.species 属涂装类（Mskin/Permoflage/Skin/Camouflage）且带
    peculiarityModels 的皮肤/永久涂装（origin="model"）。
    """

    #: 视为「涂装」的 Exterior species（小写）
    _CAMO_SPECIES = {"mskin", "permoflage", "skin", "camouflage"}

    def __init__(self, extractor=None, cache=None, bin_folder: str = ""):
        self._extractor = extractor
        self._cache = cache
        self._bin_folder = bin_folder or ""
        self._db: dict | None = None
        self._icon_map: dict[str, str] = {}
        self._exteriors: list[dict] = []

    def _build_from_db(self):
        entries: dict[str, list[CamouflageEntry]] = {}
        icon_map: dict[str, str] = {}
        for row in self._cache.get_all_camouflages(self._bin_folder):
            name = row["name"]
            uv: dict[str, UvTransform] = {}
            for tag, t in (row.get("uv") or {}).items():
                sc = (t.get("scale") or [1.0, 1.0])
                of = (t.get("offset") or [0.0, 0.0])
                uv[tag] = UvTransform(scale=(float(sc[0]), float(sc[1])),
                                      offset=(float(of[0]), float(of[1])))
            schemes = [s for s in (row.get("color_scheme") or "").split(",") if s]
            entry = CamouflageEntry(
                name=name, realm=row.get("realm", ""), tiled=bool(row.get("tiled")),
                use_color_scheme=bool(row.get("use_color_scheme")),
                textures=row.get("textures") or {},
                color_scheme=schemes[0] if schemes else None,
                color_schemes=schemes,
                uv_transforms=uv,
                ship_groups=row.get("ship_groups") or [],
                target_ships=row.get("target_ships") or [],
                display_name=row.get("display_name") or "",
            )
            entries.setdefault(name, []).append(entry)
            if row.get("icon_path"):
                icon_map[name.lower()] = row["icon_path"]
        color_schemes: dict[str, ColorScheme] = {}
        for cname, cols in (self._cache.get_all_camo_color_schemes(self._bin_folder) or {}).items():
            color_schemes[cname] = ColorScheme(name=cname, colors=[list(c) for c in cols])
        self._db = {"entries": entries, "color_schemes": color_schemes,
                    "ship_groups": self._cache.get_all_camo_ship_groups(self._bin_folder)}
        self._icon_map = icon_map
        try:
            self._exteriors = self._cache.get_exteriors(self._bin_folder)
        except Exception:  # noqa: BLE001
            self._exteriors = []

    def _ensure_loaded(self):
        if self._db is not None:
            return
        if self._cache is not None and self._bin_folder:
            try:
                self._build_from_db()
                return
            except Exception:  # noqa: BLE001
                pass
        if self._extractor is None:
            self._db = {"entries": {}, "color_schemes": {}, "ship_groups": {}}
            return
        try:
            hits = self._extractor.list_files(["camouflages.xml"])
            if not hits:
                self._db = {"entries": {}, "color_schemes": {}, "ship_groups": {}}
                return
            e = hits[0]
            data = self._extractor.pkg_reader.read_file(e.volume.filename, e.file_info)
            self._db = parse_camouflages(data)
        except Exception:
            self._db = {"entries": {}, "color_schemes": {}, "ship_groups": {}}

    def _ship_group_match(self, entry: CamouflageEntry, ship_indexes: set[str]) -> bool:
        """条目是否命中某舰船：targetShip 精确命中，或 shipGroups 含该舰船所在组。"""
        if any(t in ship_indexes for t in entry.target_ships):
            return True
        for g in entry.ship_groups:
            members = self._db["ship_groups"].get(g)
            if members and (members & ship_indexes):
                return True
        return False

    def list_camos(self, ship_indexes: set[str],
                   ship_permoflages: set | list | None = None) -> list[CamoSchemeInfo]:
        """返回该船可切换涂装列表；第一项是「无涂装」。"""
        self._ensure_loaded()
        infos: list[CamoSchemeInfo] = [
            CamoSchemeInfo(id=0, display_name="无涂装", raw_name="stock", origin="none")
        ]
        # 归属权威来源：ship_permoflages（= Vehicle.permoflages()），含 nativePermoflage
        permo = set()
        for p in (ship_permoflages or ()):
            if isinstance(p, str):
                permo.add(p)
        # 由外装（Exterior）引用的 camo 条目名：这些 camo 以 permoflages 权威 + 多配色展开，
        # 跳过下方 entries 循环里的同名裸条目（避免「无配色」的重复项被选中导致变暗）。
        permo_camo_names = set()
        for ext in getattr(self, "_exteriors", []) or []:
            sp = (ext.get("species") or "").lower()
            if sp not in self._CAMO_SPECIES:
                continue
            if (ext.get("name") or "") in permo or (ext.get("index") or "") in permo:
                d = ext.get("data") or {}
                cn = d.get("camouflage") or d.get("unpeculiarCamouflage") or ""
                if cn:
                    permo_camo_names.add(cn)

        seen = set()
        for name, variants in self._db["entries"].items():
            if name in seen or name in permo_camo_names:
                continue
            # 找命中该船的 variant
            for entry in variants:
                if self._ship_group_match(entry, ship_indexes):
                    infos.append(CamoSchemeInfo(
                        id=len(infos),
                        display_name=entry.display_name or name,
                        raw_name=name,
                        origin="mat",
                        use_color_scheme=entry.use_color_scheme,
                        uv_transforms=entry.uv_transforms,
                        icon_path=self._icon_map.get(name.lower(), ""),
                        entry=entry,
                    ))
                    seen.add(name)
                    break

        # 5) Exterior 皮肤/永久/通用涂装：归属以 ship_permoflages（= Vehicle.permoflages()）权威
        #    带 hullConfig/nodesConfig/peculiarityModels → origin=model（替换模型）；
        #    否则按 camouflage/unpeculiarCamouflage 关联 camouflages.xml 条目 → origin=mat。
        for ext in getattr(self, "_exteriors", []) or []:
            sp = (ext.get("species") or "").lower()
            if sp not in self._CAMO_SPECIES:
                continue
            ext_name = ext.get("name") or ""
            ext_index = ext.get("index") or ""
            if not (ext_name in permo or ext_index in permo):
                continue
            data = ext.get("data") or {}
            hull_config = data.get("hullConfig") or {}
            nodes_config = data.get("nodesConfig") or {}
            pmodels = data.get("peculiarityModels") or {}
            key = ext_index or ext_name
            if key in seen:
                continue
            seen.add(key)
            if hull_config or nodes_config or pmodels:
                # 模型变体
                mf = ""
                for hv in (hull_config or {}).values():
                    if isinstance(hv, dict) and hv.get("model"):
                        mf = _dir_name(hv["model"])
                        break
                if not mf and pmodels:
                    for k, v in pmodels.items():
                        if _dir_name(k) in permo and "/" in v:
                            mf = _dir_name(v)
                            break
                infos.append(CamoSchemeInfo(
                    id=len(infos),
                    display_name=ext.get("display_name") or ext_name or key,
                    raw_name=key, origin="model",
                    icon_path=ext.get("icon_path") or "",
                    model_replace=dict(pmodels), model_folder=mf,
                    skin={"hull_config": hull_config, "nodes_config": nodes_config,
                          "peculiarity_models": pmodels, "model_folder": mf}))
            else:
                # 材质涂装：由 camouflage/unpeculiarCamouflage 关联 camouflages.xml 条目。
                # 一个 camo 可含多个 <colorSchemes>（不同配色）→ 每个配色展开为一个可选涂装
                camo_name = data.get("camouflage") or data.get("unpeculiarCamouflage") or ""
                entry = None
                if camo_name:
                    vs = (self._db or {}).get("entries", {}).get(camo_name) or []
                    entry = vs[0] if vs else None
                if entry is not None:
                    schemes = entry.color_schemes or ([entry.color_scheme] if entry.color_scheme else [])
                    base_name = ext.get("display_name") or ext_name or key
                    if not schemes:
                        infos.append(CamoSchemeInfo(
                            id=len(infos), display_name=base_name, raw_name=key, origin="mat",
                            icon_path=ext.get("icon_path") or "",
                            entry=replace(entry, colors=None)))
                    else:
                        for si, sch in enumerate(schemes):
                            cs = (self._db or {}).get("color_schemes", {}).get(sch)
                            e2 = replace(entry, colors=cs.colors if cs is not None else None)
                            dname = base_name
                            if len(schemes) > 1:
                                dname = f"{base_name}（配色{si + 1}）"
                            infos.append(CamoSchemeInfo(
                                id=len(infos), display_name=dname, raw_name=key, origin="mat",
                                icon_path=ext.get("icon_path") or "", entry=e2))
        return infos

    def entry_by_name(self, name: str, ship_indexes: set[str]) -> CamouflageEntry | None:
        self._ensure_loaded()
        for entry in self._db["entries"].get(name, []):
            if self._ship_group_match(entry, ship_indexes):
                return entry
        return None
