# xdc (XSens DOT Connector)

> Use an XSens DOT from pure python code, using `bleak`

> ⚠️**EXPERIMENTAL** ⚠️: this is just something I'm hacking together to move a
project forward. It is not a full-fat library, nor robust.

The Python code in here is a low-level [Bluetooth Low-Energy](https://en.wikipedia.org/wiki/Bluetooth_Low_Energy)
client implementation that can pull useful information from an [XSens DOT](https://www.xsens.com/xsens-dot). The
implementation is pure Python that is only dependent on the Python standard library and [bleak](https://github.com/hbldh/bleak).

This implements an extremely basic wrapper over XSens's "raw" BLE specification, rather than relying on any XSens 
library code. The motivation for this is that other solutions out there involve using different platforms 
(e.g. the Android SDK /w Kotlin or Java, NodeJS) or involve installing third-party applications. It's *much* cleaner
to have a system that is written in one language with minimal dependencies, which is why I
wrote these bindings.

## Requirements

- `python>=3.9`: may work on earlier pythons. Haven't tested
- `pip`: to install `bleak`. Not a hard requirement, if you know how to manually install packages


## Instal Dependencies

```bash
pip3 install -r requirements.txt
```

## API Usage Examples

```python
import xdc

# xdc code here, e.g.:

## DEVICE/CONNECTION LAYER: ##

# scan for all BLE devices the computer can see
#
# returns a list of `bleak.backends.device.BLEDevice`
xdc.scan_all()

# scan for all DOT devices the computer can see
#
# returns a list of `bleak.backends.device.BLEDevice`
xdc.scan()

# take an element from the scan list (`bleak.backends.device.BLEDevice`)
device = xdc.scan()[0]

# take the address (a string) of the device
#
# handy, because you can save the string to a config file etc. and use it
# to reconnect to the device after reboots etc.
address = device.address

# finds a BLE device by an address string
#
# returns `bleak.backends.device.BLEDevice`
xdc.find_by_address(address)

# same as above, but ensures the address points to a DOT by checking
# whether the device is a DOT after establishing the connection
#
# returns `bleak.backends.device.BLEDevice`
dot = xdc.find_dot_by_address(address)

## EXAMPLE CHARACTERISTIC USE (see source code for more examples) ##

# read the "Device Info Characteristic" for the given DOT
#
# returns `xdc.DeviceInfoCharacteristic`
xdc.device_info_read(dot)

# read the "Device Control Characteristic" for the given DOT
#
# returns `xdc.DeviceControlCharacteristic`
control_chr = xdc.device_control_read(dot)

# (example of modifying a characteristic before sending the
# modification to the DOT)
control_chr.output_rate = 4

# write a (potentially, modified) `xdc.DeviceControlCharacteristic` to
# the DOT. This is how you control the device
xdc.device_control_write(dot, control_chr)


# !!! HIGH-LEVEL CONVENIENCE API !!!
#
# this API is easy to use, but slow: it requires setting up and
# tearing down a new BLE connection every time a method is called
#
# see: `with xdc.Dot(...)` context manager, and `async` examples
# below if you need higher performance

# make the DOT flash its LED light a little bit, so that you can identify it
xdc.identify(dot)

# turn the DOT off
#
# turn it back on by pressing the DOT's button or shaking it
xdc.power_off(dot)

# enable powering the DOT on whenever the micro-USB charger is plugged in
#
# (handy for development)
xdc.enable_power_on_by_usb_plug_in(dot)

# disable powering the DOT on whenever the micro-USB charger is plugged in
#
# (opposite of the above)
xdc.disable_power_on_by_usb_plug_in(dot)

# set the output rate of the DOT
#
# this is the frequency at which the reporting characteristic (i.e. the
# thing that is emitted whenever the DOT reports telemetry) reports
#
# must be 1, 4, 10, 12, 15, 20, 30, 60, 120 (see official XSens spec: Device Control Characteristic)
xdc.set_output_rate(dot, 10)

# reset the output rate to the default rate
xdc.reset_output_rate(dot)


## READING DATA FROM THE DOT ##
#
# Once you enable reporting, the DOT will asynchronously send telemetry data to the computer.
#
# Robust downstream code should assume that notifications sometimes go missing (e.g. due to
# connection issues)

# e.g. #1: create a function that is called whenever the computer receives a device
#          report notification from the DOT
#
#          - after giving this function to `device_report_start_notify`, it will be
#            called by the backend
#
#          - the callee (i.e. this function) should handle the message bytes as
#            appropriate (e.g. by pumping them into a parser)
#
def on_device_report(message_id, message_bytes):
    # parse the message bytes as a characteristic
    parsed = xdc.DeviceReportCharacteristic.from_bytes(message_bytes)
    print(parsed)

# e.g. #2 create a function that is called whenever the computer receives a long
#         payload report from the DOT
#
#         - same as above, but for a different payload message type (see the XSens
#           BLE specification for specifics)
def on_long_payload_report(message_id, message_bytes):
    print(message_bytes)

# e.g. #3 create a function that is called whenever the computer receives a medium
#         payload report from the DOT
#
#         - same as above, but for a different payload message type (see the XSens
#           BLE specification for specifics)
def on_medium_payload_report(message_id, message_bytes):
    print(message_bytes)

# e.g. #4 create a function that is called whenever the computer receives a short
#         payload report from the DOT
#
#         - same as above, but for a different payload message type (see the XSens
#           BLE specification for specifics)
def on_short_payload_report(message_id, message_bytes):
    print(message_bytes)

# e.g. #5 create a function that is called whenever the computer receives a battery
#         report from the DOT
#
#         - same as above, but for a different payload message type (see the XSens
#           BLE specification for specifics)
def on_battery_report(message_id, message_bytes):
    print(message_bytes)

## SYNCHRONOUS API (simpler, but not exactly how the communication actually works)

with xdc.Dot(dot) as device:
    # subscribe to notifications
    device.device_report_start_notify(on_device_report)
    device.long_payload_start_notify(on_long_payload_report)
    device.medium_payload_start_notify(on_medium_payload_report)
    device.short_payload_start_notify(on_short_payload_report)

    # make the calling (synchronous) pump the asynchronous event queue forever
    #
    # this is required, because the main thread is responsible for pumping the
    # message queue that contains the above notifications. If you don't pump
    # the queue then you won't see the notifications
    device.pump_forever()


## ASYNCHRONOUS API (this is actually how communication with the `bleak` backend actually works)

# define an asynchronous function that should be used as the entrypoint for the asynchronous
# event loop (`asyncio.run_until_complete`)
async def arun():
    async with xdc.Dot(dot) as device:
        # asynchronously subscribe to notifications
        await device.adevice_report_start_notify(on_device_report)
        await device.along_payload_start_notify(on_long_payload_report)
        await device.amedium_payload_start_notify(on_medium_payload_report)
        await device.ashort_payload_start_notify(on_short_payload_report)

        # sleep for some amount of time, while pumping the message queue
        #
        # note: this differs from python's `sleep` function, because it doesn't cause the
        #       calling (asynchronous) thread to entirely sleep - it still processes any
        #       notifications that come in, unlike the synchronous API
        await asyncio.sleep(10)

        # (optional): unsubscribe to the notifications
        await device.adevice_report_stop_notify()
        await device.along_payload_stop_notify()
        await device.amedium_payload_stop_notify()
        await device.ashort_payload_stop_notify()

# start running the async task from the calling thread (by making the calling thread fully
# pump the event loop until the task is complete)

import asyncio
loop = asyncio.new_event_loop()
loop.run_until_complete(arun())
```

## General Tips & Tricks

People have emailed me about using this library. To be clear, `xdc` is an **experimental** library. I am far too busy to
productionize it right now (with tests, full documentation etc.). This is why it feels a bit hacky.

Just to answer some previous questions I have received about `xdc`:

- It's a library I tinker with occasionally in my spare time. My primary area of interest is C++; specifically,
  [OpenSim Creator](https://github.com/ComputationalBiomechanicsLab/opensim-creator), which may eventually include
  in-UI XDC support, if I ever get the time.

- The entire implementation of `xdc` is in one file, `xdc.py`. I have tried to make the code simple. You may
  find that you can hack around some of `xdc`'s, uh, "quirks" by reading through the source and changing a line or two

- Synchronous methods use a standard naming convention, e.g. `xdc.identify`. Asynchronous equivalents typically prefix
  an `a` before the method name, e.g. `xdc.aidentify`. In almost all cases, the synchronous API will call into the
  asynchronous API because the underlying BLE library being used (`bleak`) is asynchronous by design (which is a
  reasonable design decision, given how BLE devices typically work).

- Almost all DOT "messages" are named `[Message]Characteristic` in the source code to reflect how they are represented
  by BLE. Most of the characteristics described in the official XSens DOT documentation are represented by an equivalent
  python class (e.g. `xdc.DeviceControlCharacteristic`). Almost all characteristics have `UUID`, `SIZE`, `from_bytes`, and
  `to_bytes` properties/methods. The `xdc` API effectively pumps raw byte-messages into- and out-of these classes

- `xdc` is composed of roughly 4 layers of API:

  - Lowest-level byte parsers and characteristic representations (i.e. any class with `Characteristic` in the name)

  - Low-level asynchronous `Dot` lifetime wrapper. I.e. the thing that lets you write `async with xdc.Dot(dev) as device:`. This is
    effectively what all the higher-level and synchronous APIs defer to eventually

  - Medium-level `Dot` synchronous lifetime wrapper. I.e. the thing that lets you write `with xdc.Dot(dev) as device:`. This is the
    same class as the asynchronous one, but wraps up calling into/out-of the asynchronous event loop. All methods on this class
    ultimately use the asynchronous API of the `Dot` lifetime wrapper

  - High-level asynchronous free-functions (e.g. `xdc.aidentify(device)`, `xdc.ascan()`). These are higher-level free functions that probably use `bleak` and the `Dot` lifetime wrapper internally. These are lower-performance than using the `Dot` lifetime wrapper yourself because they internally need to connect and tear-down a `Dot` wrapper on every call

  - Highest-level synchronous free-functions (e.g. `xdc.idenfity(device)`, `xdc.power_off(device)`). These are high-level free functions that internally use the asynchronous event loop, `bleak`, and the `Dot` lifetime wrapper. These are the lowest-performance API because they need to hop into the asynchronous event loop, create a `Dot` connection, tear it down, and exit the event loop.

- Overall, it's recommended to use the highest-level API to test whether the DOT works etc. (it's the easiest API to use), but you will probably find that your code needs to go deeper and deeper into the lower-levels once you (e.g.) need certain performance guarantees, or need to handle receiving notifications from multiple DOTs concurrently, etc. - there are no silver bullets in unreliable hardware communication protocols
