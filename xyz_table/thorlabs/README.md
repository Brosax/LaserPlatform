
Thorlabs Motion Controller plugin for **Analyzr2**.

Currently supported controllers:
- MLJ250 (should work with MLJ050 and MLJ150)

The `driver` folder contains files separated from the Analyzr2 ecosystem for optional external usage.

## Setup

For the Motion Controller devices to be controllable from a computer, the associated drivers need to be installed first.\
They are installed with the [Thorlabs APT Software](https://www.thorlabs.com/software_pages/viewsoftwarepage.cfm?code=Motion_Control).

This allow the Motion Controller devices to be visible as USB device, but since the plugin uses serial communication, an additional step is required.

Within the **Device Manager**, right click on the APT USB device and select `Properties`. Under the `Advanced` tab, check the "Load VCP" checkbox, and unplug / replug the USB device. An additional APT USB device should now appear within the COM ports.

Note that this step must be done each type the Motion Controller is disconnected / reconnected to the computer.

## Python requirements

This plugin only requires the `pyserial` package, which is already included in the Analyzr2 requirements.
