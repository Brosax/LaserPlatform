from __future__ import annotations
import struct
import typing

import serial

class ThorlabsMessage():
    """
    Defines the structure of the messages sent to and from a Thorlabs device.
    """
    HEADER_FORMAT = "<HBBBB"

    def __init__(
        self,
        command: int,
        source: int,
        destination: int,
        *,
        param_1: int = 0x00,
        param_2: int = 0x00,
        data: typing.Optional[bytes] = None
    ) -> None:
        self.command: int = command
        self.source = source
        self.destination = destination
        self.param_1: int = param_1
        self.param_2: int = param_2
        self.data: typing.Optional[bytes] = data

    def pack(self) -> bytes:
        """
        Pack this message into bytes.
        """
        if self.data is None:
            request = struct.pack(
                self.HEADER_FORMAT,
                self.command,
                self.param_1,
                self.param_2,
                self.destination,
                self.source
            )
        else:
            request = struct.pack(
                self.HEADER_FORMAT,
                self.command,
                len(self.data),
                0x00,
                self.destination^0x80,
                self.source
            ) + self.data
        return request


class ThorlabsDevice():
    """
    Common class shared between all Thorlabs devices.
    """
    def __init__(self, ser: serial.Serial, channel: int):
        self.serial = ser
        # Controller configuration
        self.channel = channel
        # Status attributes
        self._position: int = 0
        self._velocity: int = 0
        self._current: int = 0
        self._status_bits: int = 0

    # ==== Properties

    @property
    def moving(self) -> bool:
        """
        True if currently in motion for absolute/relative movement, else False.
        """
        return bool(self._status_bits & 0x00000030)

    @property
    def jogging(self) -> bool:
        """
        True if currently in motion for jogging movement, else False.
        """
        return bool(self._status_bits & 0x000000C0)

    @property
    def homing(self) -> bool:
        """
        True if currently in motion for homing operation, else False.
        """
        return bool(self._status_bits & 0x00000200)

    @property
    def homed(self) -> bool:
        """
        True if homing has been completed, else False.
        """
        return bool(self._status_bits & 0x00000400)

    @property
    def interlock(self) -> bool:
        """
        True if the controller is in interlock state, else False.
        """
        return bool(self._status_bits & 0x00001000)

    # ==== Serial communication

    def send_message(self, message: ThorlabsMessage) -> None:
        """
        Send a given message to the controller.
        """
        # Send packed request
        self.serial.write(message.pack())

    def read_message(self) -> typing.Union[ThorlabsMessage, None]:
        """
        Read a message from the controller.

        Returns None on timeout.
        """
        header = self.serial.read(6)
        if len(header) < 6:
            raise TimeoutError("A timeout occured while waiting for reply header.\n"
                               f"Currently have: {header}")
        # Unpack the header
        command, param_1, param_2, destination, source = struct.unpack(
            ThorlabsMessage.HEADER_FORMAT,
            header
        )
        data = None
        # Read additional data if expected (8th bit set to 1 if additional data is present)
        if destination >> 7:
            data = self.serial.read(param_1)
            if len(data) < param_1:
                raise TimeoutError("A timeout occured while waiting for reply data.\n"
                                   f"Currently have: {data}")
        # Create object
        return ThorlabsMessage(
            command, source, destination, param_1=param_1, param_2=param_2, data=data
        )

    def validate_message(
        self,
        message: ThorlabsMessage,
        command: int,
        *,
        param_1: int = 0,
        param_2: int = 0
    ) ->  bool:
        """
        Validate a received message.
        Only check command type and param_1 / param_2.
        """
        if message is None:
            return False
        if param_1 not in (0, message.param_1):
            return False
        if param_2 not in (0, message.param_2):
            return False
        return command == message.command

    # ==== Status management (common for all controllers)

    def _set_internal_status(self, data: bytes):
        """
        Update the internal status of this controller object from the received data.
        """
        channel, position, velocity, current, bits = struct.unpack("<HLHHL", data)
        # Verify channel is correct
        if channel != self.channel:
            raise ValueError(f"Received status update for incorrect channel: {channel}")
        # Update status
        self._position = position
        self._velocity = velocity
        self._current = current
        self._status_bits = bits
