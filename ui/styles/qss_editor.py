import sys
import re
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QTabWidget, QScrollArea, QLabel, QSpinBox, QDoubleSpinBox,
                               QPushButton, QFrame, QCheckBox, QMessageBox, QColorDialog)
from PySide6.QtGui import QColor, QPalette, QIcon
from PySide6.QtCore import Qt

class ColorEntry:
    def __init__(self, line_idx, category, description, selector, prop_name, color_format, values, original_line):
        self.line_idx = line_idx
        self.category = category
        self.description = description
        self.selector = selector
        self.prop_name = prop_name
        self.color_format = color_format
        self.values = values.copy()
        self.original_line = original_line

def parse_qss(file_path):
    entries = []
    lines = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    category = "Global & Uncategorized"
    description = ""
    selector = ""
    in_block = False
    selector_buffer = []
    
    for i, line in enumerate(lines):
        line_strip = line.strip()
        
        # Detect Category from comments like /* 1. GLOBAL & WINDOW STYLES ... */
        cat_match = re.match(r'^\s*(\d+\.\s+.*)', line_strip)
        if cat_match:
            category = cat_match.group(1).replace("*/", "").strip()
            
        # Detect Description from other comments
        if line_strip.startswith("/*") and "====" not in line_strip:
            desc = line_strip.replace("/*", "").replace("*/", "").strip()
            if not re.match(r'^\d+\.', desc):
                description = desc
                
        # Parse CSS Blocks
        if "{" in line_strip:
            in_block = True
            part = line_strip.split("{")[0].strip()
            if part:
                selector_buffer.append(part)
            selector = " ".join(selector_buffer)
            # Clean up trailing comments in selector string
            selector = re.sub(r'/\*.*?\*/', '', selector).strip()
            selector_buffer = []
        elif "}" in line_strip:
            in_block = False
            selector = ""
            description = ""
        elif not in_block and line_strip and not line_strip.startswith("/*") and not line_strip.startswith("*"):
            selector_buffer.append(line_strip)
            
        if in_block:
            # Match CSS property lines, including Qt specific qproperty-*
            prop_match = re.search(r'^\s*(qproperty-[a-zA-Z\_]+|[a-zA-Z\-]+)\s*:', line)
            if prop_match:
                prop_name = prop_match.group(1)
                
                # Match color formats
                hsv_match = re.search(r'hsv\((\d+),\s*(\d+),\s*(\d+)\)', line)
                rgba_match = re.search(r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d\.]+)\)', line)
                
                if hsv_match:
                    entries.append(ColorEntry(i, category, description, selector, prop_name, "hsv", 
                                             [int(hsv_match.group(1)), int(hsv_match.group(2)), int(hsv_match.group(3))],
                                             line))
                elif rgba_match:
                    entries.append(ColorEntry(i, category, description, selector, prop_name, "rgba", 
                                             [int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3)), float(rgba_match.group(4))],
                                             line))
    return entries, lines

class ColorEditorRow(QFrame):
    def __init__(self, entry, on_change_callback):
        super().__init__()
        self.entry = entry
        self.on_change_callback = on_change_callback
        
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("ColorEditorRow { background-color: #2d2d30; border: 1px solid #3e3e42; border-radius: 6px; }")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(15)
        
        # --- Left: Meta Info ---
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        sel_label = QLabel(entry.selector)
        sel_label.setStyleSheet("font-weight: bold; color: #d4d4d4; font-size: 13px; font-family: Consolas, monospace;")
        sel_label.setWordWrap(True)
        
        prop_label = QLabel(f"{entry.prop_name}: {entry.color_format}(...)")
        prop_label.setStyleSheet("color: #9cdcfe; font-family: Consolas, monospace; font-size: 12px;")
        prop_label.setWordWrap(True)
        
        info_layout.addWidget(sel_label)
        info_layout.addWidget(prop_label)
        info_layout.addStretch()
        
        layout.addLayout(info_layout, stretch=4)
        
        # --- Middle: Numeric Controls ---
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(8)
        
        self.spinboxes = []
        if entry.color_format == "hsv":
            labels = ["H", "S", "V"]
            ranges = [(0, 359), (0, 255), (0, 255)]
        else:
            labels = ["R", "G", "B", "A"]
            ranges = [(0, 255), (0, 255), (0, 255), (0.0, 1.0)]
            
        for i, (lbl_txt, (vmin, vmax)) in enumerate(zip(labels, ranges)):
            v_layout = QVBoxLayout()
            v_layout.setSpacing(2)
            
            lbl = QLabel(lbl_txt)
            lbl.setStyleSheet("color: #858585; font-size: 11px; font-weight: bold;")
            lbl.setAlignment(Qt.AlignCenter)
            
            if isinstance(vmax, float):
                sp = QDoubleSpinBox()
                sp.setRange(vmin, vmax)
                sp.setSingleStep(0.1)
                sp.setValue(entry.values[i])
            else:
                sp = QSpinBox()
                sp.setRange(vmin, vmax)
                sp.setValue(entry.values[i])
                
            sp.setKeyboardTracking(False) # Allows typing the whole number before updating
            sp.setFocusPolicy(Qt.WheelFocus) # Enable scroll wheel support when focused/hovered
            sp.setStyleSheet("""
                QSpinBox, QDoubleSpinBox { 
                    background: #1e1e1e; 
                    color: #d4d4d4; 
                    border: 1px solid #3e3e42; 
                    border-radius: 3px; 
                    padding: 4px; 
                    min-width: 45px;
                }
                QSpinBox::up-button, QDoubleSpinBox::up-button, 
                QSpinBox::down-button, QDoubleSpinBox::down-button { 
                    width: 16px; 
                }
            """)
            sp.valueChanged.connect(self.on_value_changed)
            self.spinboxes.append(sp)
            
            v_layout.addWidget(lbl)
            v_layout.addWidget(sp)
            v_layout.addStretch()
            
            ctrl_layout.addLayout(v_layout)
            
        layout.addLayout(ctrl_layout, stretch=3)
        
        # --- Right: Live Preview Block ---
        self.preview_btn = QPushButton()
        self.preview_btn.setFixedSize(110, 50)
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self.open_color_picker)
        layout.addWidget(self.preview_btn, stretch=1)
        
        self.update_preview()
        
    def open_color_picker(self):
        v = self.entry.values
        if self.entry.color_format == "hsv":
            current_color = QColor.fromHsv(v[0], v[1], v[2])
        else:
            alpha_val = int(v[3] * 255)
            current_color = QColor(v[0], v[1], v[2], alpha_val)
            
        color = QColorDialog.getColor(current_color, self, "Select Color", QColorDialog.ShowAlphaChannel)
        if color.isValid():
            if self.entry.color_format == "hsv":
                h = max(0, color.hsvHue())
                s = color.hsvSaturation()
                v_val = color.value()
                self.spinboxes[0].setValue(h)
                self.spinboxes[1].setValue(s)
                self.spinboxes[2].setValue(v_val)
            else:
                self.spinboxes[0].setValue(color.red())
                self.spinboxes[1].setValue(color.green())
                self.spinboxes[2].setValue(color.blue())
                self.spinboxes[3].setValue(color.alphaF())
                
    def on_value_changed(self):
        for i, sp in enumerate(self.spinboxes):
            self.entry.values[i] = sp.value()
        self.update_preview()
        self.on_change_callback(self.entry)
        
    def update_preview(self):
        v = self.entry.values
        if self.entry.color_format == "hsv":
            color = QColor.fromHsv(v[0], v[1], v[2])
            css_color = color.name() # Return hex string for background-color mapping
        else:
            alpha_val = int(v[3] * 255)
            color = QColor(v[0], v[1], v[2], alpha_val)
            css_color = f"rgba({v[0]}, {v[1]}, {v[2]}, {v[3]})"
            
        self.preview_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {css_color}; 
                border: 2px solid #555; 
                border-radius: 6px;
            }}
        """)

class QssEditor(QMainWindow):
    def __init__(self, qss_path):
        super().__init__()
        self.qss_path = qss_path
        self.entries = []
        self.lines = []
        
        self.setWindowTitle(f"OmniPack QSS Visual Editor - {os.path.basename(qss_path)}")
        self.resize(900, 800)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QTabWidget::pane { border: 1px solid #3e3e42; border-radius: 4px; }
            QTabBar::tab { 
                background: #2d2d30; 
                color: #9d9d9d; 
                padding: 10px 16px; 
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected { 
                background: #1e1e1e; 
                color: #ffffff; 
                font-weight: bold; 
                border: 1px solid #3e3e42; 
                border-bottom: none; 
            }
            QScrollArea { border: none; background-color: #1e1e1e; }
            QScrollArea > QWidget > QWidget { background-color: #1e1e1e; }
        """)
        
        main_widget = QWidget()
        m_layout = QVBoxLayout(main_widget)
        m_layout.setContentsMargins(10, 10, 10, 10)
        
        # Header Info
        header = QLabel(f"<b>Target:</b> {self.qss_path}")
        header.setStyleSheet("color: #007acc; font-size: 14px; margin-bottom: 8px;")
        m_layout.addWidget(header)
        
        self.tabs = QTabWidget()
        m_layout.addWidget(self.tabs)
        
        # Bottom Actions Panel
        self.bottom_panel = QWidget()
        b_layout = QHBoxLayout(self.bottom_panel)
        b_layout.setContentsMargins(0, 10, 0, 0)
        
        self.live_save_cb = QCheckBox("Live Save (Auto-update file on adjust)")
        self.live_save_cb.setChecked(True)
        self.live_save_cb.setStyleSheet("color: #cccccc; font-size: 13px;")
        
        save_btn = QPushButton("Save Config Manually")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton { 
                background-color: #0e639c; 
                color: white; 
                border: none; 
                padding: 8px 24px; 
                border-radius: 4px; 
                font-weight: bold; 
                font-size: 14px;
            }
            QPushButton:hover { background-color: #1177bb; }
            QPushButton:pressed { background-color: #094771; }
        """)
        save_btn.clicked.connect(self.save_to_file)
        
        b_layout.addWidget(self.live_save_cb)
        b_layout.addStretch()
        b_layout.addWidget(save_btn)
        
        m_layout.addWidget(self.bottom_panel)
        self.setCentralWidget(main_widget)
        
        self.load_data()
        
    def load_data(self):
        if not os.path.exists(self.qss_path):
            QMessageBox.critical(self, "Error", f"File not found: {self.qss_path}")
            sys.exit(1)
            
        try:
            self.entries, self.lines = parse_qss(self.qss_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse QSS:\n{e}")
            return
            
        # Group entries by parsed category
        categories = {}
        for entry in self.entries:
            if entry.category not in categories:
                categories[entry.category] = []
            categories[entry.category].append(entry)
            
        for cat, entries in categories.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            
            container = QWidget()
            v_layout = QVBoxLayout(container)
            v_layout.setContentsMargins(10, 10, 10, 10)
            v_layout.setSpacing(12)
            
            for entry in entries:
                row = ColorEditorRow(entry, self.on_color_changed)
                v_layout.addWidget(row)
                
            v_layout.addStretch()
            scroll.setWidget(container)
            
            # Formatting the tab names visually
            cat_name = cat.split("/")[0].strip() if "/" in cat else cat
            cat_name = re.sub(r'^\d+\.\s*', '', cat_name)
            self.tabs.addTab(scroll, cat_name)
            
    def on_color_changed(self, entry):
        v = entry.values
        if entry.color_format == "hsv":
            new_val = f"hsv({v[0]}, {v[1]}, {v[2]})"
            pattern = r'hsv\(\d+,\s*\d+,\s*\d+\)'
        else:
            new_val = f"rgba({v[0]}, {v[1]}, {v[2]}, {v[3]})"
            pattern = r'rgba\(\d+,\s*\d+,\s*\d+,\s*[\d\.]+\)'
            
        self.lines[entry.line_idx] = re.sub(pattern, new_val, self.lines[entry.line_idx])
        
        if self.live_save_cb.isChecked():
            self.do_save()
            
    def save_to_file(self):
        self.do_save()
        QMessageBox.information(self, "Saved", "QSS file saved successfully!")
        
    def do_save(self):
        try:
            with open(self.qss_path, 'w', encoding='utf-8') as f:
                f.writelines(self.lines)
        except Exception as e:
            print(f"Auto-save failed: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Better looking across platforms
    
    # Try resolving path naturally or use passed argument
    default_qss = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dark.qss")
    qss_path = sys.argv[1] if len(sys.argv) > 1 else default_qss
    
    editor = QssEditor(qss_path)
    editor.show()
    sys.exit(app.exec())
