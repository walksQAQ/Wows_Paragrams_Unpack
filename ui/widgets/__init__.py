"""通用可视化控件包（纯表现层，不含业务逻辑）。"""

from ui.widgets.scifi_panel import (
    CrystalMark,
    HoloBackdrop,
    ScanStrip,
    SciFiPanel,
    SparkDot,
    apply_holo_enabled,
)
from ui.widgets.dialog_style import DIALOG_QSS, PRIMARY_BTN_QSS, HoloDialog, HoloWindow
from ui.widgets.scifi_button import SciFiButton
from ui.widgets.skin_art import (
    ART_SUBDIR,
    ART_SUFFIXES,
    ART_WIDTH,
    MIN_WINDOW_WIDTH,
    SkinArtSlot,
    SkinWatermarkOverlay,
    art_slot_visible,
    resolve_art_path,
    skin_art_files,
    skins_dir,
)

__all__ = ["HoloBackdrop", "SciFiPanel", "SparkDot", "CrystalMark", "ScanStrip",
           "apply_holo_enabled", "HoloDialog", "HoloWindow", "DIALOG_QSS",
           "PRIMARY_BTN_QSS", "SciFiButton",
           "SkinArtSlot", "SkinWatermarkOverlay", "ART_WIDTH", "MIN_WINDOW_WIDTH",
           "art_slot_visible", "resolve_art_path", "skin_art_files", "skins_dir",
           "ART_SUBDIR", "ART_SUFFIXES"]
