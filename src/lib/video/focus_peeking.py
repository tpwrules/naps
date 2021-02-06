from itertools import chain

from nmigen import *

from lib.peripherals.csr_bank import ControlSignal
from lib.video.image_stream import ImageStream
from lib.video.rgb import RGB24
from lib.video.video_transformer import VideoTransformer
from util.nmigen_misc import nAbsDifference


class FocusPeeking(Elaboratable):
    """Adds A focus peeking overlay to the image"""
    def __init__(self, input: ImageStream, width=3000, height=3000):
        self.input = input
        self.output = ImageStream(24)

        self.width = width
        self.height = height

        self.threshold = ControlSignal(16, reset=255)
        self.highlight_r = ControlSignal(8, reset=255)
        self.highlight_g = ControlSignal(8)
        self.highlight_b = ControlSignal(8)

    def elaborate(self, platform):
        m = Module()

        def transformer_function(x, y, image_proxy):
            self_rgb = RGB24(image_proxy[x, y])
            other_rgbs = [
                RGB24(image_proxy[x + dx, y + dy])
                for dx in range(-1, 2)
                for dy in range(-1, 2)
            ]

            deviations = [[nAbsDifference(self_rgb.r, o.r), nAbsDifference(self_rgb.g, o.g), nAbsDifference(self_rgb.b, o.b)] for o in other_rgbs]
            total_deviation = sum(chain(*deviations))

            output = RGB24()
            m.d.comb += output.eq(RGB24(image_proxy[x, y]))
            with m.If(total_deviation > self.threshold):
                m.d.comb += output.r.eq(self.highlight_r)
                m.d.comb += output.g.eq(self.highlight_g)
                m.d.comb += output.b.eq(self.highlight_b)

            return output

        video_transformer = m.submodules.video_transformer = VideoTransformer(self.input, transformer_function,
                                                                              self.width, self.height)
        m.d.comb += self.output.connect_upstream(video_transformer.output)

        return m


def stream_ports(stream):
    return [getattr(stream, n) for n in [*stream._downwards_ports, *stream._upwards_ports]]

if __name__ == "__main__":
    in_stream = ImageStream(len(RGB24()))
    dut = FocusPeeking(in_stream, width=512, height=512)

    from nmigen.back.cxxrtl import convert
    from pathlib import Path
    (Path(__file__).parent / "focus_peeking_cxxrtl_test" / "focus_peeking_test.cpp").write_text(convert(dut, ports=[*stream_ports(in_stream), *stream_ports(dut.output), dut.threshold, dut.highlight_r, dut.highlight_g, dut.highlight_b]))
