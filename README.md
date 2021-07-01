# xsens-dot-connector

> Use an XSens DOT from pure python code, with no external dependencies

**EXPERIMENTAL**: this is just something I'm hacking together to move a 
project forward. It is not a full-fat library, nor robust.

The Python code in here is a low-level [Bluetooth Low-Energy](https://en.wikipedia.org/wiki/Bluetooth_Low_Energy)
client implementation that can pull useful information from an [XSens DOT](https://www.xsens.com/xsens-dot). The
implementation is pure Python that is only dependent on the Python standard library and [bleak](https://github.com/hbldh/bleak).

This implements an extremely basic wrapper over XSens's "raw" BLE specification, rather than relying on any XSens 
library code. The motivation for this is that other solutions out there involve using different platforms 
(e.g. the Android SDK /w Kotlin or Java, NodeJS) or involve installing third-party applications. It's *much* cleaner
to have a system that is written in one language with no third-party software required to run it, so that's why I
wrote these bindings.

## Requirements

- `python>=3.9`: may work on earlier pythons. Haven't tested
- `pip`: to install `bleak`. Not a hard requirement, if you know how to manually install packages

## Usage

- Install dependencies

```bash
pip3 install -r requirements.txt
```

- Use it:

```python
import xdc
import asyncio

async def run():
    dot_bles = await xdc.scan_for_DOT_BLEDevices()
    for dot_ble in dot_bles:
        async with xdc.DotDevice(dot_ble) as dot:
            info = await d.device_info()
            print(info)
            
loop = asyncio.get_event_loop()
loop.run_until_complete(run())
```
