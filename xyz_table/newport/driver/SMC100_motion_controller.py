import time
import typing

import serial

class ControllerError(RuntimeError):
    """
    Raised when an error is returned by the Controller following a command.
    """

class NewportMessage():
    """
    Defines the structure of the messages sent to and from a Newport device.
    """
    def __init__(
        self,
        command: str,
        *,
        address: str = "",
        data: str = ""
    ) -> None:
        self.address: str = address
        self.command: str = command
        self.data: typing.Optional[str] = data

    def pack(self) -> bytes:
        """
        Pack this message into bytes.
        """
        return (self.address + self.command + self.data + "\r\n").encode("utf-8")

    def __str__(self):
        return self.address + self.command + self.data

class SMC100MotionController():
    """
    Implementation of the SMC100 Motion Controller from Newport.
    """
    MAX_RETRY = 4

    def __init__(self, ser: serial.Serial, address: int):
        self.serial = ser
        self._address = address
        self.position: float = 0.0
        self._error: str = "0000"
        self._state: str = "0A"
        # Number of retries for current query
        self._retries = 0
        # Ensure current state
        self.update_status()
        # Read identifier
        # self.send_message(NewportMessage("ID", address=self.address, data="?"))
        # self.read_message()
        # Read software limits
        reply = self.query(NewportMessage("SL", address=self.address, data="?"))
        self._neg_limit = float(reply.data) * 1000
        reply = self.query(NewportMessage("SR", address=self.address, data="?"))
        self._pos_limit = float(reply.data) * 1000

    def configure_homing(self):
        """
        Configure homing parameters, done automatically if axis is not homed.
        """
        # Enter configuration mode
        self.send_message(NewportMessage("PW", address=self.address, data="1"))
        while self._state != "14": # '14' = CONFIGURATION
            self.update_status()
            time.sleep(0.05)
        # Set Home search parameters
        self.set_home_velocity()
        self.set_home_timeout(60)
        # Leave configuration mode, now ready for homing
        self.send_message(NewportMessage("PW", address=self.address, data="0"))
        while self._state != "0C": # '0C' = NOT REFERENCED from CONFIGURATION
            self.update_status()
            time.sleep(0.05)

    def configure_limits(self, neg_limit: float, pos_limit: float):
        """
        Configure the SMC100 Motion Controller software limits.

        The controller normally comes with correct predefined limits, so use this method with care.
        Limits are expected to be expressed in micrometers.
        """
        # Enter configuration mode
        self.send_message(NewportMessage("PW", address=self.address, data="1"))
        while self._state != "14": # '14' = CONFIGURATION
            self.update_status()
            time.sleep(0.05)
        # Configure limits
        self._neg_limit = neg_limit * 1000
        self.send_message(NewportMessage("SL", address=self.address, data=str(self._neg_limit)))
        self._pos_limit = pos_limit * 1000
        self.send_message(NewportMessage("SR", address=self.address, data=str(self._pos_limit)))
        # Leave configuration mode, now ready for homing
        self.send_message(NewportMessage("PW", address=self.address, data="0"))
        while self._state != "0C": # '0C' = NOT REFERENCED from CONFIGURATION
            self.update_status()
            time.sleep(0.05)

    # ==== Properties

    @property
    def address(self) -> str:
        """
        The address of this device, used if multiple devices are daisy-chained and accessible
        through the same Serial communication.
        """
        return str(self._address)

    @property
    def moving(self) -> bool:
        """
        True if currently in motion for absolute/relative movement, else False.
        """
        return self._state == "28"

    @property
    def jogging(self) -> bool:
        """
        True if currently in motion for jogging movement, else False.
        """
        return self._state in ("46", "47")

    @property
    def homing(self) -> bool:
        """
        True if currently in motion for homing operation, else False.
        """
        return self._state in ("1E", "1F")

    @property
    def homed(self) -> bool:
        """
        True if homing has been completed, else False.
        """
        return self._state not in ("0A", "0B", "0C", "0D", "0E", "0F", "10", "11", "14", "1E", "1F")

    @property
    def ready(self) -> bool:
        """
        True if ready for a new action, else False.
        """
        return self._state in ("32", "33", "34", "35")

    # ==== Serial communication

    def send_message(self, message: NewportMessage):
        """
        Send a given message to the controller.
        """
        self.serial.write(message.pack())

    def read_message(self) -> NewportMessage:
        """
        Read a message from the controller.
        Return the reply as a NewportMessage.

        Raises UnicodeDecodeError on invalid reply received and TimeoutError on timeout.
        """
        # Replies are expected to end with '\r\n'
        reply = self.serial.read_until("\r\n")
        if reply is None:
            raise TimeoutError("A timeout occured while waiting for reply.")
        reply = reply.decode("utf-8").rstrip("\r\n")
        return NewportMessage(
            reply[len(self.address):len(self.address)+2],
            address=reply[:len(self.address)],
            data=reply[len(self.address)+2:]
        )

    def query(self, message: NewportMessage) -> NewportMessage:
        """
        Send and receive combined in a single method.
        If the received reply is empty, resend the message.

        Raises a TimeoutError on timeout or after MAX_RETRY retries.
        """
        # Check number of retries
        if self._retries > self.MAX_RETRY:
            raise TimeoutError(f"Unable to receive a valid reply after {self._retries} retries.")
        # Send message
        self.send_message(message)
        try:
            reply = self.read_message()
            # Reset number of retries on success
            self._retries = 0
        except UnicodeDecodeError:
            # Increase number of retries and retry
            self._retries += 1
            return self.query(message)
        return reply

    # ==== Error management

    def verify_last_command(self):
        """
        Retrieve the last command error, and raise an error if required.

        Must be called after most commands.
        """
        reply = self.query(NewportMessage("TE", address=self.address))
        # '@' means no error occured during last command
        if reply.data == "@":
            return
        # Query command error explanation
        reply = self.query(NewportMessage("TB", address=self.address, data=reply.data))
        raise ControllerError(f"Controller returned a command error: {reply.data}")

    # ==== Status management

    def update_status(self) -> bool:
        """
        Update this controller internal status and position.
        """
        # First update status
        reply = self.query(NewportMessage("TS", address=self.address))
        self._error = reply.data[0:4]
        self._state = reply.data[4:6]
        if self._error != "0000":
            raise ControllerError(f"Controller returned a status error code: {self._error}")
        # Then update position
        reply = self.query(NewportMessage("TP", address=self.address))
        self.position = float(reply.data) * 1000

    # ==== Parameters commands

    def set_motion_acceleration(self, acceleration: float):
        """
        Set the acceleration of the axis for motion operations.

        Acceleration is expected to be in µm/s².
        """
        # Scale value
        acceleration /= 1000.
        # Send command
        self.send_message(NewportMessage("AC", address=self.address, data=str(acceleration)))
        self.verify_last_command()

    def set_motion_velocity(self, velocity: float):
        """
        Set the velocity of the axis for motion operations.

        Velocity is expected to be in µm/s.
        """
        # Scale value
        velocity /= 1000.
        # Send command
        self.send_message(NewportMessage("VA", address=self.address, data=str(velocity)))
        self.verify_last_command()

    def set_home_velocity(self):
        """
        Configure the home search velocity of the axis to 2mm/s.
        """
        self.send_message(NewportMessage("OH", address=self.address, data="2"))
        self.verify_last_command()

    def set_home_timeout(self, timeout: float):
        """
        Configure the home search timeout. Timeout is expressed in seconds.
        """
        self.send_message(NewportMessage("OT", address=self.address, data=str(timeout)))
        self.verify_last_command()

    # ==== Movement commands

    def home(self):
        """
        Request a homing operation.
        """
        self.send_message(NewportMessage("OR", address=self.address))
        self.verify_last_command()

    def move_absolute(self, position_um: float):
        """
        Request a move to the positon `position_um` micrometers.
        """
        # Scale value
        position_um /= 1000.
        # Send command
        self.send_message(NewportMessage("PA", address=self.address, data=str(position_um)))
        self.verify_last_command()

    def move_relative(self, distance_um: float):
        """
        Request a move by a distance of `distance_um` micrometers.
        """
        # Scale value
        distance_um /= 1000.
        # Send command
        self.send_message(NewportMessage("PR", address=self.address, data=str(distance_um)))
        self.verify_last_command()

    def stop(self):
        """
        Stop any ongoing operation.
        """
        self.send_message(NewportMessage("ST", address=self.address))
        self.verify_last_command()
