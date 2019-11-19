import struct

from mp3frame import MP3FrameHeader
from id3 import ID3v2Tag


def find_next_frame(buf, offset):
    pos = offset
    bufsiz = len(buf)
    while pos < bufsiz - 1:
        if buf[pos] != 0xff:
            pos += 1
            continue
        if ((buf[pos+1] >> 5) & 0x7) == 0x7:
            return pos
        pos += 2


class MP3File:
    def __init__(self, data):
        self.data = data
        offset = 0
        if ID3v2Tag.has_id3v2(data[offset:]):
            self.id3v2 = ID3v2Tag(data)
            offset += self.id3v2.size
        offset = find_next_frame(data, offset)
        
