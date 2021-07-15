from nmigen import *
from nmigen._unused import MustUse

from naps.soc.memorymap import Address
from naps.soc.peripheral import Response

__all__ = ["ControlSignal", "StatusSignal", "EventReg"]


class UncollectedCsrWarning(Warning):
    pass


class _Csr(MustUse):
    """a marker class to collect the registers easily"""
    _MustUse__warning = UncollectedCsrWarning
    _MustUse__silence = True
    _address = None


class ControlSignal(Signal, _Csr):
    """ Just a Signal. Indicator, that it is for controlling some parameter (i.e. can be written from the outside)
    Is mapped as a CSR in case the design is build with a SocPlatform.
    """

    def __init__(self, shape=None, *, address=None, read_strobe=None, write_strobe=None, src_loc_at=0, **kwargs):
        super().__init__(shape, src_loc_at=src_loc_at + 1, **kwargs)
        self.src_loc_at = src_loc_at
        self._shape = shape
        self._kwargs = kwargs

        self._address = Address.parse(address)
        self._write_strobe = write_strobe
        self._read_strobe = read_strobe


class StatusSignal(Signal, _Csr):
    """ Just a Signal. Indicator, that it is for communicating the state to the outside world (i.e. can be read but not written from the outside)
        Is mapped as a CSR in case the design is build with a SocPlatform.
    """

    def __init__(self, shape=None, *, address=None, read_strobe=None, src_loc_at=0, **kwargs):
        super().__init__(shape, src_loc_at=src_loc_at + 1, **kwargs)

        self._address = Address.parse(address)
        self._read_strobe = read_strobe


class EventReg(_Csr):  # TODO: bikeshed name
    """ A "magic" register, that doesnt have to be backed by a real register. Useful for implementing resets,
    fifo interfaces, ...
    The logic generated by the handle_read and handle_write hooks is part of the platform defined BusSlave and runs in its clockdomain.
    """

    def __init__(self, bits=None, address=None):
        super().__init__()
        assert address is not None or bits is not None
        if bits is not None:
            assert bits <= 32, "EventReg access would not be atomic!"
        self._bits = bits
        self._address = Address.parse(address)

        def handle_read(m, data, read_done):
            read_done(Response.ERR)

        self.handle_read = handle_read

        def handle_write(m, data, write_done):
            write_done(Response.ERR)

        self.handle_write = handle_write

    def __len__(self):
        if self._address is not None:
            return self._address.bit_len
        return self._bits
