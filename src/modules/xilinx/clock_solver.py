"""Generates multiple Clocks using the Xilinx clocking primitives"""

from itertools import product
from nmigen import *

from .blocks import Mmcm, Pll


class ClockSolver(Elaboratable):
    def __init__(self, clocks, in_clk, f_in):
        self.f_in = f_in
        self.in_clk = in_clk
        self.clocks = clocks
        self.available_resources = ([Mmcm] * 2) + ([Pll] * 2)

    def elaborate(self, platform):
        mod = Module()

        self.clocks = self.clocks.copy()

        while self.clocks:
            resource = self.available_resources.pop(0)()
            frequencies = list(set(self.clocks.values()))[0:resource.CLOCK_COUNT]

            (global_m, global_d), dividers = ClockSolver._solve(resource, self.f_in, frequencies)
            mod.d.comb += resource.get_in_clk().eq(self.in_clk)
            resource.set_vco(global_m, global_d)
            for d, f in zip(dividers, frequencies):
                # first, add a domain named after the requested frequency
                clock = resource.get_clock(d)
                actual_freq = int(self.f_in * global_m / global_d / d)

                frequency_domain = ClockDomain("clk{}".format(f))
                mod.domains += frequency_domain
                mod.d.comb += frequency_domain.clk.eq(clock)

                # then assign the named domains to it
                done = []
                for name, freq in self.clocks.items():
                    if freq == f:
                        name_domain = ClockDomain(name)
                        mod.domains += name_domain
                        mod.d.comb += name_domain.clk.eq(ClockSignal("clk{}".format(f)))
                        done.append(name)
                        print("clock {}: \t\t {} actual; {} requested; {:10.0f}% off".format(name, actual_freq, freq, (1 - actual_freq / freq) * 100))
                for name in done:
                    self.clocks.pop(name)
            setattr(mod.submodules, "{}".format(resource.__class__.__name__), resource)
        return mod

    @staticmethod
    def _solve(cr, f_in, clock_freqs, output_divider_step=1):
        assert len(clock_freqs) < cr.CLOCK_COUNT

        possible_vco_freqs = [(f_in * (m / d), (m, d)) for m, d in product(range(1, 128), range(1, 128))
                              if cr.VCO_MIN < (f_in * (m / d)) < cr.VCO_MAX]

        def dividers(f_in, f_out):
            return [round(f_in / target_freq / output_divider_step) * output_divider_step for target_freq in f_out]

        rated_vco_freqs = [(
            [(f_target - (f_vco / d)) ** 2 for f_target, d in zip(clock_freqs, dividers(f_vco, clock_freqs))],
            comb, dividers(f_vco, clock_freqs)
        ) for f_vco, comb in possible_vco_freqs]

        return max(rated_vco_freqs, key=lambda x: x[0])[1:]
