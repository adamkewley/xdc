import struct  # for unpacking floating-point data
import asyncio  # for async BLE IO
from bleak import BleakScanner, BleakClient  # for BLE communication

# make an XSENS UUID from an (assumed to be 4 nibbles) number
#
# from BLE spec, sec 1.1: "Base UUID"
#
# e.g. 0x1000 --> 15171000-4947-11E9-8646-D663BD873D93
def xuuid(hexnum):
    XSENS_BASE_UUID = "1517xxxx-4947-11E9-8646-D663BD873D93"
    s = hex(hexnum)[2:]
    assert len(s) == 4
    return XSENS_BASE_UUID.replace("xxxx", s)

# the XSens DOT provides BLE services with the following prefixes on the
# UUID:
#
# 0x1000 (e.g. 15171000-4947-...): configuration service
# 0x2000                         : measurement service
# 0x3000                         : charging status/battery level service
# 0x7000                         : message service

# helper class for reading + parsing bytes according to XSens's
# specification (little endian, IEE754, etc.)
class ResponseReader:

    # parse arbitrary byte sequence as little-endian integer
    def b2i(b, signed=False):
        return int.from_bytes(b, "little", signed=False)

    def __init__(self, data):
        self.pos = 0
        self.data = data

    # returns number of remaining bytes
    def rem(self):
        return len(self.data) - self.pos

    # extract n raw bytes
    def raw(self, n):
        rv = self.data[self.pos:self.pos+n]
        self.pos += n
        return rv

    # read 1 byte as int
    def u8(self):
        return ResponseReader.b2i(self.raw(1))

    # read 2 bytes as int
    def u16(self):
        return ResponseReader.b2i(self.raw(2))

    # read 4 bytes as int
    def u32(self):
        return ResponseReader.b2i(self.raw(4))

    # read 8 bytes as int
    def u64(self):
        return ResponseReader.b2i(self.raw(8))

    # read 4 bytes as a IEE754 float
    def f32(self):
        return struct.unpack('f', self.raw(4))

# helper that pretty-prints an arbitrary class
#
# handy for printing the characteristic data types, etc.
def pretty_print(obj):
    return f"{obj.__class__.__name__}({', '.join('%s=%s' % item for item in vars(obj).items())})"

# Device Info Characteristic (sec 2.1, p8)
class DeviceInfoCharacteristic:

    # UUID string
    UUID = xuuid(0x1001)

    # read charactertistic data from a byte reader
    def read(r):
        assert r.rem() >= 34

        rv = DeviceInfoCharacteristic()
        rv.bt_identity_addr = r.raw(6)
        rv.version_major = r.u8()
        rv.version_minor = r.u8()
        rv.version_revision = r.u8()
        rv.build_year = r.u16()
        rv.build_month = r.u8()
        rv.build_date = r.u8()
        rv.build_hour = r.u8()
        rv.build_minute = r.u8()
        rv.build_second = r.u8()
        rv.softdevice_version = r.u32()
        rv.serial_number = r.u64()
        rv.short_product_code = r.raw(6)

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceInfoCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Device Control Characteristic (sec 2.2, p9)
class DeviceControlCharacteristic:

    # UUID string
    UUID = xuuid(0x1002)

    # read characteristic data from a byte reader
    def read(r):
        assert r.rem() >= 16

        rv = DeviceControlCharacteristic()
        rv.visit_index = r.u8()
        rv.identifying = r.u8()
        rv.poweroff = r.u8()
        rv.timeoutx_min = r.u8()
        rv.timeoutx_sec = r.u8()
        rv.timeouty_min = r.u8()
        rv.timeouty_sec = r.u8()
        rv.device_tag_len = r.u8()
        rv.device_tag = r.raw(16)
        rv.output_rate = r.u16()
        rv.filter_profile_idx = r.u8()
        rv.reserved = r.raw(5)  # just in case someone's interested

        return rv

    # parse bytes as characteristic data
    def parse(b):
        r = ResponseReader(b)
        return DeviceControlCharacteristic.read(r)

    # write characteristic as bytes
    def to_bytes(self):
        rv = bytearray()
        rv.extend(self.visit_index.to_bytes(1, "little"))
        rv.extend(self.identifying.to_bytes(1, "little"))
        rv.extend(self.poweroff.to_bytes(1, "little"))
        rv.extend(self.timeoutx_min.to_bytes(1, "little"))
        rv.extend(self.timeoutx_sec.to_bytes(1, "little"))
        rv.extend(self.timeouty_min.to_bytes(1, "little"))
        rv.extend(self.timeouty_sec.to_bytes(1, "little"))
        rv.extend(self.device_tag_len.to_bytes(1, "little"))
        rv.extend(self.device_tag)
        rv.extend(self.output_rate.to_bytes(2, "little"))
        rv.extend(self.filter_profile_idx.to_bytes(1, "little"))
        rv.extend(self.reserved)
        return rv

    def __repr__(self):
        return pretty_print(self)

# Device Report Characteristic (sec 2.3, p 10)
#
# these are emitted as notifications from the DOT to the host whenever a
# significant event (e.g. button press) happens
class DeviceReportCharacteristic:

    UUID = xuuid(0x1004)

    def read(r):
        assert r.rem() == 36

        rv = DeviceReportCharacteristic()
        rv.typeid = r.u8()
        if rv.typeid == 5:
            rv.length = r.u8()
            if rv.length == 4:
                rv.timestamp = r.u32()
            elif rv.length == 8:
                rv.timestamp = r.u64()
        rv.unused = r.raw(r.rem())

        return rv

    def parse(b):
        r = ResponseReader(b)
        return DeviceReportCharacteristic.read(r)

    def __repr__(self):
        return pretty_print(self)

# Measurement Service: Control (sec 3.1, p12)
class ControlCharacteristic:

    # UUID string
    UUID = xuuid(0x2001)

    # convert payload mode (an int) into human-readable representation
    def payload_mode_str(i):
        lut = {
            1: "High Fidelity (with mag)",
            2: "Extended (Quaterion)",
            3: "Complete (Quaterion)",
            4: "Orientation (Euler)",
            5: "Orientation (Quaterion)",
            6: "Free Acceleration",
            7: "Extended (Euler)",
            16: "Complete (Euler)",
            17: "High Fidelity",
            18: "Delta quantities (with mag)",
            19: "Delta quantities",
            20: "Rate quantities (with mag)",
            21: "Rate quantities",
            22: "Custom mode 1",
            23: "Custom mode 2",
            24: "Custom mode 3",
        }
        return lut[i]

    # read characteristic data from byte reader
    def read(r):
        assert r.rem() >= 3

        rv = ControlCharacteristic()
        rv.Type = r.u8()
        rv.action = r.u8()
        rv.payload_mode = r.u8()

        return rv

    def parse(b):
        r = ResponseReader(b)
        return ControlCharacteristic.read(r)

    # convert characteristic data back to bytes
    def to_bytes(self):
        assert self.Type < 0xff
        assert self.action <= 1
        assert self.payload_mode <= 24

        b = bytes()
        b += bytes([self.Type])
        b += bytes([self.action])
        b += bytes([self.payload_mode])

        return b

    def __repr__(self):
        return pretty_print(self)

o.i# timestamp data, usually appears in a measurement responses
class TimestampData:

    nbytes = 4

    def read(r):
        assert r.rem() >= TimestampData.nbytes

        rv = TimestampData()
        rv.value = r.u32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# Euler angle data, usually appears in measurement responses
class EulerAngleData:

    nbytes = 12

    def read(r):
        assert r.rem() >= EulerAngleData.nbytes

        rv = EulerAngleData()
        rv.x = r.f32()
        rv.y = r.f32()

        # seems to point orthogonally to earth's surface
        rv.z = r.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# free acceleration data, usually appears in measurement responses
class FreeAccelerationData:

    nbytes = 12

    def read(r):
        assert r.rem() >= FreeAccelerationData.nbytes

        rv = FreeAccelerationData()
        rv.x = r.f32()
        rv.y = r.f32()
        rv.z = r.f32()

        return rv

    def __repr__(self):
        return pretty_print(self)

# data related to medium payloads
#
# there isn't one "universal" medium payload we can parse. The sensor
# uses the medium payload notification to send a variety of types that
# are all <= 40 bytes (see spec)
class MediumPayload:
    UUID = xuuid(0x2003)

# Measurement Service: Measurement Data: Medium Payload: 'Complete (Euler)'
#
# a concrete instance of a medium payload. You need to check whether the
# device is set to emit these by checking the ControlCharacteristic (above)
class MediumPayloadCompleteEuler:

    def parse(b):
        assert len(b) >= 28, f"len is {len(b)}"
        r = ResponseReader(b)

        rv = MediumPayloadCompleteEuler()
        rv.timestamp = TimestampData.read(r)
        rv.euler = EulerAngleData.read(r)
        rv.free_accel = FreeAccelerationData.read(r)

        return rv

    def __repr__(self):
        return pretty_print(self)

# lifetime wrapper around a BLE device that is specialized for
# the DOT
#
# this is what resource- and timing-sensitive code should use, because
# it minimizes the number of (re)connections to the device. Procedural
# (esp. synchronous) code using the helper methods (below) will run slower
# because the API has to handle setting up and tearing down a new connection
class Dot:

    # init/enter/exit: connect/disconnect to the DOT

    def __init__(self, ble_device):
        self.dev = ble_device
        self.client = BleakClient(self.dev.address)

    async def __aenter__(self):
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, value, traceback):
        await self.client.__aexit__(exc_type, value, traceback)

    def __enter__(self):
        asyncio.get_event_loop().run_until_complete(self.__aenter__())
        return self

    def __exit__(self, exc_type, value, traceback):
        asyncio.get_event_loop().run_until_complete(self.__aexit__(exc_type, value, traceback))

    # manual connection management (handy for manual use in a terminal or something)

    async def aconnect(self):
        return await self.client.connect()

    def connect(self):
        return asyncio.get_event_loop().run_until_complete(self.aconnect())

    async def adisconnect(self):
        return await self.client.disconnect()

    def disconnect(self):
        return asyncio.get_event_loop().run_until_complete(self.adisconnect())

    # low-level characteristic accessors

    async def adevice_info_read(self):
        resp = await self.client.read_gatt_char(DeviceInfoCharacteristic.UUID)
        return DeviceInfoCharacteristic.parse(resp)

    def device_info_read(self):
        return asyncio.get_event_loop().run_until_complete(self.adevice_info_read())

    async def adevice_control_read(self):
        resp = await self.client.read_gatt_char(DeviceControlCharacteristic.UUID)
        return DeviceControlCharacteristic.parse(resp)

    def device_control_read(self):
        return asyncio.get_event_loop().run_until_complete(self.adevice_control_read())

    async def adevice_control_write(self, device_control_characteristic):
        msg_bytes = device_control_characteristic.to_bytes()
        await self.client.write_gatt_char(DeviceControlCharacteristic.UUID, msg_bytes, True)

    def device_control_write(self, device_control_characteristic):
        asyncio.get_event_loop().run_until_complete(self.adevice_control_write(device_control_characteristic))

    async def adevice_report_start_notify(self, callback):
        await self.client.start_notify(DeviceReportCharacteristic.UUID, callback)

    def device_report_start_notify(self, callback):
        asyncio.get_event_loop().run_until_complete(self.adevice_report_start_notify(callback))

    async def adevice_report_stop_notify(self):
        await self.client.stop_notify(DeviceReportCharacteristic.UUID)

    def device_report_stop_notify(self):
        asyncio.get_event_loop().run_until_complete(self.adevice_report_stop_notify())

    async def acontrol_read(self):
        resp = await self.client.read_gatt_char(ControlCharacteristic.UUID)
        return ControlCharacteristic.parse(resp)

    def control_read(self):
        return asyncio.get_event_loop().run_until_complete(self.acontrol_read())
    

    # high-level operations

    async def aidentify(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x01
        dc.identifying = 0x01
        await self.adevice_control_write(dc)

    def identify(self):
        asyncio.get_event_loop().run_until_complete(self.aidentify())

    async def apower_off(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff | 0x01
        await self.adevice_control_write(dc)

    def power_off(self):
        asyncio.get_event_loop().run_until_complete(self.apower_off())

    async def aenable_power_on_by_usb_plug_in(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff | 0x02
        await self.adevice_control_write(dc)

    def enable_power_on_by_usb_plug_in(self):
        asyncio.get_event_loop().run_until_complete(self.aenable_power_on_by_usb_plug_in())

    async def adisable_power_on_by_usb_plug_in(self):
        dc = await self.adevice_control_read()
        dc.visit_index = 0x02
        dc.poweroff = dc.poweroff & ~(0x02)
        await self.adevice_control_write(dc)

    def disable_power_on_by_usb_plug_in(self):
        asyncio.get_event_loop().run_until_complete(self.adisable_power_on_by_usb_plug_in())

    async def aset_output_rate(self, rate):
        assert rate in {1, 4, 10, 12, 15, 20, 30, 60, 120}

        dc = await self.adevice_control_read()
        dc.visit_index = 0x10
        dc.output_rate = rate
        await self.adevice_control_write(dc)

    def set_output_rate(self, rate):
        asyncio.get_event_loop().run_until_complete(self.aset_output_rate(rate))

    async def areset_output_rate(self):
        await self.aset_output_rate(60)  # default, according to BLE spec

    def reset_output_rate(self):
        asyncio.get_event_loop().run_until_complete(self.areset_output_rate())

    # sets the "Filter Profile Index" field in the Device Control Characteristic
    #
    # this sets how the DOT filters measurements?
    async def aset_filter_profile_index(self, idx):
        assert idx in {0, 1}

        dc = await self.adevice_control_read()
        dc.visit_index = 0x20
        dc.filter_profile_index = idx
        await self.adevice_control_write(dc)

    def set_filter_profile_index(self, idx):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_index(idx))

    async def aset_filter_profile_to_general(self):
        await self.aset_filter_profile_index(0)

    def set_filter_profile_to_general(self):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_to_general())

    async def aset_filter_profile_to_dynamic(self):
        await self.aset_filter_profile_index(1)

    def set_filter_profile_to_dynamic(self):
        asyncio.get_event_loop().run_until_complete(self.aset_filter_profile_to_dynamic())

    async def enable_measurement_action(self):
        # read current control settings
        resp = await self.client.read_gatt_char(ControlCharacteristic.UUID)
        parsed = ControlCharacteristic.parse(resp)

        # set current control setting to "on"
        parsed.action = 1

        # re-write the control settings to bytes
        msg = parsed.to_bytes()

        # send the (now enabled) control back to the device
        await self.client.write_gatt_char(ControlCharacteristic.UUID, msg)

    # `f` should be a `callable` that receives sender (ID) + data
    # (bytes) as args
    async def start_notify_medium_payload(self, f):
        await self.client.start_notify(MediumPayload.UUID, f)

# a python `Callable` that is called whenever a notification is
# received by the bluetooth backend
class ResponseHandler:
    def __init__(self):
        self.i = 0

    def __call__(self, sender, data):
        self.i += 1

        parsed = MediumPayloadCompleteEuler.parse(data)
        print(f"i={self.i} t={parsed.timestamp.value} x={parsed.euler.x}, y={parsed.euler.y}, z={parsed.euler.z}")

# asynchronously returns `True` if the provided `bleak.backends.device.BLEDevice`
# is believed to be an XSens DOT sensor
async def ais_DOT(bledevice):
    if bledevice.name and "xsens dot" in bledevice.name:
        # spec: 1.2: Scanning and Filtering: tag name is "Xsens DOT"
        #
        # other devices in the wild *may* have a name collision with this, but it's
        # unlikely
        return True
    elif bledevice.metadata.get("manufacturer_data") and bledevice.metadata["manufacturer_data"].get(2182):
        # spec: 1.2: Scanning and Filtering: Bluetooth SIG identifier for XSens Technologies B.V. is 2182 (0x0886)
        #
        # this ambiguously identifies an XSens DOT. XSens might recycle its bluetooth
        # ID for other products, though, so we need to check that the device actually
        # responds to a DOT-like packet
        try:
            async with Dot(bledevice) as dot:
                await dot.adevice_info_read()  # typical request
                return True
        except asyncio.exceptions.TimeoutError as ex:
            return False

# synchronously returns `True` if the provided `bleak.backends.device.BLEDevice` is an
# XSens DOT
def is_DOT(bledevice):
    return asyncio.get_event_loop().run_until_complete(ais_DOT(bledevice))

# asynchronously returns a list of all (not just DOT) BLE devices that
# the host's bluetooth adaptor can see. Each element in the list is an
# instance of `bleak.backends.device.BLEDevice`
async def ascan_all():
    async with BleakScanner() as scanner:
        return list(await scanner.discover())

# synchronously returns a list of all (not just DOT) BLE devices that the
# host's bluetooth adaptor can see. Each element in the list is an instance
# of `bleak.backends.device.BLEDevice`
def scan_all():
    return asyncio.get_event_loop().run_until_complete(ascan_all_raw())

# asynchronously returns a list of all XSens DOTs that the host's bluetooth
# adaptor can see. Each element in the list is an instance of
# `bleak.backends.device.BLEDevice`
async def ascan():
    return [d for d in await ascan_all() if await ais_DOT(d)]

# synchronously returns a list of all XSens DOTs that the host's bluetooth
# adaptor can see. Each element in the list is an instance of
# `bleak.backends.device.BLEDevice`
def scan():
    return asyncio.get_event_loop().run_until_complete(ascan())

# asynchronously returns a BLE device with the given identifier/address
#
# returns `None` if the device cannot be found (e.g. no connection, wrong
# address)
async def afind_by_address(device_identifier):
    async with BleakScanner() as scanner:
        return await scanner.find_device_by_address(device_identifier)

# synchronously returns a BLE device with the given identifier/address
#
# returns `None` if the device cannot be found (e.g. no connection, wrong
# address)
def find_by_address(device_identifier):
    return asyncio.get_event_loop().run_until_complete(afind_by_address(device_identifier))

# asynchronously returns a BLE device with the given identifier/address if the
# device appears to be an XSens DOT
#
# effectively, the same as `afind_by_address` but with the extra stipulation that
# the given device must be a DOT
async def afind_dot_by_address(device_identifier):
    dev = await afind_by_address(device_identifier)

    if dev is None:
        return None  # device cannot be found
    elif not await ais_DOT(dev):
        return None  # device exists but is not a DOT
    else:
        return dev

# synchronously returns a BLE device with the given identifier/address, if the device
# appears to be an XSens DOT
#
# effectively, the same as `find_by_address`, but with the extra stipulation that
# the given device must be a DOT
def find_dot_by_address(device_identifier):
    return asyncio.get_event_loop().run_until_complete(afind_dot_by_address(device_identifier))


# low-level characteristic accessors (free functions)


# asynchronously returns the "Device Info Characteristic" for the given DOT device
#
# see: sec 2.1 Device Info Characteristic in DOT BLE spec
async def adevice_info_read(bledevice):
    async with Dot(bledevice) as dot:
        return await dot.adevice_info_read()

# synchronously returns the "Device Info Characteristic" for the given DOT device
#
# see: sec 2.1: Device Info Characteristic in DOT BLE spec
def device_info_read(bledevice):
    return asyncio.get_event_loop().run_until_complete(adevice_info_read(bledevice))

# asynchronously returns the "Device Control Characteristic" for the given DOT device
#
# see: sec 2.2: Device Control Characteristic in DOT BLE spec
async def adevice_control_read(bledevice):
    async with Dot(bledevice) as dot:
        return await dot.adevice_control_read()

# synchronously returns the "Device Control Characteristic" for the given DOT device
#
# see: sec 2.2: Device Control Characteristic in DOT BLE spec
def device_control_read(bledevice):
    return asyncio.get_event_loop().run_until_complete(adevice_control_read(bledevice))

# asynchronously write the provided DeviceControlCharacteristic to the provided
# DOT device
async def adevice_control_write(bledevice, device_control_characteristic):
    async with Dot(bledevice) as dot:
        await dot.adevice_control_write(device_control_characteristic)

def device_control_write(bledevice, device_control_characteristic):
    asyncio.get_event_loop().run_until_complete(adevice_control_write(bledevice, device_control_characteristic))

# high-level operations (free functions)

async def aidentify(bledevice):
    async with Dot(bledevice) as dot:
        await dot.aidentify()

def identify(bledevice):
    asyncio.get_event_loop().run_until_complete(aidentify(bledevice))

async def apower_off(bledevice):
    async with Dot(bledevice) as dot:
        await dot.apower_off()

def power_off(bledevice):
    asyncio.get_event_loop().run_until_complete(apower_off(bledevice))

async def aenable_power_on_by_usb_plug_in(bledevice):
    async with Dot(bledevice) as dot:
        await dot.aenable_power_on_by_usb_plug_in()

def enable_power_on_by_usb_plug_in(bledevice):
    asyncio.get_event_loop().run_until_complete(aenable_power_on_by_usb_plug_in(bledevice))

async def adisable_power_on_by_usb_plug_in(bledevice):
    async with Dot(bledevice) as dot:
        await dot.adisable_power_on_by_usb_plug_in()

def disable_power_on_by_usb_plug_in(bledevice):
    asyncio.get_event_loop().run_until_complete(adisable_power_on_by_usb_plug_in(bledevice))

async def aset_output_rate(bledevice, rate):
    async with Dot(bledevice) as dot:
        await dot.aset_output_rate(rate)

def set_output_rate(bledevice, rate):
    asyncio.get_event_loop().run_until_complete(aset_output_rate(bledevice, rate))

async def areset_output_rate(bledevice):
    async with Dot(bledevice) as dot:
        await dot.areset_output_rate()

def reset_output_rate(bledevice):
    asyncio.get_event_loop().run_until_complete(areset_output_rate(bledevice))

async def aset_filter_profile_index(bledevice, idx):
    async with Dot(bledevice) as dot:
        await dot.aset_filter_profile_index(idx)

def set_filter_profile_index(bledevice, idx):
    asyncio.get_event_loop().run_until_complete(aset_filter_profile_index(bledevice, idx))
