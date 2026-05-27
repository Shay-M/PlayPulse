def load_stylesheet() -> str:
    return """
QWidget {
    background: #F6F7FB;
    color: #111827;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 12px;
}
QLabel {
    background: transparent;
}
QScrollArea#pageScroll {
    background: #F6F7FB;
    border: none;
}
QScrollArea#pageScroll > QWidget > QWidget {
    background: #F6F7FB;
}
#sidebar {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
}
#sidebarTitle {
    color: #111827;
    font-size: 20px;
    font-weight: 800;
}
#sidebarSubtitle {
    color: #6B7280;
    font-size: 12px;
}
#navigationButton {
    min-height: 40px;
    padding: 9px 12px;
    border: none;
    text-align: left;
    color: #374151;
    border-radius: 8px;
    background: transparent;
    font-weight: 600;
}
#navigationButton:hover {
    background: #EFF6FF;
    color: #1D4ED8;
}
#navigationButton[active="true"] {
    background: #E0E7FF;
    color: #1D4ED8;
    font-weight: 800;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QFrame#inlinePanel {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QFrame#previewCard {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
}
QFrame#phonePlaceholder {
    background: #F3F4F6;
    border: 1px dashed #CBD5E1;
    border-radius: 8px;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 800;
}
QLabel#pageSubtitle {
    color: #6B7280;
    font-size: 13px;
}
QLabel#cardTitle {
    color: #111827;
    font-size: 14px;
    font-weight: 800;
}
QLabel#fieldLabel {
    color: #374151;
    font-weight: 700;
}
QLabel#helperText, QLabel#mutedText, QLabel#progressPanelStatus {
    color: #6B7280;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #BFDBFE;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #2563EB;
}
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QPushButton {
    background: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
    min-height: 20px;
}
QPushButton:hover {
    background: #1D4ED8;
}
QPushButton:disabled {
    background: #CBD5E1;
    color: #F8FAFC;
}
QPushButton#secondaryButton {
    background: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
}
QPushButton#secondaryButton:hover {
    background: #DBEAFE;
}
QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    gridline-color: #EEF2F7;
    alternate-background-color: #F9FAFB;
}
QTableWidget::item {
    padding: 7px;
}
QTableWidget::item:selected {
    background: #DBEAFE;
    color: #111827;
}
QHeaderView::section {
    background: #F3F4F6;
    border: none;
    border-bottom: 1px solid #E5E7EB;
    color: #374151;
    font-weight: 800;
    padding: 8px;
}
QProgressBar {
    border: 1px solid #D1D5DB;
    border-radius: 7px;
    background: #F3F4F6;
    height: 14px;
    text-align: center;
    color: #374151;
}
QProgressBar::chunk {
    background: #4F46E5;
    border-radius: 7px;
}
QListWidget {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 6px;
}
QListWidget::item {
    padding: 8px;
    border-radius: 6px;
}
QListWidget::item:selected {
    background: #DBEAFE;
    color: #111827;
}
QPlainTextEdit {
    line-height: 1.35;
}
QLabel#statusBadge {
    font-size: 11px;
}
"""
