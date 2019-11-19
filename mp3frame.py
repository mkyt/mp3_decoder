from enum import IntEnum
import struct

from binary import BitsParserBase, BitfieldBase, Field, Bits, BitsReader


class MPEGAudioVersionID(IntEnum):
    VERSION_2_5 = 0
    RESERVED = 1
    VERSION_2 = 2
    VERSION_1 = 3


class LayerDescription(IntEnum):
    RESERVED = 0
    LAYER_III = 1
    LAYER_II = 2
    LAYER_I = 3


class ChannelMode(IntEnum):
    STEREO = 0
    JOINT_STEREO = 1
    DUAL_CHANNEL = 2
    SINGLE_CHANNEL = 3


bitrate_tbl = [
    [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
]


class MP3FrameHeader(BitfieldBase):
    frame_sync = Field(11)
    mpeg_audio_version = Field(2, MPEGAudioVersionID)
    layer_description = Field(2, LayerDescription)
    protection = Field(1) # 0 : CRC-protected , 1: not protected
    bitrate_index = Field(4)
    sample_rate_index = Field(2)
    padding = Field(1, bool)
    private = Field(1, bool)
    channel_mode = Field(2, ChannelMode)
    mode_extension = Field(2)
    copyright = Field(1, bool)
    original = Field(1, bool)
    emphasis = Field(2)
    
    @staticmethod
    def has_frame_sync(buf):
        return buf[0] == 0xff and ((buf[1] >> 5) & 0x7) == 0x7

    @property
    def bitrate(self):
        if self.bitrate_index == 0xf:
            raise ValueError
        idx = None
        if self.mpeg_audio_version == MPEGAudioVersionID.VERSION_1:
            if self.layer_description == LayerDescription.LAYER_I:
                idx = 0
            elif self.layer_description == LayerDescription.LAYER_II:
                idx = 1
            elif self.layer_description == LayerDescription.LAYER_III:
                idx = 2
        elif self.mpeg_audio_version == MPEGAudioVersionID.VERSION_2 or self.mpeg_audio_version == MPEGAudioVersionID.VERSION_2_5:
            if self.layer_description == LayerDescription.LAYER_I:
                idx = 3
            else:
                idx = 4
        return bitrate_tbl[idx][self.bitrate_index]

    @property
    def sample_rate(self):
        if self.sample_rate_index == 0x3:
            raise ValueError
        res = [44100, 48000, 32000][self.sample_rate_index]
        if self.mpeg_audio_version == MPEGAudioVersionID.VERSION_2:
            res /= 2
        elif self.mpeg_audio_version == MPEGAudioVersionID.VERSION_2_5:
            res /= 4
        return res

    @property
    def frame_length(self):
        if self.layer_description == LayerDescription.LAYER_I:
            return (int(12 * self.bitrate * 1000 / self.sample_rate) + (1 if self.padding else 0)) * 4
        else:
            return int(144 * self.bitrate * 1000 / self.sample_rate) + (1 if self.padding else 0)

    @property
    def n_channels(self):
        return 1 if self.channel_mode == ChannelMode.SINGLE_CHANNEL else 2


class BlockWindowType(IntEnum):
    NORMAL = 0
    START = 1
    SHORT = 2
    END = 3


class SideInfoForGranule(BitsParserBase):
    '''sideinfo for each granule
    
    length: 59 bits (34 + 22 + 3)

    '''
    bits = 59

    pre_fields = { # 34 bits
        'part2_3_length': Field(12),
        'big_values': Field(9),
        'global_gain': Field(8),
        'scalefac_compress': Field(4),
        'win_switch_flag': Field(1, bool)
    }

    non_normal_window = { # 22 bits : 2 + 1 + 10(5x2) + 9(3x3)
        'block_type': Field(2, BlockWindowType),
        'mixed_block_flag': Field(1, bool),
        'table_select': Field(5, shape=2),
        'subblock_gain': Field(3, shape=3)            
    }

    normal_window = { # 22 bits : 15(5x3) + 4 + 3
        'table_select': Field(5, shape=3),
        'region0_count': Field(4),
        'region1_count': Field(3)
    }

    rest_fields = { # 3 bits
        'preflag': Field(1, bool),
        'scalefac_scale': Field(1),
        'count1table_select': Field(1)
    }

    slen_table = {
        0: (0, 0),
        1: (0, 1),
        2: (0, 2),
        3: (0, 3),
        4: (3, 0),
        5: (1, 1),
        6: (1, 2),
        7: (1, 3),
        8: (2, 1),
        9: (2, 2),
        10: (2, 3),
        11: (3, 1),
        12: (3, 2),
        13: (3, 3),
        14: (4, 2),
        15: (4, 3)
    }

    def __init__(self, reader):
        super().__init__(reader)

        self.set_fields(self.pre_fields)

        if self.win_switch_flag:
            self.set_fields(self.non_normal_window)
        else:
            self.set_fields(self.normal_window)
            self.block_type = BlockWindowType.NORMAL

        self.set_fields(self.rest_fields)

        self.slen1, self.slen2 = self.slen_table[self.scalefac_compress]


class MP3SideInfoMono(BitfieldBase):
    '''Sideinfo for mono frame

    17 bytes = 136 bits (9 + 5 + 4 + 59 * 2)
    '''
    size = 17 # in bytes

    main_data_begin = Field(9)
    private_bits = Field(5)
    scale_factor_selection_info = Field(1, shape=(1,4))
    granules = Field(59, SideInfoForGranule, shape=(2,1)) # gr,ch


class MP3SideInfoStereo(BitfieldBase):
    '''Sideinfo for stereo frame

    32 bytes = 256 bits (9 + 3 + 8(4*2) + 59 * 2 * 2)

    '''
    size = 32 # in bytes

    main_data_begin = Field(9)
    private_bits = Field(3)
    scale_factor_selection_info = Field(1, shape=(2,4))
    granules = Field(59, SideInfoForGranule, shape=(2,2)) # gr,ch


class MP3Frame:
    def __init__(self, data):
        # read frame header
        offset = 0
        self.header = MP3FrameHeader(data)
        offset += self.header.size

        # read CRC if present
        if self.header.protection == 0:
            self.crc = struct.unpack_from('>H', data, offset)
            offset += 2
        
        # read sideinfo
        if self.header.n_channels == 1:
            self.sideinfo = MP3SideInfoMono(data[offset:])
        else:
            self.sideinfo = MP3SideInfoStereo(data[offset:])
        offset += self.sideinfo.size

