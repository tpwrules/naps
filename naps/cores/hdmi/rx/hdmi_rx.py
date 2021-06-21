from nmigen import *

from naps import ImageStream, StreamGearbox, BufferedAsyncStreamFIFO, StatusSignal, ControlSignal, BasicStream, driver_method, driver_init, StreamBuffer, Rose
from naps.cores import probe, trigger
from naps.cores.hdmi.rx.tmds_decoder import TmdsDecoder
from naps.cores.serdes.inputgearbox import StreamWindow, StreamSelect
from naps.vendor.lattice_ecp5 import Pll
from naps.vendor.lattice_ecp5.io import DelayF, IDDRX2F

__all__ = ["HdmiStreamSource"]


class HdmiStreamSource(Elaboratable):
    def __init__(self, resource):
        self.resource = resource

        self.hsync_polarity = ControlSignal()
        self.vsync_polarity = ControlSignal()

        self.width = StatusSignal(16)
        self.height = StatusSignal(16)

        self.blank_r = ControlSignal()
        self.blank_g = ControlSignal()
        self.blank_b = ControlSignal()

        self.stable_lines_needed = 2000
        self.stable = StatusSignal()
        self.frames_stable = StatusSignal(32)

        self.output_not_ready = StatusSignal(32)

        self.output = ImageStream(24)

    def elaborate(self, platform):
        m = Module()

        resource = self.resource

        self.lane_b = m.submodules.lane_b = HdmiRxLane(resource.b, "hdmi_eclk", "hdmi_qdr")
        self.lane_g = m.submodules.lane_g = HdmiRxLane(resource.g, "hdmi_eclk", "hdmi_qdr")
        self.lane_r = m.submodules.lane_r = HdmiRxLane(resource.r, "hdmi_eclk", "hdmi_qdr")

        stable_lines_ctr = Signal(range(self.stable_lines_needed + 1))
        m.d.comb += self.stable.eq(stable_lines_ctr > self.stable_lines_needed - 1)

        x_ctr = Signal(16)
        y_ctr = Signal(16)

        output = self.output.clone()
        with m.If(self.lane_b.data_enable):
            with m.If(~output.ready):
                self.output_not_ready.eq(self.output_not_ready + 1)
            m.d.sync += x_ctr.eq(x_ctr + 1)
            m.d.comb += output.valid.eq(self.stable)
            m.d.comb += output.payload.eq(Cat(
                self.lane_r.data & Repl(~self.blank_r, 8),
                self.lane_g.data & Repl(~self.blank_g, 8),
                self.lane_b.data & Repl(~self.blank_b, 8),
            ))
            m.d.comb += output.line_last.eq(x_ctr == self.width - 1)
            m.d.comb += output.frame_last.eq((x_ctr == self.width - 1) & (y_ctr == self.height - 1))

        hsync = (self.lane_b.control[0] ^ self.hsync_polarity) & ~self.lane_b.data_enable
        with m.If((x_ctr > 128) & hsync):
            m.d.sync += y_ctr.eq(y_ctr + 1)
            m.d.sync += x_ctr.eq(0)
            m.d.sync += self.width.eq(x_ctr)
            with m.If(x_ctr == self.width):
                with m.If(stable_lines_ctr < self.stable_lines_needed):
                    m.d.sync += stable_lines_ctr.eq(stable_lines_ctr + 1)
            with m.Else():
                m.d.sync += stable_lines_ctr.eq(0)

        vsync = (self.lane_b.control[1] ^ self.vsync_polarity) & ~self.lane_b.data_enable
        with m.If((y_ctr > 128) & vsync):
            m.d.sync += y_ctr.eq(0)
            m.d.sync += self.height.eq(y_ctr)
            with m.If(y_ctr == self.height):
                m.d.sync += self.frames_stable.eq(self.frames_stable + 1)

        buffer = m.submodules.buffer = StreamBuffer(output)
        m.d.comb += self.output.connect_upstream(buffer.output)

        return m

    @driver_method
    def train(self):
        print("training hdmi")
        print("tranining lane b...")
        _, delay, alignment = self.lane_b.train(0, 10, 3)
        self.lane_g.delayf.set_delay(delay)
        self.lane_g.select.offset = alignment
        self.lane_r.delayf.set_delay(delay)
        self.lane_r.select.offset = alignment


class HdmiRxLane(Elaboratable):
    def __init__(self, pin, ddr_domain, qdr_domain):
        self.pin = pin
        self.ddr_domain = ddr_domain
        self.qdr_domain = qdr_domain

        self.not_valid_cnt = StatusSignal(16)

        self.blanking_threshold = 128  # this is dvi spec, for hdmi this should be 8
        self.blankings_hit = StatusSignal(32)
        self.blankings_miss = StatusSignal(32)

        self.raw_word = StatusSignal(10)
        self.invert = StatusSignal(reset=1)

        self.data = StatusSignal(8)
        self.data_enable = StatusSignal()
        self.control = StatusSignal(2)

    def elaborate(self, platform):
        m = Module()

        self.delayf = m.submodules.delayf = DelayF(self.pin.i)
        iddr = m.submodules.iddr = DomainRenamer(self.qdr_domain)(IDDRX2F(self.delayf.o, self.ddr_domain))
        iddr_stream = BasicStream(4)
        m.d.comb += iddr_stream.valid.eq(1)
        m.d.comb += iddr_stream.payload.eq(iddr.output)
        gearbox = m.submodules.gearbox = DomainRenamer(self.qdr_domain)(StreamGearbox(iddr_stream, target_width=10))
        fifo = m.submodules.fifo = BufferedAsyncStreamFIFO(gearbox.output, 32, i_domain=self.qdr_domain, o_domain="sync")
        window = m.submodules.window = StreamWindow(fifo.output, window_words=2)
        self.select = select = m.submodules.select = StreamSelect(window.output, output_width=10)

        m.d.comb += select.output.ready.eq(1)
        with m.If(~select.output.valid):
            # ths should never happen if the clock domains are correctly set up
            m.d.sync += self.not_valid_cnt.eq(self.not_valid_cnt + 1)

        m.d.comb += self.raw_word.eq(select.output.payload)
        tmds = m.submodules.tmds = TmdsDecoder(self.raw_word ^ Repl(self.invert, 10))
        m.d.comb += self.data.eq(tmds.data)
        m.d.comb += self.data_enable.eq(tmds.data_enable)
        m.d.comb += self.control.eq(tmds.control)

        blanking_ctr = Signal(16)
        with m.If(~self.data_enable):
            with m.If(blanking_ctr < self.blanking_threshold):
                m.d.sync += blanking_ctr.eq(blanking_ctr + 1)
            with m.If(blanking_ctr == (self.blanking_threshold - 1)):
                m.d.sync += self.blankings_hit.eq(self.blankings_hit + 1)
        with m.Else():
            with m.If((blanking_ctr != 0) & (blanking_ctr < self.blanking_threshold)):
                m.d.sync += self.blankings_miss.eq(self.blankings_miss + 1)
            m.d.sync += blanking_ctr.eq(0)

        return m

    @driver_method
    def train(self, start=0, step=10, n=12, fine_training=False):
        self.delayf.set_delay(start)
        from time import sleep
        best = (0.0, 0, 0)
        for i in range(n):
            delay = i * step + start
            print(f"delay {delay}")

            for alignment in range(9):
                self.select.offset = alignment
                hit_before = self.blankings_hit
                miss_before = self.blankings_miss
                sleep(0.1)
                hit = self.blankings_hit - hit_before
                miss = self.blankings_miss - miss_before
                ratio = hit / (miss + 1)
                if ratio > best[0]:
                    best = (ratio, delay, alignment)
                print(f"alignment {alignment} ratio {ratio} hit/miss {hit}/{miss}")

            self.delayf.forward(step)

        ratio, delay, alignment = best
        print(f"elected ratio={ratio} delay={delay} alignment={alignment}")
        self.delayf.set_delay(delay)
        self.select.offset = alignment
        if fine_training:
            if ratio != 0:
                return self.train(start=delay - 10, step=1, n=20, fine_training=False)
            else:
                print("failed training")
        else:
            return best
