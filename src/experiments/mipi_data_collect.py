# An experiment that allows to capture the raw mipi data with 1:8 serdes to feed into the
# simulation tests

from nmigen import *
from nmigen.build import Subsignal, Pins, PinsN, Attrs, DiffPairs, Resource

from devices import MicroR2Platform
from lib.bus.stream.fifo import BufferedAsyncStreamFIFO
from lib.bus.stream.pipeline import Pipeline
from lib.bus.stream.stream import PacketizedStream
from lib.debug.clocking_debug import ClockingDebug
from lib.dram_packet_ringbuffer.stream_if import DramPacketRingbufferStreamWriter
from lib.io.mipi.s7_phy import ClockRxPhy, LaneRxPhy
from lib.peripherals.csr_bank import ControlSignal
from lib.peripherals.i2c.bitbang_i2c import BitbangI2c
from lib.primitives.xilinx_s7.io import IDelayCtrl
from soc.cli import cli
from soc.platforms import ZynqSocPlatform
from soc.pydriver.drivermethod import driver_method


class Top(Elaboratable):
    def __init__(self):
        self.sensor_reset_n = ControlSignal(name='sensor_reset', reset=1)
        self.enable_write = ControlSignal()
        self.change_packet = ControlSignal()

    def elaborate(self, platform):
        m = Module()

        platform.ps7.fck_domain(100e6, "axi_hp")

        # Control Pane
        i2c_pads = platform.request("i2c")
        m.submodules.i2c = BitbangI2c(i2c_pads)

        clocking = m.submodules.clocking = ClockingDebug("sync", "sensor_clk", "axi_hp")

        # Input Pipeline
        platform.add_resources([
            Resource("sensor2", 0,
                     Subsignal("shutter", Pins("25", dir='o', conn=("expansion", 0)), Attrs(IOSTANDARD="LVCMOS25")),
                     Subsignal("trigger", Pins("27", dir='o', conn=("expansion", 0)), Attrs(IOSTANDARD="LVCMOS25")),
                     Subsignal("reset", PinsN("31", dir='o', conn=("expansion", 0)), Attrs(IOSTANDARD="LVCMOS25")),
                     Subsignal("clk", Pins("33", dir='o', conn=("expansion", 0)), Attrs(IOSTANDARD="LVCMOS25")),
                     Subsignal("lvds_clk", DiffPairs("51", "53", dir='i', conn=("expansion", 0)), Attrs(IOSTANDARD="LVDS_25", DIFF_TERM="TRUE")),
                     Subsignal("lvds", DiffPairs("41 45 55 65", "43 47 57 67", dir='i', conn=("expansion", 0)), Attrs(IOSTANDARD="LVDS_25", DIFF_TERM="TRUE")),
                     ),
        ])
        sensor = platform.request("sensor2")
        platform.ps7.fck_domain(24e6, "sensor_clk")
        m.d.comb += sensor.clk.eq(ClockSignal("sensor_clk"))
        m.d.comb += sensor.reset.eq(~self.sensor_reset_n)

        # this experiment requires bodging the MicroR2 in a way to connect the mipi lanes of the ar0330
        # to the pins where normally the hispi would be connected. the normal hispi traces must be cut.
        mipi_clock = sensor.lvds[0]
        mipi_lane4 = sensor.lvds[1]
        mipi_lane3 = sensor.lvds_clk
        mipi_lane2 = sensor.lvds[2]
        mipi_lane1 = sensor.lvds[3]

        m.domains.sync = ClockDomain()
        m.submodules.clock_rx = ClockRxPhy(mipi_clock, ddr_domain="ddr")
        lanes = [mipi_lane1, mipi_lane2, mipi_lane3, mipi_lane4]
        lane_phys = [LaneRxPhy(p, ddr_domain="ddr") for p in lanes]
        for i, phy in enumerate(lane_phys):
            m.submodules[f'lane{i + 2}_phy'] = phy

        platform.ps7.fck_domain(200e6, "idelay_ref")
        m.submodules.idelay_ctrl = IDelayCtrl("idelay_ref")

        data_stream = PacketizedStream(32)
        m.d.comb += data_stream.payload.eq(Cat(phy.output for phy in lane_phys))
        m.d.comb += data_stream.valid.eq(self.enable_write)
        m.d.comb += data_stream.last.eq(self.change_packet)

        p = Pipeline(m)
        p += BufferedAsyncStreamFIFO(data_stream, 2048, o_domain="axi_hp")
        p += DramPacketRingbufferStreamWriter(p.output, max_packet_size=0x800000, n_buffers=1)

        return m

    @driver_method
    def kick_sensor(self):
        from os import system
        system("cat /axiom-api/scripts/kick/value")


if __name__ == "__main__":
    cli(Top, runs_on=(MicroR2Platform,), possible_socs=(ZynqSocPlatform,))
