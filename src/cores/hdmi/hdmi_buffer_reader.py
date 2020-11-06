from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from cores.axi.buffer_reader import AxiBufferReader
from cores.csr_bank import ControlSignal, StatusSignal
from cores.hdmi.hdmi import Hdmi
from cores.hdmi.parse_modeline import VideoTiming
from cores.ring_buffer_address_storage import RingBufferAddressStorage
from cores.stream.fifo import AsyncStreamFifo
from soc.devicetree.overlay import devicetree_overlay
from soc.pydriver.drivermethod import driver_property
from util.stream import StreamEndpoint


class AddressGenerator(Elaboratable):
    def __init__(
            self,
            ringbuffer: RingBufferAddressStorage,
            initial_video_timing: VideoTiming,
            pixels_per_word=2,
            max_line_width=5000, address_width=32, data_width=64,
    ):
        self.next_frame = Signal()
        self.total_x = ControlSignal(32, reset=1920)
        self.to_read_x = ControlSignal(32, reset=initial_video_timing.hres)
        self.to_read_y = ControlSignal(32, reset=initial_video_timing.vres)
        self.current_buffer = StatusSignal(ringbuffer.current_write_buffer.shape())
        self.frame_count = StatusSignal(32)
        self.speculative_fetch = ControlSignal()

        self.pixels_per_word = pixels_per_word
        self.ringbuffer = ringbuffer
        self.address_width = address_width
        self.data_width_bytes = data_width // 8
        self.max_line_width = max_line_width

        self.output = StreamEndpoint(address_width, is_sink=False, has_last=False)

    def elaborate(self, platform):
        m = Module()

        x_ctr = Signal(range(self.max_line_width))
        y_ctr = Signal.like(self.to_read_y)
        line_base = Signal(self.address_width, reset=self.ringbuffer.buffer_base_list[0])
        with m.If(self.output.ready & (y_ctr < self.to_read_y)):
            m.d.comb += self.output.valid.eq(1)
            with m.If(x_ctr < self.to_read_x - self.pixels_per_word):
                m.d.sync += self.output.payload.eq(self.output.payload + self.data_width_bytes)
                m.d.sync += x_ctr.eq(x_ctr + self.pixels_per_word)
            with m.Else():
                m.d.sync += x_ctr.eq(0)
                m.d.sync += y_ctr.eq(y_ctr + 1)
                m.d.sync += self.output.payload.eq(line_base + self.total_x * self.data_width_bytes // self.pixels_per_word)
                m.d.sync += line_base.eq(line_base + self.total_x  * self.data_width_bytes // self.pixels_per_word)

        def next_buffer():
            m.d.sync += self.frame_count.eq(self.frame_count + 1)
            current_buffer = Signal.like(self.current_buffer)
            with m.If(self.ringbuffer.current_write_buffer == 0):
                m.d.comb += current_buffer.eq(len(self.ringbuffer.buffer_base_list) - 1)
            with m.Else():
                m.d.comb += current_buffer.eq(self.ringbuffer.current_write_buffer - 1)
            m.d.sync += x_ctr.eq(0)
            m.d.sync += y_ctr.eq(0)
            m.d.sync += self.current_buffer.eq(current_buffer)
            m.d.sync += self.output.payload.eq(self.ringbuffer.buffer_base_list[self.current_buffer])
            m.d.sync += line_base.eq(self.ringbuffer.buffer_base_list[self.current_buffer])

        with m.If((y_ctr == self.to_read_y) & self.speculative_fetch):
            next_buffer()

        last_next_frame = Signal()
        m.d.sync += last_next_frame.eq(self.next_frame)
        with m.If(self.next_frame & ~last_next_frame & ~self.speculative_fetch):
            next_buffer()

        return m

    @driver_property
    def fps(self):
        from time import sleep
        start_frames = self.frame_count
        sleep(1)
        return self.frame_count - start_frames


class HdmiBufferReader(Elaboratable):
    def __init__(self, ring_buffer, hdmi_plugin, modeline):
        self.modeline = modeline
        self.hdmi_plugin = hdmi_plugin
        self.ring_buffer = ring_buffer

        self.allow_fifo_reset = ControlSignal()

    def elaborate(self, platform):
        m = Module()

        hdmi = m.submodules.hdmi = Hdmi(self.hdmi_plugin, self.modeline)
        last_blanking_y = Signal()
        m.d.pix += last_blanking_y.eq(hdmi.timing_generator.is_blanking_y)
        begin_blanking_in_axi_domain = Signal()
        m.submodules += FFSynchronizer(hdmi.timing_generator.is_blanking_y & ~last_blanking_y, begin_blanking_in_axi_domain, o_domain="axi_hp")

        addr_gen = m.submodules.addr_gen = DomainRenamer("axi_hp")(AddressGenerator(self.ring_buffer, hdmi.initial_video_timing, pixels_per_word=2))
        m.d.comb += addr_gen.next_frame.eq(begin_blanking_in_axi_domain)
        reader = m.submodules.reader = DomainRenamer("axi_hp")(AxiBufferReader(addr_gen.output))
        m.d.comb += reader.flush.eq(begin_blanking_in_axi_domain)

        m.domains += ClockDomain("buffer_reader_fifo")
        m.d.comb += ClockSignal("buffer_reader_fifo").eq(ClockSignal("axi_hp"))
        m.d.comb += ResetSignal("buffer_reader_fifo").eq(begin_blanking_in_axi_domain & self.allow_fifo_reset)
        pixel_fifo = m.submodules.pixel_fifo = AsyncStreamFifo(reader.output, depth=1024 * 8, w_domain="buffer_reader_fifo", r_domain="pix")

        output = StreamEndpoint.like(pixel_fifo.output, is_sink=True, name="hdmi_reader_output_sink")
        m.d.comb += output.connect(pixel_fifo.output)

        current_pixel_per_word = Signal()
        with m.If(hdmi.timing_generator.active):
            m.d.pix += current_pixel_per_word.eq(current_pixel_per_word + 1)
            with m.If(current_pixel_per_word == 0):
                m.d.comb += output.ready.eq(1)
                m.d.comb += hdmi.rgb.r.eq(output.payload[0+32:8+32])
                m.d.comb += hdmi.rgb.g.eq(output.payload[8+32:16+32])
                m.d.comb += hdmi.rgb.b.eq(output.payload[16+32:24+32])
            with m.Elif(current_pixel_per_word == 1):
                m.d.comb += hdmi.rgb.r.eq(output.payload[0:8])
                m.d.comb += hdmi.rgb.g.eq(output.payload[8:16])
                m.d.comb += hdmi.rgb.b.eq(output.payload[16:24])
        with m.Else():
            m.d.pix += current_pixel_per_word.eq(0)


        overlay_content = """
            reserved-memory {
                #address-cells = <1>;
                #size-cells = <1>;
                ranges;
                
                %overlay_name%_reserved: framebuffer@12800000 {
                    reg = <0x12800000 (1920 * 1080 * 4)>;
                    no-map;
                };
            };

        
            %overlay_name%: framebuffer@12800000 {
                compatible = "simple-framebuffer";
                reg = <0x12800000 (1920 * 1080 * 4)>;
                width = <1920>;
                height = <1080>;
                stride = <(1920 * 4)>;
                format = "a8b8g8r8";
            };
        """
        devicetree_overlay(platform, "framebuffer", overlay_content)

        return m
