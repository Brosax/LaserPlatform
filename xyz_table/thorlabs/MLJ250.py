"""
Plugin for controlling the Thorlabs MLJ250 Motion Controller.
"""
import functools
import time

from PySide6 import QtCore, QtWidgets
import serial

import analyzr2
from .driver.MLJ250_motion_controller import MLJ250MotionController
from ..interfaces.axis import AxisInterface

# ==== AxisInterface implementation

class MLJ250(AxisInterface):
    """
    AxisInterface implementation of the MLJ250 controller.
    """
    COM_SETTINGS = {
        "baudrate": 115200,
        "bytesize": serial.EIGHTBITS,
        "stopbits": serial.STOPBITS_ONE,
        "parity": serial.PARITY_NONE,
        "rtscts": True,
    }

    def __init__(self, port: str, address: int, timeout: float):
        super().__init__(port, address, timeout)
        self.controller = MLJ250MotionController(self.serial)

    @property
    def homed(self):
        return self.controller.homed

    @property
    def position(self):
        return self.controller.position_um

    def set_motion_profile(self, velocity: float, acceleration: float):
        self.controller.set_velocity_parameters(0.0, velocity, acceleration)

    def homing(self):
        self.controller.set_home_parameters()
        self.controller.home()
        self.controller.update_status()
        # Wait until controller is homed (compute homing time, expect ~50s if extended to max)
        start_time = time.monotonic()
        while not self.controller.homed:
            # Request a status update
            self.controller.update_status()
            time.sleep(0.01)
            if (time.monotonic() - start_time) > 120:
                raise TimeoutError("Could not home within the expected time (2 minutes).")
        analyzr2.logger.info(f"Took {time.monotonic() - start_time}s to come home.")
        # Set encounder count to 0 if homed
        self.controller.set_encoder_count(0)

    def move_to(self, position_um: float):
        start_time = time.monotonic()
        self.controller.move_absolute(position_um)
        self.controller.update_status()
        # Wait for move to complete
        while self.controller.moving:
            # Request a status update
            self.controller.update_status()
            time.sleep(0.01)
            if (time.monotonic() - start_time) > 120:
                raise TimeoutError("Could not move within the expected time (2 minutes).")
        analyzr2.logger.info(f"Took {time.monotonic() - start_time}s to complete move.")

    def move_by(self, distance_um: float):
        start_time = time.monotonic()
        self.controller.move_relative(distance_um)
        self.controller.update_status()
        # Wait for move to complete
        while self.controller.moving:
            # Request a status update
            self.controller.update_status()
            time.sleep(0.01)
            if (time.monotonic() - start_time) > 120:
                raise TimeoutError("Could not move within the expected time (2 minutes).")
        analyzr2.logger.info(f"Took {time.monotonic() - start_time}s to complete move.")

    def halt(self):
        self.controller.stop()

# ==== Custom widgets

class MLJ250StatusViewer(analyzr2.widgets.EmbeddedWidget):
    def __init__(self):
        super().__init__(QtWidgets.QFormLayout)
        self.position_label = QtWidgets.QLabel("0.0µm")
        self.position_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.moving_label = QtWidgets.QLabel("False")
        self.moving_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.homing_label = QtWidgets.QLabel("False")
        self.homing_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.layout().addRow("Position", self.position_label)
        self.layout().addRow("Moving", self.moving_label)
        self.layout().addRow("Homing", self.homing_label)
        self.layout().setContentsMargins(QtCore.QMargins(10, 10, 10, 10))
        self.setMinimumWidth(140)
        self.setMinimumHeight(80)

    def update_status(self, position: float, moving: bool, homing: bool):
        # Display position in micrometer
        self.position_label.setText(f"{position}µm")
        self.moving_label.setText(str(moving))
        self.homing_label.setText(str(homing))

# ==== Blocks

class _MLJ250MoveTo(analyzr2.Block):
    """
    Request the MLJ250 Motion Controller to move to the given position.

    Inputs
    ------
    MLJ250 : MLJ250
        Object representing the MLJ250 Motion Controller.

    Parameters
    ----------
    position : Quantity[micrometer]
        The target position. Range of this controller is [0:50]mm.
    """
    configuration = {"name": "Move to"}
    inputs = {
        analyzr2.TypedSlot("MLJ250", MLJ250): analyzr2.Undefined
    }
    parameters = {
        "position": analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.micrometer,
            prefixes=["milli", "micro"],
            min=0.0*analyzr2.pint.registry.millimeter,
            max=50.0*analyzr2.pint.registry.millimeter,
            default=0.0*analyzr2.pint.registry.micrometer
        ),
        # "relative": analyzr2.inputs.boolean(False) # Unused for now
    }

    def process(self):
        if isinstance(self.position, analyzr2.pint.Unit):
            position = self.position
        else:
            position = analyzr2.pint.get_suitable_quantity(self.position, analyzr2.pint.registry.micrometer)
        self.MLJ250.move_to(position.to(analyzr2.pint.registry.micrometer).magnitude)


class _MLJ250GetPosition(analyzr2.Block):
    """
    Return the current position of the MLJ250 Motion Controller, in micrometer.

    Inputs
    ------
    MLJ250 : MLJ250
        Object representing the MLJ250 Motion Controller.
    """
    configuration = {"name": "Get position"}
    inputs = {
        analyzr2.TypedSlot("MLJ250", MLJ250): analyzr2.Undefined
    }
    outputs = ["position"]

    def process(self):
        self.position = self.MLJ250.controller.position_um


class _MLJ250SetVelocity(analyzr2.Block):
    """
    Set the velocity of the MLJ250 Motion Controller.

    Inputs
    ------
    MLJ250 : MLJ250
        Object representing the MLJ250 Motion Controller.

    Parameters
    ----------
    min_velocity : Quantity[micrometer/second]
        The starting velocity during a move operation.
    max_velocity : Quantity[micrometer/second]
        The maximum velocity during a move operation.
    acceleration : Quantity[micrometer/second²]
        The acceleration rate during a move operation.
    """
    MIN_VELOCITY = 0.0*(analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second)
    MAX_VELOCITY = 2000.0*(analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second)

    inputs = {
        analyzr2.TypedSlot("MLJ250", MLJ250): analyzr2.Undefined
    }
    parameters = {
        "min_velocity": analyzr2.parameters.pint_quantity(
            analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second,
            prefixes=[""],
            min = MIN_VELOCITY,
            max = MAX_VELOCITY,
            default = 0.0*(analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second)
        ),
        "max_velocity": analyzr2.parameters.pint_quantity(
            analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second,
            prefixes=[""],
            min = MIN_VELOCITY,
            max = MAX_VELOCITY,
            default = 500.0*(analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second)
        ),
        "acceleration": analyzr2.parameters.pint_quantity(
            analyzr2.pint.registry.micrometer / (analyzr2.pint.registry.second**2),
            prefixes=[""],
            min = 0.0*(analyzr2.pint.registry.micrometer / (analyzr2.pint.registry.second**2)),
            max = 1000.0*(analyzr2.pint.registry.micrometer / (analyzr2.pint.registry.second**2)),
            default = 250.0*(analyzr2.pint.registry.micrometer / (analyzr2.pint.registry.second**2))
        ),
    }

    def process(self):
        self.MLJ250.controller.set_velocity_parameters(
            self.min_velocity.magnitude,
            self.max_velocity.magnitude,
            self.acceleration.magnitude,
        )


class _MLJ250SetPower(analyzr2.Block):
    """
    Set the power usages of the MLJ250 Motion Controller (in percentage of the maximum power).

    Inputs
    ------
    MLJ250 : MLJ250
        Object representing the MLJ250 Motion Controller.

    Parameters
    ----------
    rest_power : int
        The controller power usage when resting.
    move_power : int
        The controller power usage when moving.
    """
    inputs = {
        analyzr2.TypedSlot("MLJ250", MLJ250): analyzr2.Undefined
    }
    parameters = {
        "rest_power": analyzr2.parameters.slider(0, 100, 1, default=20),
        "move_power": analyzr2.parameters.slider(0, 100, 1, default=100)
    }

    def process(self):
        self.MLJ250.controller.set_power_parameters(self.rest_power, self.move_power)


class _MLJ250Stop(analyzr2.Block):
    """
    Immediately send a STOP command to the MLJ250 Motion Controller.

    This stops any movement or homing operation currently ongoing.
    Note that this may cause a timeout to be raised from the associated operation.
    """
    inputs = {
        analyzr2.TypedSlot("MLJ250", MLJ250): analyzr2.Undefined
    }
    widgets = {
        "stop_button": {
            analyzr2.widgets.Config: {
                "type": analyzr2.widgets.button("STOP")
            },
            analyzr2.widgets.Connect: {
                "clicked": "process"
            }
        }
    }

    def create(self):
        self.MLJ250 = analyzr2.Undefined

    def process(self):
        if isinstance(self.MLJ250, MLJ250):
            self.MLJ250.halt()
            # Update status
            self.MLJ250.controller.update_status()


class MLJ250Init(analyzr2.Block):
    """
    Thorlabs MLJ250 Motion Controller initialization block.

    Create the MLJ250 controller object, and home the controller if requested.

    Parameters
    ----------
    port_com : str
        Serial communication port for the controller.
    timeout : Quantity[second]
        Timeout for serial communication with the controller.
    homing : bool
        Indicates if the controller should perform an homing operation immediatly on initialization.
    """
    configuration = {
        "name": "MLJ250"
    }

    blocks = {
        # "MoveHome": _MLJ250MoveHome
        "GetPosition": _MLJ250GetPosition,
        "SetVelocity": _MLJ250SetVelocity,
        "SetPower": _MLJ250SetPower,
        "MoveTo": _MLJ250MoveTo,
        "Stop": _MLJ250Stop
    }

    parameters = {
        "port_com": analyzr2.inputs.com_port_selector(display="COM Port"),
        "timeout": analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.second,
            prefixes=["", "milli"],
            min=0.0*analyzr2.pint.registry.second,
            default=5.0*analyzr2.pint.registry.second
        ),
        "homing": analyzr2.inputs.boolean(default=True), # TODO could be an embedded button instead?
    }
    outputs = [
        analyzr2.TypedSlot("MLJ250", MLJ250)
    ]
    widgets = {
        "viewer": {
            analyzr2.widgets.Config: {
                "type": functools.partial(MLJ250StatusViewer)
            }
        },
        "update_status": {
            analyzr2.widgets.Config: {
                "type": analyzr2.widgets.button("Print status")
            },
            analyzr2.widgets.Connect: {
                "clicked": "print_status"
            }
        }
    }

    # Block logic

    def create(self):
        self.serial = analyzr2.Undefined
        self.MLJ250 = analyzr2.Undefined

    def process(self):
        # Close potentially existing connection
        # if isinstance(self.MLJ250, MLJ250):
        #     self.MLJ250.close()
        self.MLJ250 = MLJ250(
            self.port_com,
            address=None,
            timeout=self.timeout.to(analyzr2.pint.registry.second).magnitude
        )
        self.MLJ250.controller._status_callback = self._on_status_update
        # Stop anything that the controller could be doing (from previous instance)
        # self.MLJ250.stop()
        # Update status
        self.MLJ250.controller.update_status()
        # Perform homing operation if required
        if self.homing:
            self.MLJ250.homing()
        # Set backlash to 1.5µm, this prevent the motor from moving backward too strongly
        self.MLJ250.controller.set_backlash_parameters(1.5)

    def clean(self):
        # Close object on exit
        if isinstance(self.MLJ250, MLJ250):
            self.MLJ250.close()

    # Custom methods

    def _on_status_update(self):
        if not isinstance(self.MLJ250, MLJ250):
            return
        self.viewer.update_status(
            self.MLJ250.controller.position_um,
            self.MLJ250.controller.moving,
            self.MLJ250.controller.homing
        )

    def print_status(self):
        """
        Update and print the status of the Motion Controller.
        """
        if not isinstance(self.MLJ250, MLJ250):
            return
        # Request a status update
        if not self.MLJ250.controller.update_status():
            analyzr2.logger.error("Failed to update new MLJ250 controller status.")
        analyzr2.logger.debug(f"channel : {self.MLJ250.controller.channel}")
        analyzr2.logger.debug(f"position: {self.MLJ250.controller._position} "
                              f"({self.MLJ250.controller.position_um}µm)")
        analyzr2.logger.debug(f"velocity: {self.MLJ250.controller._velocity}")
        analyzr2.logger.debug(f"current : {self.MLJ250.controller._current}")
        analyzr2.logger.debug(f"status  : {self.MLJ250.controller._status_bits}")
        analyzr2.logger.debug(f" -homing   : {self.MLJ250.controller.homing}")
        analyzr2.logger.debug(f" -homed    : {self.MLJ250.controller.homed}")
        analyzr2.logger.debug(f" -interlock: {self.MLJ250.controller.interlock}")
