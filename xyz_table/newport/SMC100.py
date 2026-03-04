"""
Plugin for controlling the Newport SMC100 Motion Controller.
"""
import time

import serial

import analyzr2
from .driver.SMC100_motion_controller import SMC100MotionController
from ..interfaces.axis import AxisInterface

# ==== AxisInterface implementation

class SMC100(AxisInterface):
    """
    AxisInterface implementation of the SMC100 controller.
    """
    COM_SETTINGS = {
        "baudrate": 57600,
        "bytesize": serial.EIGHTBITS,
        "parity": serial.PARITY_NONE,
        "stopbits": serial.STOPBITS_ONE,
        "rtscts": False,
        "xonxoff": True,
    }

    def __init__(self, port: str, address: int, timeout: float):
        super().__init__(port, address, timeout)
        self.controller = SMC100MotionController(self.serial, address)

    @property
    def homed(self):
        return self.controller.homed

    @property
    def position(self):
        return self.controller.position

    def set_motion_profile(self, velocity, acceleration):
        self.controller.set_motion_acceleration(acceleration)
        self.controller.set_motion_velocity(velocity)

    def homing(self):
        # Skip homing if already homed
        if self.controller.homed:
            return
        self.controller.home()
        # Wait until controller is homed
        while True:
            time.sleep(0.05)
            self.controller.update_status()
            # Verify current controller status
            if self.controller.homing or self.controller.moving:
                continue
            if self.controller.ready:
                break
            raise ValueError(f"Controller entered unexpected state: {self.controller._state}")

    def move_to(self, position_um: float):
        # If target position is current position, skip move
        if position_um == self.controller.position:
            return
        # If target position is out of range, clamp it to accepted range (with warning message)
        if position_um > self.controller._pos_limit:
            analyzr2.logger.warning(
                f"Target position out of range: {position_um}µm. "
                f"Limiting to max position ({self.controller._pos_limit}µm)"
            )
            position_um = self.controller._pos_limit
        if position_um < self.controller._neg_limit:
            analyzr2.logger.warning(
                f"Target position out of range: {position_um}µm. "
                f"Limiting to min position ({self.controller._neg_limit}µm)"
            )
            position_um = self.controller._neg_limit
        self.controller.move_absolute(position_um)
        # Wait for move to complete
        while True:
            time.sleep(0.05)
            self.controller.update_status()
            # Verify current controller status
            if self.controller.moving:
                continue
            if self.controller.ready:
                break
            raise ValueError(f"Controller entered unexpected state: {self.controller._state}")

    def move_by(self, distance_um: float):
        # If move distance is 0, skip move
        if distance_um == 0.0:
            return
        # If target position is out of range, clamp it to accepted range (with warning message)
        if self.controller.position + distance_um > self.controller._pos_limit:
            analyzr2.logger.warning(
                f"Target position out of range: {self.controller.position + distance_um}µm. "
                f"Limiting to max position ({self.controller._pos_limit}µm)"
            )
            distance_um = abs(self.controller._pos_limit - self.controller.position)
        if self.controller.position + distance_um < self.controller._neg_limit:
            analyzr2.logger.warning(
                f"Target position out of range: {self.controller.position + distance_um}µm. "
                f"Limiting to min position ({self.controller._neg_limit}µm)"
            )
            distance_um = -abs(self.controller._neg_limit - self.controller.position)
        self.controller.move_relative(distance_um)
        # Wait for move to complete
        while True:
            time.sleep(0.05)
            self.controller.update_status()
            # Verify current controller status
            if self.controller.moving:
                continue
            if self.controller.ready:
                break
            raise ValueError(f"Controller entered unexpected state: {self.controller._state}")

    def halt(self):
        self.controller.stop()

# ==== Blocks

class _SMC100Configure(analyzr2.Block):
    """
    Configure the motion profile of a SMC100 Motion Controller.

    Inputs
    ------
    SMC100 : SMC100
        Object representing the SMC100 Motion Controller.

    Parameters
    ----------
    velocity : Quantity[micrometer/second]
        The target velocity.
    acceleration : Quantity[micrometer/second²]
        The target acceleration.
    """
    configuration = {"name": "Configure"}
    inputs = {
        analyzr2.TypedSlot("SMC100", SMC100): analyzr2.Undefined
    }
    parameters = {
        "velocity": analyzr2.inputs.pint_quantity(
            (analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second),
            prefixes=[""],
            min=0.0 * (analyzr2.pint.registry.millimeter / analyzr2.pint.registry.second),
            max=100.0 * (analyzr2.pint.registry.millimeter / analyzr2.pint.registry.second),
            default=500.0 * (analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second)
        ),
        "acceleration": analyzr2.inputs.pint_quantity(
            (analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second**2),
            prefixes=[""],
            min=0.0 * (analyzr2.pint.registry.millimeter / analyzr2.pint.registry.second**2),
            max=100.0 * (analyzr2.pint.registry.millimeter / analyzr2.pint.registry.second**2),
            default=200.0 * (analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second**2)
        ),
    }

    def process(self):
        self.SMC100.set_motion_profile(
            self.velocity.to(
                analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second
            ).magnitude,
            self.acceleration.to(
                analyzr2.pint.registry.micrometer / analyzr2.pint.registry.second**2
            ).magnitude
        )

class _SMC100GetPositon(analyzr2.Block):
    """
    Get the current position of a SMC100 Motion Controller.

    Inputs
    ------
    SMC100 : SMC100
        Object representing the SMC100 Motion Controller.

    Outputs
    -------
    position : Quantity[micrometer]
        Position of the controller, in micrometer.
    """
    configuration = {"name": "Get Position"}
    inputs = {
        analyzr2.TypedSlot("SMC100", SMC100): analyzr2.Undefined
    }
    outputs = ["position"]

    def process(self):
        self.SMC100.controller.update_status()
        self.position = self.SMC100.controller.position * analyzr2.pint.registry.micrometer

class _SMC100MoveTo(analyzr2.Block):
    """
    Request the SMC100 Motion Controller to move to the given position.

    Inputs
    ------
    SMC100 : SMC100
        Object representing the SMC100 Motion Controller.

    Parameters
    ----------
    position : Quantity[micrometer]
        The target position. Range of this controller is [0:50]mm.
    """
    configuration = {"name": "Move to"}
    inputs = {
        analyzr2.TypedSlot("SMC100", SMC100): analyzr2.Undefined
    }
    parameters = {
        "position": analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.micrometer,
            prefixes=["milli", "micro"],
            min=-50.0*analyzr2.pint.registry.millimeter,
            max=50.0*analyzr2.pint.registry.millimeter,
            default=0.0*analyzr2.pint.registry.micrometer
        ),
    }

    def process(self):
        if isinstance(self.position, analyzr2.pint.Unit):
            position = self.position
        else:
            position = analyzr2.pint.get_suitable_quantity(self.position, analyzr2.pint.registry.micrometer)
        self.SMC100.move_to(position.to(analyzr2.pint.registry.micrometer).magnitude)

class _SMC100MoveBy(analyzr2.Block):
    """
    Request the SMC100 Motion Controller to move to the given position.

    Inputs
    ------
    SMC100 : SMC100
        Object representing the SMC100 Motion Controller.

    Parameters
    ----------
    position : Quantity[micrometer]
        The target position. Range of this controller is [0:50]mm.
    """
    configuration = {"name": "Move by"}
    inputs = {
        analyzr2.TypedSlot("SMC100", SMC100): analyzr2.Undefined
    }
    parameters = {
        "position": analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.micrometer,
            prefixes=["milli", "micro"],
            min=-100.0*analyzr2.pint.registry.millimeter,
            max=100.0*analyzr2.pint.registry.millimeter,
            default=0.0*analyzr2.pint.registry.micrometer
        )
    }

    def process(self):
        if isinstance(self.position, analyzr2.pint.Unit):
            position = self.position
        else:
            position = analyzr2.pint.get_suitable_quantity(self.position, analyzr2.pint.registry.micrometer)
        self.SMC100.move_by(position.to(analyzr2.pint.registry.micrometer).magnitude)

class SMC100Init(analyzr2.Block):
    """
    Newport SMC100 Motion Controller initialization block.

    Create the SMC100 controller object, and home the controller if requested.

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
        "name": "SMC100"
    }

    blocks = {
        "Configure": _SMC100Configure,
        "GetPosition": _SMC100GetPositon,
        "MoveTo": _SMC100MoveTo,
        "MoveBy": _SMC100MoveBy
    }

    parameters = {
        "port_com": analyzr2.inputs.com_port_selector(display="COM Port"),
        "address": analyzr2.inputs.variable(itype=int, default=0),
        "timeout": analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.second,
            prefixes=["", "milli"],
            min=0.0*analyzr2.pint.registry.second,
            default=5.0*analyzr2.pint.registry.second
        ),
        "homing": analyzr2.inputs.boolean(default=True), # TODO could be an embedded button instead?
    }
    outputs = [
        analyzr2.TypedSlot("SMC100", SMC100)
    ]

    # Block logic

    def create(self):
        self.serial = analyzr2.Undefined
        self.SMC100 = analyzr2.Undefined

    def process(self):
        # Ensure previous object communication is closed
        if isinstance(self.SMC100, SMC100):
            self.SMC100.close()
        # (Re)create object
        self.SMC100 = SMC100(
            self.port_com,
            address=self.address,
            timeout=self.timeout.to(analyzr2.pint.registry.second).magnitude
        )
        # Skip homing if already homed
        if self.SMC100.controller.homed and self.homing:
            analyzr2.logger.debug("Already homed, skipping homing procedure.")
            return
        # Perform homing operation if required
        if self.homing:
            self.SMC100.homing()

    def clean(self):
        # Ensure object communication is closed
        if isinstance(self.SMC100, SMC100):
            self.SMC100.close()
