"""
Generic Axis interface.
"""
import serial

class AxisInterface():
    """
    Generic Axis interface.

    It must be reimplemented for any new axis / motion controller device that will be interfaced
    with the XYZ Table object.
    """
    # Contain communication settings to transmit to the Serial port object.
    COM_SETTINGS = {}
    # Contains opened serial ports, used if multiple axis share the same serial communication
    __OPENED_SERIALS: dict[str, serial.Serial] = {}

    def __init__(self, port: str, address: int, timeout: float):
        if port not in self.__OPENED_SERIALS:
            self.__OPENED_SERIALS[port] = serial.Serial(
                port=port,
                timeout=timeout,
                **self.COM_SETTINGS
            )
            self.__OPENED_SERIALS[port]._registered_axis = 0
        self.serial = self.__OPENED_SERIALS[port]
        self.serial._registered_axis += 1
        self.address = address

    def close(self):
        """
        Unregister this axis from its serial interface.
        Close the serial interface as needed.
        """
        self.serial._registered_axis -= 1
        # Close serial object only if no axis are using it
        if self.serial._registered_axis == 0:
            self.serial.close()

    # Common properties

    @property
    def homed(self) -> bool:
        """
        Return if the axis has been homed or not.
        """
        raise NotImplementedError

    @property
    def position(self) -> float:
        """
        Return the position of this axis, in micrometer.
        """
        raise NotImplementedError

    # Common configuration

    def set_motion_profile(self, velocity: float, acceleration: float):
        """
        Set the velocity and acceleration of this axis.

        Velocity is expected to be expressed in micrometer/second.
        Acceleration is expected to be expressed in micrometer/second².
        """

    # Common operations

    def homing(self):
        """
        Home this axis.
        """
        raise NotImplementedError

    def move_to(self, position_um: float):
        """
        Move to a given position, assumed to be given in micrometer.
        """
        raise NotImplementedError

    def move_by(self, distance_um: float):
        """
        Move by a given step distance, assumed to be given in micrometer.
        """
        raise NotImplementedError

    def halt(self):
        """
        Halt any ongoing movement.
        """
        raise NotImplementedError
