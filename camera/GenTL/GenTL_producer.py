"""
This plugin allows to control a camera through the associated GenTL Producer using the haversters
library.
"""
import functools
import os
from threading import Thread
import time
import typing

from harvesters.core import Buffer, Harvester, ImageAcquirer
from genicam.gentl import TimeoutException
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import xarray as xr

import analyzr2

# ==== Custom parameters

class DeviceInfo(typing.NamedTuple):
    """
    Tuple for GenTL Producer device information transfert between GUI and backend.
    """
    display_name: str
    cti_path: str

class _CameraFinder(analyzr2.inputs.ParameterWidget):
    """
    A widget that allows listing the available devices from a given *.cti file.
    """
    def __init__(self, **kwargs):
        super().__init__(display=None)
        # File browser
        self.file_browser = analyzr2.parameters.file_select(
            fopen=True, ftype=("CTI (*.cti)",), existing=True
        )()
        self.file_browser.validate.connect(self.discover)
        self.cti_path = analyzr2.Undefined
        # Combobox listing cameras
        self.combobox = QtWidgets.QComboBox()
        self.combobox.currentIndexChanged.connect(self.send_device_data)
        # Refresh button
        self.refresh = QtWidgets.QPushButton("Refresh")
        self.refresh.clicked.connect(self.discover)
        self.refresh.setEnabled(False)
        # Design
        self.setLayout(QtWidgets.QGridLayout())
        self.layout().addWidget(QtWidgets.QLabel("CTI file"), 0, 0, 1, 1)
        self.layout().addWidget(QtWidgets.QLabel("Devices"), 1, 0, 1, 1)
        self.layout().addWidget(self.file_browser, 0, 1, 1, 2)
        self.layout().addWidget(self.combobox, 1, 1, 1, 1)
        self.layout().addWidget(self.refresh, 1, 2, 1, 1)
        self.layout().setColumnStretch(0, 1)
        self.layout().setColumnStretch(1, 3)
        self.layout().setColumnStretch(2, 1)
        self.layout().setContentsMargins(QtCore.QMargins(0, 0, 0, 0))

    def discover(self, cti_path: str = None):
        """
        Search for all available devices from the specified CTI file.
        If no CTI file is specified, use the last saved CTI file.
        """
        if cti_path is not None:
            self.cti_path = cti_path
        # Enable Refresh button (default to disabled to prevent refresh without file)
        self.refresh.setEnabled(True)
        # Clear all current items
        self.combobox.clear()
        # Create Harvester object, and search for devices
        try:
            with Harvester() as harvester:
                harvester.add_file(self.cti_path, check_existence=True)
                harvester.update()
                # Update items
                for device_info in harvester.device_info_list:
                    self.combobox.addItem(device_info.display_name, device_info.display_name)
        except FileNotFoundError:
            analyzr2.logger.error(f"Cannot find requested CTI file at: {self.cti_path}")
        if self.combobox.count() == 0:
            analyzr2.logger.warning("No GenTL Producer devices detected.")
        # Reset value to what is was before (if device still exists)
        self.combobox.setCurrentIndex(self.combobox.findData(self._current))

    def send_device_data(self, _: int):
        """
        Send the device name and associated CTI file to the Block.
        The CTI file is necessary for the Block harvester to be able to find the device.
        """
        # Prevent sending data when reselecting the current camera
        if self.combobox.currentData() != self._current:
            self.confirm(DeviceInfo(self.combobox.currentData(), self.cti_path))
            self._current = self.combobox.currentData()

# ==== Widgets

class _VideoDisplay(QtWidgets.QLabel):
    """
        Specialized QLabel for camera feedback display.
        Allow display of a reticle.
    """

    def __init__(self):
        super().__init__(text='')
        self.setScaledContents(True)
        # Internal values
        self.show_reticle = False

    def update_reticle(self, enabled):
        """Update flag for drawing the camera reticle and request a repaint."""
        self.show_reticle = enabled
        self.update()

    def paintEvent(self, event):
        """Reimplemented. Paint the center target if required."""
        super().paintEvent(event)
        # Only paint reticle if required and if image is displayed
        if not self.pixmap().isNull() and self.show_reticle:
            painter = QtGui.QPainter(self)
            painter.setPen("red")
            # Horizontal line
            painter.drawLine(
                self.width() / 2 - 10, self.height() / 2,
                self.width() / 2 + 10, self.height() / 2
            )
            # Vertical line
            painter.drawLine(
                self.width() / 2, self.height() / 2 - 10,
                self.width() / 2, self.height() / 2 + 10
            )

class _CameraDisplay(analyzr2.widgets.EmbeddedWidget):
    """
    Simple embedded widget used to display the received camera images.
    """
    def __init__(self):
        super().__init__()
        # Add video display
        self.display = _VideoDisplay()
        self.layout().addWidget(self.display)
        # Minimum is set to half the camera resolution (GoldEye G-033 TEC1)
        self.display.setMinimumWidth(320)
        self.display.setMinimumHeight(256)
        self.display.setScaledContents(True)
        # Add screenshot button
        self.screenshot_button = _FixedSizeButton("Save screenshot")
        self.screenshot_button.clicked.connect(self.save_image)
        self.layout().addWidget(self.screenshot_button)
        # Update minimum size
        self.setMinimumSize(
            self.display.minimumWidth(),
            self.display.minimumHeight() + self.screenshot_button.height()
        )
        self.prevent_update = time.time()
        self.shared_array = None

    def update_reticle(self, enabled):
        """Update flag for drawing the camera reticle and request a repaint."""
        self.display.show_reticle = enabled
        self.update()

    def save_image(self):
        """Save the displayed image to the chosen path."""
        # Check if image is available
        if self.shared_array:
            separator = ' ' if os.name == 'posix' else ';'
            # Open save dialog
            filename = QtWidgets.QFileDialog.getSaveFileName(
                None, 'Save screenshot...', os.getcwd(),
                f"Image files ({separator.join(['*.bmp', '*.jpg', '*.png'])})"
            )
            filestr = filename[0].replace('\\', '/')
            # If invalid path received
            if filestr == '':
                analyzr2.logger.warning("Invalid path.")
            else:
                # Save pixmap
                res = self.display.pixmap().save(filestr)
                if res:
                    analyzr2.logger.success(f"Saved screenshot at {filestr}.")
                else:
                    analyzr2.logger.error("Error while saving screenshot.")
        else:
            analyzr2.logger.warning("No image to save.")

    def update_image_from_array(self, array_info):
        """
        Change the image displayed from a SharedArray.

        :param SharedArrayInfo array_info:
            Information about the SharedArray
        """
        # Update if not resizing for 1 sec
        if time.time() - self.prevent_update > 1:
            # Create array from received data
            self.shared_array = analyzr2.data.SharedArray.open(array_info)
            height, width = array_info.np_info.shape
            qimage = QtGui.QImage(
                self.shared_array.np_arr, width, height, QtGui.QImage.Format.Format_Grayscale8
            )
            # Update image
            self.display.setPixmap(QtGui.QPixmap.fromImage(qimage))

    def refresh_image(self):
        """Refresh the image displayed from the opened shared array."""
        # Update if not resizing for 1 sec and shared array is opened
        if time.time() - self.prevent_update > 1 and self.shared_array:
            height, width = self.shared_array.np_arr.shape
            qimage = QtGui.QImage(
                self.shared_array.np_arr, width, height, QtGui.QImage.Format.Format_Grayscale8
            )
            # Update image
            self.display.setPixmap(QtGui.QPixmap.fromImage(qimage))

    def clear_image(self):
        """Clear the displayed image."""
        self.display.clear()

    def resizeEvent(self, event):
        # Update prevent update timer when resizing
        self.prevent_update = time.time()
        return super().resizeEvent(event)

class _CameraConfig(analyzr2.widgets.EmbeddedWidget):
    """
    Embedded widget allowing configuration of some camera properties.
    """

    # Signals from child widgets
    reticle_checked = QtCore.Signal(bool)

    def __init__(self):
        super().__init__(QtWidgets.QHBoxLayout)
        # Create config widgets
        self.camera_reticle = analyzr2.widgets.embedded.CheckBox(text="Show reticle", checked=False)
        # Rewire signals
        self.camera_reticle.checked.connect(self.reticle_checked)
        # Build layout
        self.layout().addWidget(self.camera_reticle)

class _FixedSizeButton(analyzr2.widgets.embedded.Button):

    def __init__(self, text):
        super().__init__(text)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )
        self.setFixedHeight(24)

# ==== Blocks

class GenTLProducer(analyzr2.Block):
    """
    Open a GenTL Producer device associated with a compatible camera.

    Parameters
    ----------
    _device : DeviceInfo
        Information on the device to open (name, associated cti_file).
    """
    BUTTON_START = "Start streaming"
    BUTTON_STOP = "Stop streaming"
    MAX_CONSECUTIVE_TIMEOUT = 10

    parameters = {
        "_device": functools.partial(_CameraFinder)
    }

    widgets = {
        "camera_display": {
            analyzr2.widgets.Config: {
                "type": functools.partial(_CameraDisplay)
            }
        },
        "camera_control": {
            analyzr2.widgets.Config: {
                "type": functools.partial(_FixedSizeButton, "Start streaming")
            },
            analyzr2.widgets.Connect: {
                "clicked": "start_stop_streaming"
            }
        },
        "camera_config" : {
            analyzr2.widgets.Config: {
                "type": _CameraConfig
            },
            analyzr2.widgets.Connect: {
                "reticle_checked" : "update_reticle"
            }
        }
    }

    def create(self):
        self.ready = False
        self.shared_array = None
        self.streaming = False
        self.thread = None

    def process(self):
        # Start/stop streaming depending on current state
        self.start_stop_streaming()

    def clean(self):
        self.streaming = False
        # Wait for thread to end
        if isinstance(self.thread, Thread):
            self.thread.join(timeout=5)
        # Reset button text and clear camera
        self.camera_control.set_text(self.BUTTON_START)
        self.camera_display.clear_image()

    # Custom methods

    def update_reticle(self, enabled):
        """Update the camera reticle flag."""
        self.camera_display.update_reticle(enabled)

    @analyzr2.callback("_device")
    def configure_device(self):
        """
        Read the device information from the parameter.
        """
        self._device = DeviceInfo(*self._device)
        self.device = self._device.display_name
        self.cti_path = self._device.cti_path
        self.ready = True

    def streaming_context(self):
        """
        Run inside a thread. Regularly fetches new images.
        """
        # Create harvester and update with new CTI file
        harvester = Harvester()
        harvester.add_file(self.cti_path)
        harvester.update()
        with harvester.create({"display_name": self.device}) as acquirer:
            consecutive_timeout = 0
            # Configure image acquirer
            self.configure_acquirer(acquirer)
            acquirer.start()
            # Continuously fetch new images
            while self.streaming:
                try:
                    with acquirer.fetch() as buffer:
                        self.update_frame(buffer)
                    consecutive_timeout = 0
                # Stop streaming on consecutive timeouts
                except TimeoutException:
                    consecutive_timeout += 1
                    if consecutive_timeout >= self.MAX_CONSECUTIVE_TIMEOUT:
                        analyzr2.logger.error(
                            f"Camera failed to fetch a new image {consecutive_timeout} ",
                            "consecutive times. Stopping image acquisition."
                        )
                        self.streaming = False
                time.sleep(1/60)
            acquirer.stop()
        # Request closure of the shared array
        if self.shared_array:
            self.shared_array.close()
            self.shared_array = None
        harvester.reset()
        self.camera_display.clear_image()
        # Reset status and button
        self._set_status(analyzr2.BlockStatus.IDLE)
        self.camera_control.set_text(self.BUTTON_START)

    def configure_acquirer(self, acquirer: ImageAcquirer):
        """
        Configure the ImageAcquirer. Must be called before acquiring frames.
        If packet size is not configured, the acquirer might hangout even with a timeout.
        """
        configuration = {
            "PixelFormat": "Mono14",
            "DeviceStreamChannelPacketSize": 1500,
            "GevSCPSPacketSize": 1500
        }
        # NOTE: We use 'remote_device" which is the actual camera, device is just a proxy
        for node, value in configuration.items():
            try:
                getattr(acquirer.remote_device.node_map, node).value = value
            except AttributeError:
                analyzr2.logger.warning(f"Not configuring {node}: unavailable on selected device.")

    def update_frame(self, frame: Buffer):
        """
        Update the Frame displayed on the associated EmbeddedWidget upon receiving a new Frame.

        For now, only handle Mono14 formatted images.
        """
        # First reshape image to a 2D array
        component = frame.payload.components[0]
        data_format = component.data_format
        # From Harvester documentation
        if component.data_format == "Mono14":
            content = component.data.reshape(component.height, component.width).astype(np.uint16)
            content = (content / 64).astype(np.uint8)  # Scale 14-bit to 8-bit
        elif component.data_format == "Mono8":
            content = component.data.reshape(component.height, component.width)
        else:
            analyzr2.logger.warning(f"Unsupported data_format: {data_format}")
            return
        if not self.shared_array:
            # Prepare shared array and sent it
            self.shared_array = analyzr2.data.SharedArray.create(xr.DataArray(data=content))
            self.camera_display.update_image_from_array(self.shared_array.as_sharable_tuple())
        else:
            self.shared_array.np_arr[:] = content[:]
            self.camera_display.refresh_image()

    def start_stop_streaming(self):
        """
        Called when the control button is clicked.

        Start or stop the streaming of the camera.
        """
        if not self.ready:
            return
        self.streaming = not self.streaming
        # Start thread, update status
        if self.streaming:
            # Start thread
            self.thread = Thread(target=self.streaming_context)
            self.thread.start()
            self._set_status(analyzr2.BlockStatus.RUNNING)
            self.camera_control.set_text(self.BUTTON_STOP)
        # Thread should stop by itself, wait a bit
        else:
            if isinstance(self.thread, Thread):
                self.thread.join(timeout=5)
            self.camera_control.set_text(self.BUTTON_START)
