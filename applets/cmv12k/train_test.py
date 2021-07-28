# set up and demonstrate training of CMV12k

from nmigen import *
from naps import *

class Top(Elaboratable):
    def __init__(self):
        self.sensor_reset = ControlSignal()

    def elaborate(self, platform: BetaPlatform):
        m = Module()

        platform.ps7.fck_domain(requested_frequency=100e6)

        sensor = platform.request("sensor")
        platform.ps7.fck_domain(250e6, "sensor_clk")
        m.d.comb += sensor.lvds_clk.eq(ClockSignal("sensor_clk"))
        m.d.comb += sensor.reset.eq(self.sensor_reset)

        m.d.comb += [
            sensor.frame_req.eq(0),
            sensor.t_exp1.eq(0),
            sensor.t_exp2.eq(0),
        ]

        spi_pads = platform.request("sensor_spi")
        m.submodules.spi = BitbangSPI(spi_pads)

        sensor_rx = m.submodules.sensor_rx = Cmv12kRx(sensor)

        return m

    @driver_method
    def write_reg(self, reg, value):
        import spidev
        spi = spidev.SpiDev()
        spi.open(3, 0)

        reg = int(reg) & 0x7F
        value = int(value) & 0xFFFF
        spi.xfer2([reg | 0x80, (value & 0xFF00) >> 8, value & 0xFF])

        spi.close()

    @driver_method
    def read_reg(self, reg):
        import spidev
        spi = spidev.SpiDev()
        spi.open(3, 0)

        reg = int(reg) & 0x7F
        response = spi.xfer2([reg, 0, 0])
        value = (response[1] << 8) | response[2]

        spi.close()
        return value

    @driver_method
    def train(self):
        self.sensor_rx.trainer.train(self)

if __name__ == "__main__":
    cli(Top, runs_on=(BetaPlatform, ), possible_socs=(ZynqSocPlatform, ))
