#!/usr/bin/env python3
"""
Module Docstring
"""

__author__ = "Your Name"
__version__ = "0.1.0"
__license__ = "MIT"

from dataclasses import dataclass, field, InitVar
from enum import Enum
from io import BufferedReader, BytesIO, SEEK_CUR, SEEK_SET
import argparse
import functools
import struct

SND_SOC_FW_MIXER = 1
SND_SOC_FW_DAPM_GRAPH = 2
SND_SOC_FW_DAPM_WIDGET = 3
SND_SOC_FW_DAI_LINK = 4
SND_SOC_FW_COEFF = 5

SND_SOC_FW_VENDOR_FW = 1000
SND_SOC_FW_VENDOR_CONFIG = 1001
SND_SOC_FW_VENDOR_COEFF = 1002
SND_SOC_FW_VENDOR_CODEC = 1003

SND_SOC_FW_NUM_TEXTS = 16
SND_SOC_FW_TEXT_SIZE = 32

class SocType(Enum):
    CONTROL_EXT = 0
    CONTROL_VOLSW = 1
    CONTROL_VOLSW_SX = 2
    CONTROL_VOLSW_S8 = 3
    CONTROL_VOLSW_XR_SX = 4
    CONTROL_ENUM = 6
    CONTROL_ENUM_EXT = 7
    CONTROL_BYTES = 8
    CONTROL_BOOL_EXT = 9
    CONTROL_ENUM_VALUE = 10
    CONTROL_RANGE = 11
    CONTROL_STROBE = 12

    DAPM_VOLSW = 64
    DAPM_ENUM_DOUBLE = 65
    DAPM_ENUM_VIRT = 66
    DAPM_ENUM_VALUE = 67
    DAPM_PIN = 68
    DAPM_ENUM_EXT = 69

def header(fmt):
    def wrapper(cls):
        @functools.wraps(cls)
        def class_wrapper(stream: BufferedReader):
            s = struct.Struct(fmt)
            return cls(*s.unpack_from(stream.read(s.size)))
        return class_wrapper
    return wrapper

@header('<4s5L')
@dataclass
class SndSocFwHeader:
    magic: str
    abi: int
    type: int
    vendor_type: int
    vendor_version: int
    size: int

@header('<2L')
@dataclass
class SndSocFwControlTlv:
    numid: int
    length: int

@header('<32s3L')
@dataclass
class SndSocFwControlHeader:
    name: str
    index: int
    access: int
    tlv_size: int

    id_info: SocType = field(init=False)

    def __post_init__(self):
        self.name = self.name.decode('utf-8').rstrip('\x00')
        self.id_info = SocType(self.index & 0xff)

@header('<8L')
@dataclass
class SndSocFwMixerControl:
    min: int
    max: int
    platform_max: int
    reg: int
    rreg: int
    shift: int
    rshift: int
    invert: int

@header('<7L1024s')
@dataclass
class SndSocFwEnumControl:
    reg: int
    reg2: int
    shift_l: int
    shift_r: int
    max: int
    mask: int
    count: int
    payload: InitVar[str]
    texts: list = field(default_factory=list, init=False)
    values: list = field(default_factory=list, init=False)

    def __post_init__(self, payload):
        stream = BytesIO(payload)
        for i in range(SND_SOC_FW_NUM_TEXTS):
            text = struct.unpack('<32s', stream.read(SND_SOC_FW_TEXT_SIZE))[0]
            self.texts.append(text.decode('utf-8').rstrip('\x00'))
        self.values = struct.unpack('<128L', stream.read(SND_SOC_FW_NUM_TEXTS*SND_SOC_FW_TEXT_SIZE))

@header('<L')
@dataclass
class SndSocFwKControl:
    count: int

@header('<32s32s32s')
@dataclass
class SndSocFwDapmGraphElem:
    sink: str
    control: str
    source: str

    def __post_init__(self):
        self.sink = self.sink.decode('utf-8').rstrip('\x00')
        self.control = self.control.decode('utf-8').rstrip('\x00')
        self.source = self.source.decode('utf-8').rstrip('\x00')

@header('<L32s32slLL??2xL')
@dataclass
class SndSocFwDapmWidget:
    id: int
    name: str
    sname: str
    reg: int
    shift: int
    mask: int
    invert: bool
    ignore_suspend: bool
    kcontrol_count: int

    def __post_init__(self):
        self.name = self.name.decode('utf-8').rstrip('\x00')
        self.sname = self.sname.decode('utf-8').rstrip('\x00')

SndSocFwDapmElems = SndSocFwKControl

@header('<3L')
@dataclass
class SndSocFileCoeffData:
    count: int
    size: int
    id: int

@header('<5L')
@dataclass
class AbeFirmwareHeader:
    version: int
    pmem_size: int
    cmem_size: int
    dmem_size: int
    smem_size: int

def main(args):
    """ Main entry point of the app """
    fw = args.fw_file
    while fw.peek(1):
        hdr = SndSocFwHeader(fw)
        print(f'ASoC: Got 0x{hdr.size:x} bytes of type {hdr.type} version {hdr.abi} vendor {hdr.vendor_type} at pass X')
        next_offset = fw.tell() + hdr.size
        if hdr.type == SND_SOC_FW_MIXER:
            sfwk = SndSocFwKControl(fw)
            print(f'ASoC: adding {sfwk.count} kcontrols')
            for index in range(sfwk.count):
                control_hdr = SndSocFwControlHeader(fw)
                if control_hdr.id_info in [
                        SocType.CONTROL_VOLSW,
                        SocType.CONTROL_STROBE,
                        SocType.CONTROL_VOLSW_SX,
                        SocType.CONTROL_VOLSW_S8,
                        SocType.CONTROL_VOLSW_XR_SX,
                        SocType.CONTROL_BYTES,
                        SocType.CONTROL_BOOL_EXT,
                        SocType.CONTROL_RANGE,
                        SocType.DAPM_VOLSW,
                        SocType.DAPM_PIN ]:
                    mc = SndSocFwMixerControl(fw)
                    print(f'ASoC: adding mixer kcontrol {control_hdr.name} with access 0x{control_hdr.access}')
                    if control_hdr.tlv_size != 0:
                        tlv = SndSocFwControlTlv(fw)
                        fw.seek(tlv.length, SEEK_CUR)
                        print(f' created TLV type {tlv.numid} size {tlv.length} bytes')
                elif control_hdr.id_info in [
                        SocType.CONTROL_ENUM,
                        SocType.CONTROL_ENUM_EXT,
                        SocType.CONTROL_ENUM_VALUE,
                        SocType.DAPM_ENUM_DOUBLE,
                        SocType.DAPM_ENUM_VIRT,
                        SocType.DAPM_ENUM_VALUE,
                        SocType.DAPM_ENUM_EXT ]:
                    ec = SndSocFwEnumControl(fw)
                    print(f'ASoC: adding enum kcontrol {control_hdr.name} size {ec.max}')
                else:
                    print(f'ASoC: invalid control type')
        elif hdr.type == SND_SOC_FW_DAPM_GRAPH:
            elem_info = SndSocFwDapmElems(fw)
            print(f'ASoC: adding {elem_info.count} DAPM routes')
            for index in range(elem_info.count):
                elem = SndSocFwDapmGraphElem(fw)
        elif hdr.type == SND_SOC_FW_DAPM_WIDGET:
            elem_info = SndSocFwDapmElems(fw)
            print(f'ASoC: adding {elem_info.count} DAPM widgets')
            for index in range(elem_info.count):
                widget = SndSocFwDapmWidget(fw)
                print(f'ASoC: creating DAPM widget {widget.name} id {widget.id}')
                if widget.kcontrol_count != 0:
                    control_hdr = SndSocFwControlHeader(fw)
                    print(f'ASoC: widget {widget.name} has {widget.kcontrol_count} controls of type {control_hdr.index:x}')
                    if control_hdr.id_info in [
                            SocType.CONTROL_VOLSW,
                            SocType.CONTROL_STROBE,
                            SocType.CONTROL_VOLSW_SX,
                            SocType.CONTROL_VOLSW_S8,
                            SocType.CONTROL_VOLSW_XR_SX,
                            SocType.CONTROL_BYTES,
                            SocType.CONTROL_BOOL_EXT,
                            SocType.CONTROL_RANGE,
                            SocType.DAPM_VOLSW ]:
                        for mixer in range(widget.kcontrol_count):
                            # already read control_hdr for first entry
                            if mixer != 0:
                                control_hdr = SndSocFwControlHeader(fw)
                            mc = SndSocFwMixerControl(fw)
                            print(f' adding DAPM widget mixer control {control_hdr.name} at {mixer}')
                    elif control_hdr.id_info in [
                            SocType.CONTROL_ENUM,
                            SocType.CONTROL_ENUM_EXT,
                            SocType.CONTROL_ENUM_VALUE,
                            SocType.DAPM_ENUM_DOUBLE,
                            SocType.DAPM_ENUM_VIRT,
                            SocType.DAPM_ENUM_VALUE,
                            SocType.DAPM_ENUM_EXT ]:
                        ec = SndSocFwEnumControl(fw)
                        print(f' adding DAPM widget enum control {control_hdr.name}')
                    else:
                        print(f'ASoC: invalid widget control type')
        elif hdr.type == SND_SOC_FW_DAI_LINK:
            print('ASoC: Firmware DAIs not supported')
        elif hdr.type == SND_SOC_FW_COEFF:
            if hdr.vendor_type == 0:
                sfwk = SndSocFwKControl(fw)
                print(f'ASoC: got {sfwk.count} new coefficients')
                control_hdr = SndSocFwControlHeader(fw)
                if control_hdr.id_info in [
                        SocType.CONTROL_ENUM,
                        SocType.CONTROL_ENUM_EXT,
                        SocType.CONTROL_ENUM_VALUE]:
                    ec = SndSocFwEnumControl(fw)
                    print(f'ASoC: adding enum kcontrol {control_hdr.name} size {ec.max}')
                else:
                    print(f'ASoC: invalid coeff control type {control_hdr.id_info.name} count {sfwk.count}')
                hdr = SndSocFwHeader(fw)
                next_offset = fw.tell() + hdr.size
                cd = SndSocFileCoeffData(fw)
                print(f'coeff {cd.id} size 0x{cd.size:x} with {cd.count} elems')
                fw.seek(cd.size, SEEK_CUR)
        elif hdr.type == SND_SOC_FW_VENDOR_FW:
            abe = AbeFirmwareHeader(fw)
            print(f'ABE firmware size {hdr.size} bytes')
            print(f'ABE mem P {abe.pmem_size} C {abe.cmem_size} D {abe.dmem_size} S {abe.smem_size} bytes')
            print(f'ABE Firmware version {abe.version:x}')
            fw.seek(abe.pmem_size, SEEK_CUR)
            fw.seek(abe.cmem_size, SEEK_CUR)
            fw.seek(abe.dmem_size, SEEK_CUR)
            fw.seek(abe.smem_size, SEEK_CUR)
        elif hdr.type == SND_SOC_FW_VENDOR_CONFIG:
            print(f'ABE Config size {hdr.size} bytes')
            fw.seek(hdr.size, SEEK_CUR)
        else:
            print(f'vendor type {hdr.type}:{hdr.vendor_type} not supported')
        assert fw.tell() == next_offset

if __name__ == "__main__":
    """ This is executed when run from the command line """
    parser = argparse.ArgumentParser()

    # Required positional argument
    parser.add_argument("fw_file", help="ABE firmware", type=argparse.FileType('rb'))

    # Optional verbosity counter (eg. -v, -vv, -vvv, etc.)
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Verbosity (-v, -vv, etc)")

    # Specify output of "--version"
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s (version {version})".format(version=__version__))

    args = parser.parse_args()
    main(args)
