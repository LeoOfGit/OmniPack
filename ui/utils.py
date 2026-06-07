from PySide6.QtWidgets import QPushButton, QDialogButtonBox, QMessageBox, QLabel, QDialog
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer, QObject, QEvent, Qt

def add_copy_details_button(dialog, get_details_func, button_box_or_layout):
    """
    Adds a 'Copy Info' button to a dialog that copies formatted details to the clipboard.
    
    :param dialog: The QDialog instance.
    :param get_details_func: A zero-argument function returning a string (the formatted details).
    :param button_box_or_layout: QDialogButtonBox or a QLayout where the button should be inserted.
    """
    copy_btn = QPushButton("📋 Copy Info")
    copy_btn.setAutoDefault(False)
    
    def on_copy():
        text = get_details_func()
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        
        # Temporary visual feedback
        original_text = copy_btn.text()
        copy_btn.setText("✓ Copied!")
        copy_btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: (copy_btn.setText(original_text), copy_btn.setEnabled(True)))
        
    copy_btn.clicked.connect(on_copy)
    
    if isinstance(button_box_or_layout, QDialogButtonBox):
        button_box_or_layout.addButton(copy_btn, QDialogButtonBox.ActionRole)
    else:
        button_box_or_layout.addWidget(copy_btn)
        
    return copy_btn

class GlobalDialogTextSelector(QObject):
    """
    An event filter that dynamically makes all labels inside QDialogs (including QMessageBoxes)
    selectable by mouse, allowing users to copy error and details text for troubleshooting.
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show:
            if isinstance(obj, QMessageBox):
                obj.setTextInteractionFlags(obj.textInteractionFlags() | Qt.TextSelectableByMouse)
            elif isinstance(obj, QLabel):
                parent = obj.parentWidget()
                is_in_dialog = False
                while parent is not None:
                    if isinstance(parent, QDialog):
                        is_in_dialog = True
                        break
                    parent = parent.parentWidget()
                if is_in_dialog:
                    obj.setTextInteractionFlags(obj.textInteractionFlags() | Qt.TextSelectableByMouse)
        return super().eventFilter(obj, event)

def install_global_dialog_text_selector(app):
    """
    Installs the GlobalDialogTextSelector event filter on the QApplication instance.
    """
    selector = GlobalDialogTextSelector(app)
    app.installEventFilter(selector)
    # Prevent garbage collection of the filter object
    app._global_dialog_text_selector = selector

def clear_layout(layout):
    """
    Safely removes and deletes all widgets and child layouts from a given layout.
    """
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())

def update_widget_style_property(widget, property_name, value):
    """
    Sets a dynamic stylesheet property on a widget and triggers QSS stylesheet re-evaluation.
    This avoids the standard Qt bug where stylesheet styles do not update when properties change.
    """
    widget.setProperty(property_name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
