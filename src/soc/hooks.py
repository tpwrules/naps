from functools import reduce

from nmigen import *
from nmigen.hdl.ast import SignalSet

from lib.peripherals.csr_bank import CsrBank, _Csr, ControlSignal, StatusSignal, EventReg
from soc.memorymap import MemoryMap
from soc.pydriver.drivermethod import DriverMethod
from soc.tracing_elaborate import ElaboratableSames


def csr_and_driver_method_hook(platform, top_fragment: Fragment, sames: ElaboratableSames):
    already_done = []

    def inner(fragment):
        elaboratable = sames.get_elaboratable(fragment)
        if elaboratable:
            class_members = [(s, getattr(elaboratable, s)) for s in dir(elaboratable)]
            csr_signals = [(name, member) for name, member in class_members if isinstance(member, _Csr)]
            fragment_signals = reduce(lambda a, b: a | b, fragment.drivers.values(), SignalSet())
            csr_signals += [
                (signal.name, signal) for signal in fragment_signals
                if isinstance(signal, _Csr)
                   and signal.name != "$signal"
                   and not any(signal is cmp_signal for name, cmp_signal in csr_signals)
            ]

            new_csr_signals = [(name, signal) for name, signal in csr_signals if not any(signal is done for done in already_done)]
            old_csr_signals = [(name, signal) for name, signal in csr_signals if any(signal is done for done in already_done)]
            for name, signal in new_csr_signals:
                already_done.append(signal)

            mmap = fragment.memorymap = MemoryMap()

            if new_csr_signals:
                m = Module()
                csr_bank = m.submodules.csr_bank = CsrBank()
                for name, signal in new_csr_signals:
                    if isinstance(signal, (ControlSignal, StatusSignal)):
                        csr_bank.reg(name, signal)
                        signal._MustUse__used = True
                    elif isinstance(signal, EventReg):
                        raise NotImplementedError()

                mmap.allocate_subrange(csr_bank.memorymap, name=None)  # name=None means that the Memorymap will be inlined
                platform.to_inject_subfragments.append((m, "ignore"))

            for name, signal in old_csr_signals:
                mmap.add_alias(name, signal)

            driver_methods = [(name, getattr(elaboratable, name)) for name in dir(elaboratable)
                              if isinstance(getattr(elaboratable, name), DriverMethod)]
            for name, driver_method in driver_methods:
                fragment.memorymap.add_driver_method(name, driver_method)

        for subfragment, name in fragment.subfragments:
            inner(subfragment)
    inner(top_fragment)


def address_assignment_hook(platform, top_fragment: Fragment, sames: ElaboratableSames):
    def inner(fragment):
        module = sames.get_module(fragment)
        if hasattr(module, "peripheral"):  # we have the fragment of a marker module for a peripheral
            fragment.memorymap = module.peripheral.memorymap
            return

        # depth first recursion is important so that all the subfragments have a fully populated memorymap later on
        for sub_fragment, sub_name in fragment.subfragments:
            if sub_name != "ignore":
                inner(sub_fragment)

        # add everything to the own memorymap
        if not hasattr(fragment, "memorymap"):
            fragment.memorymap = MemoryMap()
        for sub_fragment, sub_name in fragment.subfragments:
            if sub_name != "ignore":
                assert hasattr(sub_fragment, "memorymap")  # this holds because we did depth first recursion
                fragment.memorymap.allocate_subrange(sub_fragment.memorymap, sub_name)
    inner(top_fragment)

    # prepare and finalize the memorymap
    top_memorymap: MemoryMap = top_fragment.memorymap
    top_memorymap.is_top = True

    assert platform.base_address is not None
    top_memorymap.place_at = platform.base_address

    print("memorymap:\n" + "\n".join(
        "    {}: {!r}".format(".".join(k), v) for k, v in top_memorymap.flattened.items()))
    platform.memorymap = top_memorymap


def peripherals_collect_hook(platform, top_fragment: Fragment, sames: ElaboratableSames):
    platform.peripherals = []

    def collect_peripherals(platform, fragment: Fragment, sames):
        module = sames.get_module(fragment)
        if module:
            if hasattr(module, "peripheral"):
                platform.peripherals.append(module.peripheral)
        for (f, name) in fragment.subfragments:
            collect_peripherals(platform, f, sames)

    collect_peripherals(platform, top_fragment, sames)

    ranges = [(peripheral.range(), peripheral) for peripheral in platform.peripherals
              if not peripheral.memorymap.is_empty and not peripheral.memorymap.was_inlined]

    def range_overlapping(x, y):
        if x.start == x.stop or y.start == y.stop:
            return False
        return ((x.start < y.stop and x.stop > y.start) or
                (x.stop > y.start and y.stop > x.start))

    for a, peripheral_a in ranges:
        for b, peripheral_b in ranges:
            if a is not b and range_overlapping(a, b):
                raise AssertionError("{!r} overlaps with {!r}".format(peripheral_a, peripheral_b))
