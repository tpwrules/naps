from nmigen import *
from nmigen.cli import main

from modules.xilinx.blocks import Ps7
from modules.quadrature_decoder import QuadratureDecoder
from modules.managers import anarchy_manager, clock_manager
from util.nmigen import get_signals
from modules.nws2812 import nWs2812
import devices.common.layouts as layouts


class Top:
    """The top entity of the gateware.

    Only instantiates the right parts and connects them.
    Also takes care of the connections managed by the `anarchy`.
    """

    def __init__(self):
        self.sensor = Record(layouts.ar0330)
        self.i2c = Record(layouts.i2c)  # i2c also somehow belongs to the image sensor. it is shared globally

        self.plugin_n = Record(layouts.plugin_module)
        self.plugin_s = Record(layouts.plugin_module)

        self.pmod_n = Signal(8)
        self.pmod_s = Signal(8)
        self.pmod_e = Signal(4)

        self.ws2812 = Signal()
        self.encoder = Record(layouts.encoder)

        self._clk = Signal()

        # as the very last step, assign the out of tree resources
        anarchy_manager.add_params(self)

    def elaborate(self, platform):
        m = Module()

        ps7 = m.submodules.ps7_wrapper = Ps7()

        m.d.comb += self._clk.eq(ClockSignal())
        m.d.comb += ClockSignal().eq(ps7.fclk.clk[0])
        m.d.comb += ResetSignal().eq(0)

        # quadrature_decoder = m.submodules.quadrature_decoder = QuadratureDecoder(self.encoder.quadrature)

        ws2812 = m.submodules.ws2812 = nWs2812()
        m.d.comb += self.ws2812.eq(ws2812.out)

        m.d.comb += ws2812.input.eq(0xff000000ff000000ff)

        # clock_manager.generate_clock("10Mhz")
        # clock_manager.manage_clocks(m, "100 Mhz")
        return m


if __name__ == "__main__":
    top = Top()
    main(top, ports=get_signals(top) + [top._clk])
