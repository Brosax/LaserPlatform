"""
Plugin dedicated to the use of an Allied Vision camera through the Vimba X SDK.
"""
import functools
import os
from threading import Thread

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import vmbpy
import xarray as xr

import analyzr2

class CameraFinder(analyzr2.inputs.ParameterWidget):
    """
    ComboBox that detects Allied's Vision cameras connected to the user computer.
    """
    def __init__(self, **kwargs):
        super().__init__(display=None)
        # Combobox listing cameras
        self.combobox = QtWidgets.QComboBox()
        self.combobox.currentIndexChanged.connect(self.send_camera_id)
        # Refresh button
        self.refresh = QtWidgets.QPushButton("Refresh")
        self.refresh.clicked.connect(self.discover)
        # Design
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().addWidget(self.combobox)
        self.layout().addWidget(self.refresh)
        self.layout().setContentsMargins(QtCore.QMargins(0, 0, 0, 0))
        # Update combobox
        self.discover()

    def set_default(self, default):
        self.combobox.setCurrentIndex(self.combobox.findData(default))

    def discover(self):
        """
        Search for all connected cameras.
        """
        # Clear all current items
        current_data = self._current
        self.combobox.clear()
        # Update items
        with vmbpy.VmbSystem.get_instance() as vmb:
            for camera in vmb.get_all_cameras():
                self.combobox.addItem(camera.get_name(), camera.get_id())
        if self.combobox.count() == 0:
            analyzr2.logger.warning("No camera detected.")
        # Reset value to what is was before (if camera ID still exists)
        self.combobox.setCurrentIndex(self.combobox.findData(current_data))

    def send_camera_id(self, _: int):
        """
        Send the ID of the selected camera to the Block.
        """
        # Prevent sending data when reselecting the current camera
        if self.combobox.currentData() != self._current:
            self.confirm(self.combobox.currentData())
            self._current = self.combobox.currentData()

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

class CameraDisplay(analyzr2.widgets.EmbeddedWidget):
    """
    Simple embedded widget used to display the received camera images.
    """
    def __init__(self):
        super().__init__()
        # Internal values
        self.shared_array = None
        # Add video display
        self.display = _VideoDisplay()
        self.layout().addWidget(self.display)
        # Add screenshot button
        self.screenshot_button = _FixedSizeButton("Save screenshot")
        self.screenshot_button.clicked.connect(self.save_image)
        self.layout().addWidget(self.screenshot_button)
        # Minimum is set to half the camera resolution (GoldEye G-033 TEC1)
        self.display.setMinimumWidth(320)
        self.display.setMinimumHeight(256)

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
        # Create array from received data
        self.shared_array = analyzr2.data.SharedArray.open(array_info)
        height, width = array_info.np_info.shape
        qimage = QtGui.QImage(
            self.shared_array.np_arr, width, height, QtGui.QImage.Format.Format_Grayscale16
        )
        # Update image
        self.display.setPixmap(qimage)
        self.display.setScaledContents(True)

class _CameraConfig(analyzr2.widgets.EmbeddedWidget):
    """
    Embedded widget allowing configuration of some camera properties.
    """

    # Signals from child widgets
    gain_range_changed = QtCore.Signal()
    gain_selection_changed = QtCore.Signal(object)
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

class AVCamera(analyzr2.Block):
    """
    Allied Vision camera controller.

    Parameters
    ----------
    camera_id : str
        Identifier of the camera to control.
    """
    BUTTON_START = "Start streaming"
    BUTTON_STOP = "Stop streaming"
    MAX_CONSECUTIVE_TIMEOUT = 10

    parameters = {
        "camera_id": functools.partial(CameraFinder)
    }

    widgets = {
        "camera_display": {
            analyzr2.widgets.Config: {
                "type": functools.partial(CameraDisplay)
            }
        },
        "camera_control": {
            analyzr2.widgets.Config: {
                "type": analyzr2.widgets.button(BUTTON_START)
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
        self.shared_array = None
        self.streaming = False
        self.thread = None

    def process(self):
        # Stop current streaming
        if self.streaming:
            self.start_stop_streaming()
        # Start streaming
        self.start_stop_streaming()

    def clean(self):
        self.streaming = False
        # Wait for thread to end
        if isinstance(self.thread, Thread):
            self.thread.join(timeout=5)

    # Custom methods

    def update_reticle(self, enabled):
        """Update the camera reticle flag."""
        self.camera_display.update_reticle(enabled)

    def streaming_context(self):
        """
        Run inside a thread to keep the current Vimba context alive.
        """
        with vmbpy.VmbSystem.get_instance() as vmb:
            try:
                with vmb.get_camera_by_id(self.camera_id) as camera:
                    self.configure_camera(camera)
                    consecutive_timeout = 0
                    # Continuously fetch new images
                    while self.streaming:
                        try:
                            frame = camera.get_frame(timeout_ms=100)
                            self.update_frame(frame)
                            consecutive_timeout = 0
                        # Stop streaming on consecutive timeouts
                        except vmbpy.VmbTimeout:
                            consecutive_timeout += 1
                            if consecutive_timeout >= self.MAX_CONSECUTIVE_TIMEOUT:
                                analyzr2.logger.error(
                                    f"Camera failed to fetch a new image {consecutive_timeout} ",
                                    "consecutive times. Stopping image acquisition."
                                )
                                self.streaming = False
            # Raise if the given ID was not found in the camera list
            except vmbpy.VmbCameraError:
                analyzr2.logger.warning(f"Could not find camera of ID '{self.id}'!")
        # Reset status and button
        self._set_status(analyzr2.BlockStatus.IDLE)
        self.camera_control.set_text(self.BUTTON_START)

    def configure_camera(self, camera: vmbpy.Camera):
        """
        Configure the Camera. Must be called before acquiring frames.
        """
        # Set output pixel format to Mono14
        camera.set_pixel_format(vmbpy.PixelFormat.Mono14)
        # Configure framerate to 60fps
        camera.get_feature_by_name("AcquisitionFrameRate").set(60.0)

    def update_frame(self, frame: vmbpy.Frame):
        """
        Update the Frame displayed on the associated EmbeddedWidget upon receiving a new Frame.
        """
        # Create new shared array
        self.shared_array = analyzr2.data.SharedArray.create(
            xr.DataArray(data=np.squeeze(frame.as_numpy_ndarray().copy()))
        )
        # Request camera update
        self.camera_display.update_image_from_array(self.shared_array.as_sharable_tuple())

    def start_stop_streaming(self):
        """
        Called when the control button is clicked.

        Start or stop the streaming of the camera.
        """
        self.streaming = not self.streaming
        # Start thread, update status
        if self.streaming:
            self.thread = Thread(target=self.streaming_context)
            self.thread.start()
            self._set_status(analyzr2.BlockStatus.RUNNING)
            self.camera_control.set_text(self.BUTTON_STOP)
        else:
            if isinstance(self.thread, Thread):
                self.thread.join(timeout=5)
