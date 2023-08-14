#!/usr/bin/env python3
"""
Module Docstring
"""

__author__ = "Patrik Dahlström"
__version__ = "0.1.0"
__license__ = "MIT"

from base64 import b64encode
from dataclasses import asdict, dataclass, field, InitVar, make_dataclass
from enum import IntEnum
from io import BufferedReader, BytesIO, SEEK_CUR, SEEK_SET
import argparse
import functools
import json
import logging
import struct

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('main')

class FwType(IntEnum):
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

class SocType(IntEnum):
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
            class_name = cls.__name__
            Class = make_dataclass(class_name, fields=[('c_header', str)], bases=(cls,))
            s = struct.Struct(fmt)
            return Class(c_header=class_name, *s.unpack_from(stream.read(s.size)))
        return class_wrapper
    return wrapper

def abi_version(fw):
    (magic, abi) = struct.unpack_from('<4sL', fw.peek(8))
    return abi

@header('<4s5L')
@dataclass
class SndSocFwHeader:
    magic: str
    abi: int
    type: FwType
    vendor_type: int
    vendor_version: int
    size: int

    def __post_init__(self):
        self.magic = self.magic.decode('utf-8')
        self.type = FwType(self.type)

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
    values: dict = field(default_factory=dict, init=False)

    def __post_init__(self, payload):
        stream = BytesIO(payload)
        texts = []
        for i in range(SND_SOC_FW_NUM_TEXTS):
            text = struct.unpack('<32s', stream.read(SND_SOC_FW_TEXT_SIZE))[0]
            texts.append(text.decode('utf-8').rstrip('\x00'))
        values = struct.unpack('<128L', stream.read(SND_SOC_FW_NUM_TEXTS*SND_SOC_FW_TEXT_SIZE))
        for i in range(SND_SOC_FW_NUM_TEXTS):
            text = texts[i]
            if text:
                self.values[text] = values[i]

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
        self.control = self.control.decode('utf-8').rstrip('\x00') or None
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
    if args.verbose >= 1:
        log.setLevel(logging.DEBUG)
    fw = args.fw_file
    fw_list = []
    while fw.peek(1):
        abi = abi_version(fw)
        if abi == 1:
            hdr = SndSocFwHeader(fw)
        else:
            log.error(f'Unsupported ABI version: {abi}')

        fw_list.append({
            'type': hdr.type,
            'type_string': hdr.type.name,
            'vendor_type': hdr.vendor_type,
            'vendor_version': hdr.vendor_version,
            'size': hdr.size,
        })

        log.debug(f'ASoC: Got 0x{hdr.size:x} bytes of type {hdr.type} version {hdr.abi} vendor {hdr.vendor_type} at pass X')
        next_offset = fw.tell() + hdr.size
        if hdr.type == FwType.SND_SOC_FW_MIXER:
            sfwk = SndSocFwKControl(fw)
            log.debug(f'ASoC: adding {sfwk.count} kcontrols')
            fw_list[-1]['mixer'] = asdict(sfwk)
            kcontrols = []
            for index in range(sfwk.count):
                control_hdr = SndSocFwControlHeader(fw)
                kcontrols.append(asdict(control_hdr))
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
                    kcontrols[-1]['mixer'] = asdict(mc)
                    log.debug(f'ASoC: adding mixer kcontrol {control_hdr.name} with access 0x{control_hdr.access}')
                    if control_hdr.tlv_size != 0:
                        tlv = SndSocFwControlTlv(fw)
                        value = fw.read(tlv.length)
                        kcontrols[-1]['mixer']['tlv'] = asdict(tlv)
                        kcontrols[-1]['mixer']['tlv']['value'] = b64encode(value).decode()
                        log.debug(f' created TLV type {tlv.numid} size {tlv.length} bytes')
                elif control_hdr.id_info in [
                        SocType.CONTROL_ENUM,
                        SocType.CONTROL_ENUM_EXT,
                        SocType.CONTROL_ENUM_VALUE,
                        SocType.DAPM_ENUM_DOUBLE,
                        SocType.DAPM_ENUM_VIRT,
                        SocType.DAPM_ENUM_VALUE,
                        SocType.DAPM_ENUM_EXT ]:
                    ec = SndSocFwEnumControl(fw)
                    kcontrols[-1]['enum'] = asdict(ec)
                    log.debug(f'ASoC: adding enum kcontrol {control_hdr.name} size {ec.max}')
                else:
                    log.warning(f'ASoC: invalid control type')
            fw_list[-1]['mixer']['controls'] = kcontrols
        elif hdr.type == FwType.SND_SOC_FW_DAPM_GRAPH:
            elem_info = SndSocFwDapmElems(fw)
            fw_list[-1]['dapm_graph'] = asdict(elem_info)
            log.debug(f'ASoC: adding {elem_info.count} DAPM routes')
            routes = []
            for index in range(elem_info.count):
                elem = SndSocFwDapmGraphElem(fw)
                routes.append(asdict(elem))
            fw_list[-1]['dapm_graph']['routes'] = routes
        elif hdr.type == FwType.SND_SOC_FW_DAPM_WIDGET:
            elem_info = SndSocFwDapmElems(fw)
            fw_list[-1]['dapm_widget'] = asdict(elem_info)
            log.debug(f'ASoC: adding {elem_info.count} DAPM widgets')
            widgets = []
            for index in range(elem_info.count):
                widget = SndSocFwDapmWidget(fw)
                log.debug(f'ASoC: creating DAPM widget {widget.name} id {widget.id}')
                widgets.append(asdict(widget))
                kcontrols = []
                if widget.kcontrol_count != 0:
                    control_hdr = SndSocFwControlHeader(fw)
                    kcontrols.append(asdict(control_hdr))
                    log.debug(f'ASoC: widget {widget.name} has {widget.kcontrol_count} controls of type {control_hdr.index:x}')
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
                                kcontrols.append(asdict(control_hdr))
                            mc = SndSocFwMixerControl(fw)
                            kcontrols[-1]['mixer'] = asdict(mc)
                            log.debug(f' adding DAPM widget mixer control {control_hdr.name} at {mixer}')
                    elif control_hdr.id_info in [
                            SocType.CONTROL_ENUM,
                            SocType.CONTROL_ENUM_EXT,
                            SocType.CONTROL_ENUM_VALUE,
                            SocType.DAPM_ENUM_DOUBLE,
                            SocType.DAPM_ENUM_VIRT,
                            SocType.DAPM_ENUM_VALUE,
                            SocType.DAPM_ENUM_EXT ]:
                        ec = SndSocFwEnumControl(fw)
                        kcontrols[-1]['enum'] = asdict(ec)
                        log.debug(f' adding DAPM widget enum control {control_hdr.name}')
                    else:
                        log.warning(f'ASoC: invalid widget control type')
                widgets[-1]['controls'] = kcontrols
            fw_list[-1]['dapm_widget']['widgets'] = widgets
        elif hdr.type == FwType.SND_SOC_FW_DAI_LINK:
            log.warning('ASoC: Firmware DAIs not supported')
        elif hdr.type == FwType.SND_SOC_FW_COEFF:
            if hdr.vendor_type == 0:
                sfwk = SndSocFwKControl(fw)
                fw_list[-1]['coefficients'] = asdict(sfwk)
                log.debug(f'ASoC: got {sfwk.count} new coefficients')
                control_hdr = SndSocFwControlHeader(fw)
                if control_hdr.id_info in [
                        SocType.CONTROL_ENUM,
                        SocType.CONTROL_ENUM_EXT,
                        SocType.CONTROL_ENUM_VALUE]:
                    ec = SndSocFwEnumControl(fw)
                    fw_list[-1]['coefficients']['enum'] = asdict(ec)
                    log.debug(f'ASoC: adding enum kcontrol {control_hdr.name} size {ec.max}')
                else:
                    log.debug(f'ASoC: invalid coeff control type {control_hdr.id_info.name} count {sfwk.count}')
                hdr = SndSocFwHeader(fw)
                next_offset = fw.tell() + hdr.size
                cd = SndSocFileCoeffData(fw)
                fw_list[-1]['coefficients']['data'] = asdict(cd)
                fw_list[-1]['coefficients']['data']['values'] = [
                    b64encode(fw.read(cd.size // cd.count)).decode() for _ in range(cd.count)
                ]
                log.debug(f'coeff {cd.id} size 1x{cd.size:x} with {cd.count} elems')
        elif hdr.type == FwType.SND_SOC_FW_VENDOR_FW:
            abe = AbeFirmwareHeader(fw)
            fw_list[-1]['fw'] = asdict(abe)
            fw_list[-1]['fw']['pmem'] = b64encode(fw.read(abe.pmem_size)).decode()
            fw_list[-1]['fw']['cmem'] = b64encode(fw.read(abe.cmem_size)).decode()
            fw_list[-1]['fw']['dmem'] = b64encode(fw.read(abe.dmem_size)).decode()
            fw_list[-1]['fw']['smem'] = b64encode(fw.read(abe.smem_size)).decode()
            log.debug(f'ABE firmware size {hdr.size} bytes')
            log.debug(f'ABE mem P {abe.pmem_size} C {abe.cmem_size} D {abe.dmem_size} S {abe.smem_size} bytes')
            log.debug(f'ABE Firmware version {abe.version:x}')
        elif hdr.type == FwType.SND_SOC_FW_VENDOR_CONFIG:
            log.debug(f'ABE Config size {hdr.size} bytes')
            fw_list[-1]['config'] = b64encode(fw.read(hdr.size)).decode()
        else:
            log.warning(f'vendor type {hdr.type}:{hdr.vendor_type} not supported')
        assert fw.tell() == next_offset
    log.debug(f'{json.dumps(fw_list, indent=4)}')

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
