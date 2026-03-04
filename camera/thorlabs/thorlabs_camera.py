"""
Plugin dedicated to the use of a Thorlabs camera using it's associated SDK.
"""
import functools
import os
from threading import Thread
import time
import typing

import numpy as np
import xarray as xr

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QImage, QPixmap

import analyzr2

from .source.tl_camera import TLCameraSDK, SENSOR_TYPE
from .source.tl_mono_to_color_processor import MonoToColorProcessorSDK

try:
    # if on Windows, use the provided setup script to add the DLLs folder to the PATH
    from .windows_setup import configure_path
    configure_path()
except ImportError:
    configure_path = None

class DeviceInfo(typing.NamedTuple):
    """
    Tuple for camera device information transfer between GUI and backend.
    """
    display_name: str
    camera_id: str

class _CameraFinder(analyzr2.inputs.ParameterWidget):
    """
    A widget that allows listing the available cameras.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Combobox listing cameras
        self.combobox = QtWidgets.QComboBox()
        self.combobox.currentIndexChanged.connect(self.send_device_data)
        # Refresh button
        self.refresh = QtWidgets.QPushButton("Refresh")
        self.refresh.clicked.connect(self.discover)
        # Design
        self.setLayout(QtWidgets.QGridLayout())
        self.layout().addWidget(QtWidgets.QLabel("Devices"), 0, 0, 1, 1)
        self.layout().addWidget(self.combobox, 0, 1, 1, 1)
        self.layout().addWidget(self.refresh, 0, 2, 1, 1)
        self.layout().setColumnStretch(0, 1)
        self.layout().setColumnStretch(1, 3)
        self.layout().setColumnStretch(2, 1)
        self.layout().setContentsMargins(QtCore.QMargins(0, 0, 0, 0))

    def discover(self):
        """
        Discover available cameras and update the combobox.
        """
        self.combobox.clear()
        with TLCameraSDK() as sdk:
            available_cameras = sdk.discover_available_cameras()
            for camera_id in available_cameras:
                self.combobox.addItem(camera_id, camera_id)

    def send_device_data(self):
        """
        Emit the selected camera information.
        """
        camera_id = self.combobox.currentData()
        if camera_id:
            self.confirm(DeviceInfo(camera_id, camera_id))

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
        # Internal values
        self.prevent_update = time.time()
        self.shared_array = None
        # Add video display
        self.display = _VideoDisplay()
        self.display.setScaledContents(True)
        self.layout().addWidget(self.display)
        # Add screenshot button
        self.screenshot_button = _FixedSizeButton("Save screenshot")
        self.screenshot_button.clicked.connect(self.save_image)
        self.layout().addWidget(self.screenshot_button)
        # Update minimum size
        self.setMinimumSize(
            self.minimumWidth(),
            self.display.minimumHeight() + self.screenshot_button.height()
        )

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

    def set_color_image(self, array_info):
        """Display a colored image."""
        # Update if not resizing for 1 sec
        if time.time() - self.prevent_update > 1:
            # Create array from received data
            self.shared_array = analyzr2.data.SharedArray.open(array_info)
            height, width, _ = array_info.np_info.shape
            qimage = QImage(
                self.shared_array.np_arr, width, height, QImage.Format.Format_RGB888
            )
            # Update image
            self.display.setPixmap(QPixmap.fromImage(qimage))

    def refresh_color_image(self):
        """Refresh the colored image displayed from the opened shared array."""
        if time.time() - self.prevent_update > 1 and self.shared_array:
            height, width, _ = self.shared_array.np_arr.shape
            qimage = QImage(
                self.shared_array.np_arr, width, height, QImage.Format.Format_RGB888
            )
            # Update image
            self.display.setPixmap(QPixmap.fromImage(qimage))

    def set_grey_image(self, array_info):
        """Display a grey level image."""
        # Update if not resizing for 1 sec and shared array is opened
        if time.time() - self.prevent_update > 1:
            # Create array from received data
            self.shared_array = analyzr2.data.SharedArray.open(array_info)
            height, width = array_info.np_info.shape
            qimage = QImage(
                self.shared_array.np_arr, width, height, QImage.Format.Format_Grayscale16
            )
            # Update image
            self.display.setPixmap(QPixmap.fromImage(qimage))

    def refresh_grey_image(self, array_info):
        """Refresh the grey image displayed from the opened shared array."""
        # Update if not resizing for 1 sec and shared array is opened
        if time.time() - self.prevent_update > 1 and self.shared_array:
            # Create array from received data
            height, width = array_info.np_info.shape
            qimage = QImage(
                self.shared_array.np_arr, width, height, QImage.Format.Format_Grayscale16
            )
            # Update image
            self.display.setPixmap(QPixmap.fromImage(qimage))

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
    gain_range_changed = QtCore.Signal()
    gain_selection_changed = QtCore.Signal(object)
    reticle_checked = QtCore.Signal(bool)

    def __init__(self):
        super().__init__(QtWidgets.QHBoxLayout)
        # Create config widgets
        self.camera_gain = analyzr2.widgets.embedded.EmbeddedSlider((0, 0, 1), label="Camera gain")
        self.camera_reticle = analyzr2.widgets.embedded.CheckBox(text="Show reticle", checked=False)
        # Rewire signals
        self.camera_gain.selection_changed.connect(self.gain_selection_changed)
        self.camera_gain.range_changed.connect(self.gain_range_changed)
        self.camera_reticle.checked.connect(self.reticle_checked)
        # Build layout
        self.layout().addWidget(self.camera_reticle)
        self.layout().addWidget(self.camera_gain)
        # Update minimum size
        self.setFixedHeight(max(self.camera_gain.minimumHeight(), self.camera_reticle.minimumHeight()))

    def update_gain(self, min_gain, max_gain, current_gain):
        """Setup the camera gain slider with values retrieved from the camera."""
        self.camera_gain.init_range(min_gain, max_gain, 1)
        self.camera_gain.svalue = current_gain

class _FixedSizeButton(analyzr2.widgets.embedded.Button):

    def __init__(self, text):
        super().__init__(text)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding,
            QtWidgets.QSizePolicy.Minimum
        )
        self.setFixedHeight(24)

# ==== Blocks

class ThorlabsCamera(analyzr2.Block):
    """
    Thorlabs camera controller.

    Parameters
    ----------
    camera_info : str
        Identifier of the camera to control.
    """

    parameters = {
        "camera_info": functools.partial(_CameraFinder, display=None)
    }

    widgets = {
        "camera_display": {
            analyzr2.widgets.Config: {
                "type": _CameraDisplay
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
                "gain_selection_changed" : "update_gain_from_widget",
                "reticle_checked" : "update_reticle"
            }
        }
    }

    def create(self):
        self.shared_array = None
        self.streaming = False
        self.thread = None
        self.gain_changed = None

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
        # Clear output
        self.camera_display.clear_image()
        # Reset button text
        self.camera_control.set_text("Start streaming")

    # Custom methods

    def update_reticle(self, enabled):
        """Update the camera reticle flag."""
        self.camera_display.update_reticle(enabled)

    def update_gain_from_widget(self, value):
        """Update the camera gain from the widget."""
        if self.streaming:
            self.gain_changed = value

    def update_gain_from_camera(self, current_gain, gain_range):
        """Setup the camera gain slider from information retrieved from the camera."""
        self.camera_config.update_gain(gain_range.min, gain_range.max, current_gain)

    def start_stop_streaming(self):
        """
        Called when the control button is clicked.

        Start or stop the streaming of the camera.
        """
        if self.camera_info:
            self.streaming = not self.streaming
            # Start thread, update status
            if self.streaming:
                self.camera_control.set_text("Stop streaming")
                self.thread = Thread(target=self.streaming_context)
                self.thread.start()
                self._set_status(analyzr2.BlockStatus.RUNNING)
            else:
                if isinstance(self.thread, Thread):
                    self.thread.join(timeout=5)
                self.camera_control.set_text("Start streaming")
        else:
            analyzr2.logger.error("Cannot start streaming : no camera selected")

    def streaming_context(self):
        """
        Run inside a thread to keep the Thorlabs SDK context.
        """
        # If camera connection already made, exit
        if TLCameraSDK._is_sdk_open:
            analyzr2.logger.warning("Only one camera can be opened at a time, exiting.")
            self.camera_control.set_text("Start streaming")
            self.streaming = False
        else:
            analyzr2.logger.info("Opening camera connection...")
            # Try to create camera SDK
            with TLCameraSDK() as sdk:
                # We need to discover available cameras before connecting to them
                sdk.discover_available_cameras()
                # Init camera connection
                with sdk.open_camera(self.camera_info[1]) as camera:
                    camera.exposure_time_us = 10000  # set exposure to 11 ms
                    camera.frames_per_trigger_zero_for_unlimited = 0  # start camera in continuous mode
                    camera.image_poll_timeout_ms = 1000  # 1 second polling timeout
                    camera.frame_rate_control_value = 10
                    camera.is_frame_rate_control_enabled = True

                    # Setup gain slider from camera information
                    self.update_gain_from_camera(camera.gain, camera.gain_range)

                    mono_to_color_processor = None

                    # Setup color processing if necessary
                    if camera.camera_sensor_type == SENSOR_TYPE.BAYER:
                        is_color = True
                        mono_to_color_sdk = MonoToColorProcessorSDK()
                        mono_to_color_processor = mono_to_color_sdk.create_mono_to_color_processor(
                            SENSOR_TYPE.BAYER,
                            camera.color_filter_array_phase,
                            camera.get_color_correction_matrix(),
                            camera.get_default_white_balance_matrix(),
                            camera.bit_depth
                        )
                    else:
                        is_color = False

                    camera.arm(2)
                    camera.issue_software_trigger()
                    analyzr2.logger.info("Camera opened")

                    self.running = True

                    while self.streaming:
                        # Update gain if it changed
                        if self.gain_changed is not None:
                            camera.gain = self.gain_changed
                            self.gain_changed = None
                        # Get next frame
                        frame = camera.get_pending_frame_or_null()
                        if frame is not None:

                            if is_color:
                                # Color the image
                                color_image_data = mono_to_color_processor.transform_to_24(
                                    frame.image_buffer,
                                    camera.image_width_pixels,
                                    camera.image_height_pixels
                                )
                                color_image_data = color_image_data.reshape(
                                    (camera.image_height_pixels,
                                    camera.image_width_pixels,
                                    3)
                                )
                                # Create shared array if not already done
                                if not self.shared_array:
                                    self.shared_array = analyzr2.data.SharedArray.create(xr.DataArray(data=color_image_data))
                                    self.camera_display.set_color_image(self.shared_array.as_sharable_tuple())
                                # Else update array with new data
                                else:
                                    self.shared_array.np_arr[:] = color_image_data[:]
                                    self.camera_display.refresh_color_image()
                            else:
                                # No coloring, just display the monochrome image
                                image_buffer_copy = np.copy(frame.image_buffer)
                                numpy_shaped_image = image_buffer_copy.reshape(
                                    camera.image_height_pixels,
                                    camera.image_width_pixels
                                )
                                nd_image_array = np.full((camera.image_height_pixels, camera.image_width_pixels, 3), 0, dtype=np.uint8)
                                nd_image_array[:,:,0] = numpy_shaped_image
                                nd_image_array[:,:,1] = numpy_shaped_image
                                nd_image_array[:,:,2] = numpy_shaped_image
                                # Create shared array if not already done
                                if not self.shared_array:
                                    self.shared_array = analyzr2.data.SharedArray.create(xr.DataArray(data=nd_image_array))
                                    self.camera_display.set_grey_image(self.shared_array.as_sharable_tuple())
                                # Else update array with new data
                                else:
                                    self.shared_array.np_arr[:] = nd_image_array[:]
                                    self.camera_display.refresh_grey_image()
                        time.sleep(1/60)
                    # Request closure of the shared array
                    if self.shared_array:
                        self.shared_array.close()
                        self.shared_array = None
                    # When streaming end, close the camera
                    analyzr2.logger.info("Closing camera...")
                    camera.disarm()
                    # Remove colors elements
                    if camera.camera_sensor_type == SENSOR_TYPE.BAYER:
                        mono_to_color_processor.dispose()
                        mono_to_color_sdk.dispose()
            self.camera_display.clear_image()
            analyzr2.logger.info("Camera closed")
