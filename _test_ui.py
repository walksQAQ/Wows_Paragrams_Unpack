"""Test the sub widget directly with aircraft config data"""
import sys, os
sys.path.insert(0, 'd:\\Wows Paragrams Unpack')

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from ui.detail_panel import DetailPanel
dp = DetailPanel()

# Simulate the aircraft sub_info data structure
sub_info = {
    "sub_labels": ["攻击机"],
    "sub_contents": {
        "攻击机": {
            "config_labels": ["A1 配置", "A2 配置"],
            "config_contents": {
                "A1 配置": ["飞机: Test 1", "速度: 100 kts"],
                "A2 配置": ["飞机: Test 2", "速度: 200 kts"],
            }
        }
    }
}

widget = dp._build_sub_widget(sub_info)
print(f"Widget created: {widget}")
print(f"Layout count: {widget.layout().count()}")

# Check the first page of the inner stack
inner_widget = dp.findChild(type(widget))
print("Test PASSED")
