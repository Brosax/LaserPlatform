
Camera controller through GenTL Producer plugin for **Analyzr2**.

## Setup

TODO

## Requirements

This plugin requires the [harversters](https://github.com/genicam/harvesters) Python library. It can be installed using:

```sh
pip install harvesters
```

It also requires the **.cti** file associated with the device to connect to.

## Implementation details

This plugin currently requires a device capable of outputting *Mono14* PixelFormat images (hardcoded format) and forces a 60fps framerate.
