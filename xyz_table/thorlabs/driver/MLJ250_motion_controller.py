import enum
import struct
import typing

import serial

from .thorlabs_devices import ThorlabsMessage, ThorlabsDevice

class MLJ250Commands(enum.Enum):
    MOD_IDENTIFY = 0x0223
    MOD_SET_CHANENABLESTATE = 0x0210
    HW_START_UPDATEMSGS = 0x0011
    HW_STOP_UPDATEMSGS = 0x0012
    HW_REQ_INFO = 0x0005
    HW_GET_INFO = 0x0006
    MOT_SET_ENCCOUNTER = 0x0409
    MOT_REQ_ENCCOUNTER = 0x040A
    MOT_GET_ENCCOUNTER = 0x040B
    MOT_SET_POSCOUNTER = 0x0410
    MOT_REQ_POSCOUNTER = 0x0411
    MOT_GET_POSCOUNTER = 0x0412
    MOT_SET_VELPARAMS = 0x0413
    MOT_REQ_VELPARAMS = 0x0414
    MOT_GET_VELPARAMS = 0x0415
    MOT_SET_JOGPARAMS = 0x0416
    MOT_REQ_JOGPARAMS = 0x0417
    MOT_GET_JOGPARAMS = 0x0418
    MOT_SET_GENMOVEPARAMS = 0x043A
    MOT_REQ_GENMOVEPARAMS = 0x043B
    MOT_GET_GENMOVEPARAMS = 0x043C
    MOT_SET_MOVERELPARAMS = 0x0445
    MOT_REQ_MOVERELPARAMS = 0x0446
    MOT_GET_MOVERELPARAMS = 0x0447
    MOT_SET_MOVEABSPARAMS = 0x0450
    MOT_REQ_MOVEABSPARAMS = 0x0451
    MOT_GET_MOVEABSPARAMS = 0x0452
    MOT_SET_HOMEPARAMS = 0x0440
    MOT_REQ_HOMEPARAMS = 0x0441
    MOT_GET_HOMEPARAMS = 0x0442
    MOT_SET_LIMSWITCHPARAMS = 0x0423
    MOT_REQ_LIMSWITCHPARAMS = 0x0424
    MOT_GET_LIMSWITCHPARAMS = 0x0425
    MOT_SET_POWERPARAMS = 0x0426
    MOT_REQ_POWERPARAMS = 0x0427
    MOT_GET_POWERPARAMS = 0x0428
    MOT_MOVE_HOME = 0x0443
    MOT_MOVE_HOMED = 0x0444
    MOT_MOVE_RELATIVE = 0x0448
    MOT_MOVE_COMPLETED = 0x0464
    MOT_MOVE_ABSOLUTE = 0x0453
    MOT_MOVE_JOG = 0x046A
    MOT_MOVE_VELOCITY = 0x0457
    MOT_MOVE_STOP = 0x0465
    MOT_MOVE_STOPPED = 0x0466
    MOT_SET_BOWINDEX = 0x0450
    MOT_REQ_BOWINDEX = 0x0451
    MOT_GET_BOWINDEX = 0x0452
    MOT_SET_EEPROMPARAMS = 0x04B9
    MOT_GET_STATUSUPDATE = 0x0481
    MOT_REQ_STATUSUPDATE = 0x0480
    MOT_REQ_STATUSBITS = 0x0429
    MOT_GET_STATUSBITS = 0x042A
    MOT_SET_POTPARAMS = 0x04B0
    MOT_REQ_POTPARAMS = 0x04B1
    MOT_GET_POTPARAMS = 0x04B2
    MOT_SET_BUTTONPARAMS = 0x04B6
    MOT_REQ_BUTTONPARAMS = 0x04B7
    MOT_GET_BUTTONPARAMS = 0x04B8
    MOT_SUSPEND_ENDOFMOVEMSGS = 0x046B
    MOT_RESUME_ENDOFMOVEMSGS = 0x046C

class MLJ250MotionController(ThorlabsDevice):
    """
    Implementation of the MLJ250 Motion Controller from Thorlabs.

    Note: Apparent magic numbers in some commands comes from the Analyzr JAVA LaserZAxis plugin.
    Further research is required to compute those values instead of relying on hardcoded ones...
    """
    DESTINATION = 0x50
    SOURCE = 0x01

    # 1mm is 1228800 microsteps
    POS_UM_TO_ENC_RATIO = 1228.8
    # Speed and Acceleration ratios from datasheet
    VEL_UM_TO_ENC_RATIO = POS_UM_TO_ENC_RATIO * 53.98
    ACC_UM_TO_ENC_RATIO = POS_UM_TO_ENC_RATIO / 90.9

    # ==== Init

    def __init__(
        self,
        ser: serial.Serial,
        status_callback: typing.Callable = None
    ) -> None:
        super().__init__(ser, 0x01)
        # Register status callback
        self._status_callback = status_callback

    def _set_internal_status(self, data):
        super()._set_internal_status(data)
        if self._status_callback is not None:
            self._status_callback()

    # ==== Properties

    @property
    def position_um(self) -> float:
        """
        The absolute position of this controller in micrometer.
        """
        return round((self._position / self.POS_UM_TO_ENC_RATIO), 2)

    # ==== Commands

    def request_hardware_info(self) -> bytes:
        """
        Request the hardware information of this controller.

        Reply content:
           6 ->  9: serial number
          10 -> 17: model number
          18 -> 19: type
          20 -> 23: FW version
          24 -> 83: Reserved (internal use)
          84 -> 85: HW version
          86 -> 87: Mod state
          88 -> 89: Number of channels
        TODO careful, offsets here accounts for header not included in returned bytes
        """
        self.send_message(
            ThorlabsMessage(MLJ250Commands.HW_GET_INFO.value, self.SOURCE, self.DESTINATION)
        )
        reply = self.read_message()
        if reply is None:
            raise TimeoutError
        return reply.data

    def enable_channel(self) -> None:
        """
        Enable the channel used on this controller.
        """
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOD_SET_CHANENABLESTATE.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=self.channel,
                param_2=0x1
            )
        )

    def update_status(self) -> bool:
        """
        Update this controller internal status.

        Return True if the status was updated, False otherwise.
        """
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_REQ_STATUSUPDATE.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=self.channel)
        )
        # Expect a status update message.
        reply = self.read_message()
        status = self.validate_message(
            reply,
            MLJ250Commands.MOT_GET_STATUSUPDATE.value,
            param_1=0x0E
        )
        # If command was valid, update internal status
        if status:
            self._set_internal_status(reply.data)
        return status

    # ==== Parameters commands

    def set_velocity_parameters(self, min_velocity: float, max_velocity: float, acceleration:float):
        """
        Set the velocity parameters of this controller.

        Note that the velocity during a move follows a trapezoidal profile.

        Parameters
        ----------
        min_velocity : float
            Initial velocity during movement, in µm/s
        max_velocity : float
            Final velocity during movement, in µm/s
        acceleration : float
            Acceleration during movement, in µm/s²
        """
        # channel ; min velocity ; acceleration ; max velocity
        data = struct.pack(
            "<HLLL",
            self.channel,
            int(min_velocity * self.VEL_UM_TO_ENC_RATIO),
            int(acceleration * self.ACC_UM_TO_ENC_RATIO),
            int(max_velocity * self.VEL_UM_TO_ENC_RATIO)
        )
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_VELPARAMS.value,
                source=self.SOURCE,
                destination=self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_jog_parameters(self, step_um: float=50.0):
        """
        Set the jog parameters of this controller.

        Currently, fixed to a maximum velocity of 0.5mm/s and an acceleration of 0.25mm/s².
        Later, this method should allow specifying the required parameters.

        Parameters
        ----------
        step_um : int
            The jog step in micrometer. Defaults to 50.0µm.
        """
        # channel ; single jog ; step size ; min velocity ; acceleration ; max velocity ; stop mode
        data = struct.pack(
            "<HHLLLLH",
            self.channel,
            0x02,
            int(step_um * self.POS_UM_TO_ENC_RATIO),
            0,
            250 * self.ACC_UM_TO_ENC_RATIO,
            500 * self.VEL_UM_TO_ENC_RATIO,
            0x02
        )
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_JOGPARAMS.value,
                source=self.SOURCE,
                destination=self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_limit_switch_parameters(self, cw_hard_limit: int=0x02, ccw_hard_limit: int=0x02):
        """
        Set the limit switch parameters of this controller.

        Currently, set hardware limits and ignore software limits.
        """
        # channel ; CW Hard limit ; CCW Hard limit ; CW Soft limit ; CCW Soft limit ; SW limit mode
        data = struct.pack("<HHHLLH", self.channel, cw_hard_limit, ccw_hard_limit, 0, 0, 0x01)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_LIMSWITCHPARAMS.value,
                source=self.SOURCE,
                destination=self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_power_parameters(self, rest_factor: int=20, move_factor: int=100):
        """
        Set the power parameters of this controller.

        Parameters are expressed as percentages of full power.
        """
        if rest_factor > 100:
            raise ValueError(
                f"Cannot set rest_factor larger than 100% (requested {rest_factor}%)!"
            )
        if move_factor > 100:
            raise ValueError(
                f"Cannot set move_factor larger than 100% (requested {move_factor}%)!"
            )
        data = struct.pack("<HHH", self.channel, rest_factor, move_factor)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_POWERPARAMS.value,
                source=self.SOURCE,
                destination=self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_backlash_parameters(self, distance_um: float=50.0):
        """
        Set the backlash distance of this controller.

        Parameters
        ----------
        distance_um : float
            The backlash distance in nanometers. Defaults to 50µm.
        """
        data = struct.pack("<HL", self.channel, int(distance_um * self.POS_UM_TO_ENC_RATIO))
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_GENMOVEPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_home_parameters(self): # p76
        """
        Set the homing parameters of this controller.

        Parameters of this command are currently hard coded.
        Later, this method should allow specifying them.
        """
        # Velocity: 1228800 * 53.68 for 1mm/s
        velocity = int(1228800 * 53.68)
        # channel ; direction ; limit switch ; velocity ; offset distance
        data = struct.pack("<HHHLL", self.channel, 0x02, 0x01, velocity, 0x6943)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_HOMEPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_relative_movement_parameters(self, distance_um: float=2.0):
        """
        Set the relative move distance of this controller.
        THe specified distance is used if using the relative move command without any argument.

        Parameters
        ----------
        distance_um : int
            The relative move distance in nanometers. Defaults to 2µm.
        """
        data = struct.pack("<HL", self.channel, int(distance_um * self.POS_UM_TO_ENC_RATIO))
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_MOVERELPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_absolute_movement_parameters(self, distance_um: float=0.0):
        """
        Set the absolute move distance of this controller.
        The specified distance is used if using the absolute move command without any argument.

        Parameters
        ----------
        distance_um : int
            The relative move distance in micrometers. Defaults to 0µm.
        """
        data = struct.pack("<HL", self.channel, int(distance_um * self.POS_UM_TO_ENC_RATIO))
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_MOVEABSPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_potentiometer_parameters(self):
        """
        Set the potentiometer parameters.

        Currently uses fixed values.
        """
        # channel ; zerownd ; vel1 ; wnd1 ; vel2 ; wnd2 ; vel3 ; wnd3 ; vel4
        data = struct.pack("<HHLHLHLHL", self.channel, 0x01, 0x017028, 0x32, 0, 0x54, 0, 0x64, 0)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_POTPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_button_parameters(
        self, mode: int, *, position_um1: float = None, position_um2: float = None
    ):
        """
        Set the mode for the button of this controller.
          1: Jog mode. The button jog the motor according to the jog parameters.
          2: Position mode. Each button move the controller to the given positions.

        Button timeout is fixed to 2s.
        """
        # channel ; mode ; position1 ; position2 ; timeout1 ; timeout2
        data = struct.pack("<HH", self.channel, mode)
        # Switch on requested mode
        if mode == 1:
            data += struct.pack("<LL", 0, 0)
        elif mode == 2:
            if position_um1 is None or position_um2 is None:
                raise ValueError("Positions must be defined when setting button to position mode!")
            data += struct.pack(
                "<LL",
                int(position_um1 * self.POS_UM_TO_ENC_RATIO),
                int(position_um2 * self.POS_UM_TO_ENC_RATIO)
            )
        else:
            raise ValueError(f"Incorrect requested button mode: {mode}")
        # Add fixed timeout values
        data += struct.pack("<HH", 0x7D0, 0x7D0)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_BUTTONPARAMS.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def set_encoder_count(self, count: int):
        """
        Set the encoder count to the given value.

        Following a home operation, the encoder count should be set to 0.
        """
        data = struct.pack("<Hl", self.channel, count)
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_SET_ENCCOUNTER.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    # ==== Movement commands

    def home(self) -> bool:
        """
        Send a homing request to the motion controller.
        """
        # NOTE: requires home parameters to be set, maybe do a get request to verify it is ready
        # Send homing request
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_MOVE_HOME.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=self.channel
            )
        )

    def move_absolute(self, position_um: float):
        """
        Move to the given absolute position, in micrometer.
        """
        data = struct.pack("<HL", self.channel, int(position_um * self.POS_UM_TO_ENC_RATIO))
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_MOVE_ABSOLUTE.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def move_relative(self, distance_um: float):
        """
        Move the given distance, in micrometer.
        """
        data = struct.pack("<HL", self.channel, int(distance_um * self.POS_UM_TO_ENC_RATIO))
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_MOVE_RELATIVE.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=len(data),
                data=data
            )
        )

    def stop(self) -> bool:
        """
        Immediatly stop the current moving operation.
        """
        # 0x1 requests an abrupt stop request
        self.send_message(
            ThorlabsMessage(
                MLJ250Commands.MOT_MOVE_STOP.value,
                self.SOURCE,
                self.DESTINATION,
                param_1=self.channel,
                param_2=0x1
            )
        )
