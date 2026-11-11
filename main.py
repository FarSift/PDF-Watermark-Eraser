import sys
import os
import fitz
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, 
                               QGraphicsView, QGraphicsScene, QGraphicsRectItem, 
                               QCheckBox, QColorDialog, QFileDialog, QMessageBox, QLabel,
                               QComboBox, QProgressDialog)
from PySide6.QtGui import QPixmap, QImage, QIcon, QColor, QPen, QBrush
from PySide6.QtCore import Qt, QRectF, QSize

# ----------------- 兼容打包后的资源路径获取 -----------------
def get_resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ----------------- 自定义图形视图，支持拖拽画框 -----------------
class PDFViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        self.drawing = False
        self.start_point = None
        self.current_rect_item = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drawing = True
            self.start_point = self.mapToScene(event.pos())
            
            self.current_rect_item = QGraphicsRectItem(QRectF(self.start_point, self.start_point))
            pen = QPen(QColor(255, 0, 0, 200), 2)
            brush = QBrush(QColor(255, 0, 0, 50))
            self.current_rect_item.setPen(pen)
            self.current_rect_item.setBrush(brush)
            
            self.current_rect_item.setFlags(QGraphicsRectItem.ItemIsSelectable | QGraphicsRectItem.ItemIsMovable)
            self.scene.addItem(self.current_rect_item)
            self.setDragMode(QGraphicsView.RubberBandDrag)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing and self.current_rect_item:
            current_point = self.mapToScene(event.pos())
            rect = QRectF(self.start_point, current_point).normalized()
            self.current_rect_item.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drawing:
            self.drawing = False
            if self.current_rect_item and (self.current_rect_item.rect().width() < 5 or self.current_rect_item.rect().height() < 5):
                self.scene.removeItem(self.current_rect_item)
                self.current_rect_item = None
        super().mouseReleaseEvent(event)

    def get_all_rects(self):
        return [item.rect() for item in self.scene.items() if isinstance(item, QGraphicsRectItem)]

    def load_rects(self, rect_list):
        for r in rect_list:
            rect_item = QGraphicsRectItem(r)
            pen = QPen(QColor(255, 0, 0, 200), 2)
            brush = QBrush(QColor(255, 0, 0, 50))
            rect_item.setPen(pen)
            rect_item.setBrush(brush)
            rect_item.setFlags(QGraphicsRectItem.ItemIsSelectable | QGraphicsRectItem.ItemIsMovable)
            self.scene.addItem(rect_item)

    def clear_rects(self):
        for item in self.scene.items():
            if isinstance(item, QGraphicsRectItem):
                self.scene.removeItem(item)

    def fit_page(self):
        if self.scene.sceneRect().isValid():
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page()

# ----------------- 主窗口 -----------------
class PDFWatermarkRemover(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 智能去水印工具 - 开源版")
        self.resize(1200, 850)
        self.setAcceptDrops(True)

        logo_path = get_resource_path("logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

        self.doc = None
        self.current_page_num = 0
        self.scale = 1.5 
        self.fill_color = QColor(255, 255, 255)
        self.page_rects = {}
        self.last_dir = os.path.expanduser("~")

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        self.page_list = QListWidget()
        self.page_list.setFixedWidth(150)
        self.page_list.setIconSize(QSize(120, 160))
        self.page_list.currentRowChanged.connect(self.change_page)
        main_layout.addWidget(self.page_list)

        right_layout = QVBoxLayout()
        toolbar = QHBoxLayout()
        
        self.btn_open = QPushButton("📂 打开 PDF")
        self.btn_open.clicked.connect(self.open_pdf)
        
        self.btn_save = QPushButton("💾 执行并保存")
        self.btn_save.clicked.connect(self.save_pdf)
        self.btn_save.setEnabled(False)
        
        self.btn_clear = QPushButton("🧹 清空当前页选框")
        self.btn_clear.clicked.connect(self.clear_current_rects)
        
        toolbar.addWidget(self.btn_open)
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_clear)
        
        toolbar.addSpacing(20)
        toolbar.addWidget(QLabel("擦除模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("智能剔除对象（不伤底纹）", "smart")
        self.mode_combo.addItem("涂白覆盖（强力遮蔽）", "cover")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        toolbar.addWidget(self.mode_combo)

        self.btn_color = QPushButton("🎨 颜色: 白色")
        self.btn_color.clicked.connect(self.choose_color)
        self.btn_color.setEnabled(False)
        toolbar.addWidget(self.btn_color)

        self.chk_all_pages = QCheckBox("应用到所有页")
        self.chk_all_pages.setChecked(True)
        toolbar.addWidget(self.chk_all_pages)
        
        right_layout.addLayout(toolbar)

        self.viewer = PDFViewer()
        right_layout.addWidget(self.viewer)
        
        hint_label = QLabel("💡 提示：可拖拽PDF进窗口打开。画框后可用鼠标拉伸微调。要保护印章，请务必使用【智能剔除对象】模式！")
        hint_label.setStyleSheet("color: #d35400; font-weight: bold; padding: 5px;")
        hint_label.setWordWrap(True)
        right_layout.addWidget(hint_label)

        main_layout.addLayout(right_layout)

    # ===== 拖拽打开文件 (完善版) =====
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                if path.lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = event.mimeData().urls()[0].toLocalFile()
        self.open_pdf(path)

    def on_mode_changed(self, index):
        is_cover = self.mode_combo.currentData() == "cover"
        self.btn_color.setEnabled(is_cover)
        if not is_cover:
            self.btn_color.setText("🎨 颜色: (智能剔除)")
        else:
            self.btn_color.setText(f"🎨 颜色: {self.fill_color.name()}")

    def open_pdf(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择 PDF 文件", self.last_dir, "PDF Files (*.pdf)"
            )
        if not file_path:
            return

        self.last_dir = os.path.dirname(file_path)
        try:
            self.doc = fitz.open(file_path)
            self.page_list.clear()
            self.page_rects = {}
            
            for i in range(len(self.doc)):
                page = self.doc[i]
                mat = fitz.Matrix(0.2, 0.2) 
                pix = page.get_pixmap(matrix=mat)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                icon = QIcon(QPixmap.fromImage(img))
                self.page_list.addItem(QListWidgetItem(icon, f"第 {i+1} 页"))
            
            self.page_list.setCurrentRow(0)
            self.btn_save.setEnabled(True)
            self.setWindowTitle(f"PDF 智能去水印工具 - {os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开 PDF:\n{e}")

    def change_page(self, index):
        if not self.doc or index < 0:
            return
        
        self.page_rects[self.current_page_num] = self.viewer.get_all_rects()
        self.current_page_num = index
        page = self.doc[index]
        
        mat = fitz.Matrix(self.scale, self.scale)
        pix = page.get_pixmap(matrix=mat)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(img)
        
        self.viewer.scene.clear()
        self.viewer.scene.addPixmap(pixmap)
        self.viewer.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        
        if index in self.page_rects:
            self.viewer.load_rects(self.page_rects[index])

        self.viewer.fit_page()

    def clear_current_rects(self):
        self.viewer.clear_rects()
        self.page_rects[self.current_page_num] = []

    def choose_color(self):
        color = QColorDialog.getColor(self.fill_color, self, "选择覆盖颜色")
        if color.isValid():
            self.fill_color = color
            self.btn_color.setText(f"🎨 颜色: {color.name()}")
            self.btn_color.setStyleSheet(
                f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'}"
            )

    def save_pdf(self):
        if not self.doc:
            return
        
        self.page_rects[self.current_page_num] = self.viewer.get_all_rects()
        rects = self.page_rects.get(self.current_page_num, [])
        
        if not rects and self.chk_all_pages.isChecked():
            QMessageBox.warning(self, "提示", "请先在页面中框选要擦除的区域！")
            return

        default_name = "已去除水印_完美版.pdf"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存 PDF", os.path.join(self.last_dir, default_name), "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        mode = self.mode_combo.currentData()
        apply_to_all = self.chk_all_pages.isChecked()
        
        # 确定处理页数（用于进度条）
        total_pages = len(self.doc) if apply_to_all else 1
        progress = QProgressDialog("正在处理PDF，请稍候...", "取消", 0, total_pages, self)
        progress.setWindowTitle("处理中")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        try:
            pdf_rects = []
            for r in rects:
                x0, y0 = r.x() / self.scale, r.y() / self.scale
                x1, y1 = (r.x() + r.width()) / self.scale, (r.y() + r.height()) / self.scale
                pdf_rects.append(fitz.Rect(x0, y0, x1, y1))

            processed = 0
            for page_num in range(len(self.doc)):
                if progress.wasCanceled():
                    break
                if not apply_to_all and page_num != self.current_page_num:
                    continue
                
                page = self.doc[page_num]
                for pdf_rect in pdf_rects:
                    if mode == "cover":
                        page.draw_rect(
                            pdf_rect, 
                            color=None, 
                            fill=(self.fill_color.redF(), self.fill_color.greenF(), self.fill_color.blueF()), 
                            overlay=True
                        )
                    elif mode == "smart":
                        # 【关键修复】：这里必须是 fill=None，不能填白色，否则会遮挡印章
                        page.add_redact_annot(pdf_rect, fill=None)

                if mode == "smart":
                    try:
                        page.apply_redactions(
                            images=fitz.PDF_REDACT_IMAGE_REMOVE, 
                            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE, 
                            text=fitz.PDF_REDACT_TEXT_REMOVE
                        )
                    except AttributeError:
                        page.apply_redactions()

                processed += 1
                progress.setValue(processed)
                QApplication.processEvents()

            if not progress.wasCanceled():
                self.doc.save(output_path, garbage=4, deflate=True)
                QMessageBox.information(self, "成功", f"处理完成！\n已保存至：{output_path}")
                
                self.doc.close()
                self.doc = fitz.open(output_path)
                self.change_page(self.current_page_num)
                self.last_dir = os.path.dirname(output_path)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理失败:\n{str(e)}")
        finally:
            progress.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("QWidget { font-size: 14px; font-family: 'Microsoft YaHei'; }")
    window = PDFWatermarkRemover()
    window.show()
    sys.exit(app.exec())