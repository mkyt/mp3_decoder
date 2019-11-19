from enum import IntFlag, IntEnum
import struct

from binary import BinaryBase, Item, EnumTransformer, MSBZeroBytes


def decode_unsynchronization(buf):
    return buf.replace(b'\xff\x00', b'\xff')


class ID3v2Flag(IntFlag):
    UNSYNCHRONIZATION = 1 << 7
    EXTENDED_HEADER = 1 << 6
    EXPERIMENTAL = 1 << 5


class ID3v2Header(BinaryBase):
    identifier = Item('3s')
    major_ver = Item('B')
    minor_ver = Item('B')
    flag = Item('B', EnumTransformer(ID3v2Flag))
    tagsize = Item('4B', MSBZeroBytes(4))


class ID3v2ExtendedFlag(IntFlag):
    CRC_DATA_PRESENT = 1 << 15


class ID3v2ExtendedHeader(BinaryBase):
    extended_header_size = Item('>I')
    extended_flag = Item('>H')
    padding_size = Item('>I')


class ID3v2FrameHeaderFlag(IntFlag):
    TAG_ALTER_DISCARDED = 1 << 15
    FILE_ALTER_DISCARDED = 1 << 14
    READ_ONLY = 1 << 13
    COMPRESSION = 1 << 7
    ENCRYPTION = 1 << 6
    GROUPING = 1 << 5


class ID3v2FrameHeader(BinaryBase):
    frame_id = Item('4s')
    data_size = Item('>I')
    flags = Item('>H', EnumTransformer(ID3v2FrameHeaderFlag))


class ID3v2FrameBase:
    def __init__(self, buf):
        self.raw = buf
        self.size = len(buf)


class UniqueFileIdentifierFrame(ID3v2FrameBase):
    def __init__(self, buf):
        super().__init__(buf)
        idx = self.raw.index(b'\0')
        self.owner_id = self.raw[:idx]
        self.id = self.raw[idx+1:]


class TextEncodingDescription(IntEnum):
    ISO_8859_1 = 0
    UTF_16 = 1      # UTF-16 with BOM
    UTF_16_BE = 2
    UTF_8 = 3

    @property
    def encoding_string(self):
        if self == self.__class__.ISO_8859_1:
            return 'latin-1'
        elif self == self.__class__.UTF_16:
            return 'utf-16'
        elif self == self.__class__.UTF_16_BE:
            return 'utf-16-be'
        elif self == self.__class__.UTF_8:
            return 'utf-8'
        else:
            raise ValueError


class TextFrame(ID3v2FrameBase):
    def __init__(self, buf):
        super().__init__(buf)
        self.encoding = TextEncodingDescription(int(buf[0]))
        self.text = str(buf[1:], encoding=self.encoding.encoding_string)[:-1]


def FrameForIdentifier(identifier):
    if identifier == b'UFID':
        return UniqueFileIdentifierFrame
    elif identifier == b'TXXX':
        return ID3v2FrameBase
    elif identifier.startswith(b'T'):
        return TextFrame
    elif identifier == b'WXXX':
        return ID3v2FrameBase
    elif identifier.startswith(b'W'):
        return ID3v2FrameBase
    else:
        return ID3v2FrameBase

class ID3v2Tag:

    @staticmethod
    def has_id3v2(data):
        return data.startswith(b'ID3')

    def __init__(self, data):
        offset = 0
        self.header = ID3v2Header(data[offset:])
        offset += self.header.size
        final_offset = self.header.size + self.header.tagsize
        self.size = final_offset

        # cut tag content w/o header
        content = data[offset:final_offset]
        # decode unsynchronized data if necessary
        if self.header.flag & ID3v2Flag.UNSYNCHRONIZATION:
            content = decode_unsynchronization(content)

        # process extended header if present
        offset = 0
        if self.header.flag & ID3v2Flag.EXTENDED_HEADER:
            self.ext_header = ID3v2ExtendedHeader(content[offset:])
            offset += self.ext_header.size
            if self.ext_header.extended_flag & ID3v2ExtendedFlag.CRC_DATA_PRESENT:
                self.total_frame_crc = struct.unpack_from('>I', content, offset)
                offset += 4

        self.frames = []
        while True:
            if offset >= len(content) or content[offset] == 0: # padding is filled w/ b'\0'
                break
            frame_header = ID3v2FrameHeader(content[offset:])
            offset += frame_header.size
            frame_data = FrameForIdentifier(frame_header.frame_id)(content[offset:offset+frame_header.data_size])
            offset += frame_header.data_size
            self.frames.append((frame_header, frame_data))
