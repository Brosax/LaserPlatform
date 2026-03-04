"""
Plugin for a generic XYZ table device.

Accepts any `AxisInterface` objects.
"""
import enum
import functools
import typing

from PySide6 import QtCore, QtGui, QtWidgets

import analyzr2
from .interfaces.axis import AxisInterface


class AxisEnum(enum.Enum):
    """
    Enumerate for axis positions.
    """
    X_AXIS = 0
    Y_AXIS = 1
    Z_AXIS = 2


class XYZ:
    """
    Generic class for control of 3 (X, Y, Z) AxisInterface objects.
    """
    def __init__(self, x_axis: AxisInterface, y_axis: AxisInterface, z_axis: AxisInterface):
        self._axis: dict[AxisEnum, AxisInterface] = {
            AxisEnum.X_AXIS: x_axis,
            AxisEnum.Y_AXIS: y_axis,
            AxisEnum.Z_AXIS: z_axis,
        }

    def homing(self, axis: AxisEnum=None):
        """
        Start the homing procedure on the given axis, or all axises if None is specified.
        """
        if axis:
            self._axis[axis].homing()
        else:
            for a in self._axis.values():
                a.homing()

    def move_to(self, axis: AxisEnum, position_um: float):
        """
        Move the given axis to the absolute position, in micrometer.
        """
        self._axis[axis].move_to(position_um)

    def move_by(self, axis: AxisEnum, distance_um: float):
        """
        Move the given axis by the given distance, in micrometer.
        """
        self._axis[axis].move_by(distance_um)

    def halt(self, axis: AxisEnum=None):
        """
        Halt the given axis current motion, or all axises if None is specified.
        """
        if axis:
            self._axis[axis].halt()
            return
        for ax in self._axis.values():
            if ax is not None:
                ax.halt()

# Custom Parameters

class AxisParameter(analyzr2.parameters.ParameterWidget):
    """
    Custom Parameter to allow configuration of a generic AxisInterface object.
    """
    class AxisConfiguration(typing.NamedTuple):
        """
        Tuple for Axis configuration transmission to the XYZ block.
        """
        axis_type: AxisInterface
        com_port: str
        address: int
        timeout: float

    def __init__(self, axis_name: str, **kwargs):
        super().__init__(display=None)
        self.axis_label = QtWidgets.QLabel(axis_name)
        label_font = QtGui.QFont(QtWidgets.QApplication.font())
        label_font.setBold(True)
        self.axis_label.setFont(label_font)
        # Interactive widgets
        self.type_combobox = QtWidgets.QComboBox()
        for subclass in AxisInterface.__subclasses__():
            self.type_combobox.addItem(subclass.__name__, subclass)
        self.type_combobox.setCurrentIndex(-1)
        self.com_port_combobox = analyzr2.parameters.com_port_selector()()
        self.address_field = analyzr2.parameters.variable(itype=int, default=0)()
        self.timeout_field = analyzr2.inputs.pint_quantity(
            analyzr2.pint.registry.second,
            prefixes=["", "milli"],
            min=0.0*analyzr2.pint.registry.second,
            default=10.0*analyzr2.pint.registry.second)()
        self.confirm_button = QtWidgets.QPushButton("Connect...")
        self.confirm_button.setEnabled(False)
        self.confirm_button.setProperty("class", "primary-button")
        # Connect signal
        self.type_combobox.currentIndexChanged.connect(self._on_widget_update)
        self.com_port_combobox.validate.connect(self._on_widget_update)
        self.confirm_button.clicked.connect(self._on_connect_clicked)
        # Set some tooltips
        self.type_combobox.setToolTip("The controller model for this axis.")
        self.com_port_combobox.setToolTip(
            "The COM Port used for communicating with the controller.")
        self.address_field.setToolTip(
            "Address of the controller, used if multiple controllers are chained on a single "
            "COM Port.")
        self.timeout_field.setToolTip(
            "Timeout of the COM Port communication. "
            "Behavior on controller timeout is controller-dependant.")
        # Layout creation
        self.setLayout(QtWidgets.QFormLayout())
        self.layout().addRow(self.axis_label)
        self.layout().addRow("Model", self.type_combobox)
        self.layout().addRow("COM Port", self.com_port_combobox)
        self.layout().addRow("Address", self.address_field)
        self.layout().addRow("Timeout", self.timeout_field)
        self.layout().addRow(self.confirm_button)

    def set_default(self, default: list):
        default = self.AxisConfiguration(*default)
        self.type_combobox.setCurrentIndex(self.type_combobox.findData(default.axis_type))
        self.com_port_combobox.set_default(default.com_port)
        self.address_field.set_default(default.address)
        self.timeout_field.set_default(default.timeout * analyzr2.pint.registry.second)

    def _on_widget_update(self, _):
        """
        Enable the button when comboboxes have been filled.
        """
        if self.type_combobox.currentData() is None:
            self.confirm_button.setEnabled(False)
            return
        if self.com_port_combobox.combobox.currentData() is None:
            self.confirm_button.setEnabled(False)
            return
        self.confirm_button.setEnabled(True)

    @property
    def enforced_type(self):
        """
        If set from a slot, expects a list (due to tuple -> list conversion in JSON formatting).
        """
        return typing.Union[list, AxisInterface]

    def _on_connect_clicked(self):
        """
        On clicking the Confirm button, send the AxisConfiguration to the Block.
        """
        self.confirm(self.AxisConfiguration(
            self.type_combobox.currentData(),
            self.com_port_combobox._current,
            self.address_field._current,
            self.timeout_field._current.to(analyzr2.pint.registry.second).magnitude
        ))

# Custom Widgets

class AxisPositionController(QtWidgets.QWidget):
    """
    A custom widget for controlling an axis position, either through back/forward buttons, or
    by entering the requested position.
    """
    position_updated = QtCore.Signal()

    def __init__(self, name: str, position: float):
        super().__init__()
        self.position = position
        # Widgets configuration
        self.label_name = QtWidgets.QLabel(name)
        self.label_name.setFixedWidth(
            QtGui.QFontMetrics(self.label_name.font()).horizontalAdvance(self.label_name.text()))
        self.button_back = QtWidgets.QPushButton("<")
        self.button_back.setFixedSize(QtCore.QSize(16, 16))
        self.button_back.clicked.connect(self.decrease_position)
        self.lineedit_value = QtWidgets.QLineEdit(str(self.position))
        self.lineedit_value.setValidator(
            QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"\-?[0-9]*[.]?[0-9]+")))
        self.lineedit_value.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.lineedit_value.setFixedWidth(64)
        self.lineedit_value.editingFinished.connect(self.confirm_position)
        self.label_unit = QtWidgets.QLabel("µm")
        self.label_unit.setFixedWidth(
            QtGui.QFontMetrics(self.label_unit.font()).horizontalAdvance(self.label_unit.text()))
        self.button_forward = QtWidgets.QPushButton(">")
        self.button_forward.setFixedSize(QtCore.QSize(16, 16))
        self.button_forward.clicked.connect(self.increase_position)
        # Layout configuration
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().addWidget(self.label_name)
        self.layout().addWidget(self.button_back)
        self.layout().addWidget(self.lineedit_value)
        self.layout().addWidget(self.label_unit)
        self.layout().addWidget(self.button_forward)
        self.layout().setContentsMargins(2, 2, 2, 2)
        self.layout().setSpacing(2)

    def confirm_position(self):
        """
        Validate the current position and send it.
        """
        self.position = float(self.lineedit_value.text())
        self.position_updated.emit()

    def decrease_position(self):
        """
        Called whenever button_back is clicked. Decrease the current position by 1.
        """
        self.update_position(self.position - 1.0, emit=True)

    def increase_position(self):
        """
        Called whenever button_forward is clicked. Increase the current position by 1.
        """
        self.update_position(self.position + 1.0, emit=True)

    def update_position(self, position: float, emit: bool=False):
        """
        Update the current position to the given one.
        """
        self.position = position
        self.lineedit_value.setText(str(self.position))
        if emit:
            self.position_updated.emit()


class TablePositionController(analyzr2.widgets.EmbeddedWidget):
    """
    A custom EmbeddedWidget handling AxisPositionController widgets for an XYZ table.
    """
    position_updated = QtCore.Signal(float, float, float)

    def __init__(self, layout = QtWidgets.QVBoxLayout):
        super().__init__(layout)
        self.setMinimumSize(120, 75)
        self.setEnabled(False)
        # Widget configuration
        self.x_axis_controller = AxisPositionController("X-axis", 0.0)
        self.x_axis_controller.position_updated.connect(self.send_position)
        self.y_axis_controller = AxisPositionController("Y-axis", 0.0)
        self.y_axis_controller.position_updated.connect(self.send_position)
        self.z_axis_controller = AxisPositionController("Z-axis", 0.0)
        self.z_axis_controller.position_updated.connect(self.send_position)
        # Layout configuration
        self.layout().addWidget(self.x_axis_controller)
        self.layout().addWidget(self.y_axis_controller)
        self.layout().addWidget(self.z_axis_controller)

    def set_positions(self, x_pos: float, y_pos: float, z_pos: float):
        """
        Set the current positions of the axis. Should not emit a signal.
        """
        self.x_axis_controller.update_position(x_pos)
        self.y_axis_controller.update_position(y_pos)
        self.z_axis_controller.update_position(z_pos)

    def send_position(self):
        """
        Called when an axis controller position has changed. Send the new positions.
        """
        self.position_updated.emit(
            self.x_axis_controller.position,
            self.y_axis_controller.position,
            self.z_axis_controller.position)

# XYZ Table Blocks

class _XYZManualControl(analyzr2.Block):
    """
    Allow manually adjusting an XYZ table position.

    If executed, enable/disable the embedded widget.
    """
    inputs = {
        analyzr2.TypedSlot("xyz", XYZ): analyzr2.Undefined
    }
    widgets = {
        "position_controller": {
            analyzr2.widgets.Config: {
                "type": TablePositionController
            },
            analyzr2.widgets.Connect: {
                "position_updated": "position_updated"
            }
        }
    }

    def create(self):
        self.widget_enabled = True
        self.xyz = analyzr2.Undefined

    def process(self):
        self.widget_enabled |= self.widget_enabled
        self.position_controller.setEnabled(self.widget_enabled)

    # New methods

    @analyzr2.callback("xyz")
    def configure_widget(self):
        """
        Called whenever xyz is set. Configure the widget to the current table position.
        """
        if isinstance(self.xyz, XYZ):
            self.widget_enabled = True
            self.position_controller.setEnabled(True)
            self.position_controller.set_positions(
                self.xyz._axis[AxisEnum.X_AXIS].position,
                self.xyz._axis[AxisEnum.Y_AXIS].position,
                self.xyz._axis[AxisEnum.Z_AXIS].position)

    def position_updated(self, x_pos: float, y_pos: float, z_pos: float):
        """
        Called from the widget. Request the XYZ table to move to the requested position.
        """
        if isinstance(self.xyz, XYZ):
            # Request XYZ table to move to the given position
            self.xyz.move_to(AxisEnum.X_AXIS, x_pos)
            self.xyz.move_to(AxisEnum.Y_AXIS, y_pos)
            self.xyz.move_to(AxisEnum.Z_AXIS, z_pos)


class _XYZMoveTo(analyzr2.Block):
    """
    Move the XYZ table controller to an absolute position.

    Inputs
    ------
    xyz : XYZ
        The XYZ table controller object.
    positions_um : tuple[Union[int, None]]
        An (x, y, z) tuple representing the position to move to, in micrometers.
        If a value is set to None, this axis movement is ignored.
    """
    inputs = {
        analyzr2.TypedSlot("xyz", XYZ): analyzr2.Undefined,
        analyzr2.TypedSlot("positions_um", tuple): analyzr2.Undefined
    }

    def process(self):
        if len(self.positions_um) != len(self.xyz._axis):
            raise ValueError(f"Incorrect number of values for XYZ motion in: {self.positions_um}")
        for index, position_um in enumerate(self.positions_um):
            if position_um is None:
                continue
            self.xyz.move_to(AxisEnum(index), position_um)


class _XYZStop(analyzr2.Block):
    """
    Stop any current movement on the XYZ table controller.

    Inputs
    ------
    xyz : XYZ
        The XYZ table controller object.
    """
    inputs = {
        analyzr2.TypedSlot("xyz", XYZ): analyzr2.Undefined
    }

    def process(self):
        self.xyz.halt()


class XYZTable(analyzr2.Block):
    """
    Generic XYZ table controller constructor.

    Allow the configuration of each axis from any available AxisInterface object.

    Parameters
    ----------
    X-Axis : AxisInterface
        The X-Axis controller object. If set from a slot, must be an AxisInterface object.
    Y-Axis : AxisInterface
        The Y-Axis controller object. If set from a slot, must be an AxisInterface object.
    Z-Axis : AxisInterface
        The Z-Axis controller object. If set from a slot, must be an AxisInterface object.

    Outputs
    -------
    xyz : XYZ
        The XYZ controller object.
    """
    blocks = {
        "MoveTo": _XYZMoveTo,
        "Stop": _XYZStop,
        "ManualController": _XYZManualControl
    }
    parameters = {
        "_x_axis": functools.partial(AxisParameter, "X-Axis"),
        "_y_axis": functools.partial(AxisParameter, "Y-Axis"),
        "_z_axis": functools.partial(AxisParameter, "Z-Axis"),
    }
    outputs = [analyzr2.TypedSlot("xyz", XYZ)]
    widgets = {
        "button_homing": {
            analyzr2.widgets.Config: {
                "type": analyzr2.widgets.button("Homing")
            },
            analyzr2.widgets.Connect: {
                "clicked": "_homing_procedure"
            }
        }
    }

    def create(self):
        self._xyz = XYZ(None, None, None)
        self.button_homing.setEnabled(False)

    def process(self):
        ready = True
        for axis, interface in self._xyz._axis.items():
            if interface is None:
                analyzr2.logger.warning(f"Axis {axis.name} has not been configured yet!")
                ready = False
        if ready:
            if any(not axis.homed for axis in self._xyz._axis.values()):
                self.button_homing.setEnabled(True)
            self.xyz = self._xyz

    @analyzr2.callback("_x_axis")
    def _configure_x_axis(self):
        if self._x_axis is analyzr2.Undefined:
            return
        self._update_axis(AxisEnum.X_AXIS, self._x_axis)

    @analyzr2.callback("_y_axis")
    def _configure_y_axis(self):
        if self._y_axis is analyzr2.Undefined:
            return
        self._update_axis(AxisEnum.Y_AXIS, self._y_axis)

    @analyzr2.callback("_z_axis")
    def _configure_z_axis(self):
        if self._z_axis is analyzr2.Undefined:
            return
        self._update_axis(AxisEnum.Z_AXIS, self._z_axis)

    def _update_axis(
        self,
        axis: AxisEnum,
        config: typing.Union[AxisInterface, list]
    ) -> None:
        """
        Update an axis from the XYZ object.
        """
        if axis not in AxisEnum:
            raise ValueError(f"Unknown AxisEnum value: {axis}")
        # If config is already an AxisInterface, directly assign it
        if isinstance(config, AxisInterface):
            self._xyz._axis[axis] = config
            return
        # Cast list to AxisConfiguration named tuple
        if isinstance(config, list):
            config = AxisParameter.AxisConfiguration(*config)
            # Close previous axis if necessary
            if isinstance(self._xyz._axis[axis], AxisInterface):
                self._xyz._axis[axis].close()
            # Create new object
            self._xyz._axis[axis] = config.axis_type(
                config.com_port, config.address, config.timeout)
        else:
            raise ValueError(f"Unknown axis value: {config}")

    def _homing_procedure(self):
        for direction, axis in self._xyz._axis.items():
            analyzr2.logger.info(f"Homing axis {direction}")
            axis.homing()
