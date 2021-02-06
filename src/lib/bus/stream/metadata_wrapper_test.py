import unittest
import random

import pytest

from lib.bus.stream.fifo import BufferedSyncStreamFIFO
from lib.bus.stream.formal_util import verify_stream_output_contract, LegalStreamSource
from lib.bus.stream.metadata_wrapper import LastWrapper, GenericMetadataWrapper
from lib.bus.stream.sim_util import write_packet_to_stream, read_packet_from_stream
from lib.bus.stream.stream import PacketizedStream, BasicStream
from util.sim import SimPlatform


class LastWrapperTest(unittest.TestCase):
    def test_randomized(self):
        platform = SimPlatform()

        input_stream = PacketizedStream(32)
        dut = LastWrapper(input_stream, lambda i: BufferedSyncStreamFIFO(i, 10), last_fifo_depth=1, last_rle_bits=4)

        random.seed(0)
        test_packets = [
            [random.randint(0, 2**32) for _ in range(12)],
            [random.randint(0, 2**32) for _ in range(24)],
            [random.randint(0, 2**32) for _ in range(1)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2 ** 32) for _ in range(12)],
            [random.randint(0, 2 ** 32) for _ in range(1000)],
        ]

        def writer_process():
            for packet in test_packets:
                yield from write_packet_to_stream(input_stream, packet)
        platform.add_process(writer_process, "sync")

        def reader_process():
            read_packets = []
            while len(read_packets) < len(test_packets):
                read = (yield from read_packet_from_stream(dut.output))
                read_packets.append(read)
                print([len(p) for p in read_packets])

            self.assertEqual(read_packets, test_packets)
        platform.add_process(reader_process, "sync")

        platform.add_sim_clock("sync", 100e6)
        platform.sim(dut)

    def test_long_fifo(self):
        platform = SimPlatform()

        input_stream = PacketizedStream(32)
        dut = LastWrapper(input_stream, lambda i: BufferedSyncStreamFIFO(i, 200), last_fifo_depth=1, last_rle_bits=10)

        random.seed(0)
        test_packets = [
            [random.randint(0, 2**32) for _ in range(12)],
            [random.randint(0, 2**32) for _ in range(24)],
            [random.randint(0, 2**32) for _ in range(1)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2 ** 32) for _ in range(12)],
            [random.randint(0, 2 ** 32) for _ in range(1000)],
        ]

        def writer_process():
            for packet in test_packets:
                yield from write_packet_to_stream(input_stream, packet)
        platform.add_process(writer_process, "sync")

        def reader_process():
            read_packets = []
            while len(read_packets) < len(test_packets):
                read = (yield from read_packet_from_stream(dut.output))
                read_packets.append(read)
                print([len(p) for p in read_packets])

            self.assertEqual(read_packets, test_packets)
        platform.add_process(reader_process, "sync")

        platform.add_sim_clock("sync", 100e6)
        platform.sim(dut)

    @pytest.mark.skip("yosys crashes on this input; see https://github.com/YosysHQ/yosys/issues/2577")
    def test_output_stream_contract(self):
        input_stream = PacketizedStream(32)
        dut = LastWrapper(input_stream, lambda i: BufferedSyncStreamFIFO(i, 10), last_fifo_depth=1, last_rle_bits=3)
        verify_stream_output_contract(dut, support_modules=(LegalStreamSource(input_stream),))

    @pytest.mark.skip("yosys crashes on this input; see https://github.com/YosysHQ/yosys/issues/2577")
    def test_core_output_stream_contract(self):
        input_stream = PacketizedStream(32)
        device_input_stream: BasicStream
        def core_producer(i):
            nonlocal device_input_stream
            device_input_stream = i
            return LegalStreamSource(i.clone())
        dut = LastWrapper(input_stream, core_producer, last_fifo_depth=1, last_rle_bits=3)
        verify_stream_output_contract(dut, stream_output=device_input_stream, support_modules=(LegalStreamSource(input_stream),))


@pytest.mark.skip("this core is non functional")
class GenericMetadataWrapperTest(unittest.TestCase):
    def test_randomized(self):
        platform = SimPlatform()

        input_stream = PacketizedStream(32)
        dut = GenericMetadataWrapper(input_stream, lambda i: BufferedSyncStreamFIFO(i, 10), fifo_depth=10)

        random.seed(0)
        test_packets = [
            [random.randint(0, 2**32) for _ in range(12)],
            [random.randint(0, 2**32) for _ in range(24)],
            [random.randint(0, 2**32) for _ in range(1)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2**32) for _ in range(1000)],
            [random.randint(0, 2 ** 32) for _ in range(12)],
            [random.randint(0, 2 ** 32) for _ in range(1000)],
        ]

        def writer_process():
            for packet in test_packets:
                yield from write_packet_to_stream(input_stream, packet)
        platform.add_process(writer_process, "sync")

        def reader_process():
            read_packets = []
            while len(read_packets) < len(test_packets):
                read = (yield from read_packet_from_stream(dut.output))
                read_packets.append(read)
                print([len(p) for p in read_packets])

            self.assertEqual(read_packets, test_packets)
        platform.add_process(reader_process, "sync")

        platform.add_sim_clock("sync", 100e6)
        platform.sim(dut)

    def test_output_stream_contract(self):
        input_stream = PacketizedStream(32)
        dut = GenericMetadataWrapper(input_stream, lambda i: BufferedSyncStreamFIFO(i, 10))
        verify_stream_output_contract(dut, support_modules=(LegalStreamSource(input_stream),))

    def test_core_output_stream_contract(self):
        input_stream = PacketizedStream(32)
        device_input_stream: BasicStream
        def core_producer(i):
            nonlocal device_input_stream
            device_input_stream = i
            return LegalStreamSource(i.clone())
        dut = GenericMetadataWrapper(input_stream, core_producer)
        verify_stream_output_contract(dut, stream_output=device_input_stream, support_modules=(LegalStreamSource(input_stream),))
