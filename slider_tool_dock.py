import os
from qgis.core import (
    QgsRasterLayer,
    QgsSingleBandGrayRenderer,
    QgsContrastEnhancement,
    QgsRasterBandStats,
    QgsRasterDataProvider,
    QgsTask,
    QgsApplication
)
from qgis.utils import iface
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, 
    QDockWidget, QPushButton, QProgressBar, 
    QHBoxLayout, QToolButton
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

# --- WORKER THREAD ---
class CacheWorker(QgsTask):
    progress_update = pyqtSignal(int, int, float) 
    finished_data = pyqtSignal(dict) 

    def __init__(self, layer, extent, width, height):
        super().__init__("Warming Cache", QgsTask.CanCancel)
        self.layer = layer
        self.extent = extent
        self.width = width
        self.height = height
        self.stats_lut = {}
        self.exception = None

    def run(self):
        try:
            provider = self.layer.dataProvider()
            band_count = self.layer.bandCount()

            for band_i in range(1, band_count + 1):
                if self.isCanceled(): return False

                # 1. Warm Cache (Read Block)
                _ = provider.block(band_i, self.extent, self.width, self.height)

                # 2. Calculate Stats
                stats = provider.bandStatistics(
                    band_i, QgsRasterBandStats.All, self.extent, sampleSize=25000 
                )
                min_v = stats.mean - (2.0 * stats.stdDev)
                max_v = stats.mean + (2.0 * stats.stdDev)

                if min_v < stats.minimumValue: min_v = stats.minimumValue
                if max_v > stats.maximumValue: max_v = stats.maximumValue
                if max_v <= min_v: 
                    min_v, max_v = stats.minimumValue, stats.maximumValue

                self.stats_lut[band_i] = (min_v, max_v)

                prog = (band_i / band_count) * 100
                self.progress_update.emit(band_i, band_count, prog)

            self.finished_data.emit(self.stats_lut)
            return True
        except Exception as e:
            self.exception = e
            return False

    def finished(self, result):
        if not result and self.exception: print(f"Worker Error: {self.exception}")

# --- MAIN DOCK WIDGET ---
class SliderToolDock(QDockWidget):
    def __init__(self, parent=None):
        super(SliderToolDock, self).__init__(parent)
        self.setObjectName("SliderToolDock")
        self.setWindowTitle("Band Scrubber")

        # State
        self.current_layer = None
        self.stats_lut = {} 
        self.active_ce = None 
        self.worker_task = None
        self.play_timer = QTimer()
        self.play_timer.setInterval(200)
        self.play_timer.timeout.connect(self.next_band)

        self.init_ui()

    def init_ui(self):
        self.main_widget = QWidget()
        self.layout = QVBoxLayout()
        self.main_widget.setLayout(self.layout)
        self.setWidget(self.main_widget)

        self.lbl_info = QLabel("Select Raster & Click Prepare")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.lbl_info)

        self.lbl_band = QLabel("Band: -")
        self.lbl_band.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.lbl_band.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.lbl_band)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.update_renderer)
        self.layout.addWidget(self.slider)

        btn_layout = QHBoxLayout()
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setCheckable(True)
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self.toggle_play)
        btn_layout.addWidget(self.btn_play)

        self.btn_prep = QPushButton("PREPARE")
        self.btn_prep.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_prep.clicked.connect(self.start_preparation)
        btn_layout.addWidget(self.btn_prep)
        self.layout.addLayout(btn_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.layout.addWidget(self.progress)
        self.layout.addStretch()

    def start_preparation(self):
        layer = iface.activeLayer()
        if not isinstance(layer, QgsRasterLayer):
            self.lbl_info.setText("Error: No Raster Selected")
            return

        # Safe Cancel
        if self.worker_task: 
            self.worker_task.cancel()
            self.worker_task = None
        
        self.current_layer = layer
        provider = layer.dataProvider()
        
        renderer = QgsSingleBandGrayRenderer(provider, 1)
        ce = QgsContrastEnhancement(provider.dataType(1))
        ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
        renderer.setContrastEnhancement(ce)
        layer.setRenderer(renderer)
        self.active_ce = renderer.contrastEnhancement()
        layer.triggerRepaint()
        
        # --- FIX 1: Force Layer Tree Update Initial ---
        iface.layerTreeView().refreshLayerSymbology(layer.id())

        canvas = iface.mapCanvas()
        width = min(canvas.mapSettings().outputSize().width(), 1000)
        height = min(canvas.mapSettings().outputSize().height(), 1000)

        self.btn_prep.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_info.setText("Caching...")

        self.worker_task = CacheWorker(layer, canvas.extent(), width, height)
        self.worker_task.progress_update.connect(self.on_progress)
        self.worker_task.finished_data.connect(self.on_finished)
        QgsApplication.taskManager().addTask(self.worker_task)

    def on_progress(self, current, total, percent):
        self.progress.setValue(int(percent))
        self.lbl_band.setText(f"Loading {current}/{total}")

    def on_finished(self, stats_lut):
        # --- FIX 2: Clear the worker reference now that it's done ---
        self.worker_task = None 
        
        self.stats_lut = stats_lut
        self.progress.setVisible(False)
        self.btn_prep.setEnabled(True)
        self.lbl_info.setText("Ready.")
        
        self.slider.blockSignals(True)
        self.slider.setRange(1, self.current_layer.bandCount())
        self.slider.setValue(1)
        self.slider.blockSignals(False)
        self.slider.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.update_renderer(1)

    def update_renderer(self, band_index):
        if not self.current_layer or not self.current_layer.isValid(): return
        self.lbl_band.setText(f"Band {band_index}")
        min_v, max_v = self.stats_lut.get(band_index, (0, 255))
        
        self.current_layer.renderer().setGrayBand(band_index)
        if self.active_ce:
            self.active_ce.setMinimumValue(min_v)
            self.active_ce.setMaximumValue(max_v)
        
        self.current_layer.triggerRepaint()
        
        # --- FIX 3: Force the Legend (TOC) to update its text ---
        iface.layerTreeView().refreshLayerSymbology(self.current_layer.id())

    def toggle_play(self):
        if self.btn_play.isChecked():
            self.btn_play.setText("⏸")
            self.play_timer.start()
        else:
            self.btn_play.setText("▶")
            self.play_timer.stop()

    def next_band(self):
        curr = self.slider.value()
        next_val = curr + 1 if curr < self.slider.maximum() else 1
        self.slider.setValue(next_val)

    def closeEvent(self, event):
        # --- FIX 4: Robust Close Handling ---
        # Only try to cancel if the task exists AND is still valid in Python
        if self.worker_task:
            try:
                self.worker_task.cancel()
            except RuntimeError:
                # The C++ object was already deleted, which is fine
                pass
        
        self.worker_task = None
        self.play_timer.stop()
        super().closeEvent(event)