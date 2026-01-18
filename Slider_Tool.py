import os.path
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction
from .slider_tool_dock import SliderToolDock  # Importing your dock logic

class SliderTool:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dockwidget = None
        self.pluginIsActive = False

    def initGui(self):
        # --- MODIFIED: Removed Icon dependency for now ---
        # We create a simple text-based action so we don't need resources.py
        self.action = QAction('Slider Tool', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        
        # Add to Toolbar
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('&Slider Tool', self.action)

    def unload(self):
        # Cleanup
        self.iface.removePluginMenu('&Slider Tool', self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dockwidget:
            self.dockwidget.close()

    def run(self):
        # 1. Check if dock already exists
        if not self.dockwidget:
            self.dockwidget = SliderToolDock()
            # 2. Add it to the QGIS Interface (Right Side)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dockwidget)
        
        # 3. Show it
        self.dockwidget.show()