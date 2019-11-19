# -*- coding: utf-8 -*-
import struct
from types import FunctionType
from collections import namedtuple
from abc import ABC, abstractmethod
from functools import reduce


LogEntry = namedtuple('LogEntry', 'offset size')


_product = lambda iter: reduce(lambda x,y: x*y, iter, 1)


def _reshape(vals, shape):
    '''convert 1-d array-like `vals` into multidimensional array
    whose shape is defined by tuple `shape`
    
    Example:
      >>> _reshape(list(range(12)), (2,2,3))
      [[[0, 1, 2], [3, 4, 5]], [[6, 7, 8], [9, 10, 11]]]
    '''
    if len(shape) == 1:
        if len(vals) != shape[0]:
            raise ValueError
        return vals
    else:
        res = []
        siz = _product(shape[1:])
        for i in range(shape[0]):
            res.append(_reshape(vals[siz*i:siz*(i+1)], shape[1:]))
        return res


class Field:
    def __init__(self, bits, klass=None, shape=1):
        self.bits = bits
        self.klass = klass
        if isinstance(shape, int):
            shape = (shape, )
        self.shape = shape
        self.n_elems = _product(self.shape)
        self.whole_bits = self.bits * self.n_elems


class BitsMeta(type):
    def __new__(meta, name, bases, d):
        entries = []
        for k, v in d.items():
            if isinstance(v, Field):
                entries.append(k)
        d['_entries'] = entries
        return super().__new__(meta, name, bases, d)


class Bits:
    def __init__(self, buf, offset, size=-1):
        if isinstance(buf, bytes):
            if size == -1:
                self.backing = buf[offset:] # backing buffer (bytes)
                self.size = size # in bits (-1 if unknown)
            else:
                self.backing = buf[offset:offset+size]
                self.size = size * 8
            self.bit_offset = 0 # in bits
        elif isinstance(buf, self.__class__):
            self.backing = buf.backing
            self.bit_offset = buf.bit_offset + offset
            self.size = size

    def trim(self, st, ed):
        return self.__class__(self, st, ed - st)
    
    def __int__(self):
        if self.size < 0:
            raise ValueError('cannot convert to int if size is unknown')
        left = self.size
        pos = self.bit_offset // 8
        msb = self.bit_offset % 8
        res = 0
        while True:
            b = self.backing[pos]
            bits_extractable = 8 - msb
            v = b & (2 ** bits_extractable - 1)
            if bits_extractable >= left:
                v >>= (bits_extractable - left)
                res += v
                break
            else:
                left -= bits_extractable
                res += (v << left)
                pos += 1
                msb = 0
        return res

    def __getitem__(self, key):
        if isinstance(key, slice):
            if key.step is not None and key.step != 1:
                raise ValueError('slicing of step other than 1 is not supported')
            return self.trim(key.start, key.stop)
        elif isinstance(key, int):
            offset = self.bit_offset + key
            pos = offset // 8
            b = offset % 8
            return (int(self.backing[pos]) >> (7-b)) & 1


class BitsReader:
    def __init__(self, bits):
        self.bits = bits
        self.offset = 0
    
    def get(self, size):
        portion = self.bits[self.offset:self.offset+size]
        self.offset += size
        return int(portion)


class BitfieldBase(metaclass=BitsMeta):
    def __init__(self, buffer):
        klass = self.__class__
        offset = 0
        log = {}

        siz = 0
        for k in klass._entries:
            item = getattr(klass, k)
            siz += item.whole_bits
        self.bits = siz
        self.size = (siz + 7) // 8 # in bytes

        if isinstance(buffer, bytes):
            self.reader = BitsReader(Bits(buffer, 0, self.size))
        elif isinstance(buffer, Bits):
            self.reader = BitsReader(buffer)
        elif isinstance(buffer, BitsReader):
            self.reader = buffer

        for k in klass._entries:
            init_offset = self.reader.offset
            item = getattr(klass, k)
            if item.shape != (1, ): # array-like
                vv = []
                for _ in range(item.n_elems):
                    v = self.reader.get(item.bits)
                    if item.klass:
                        v = item.klass(v)
                    vv.append(v)
                v = _reshape(vv, item.shape)
            else: # scalar
                v = self.reader.get(item.bits)
                if item.klass:
                    v = item.klass(v)
            log[k] = LogEntry(init_offset, item.whole_bits)
            setattr(self, k, v)
        self._log = log

    def dbg(self, k=None):
        klass = self.__class__
        def info(k):
            log = self._log[k]
            frm = log.offset
            siz = log.size
            item = getattr(klass, k)
            return '{}: value={}, offset={}, bits={}'.format(k, repr(getattr(self, k)), frm, siz)
        if k:
            print(info(k))
        else:
            for k in klass._entries:
                print(info(k))


################################################################################


class TransformerBase(ABC):
    @abstractmethod
    def decode(self, frm):
        pass
    
    @abstractmethod
    def encode(self, value):
        pass


class EnumTransformer(TransformerBase):
    def __init__(self, klass):
        self.klass = klass
    
    def decode(self, frm):
        return self.klass(frm)
    
    def encode(self, value):
        return int(value)


class MSBZeroBytes(TransformerBase):
    def __init__(self, size):
        self.size = size

    def decode(self, frm):
        res = 0
        for val in frm:
            res <<= 7
            res += val
        return res
    
    def encode(self, value):
        res = []
        for i in range(self.size):
            res.append(value % (2 ** 7))
            value //= (2 ** 7)
        return tuple(reversed(res))


class Item:
    def __init__(self, fmt, transformer=None, noskip=False, *kw):
        self.fmt = fmt
        self.struct = struct.Struct(fmt)
        self.size = self.struct.size
        self.transformer = transformer
        self.noskip = noskip
        self.kw = kw
    
    def pack(self, value):
        if self.transformer:
            value = self.transformer.encode(value)
        return self.struct.pack(value)
    
    def unpack(self, bin, offset=0):
        v = self.struct.unpack_from(bin, offset)
        if len(v) == 1: # singleton tuple
            v = v[0]
        if self.transformer:
            return self.transformer.decode(v)
        else:
            return v


class BinaryMeta(type):
    def __new__(meta, name, bases, d):
        entries = []
        for k, v in d.items():
            if isinstance(v, Item) or (isinstance(v, FunctionType) and hasattr(v, 'is_item')):
                entries.append(k)
        d['_entries'] = entries
        return super().__new__(meta, name, bases, d)


class BinaryBase(metaclass=BinaryMeta):
    def __init__(self, buffer):
        self.raw = buffer
        klass = self.__class__
        offset = 0
        log = {}
        for k in klass._entries:
            item = getattr(klass, k)
            if isinstance(item, Item):
                v = item.unpack(buffer, offset)
                consumed = 0 if item.noskip else item.size
            else: # functional unpacker
                v, consumed = item(buffer, offset)
            log[k] = LogEntry(offset, consumed)
            offset += consumed
            setattr(self, k, v)
        self.size = offset
        self._log = log
    
    def dbg(self, k=None):
        klass = self.__class__
        def info(k):
            log = self._log[k]
            frm = log.offset
            siz = log.size
            item = getattr(klass, k)
            fmt = item.fmt if isinstance(item, Item) else '<fn>'
            raw = self.raw[frm:frm+siz]
            return '{}: value={}, offset={} size={}, fmt="{}", raw={}, hex={}'.format(k, repr(getattr(self, k)), frm, siz, fmt, raw, raw.hex())
        if k:
            print(info(k))
        else:
            for k in klass._entries:
                print(info(k))


__all__ = [
    'Field',
    'Bits',
    'BitsReader',
    'BitfieldBase',
    'EnumTransformer',
    'MSBZeroBytes',
    'Item',
    'BinaryBase'
 ]